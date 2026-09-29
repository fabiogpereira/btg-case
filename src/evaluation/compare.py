"""Métricas contra o gabarito, separadas por camada (D-009). Sem métrica única agregada.

- Extração: tipo de evento, status de cada campo, valor exato, detecção de ausência/pendência,
  valores "inventados" (encontrados onde o gabarito diz que não há valor).
- Validação: acerto por regra, falsos negativos (gabarito FAIL, run não FAIL),
  falsos positivos (run FAIL, gabarito não FAIL) e demais divergências.
- Roteamento: acerto só onde a expectativa é DEFINED; PROVISIONAL e POLICY_DEPENDENT são
  registrados, mas não contam como erro.
- Operacional e cobertura de regras do extrator (sinal de sobreajuste).
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from corporate_actions import extraction as extraction_rules

ABSENT = "ABSENT"   # o run não produziu esse campo/regra


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_ground_truth(gt_dir: Path) -> dict:
    index = _load_json(gt_dir / "index.json")
    return {e["sha256"]: _load_json(gt_dir / e["ground_truth_file"]) for e in index["documents"]}


def load_run(run_dir: Path):
    records = {}
    for path in sorted((run_dir / "records").glob("*.json")):
        rec = _load_json(path)
        records[rec["document"]["sha256"]] = rec
    return records, _load_json(run_dir / "run_manifest.json")


def _pct(n, d):
    return None if d == 0 else round(100 * n / d, 1)


def _ratio(n, d):
    return {"correct": n, "total": d, "pct": _pct(n, d)}


def all_defined_extractor_rules() -> set[str]:
    source = Path(extraction_rules.__file__).read_text(encoding="utf-8")
    return set(re.findall(r'"((?:[a-z_]+)\.(?:label|pattern|phrase)[a-z_]*)"', source)) | \
        {rid for rules in extraction_rules.EVENT_LEXICON.values() for rid, _ in rules}


def evaluate(gt_dir: Path, run_dir: Path) -> dict:
    gts = load_ground_truth(gt_dir)
    records, manifest = load_run(run_dir)
    per_doc, invented = [], []
    field_stats = defaultdict(lambda: {"value_expected": 0, "value_match": 0, "status_total": 0, "status_match": 0})
    absence = defaultdict(lambda: [0, 0])
    rule_rows, routing_rows = [], []
    rule_docs = defaultdict(set)

    for sha, gt in gts.items():
        rec = records.get(sha)
        name = gt["document"]["file_name"]
        usable = bool(rec and (rec["document"].get("text_layer") or {}).get("usable"))
        truth = gt["document_truth"]
        exp_type = truth["classification"]["event_type"]
        got_type = (rec.get("classification") or {}).get("event_type") if rec else None
        doc = {"document": name, "sha256": sha, "text_layer_usable": usable,
               "event_type": {"expected": exp_type, "got": got_type, "match": exp_type == got_type},
               "fields": {}, "rules": {}, "routing": None}

        got_fields = {**(rec.get("fields") or {}), **(rec.get("event_specific_fields") or {})} if rec else {}
        for fname, exp in {**truth["fields"], **truth["event_specific_fields"]}.items():
            got = got_fields.get(fname)
            got_status = got["status"] if got else ABSENT
            status_match = got_status == exp["status"]
            value_match = None
            if exp["status"] == "found":
                value_match = bool(got) and got_status == "found" and got["value"] == exp["value"]
                field_stats[fname]["value_expected"] += 1
                field_stats[fname]["value_match"] += int(value_match)
            else:
                absence[exp["status"]][1] += 1
                absence[exp["status"]][0] += int(status_match)
                if got_status == "found":
                    invented.append({"document": name, "field": fname, "expected_status": exp["status"],
                                     "got_value": got["value"], "evidence": [e["text"] for e in got["evidence"]]})
            field_stats[fname]["status_total"] += 1
            field_stats[fname]["status_match"] += int(status_match)
            doc["fields"][fname] = {"expected_status": exp["status"], "got_status": got_status,
                                    "status_match": status_match, "expected_value": exp["value"],
                                    "got_value": got["value"] if got else None, "value_match": value_match}
            for rid in (got or {}).get("extraction_rules", []):
                rule_docs[rid].add(name)

        for items in ((rec or {}).get("classification") or {}).get("signals", {}).values():
            for item in items:
                rule_docs[item["rule_id"]].add(name)

        got_rules = {v["rule_id"]: v["status"] for v in (rec or {}).get("validations", [])}
        for rule in gt["validation_truth"]["rules"]:
            got = got_rules.get(rule["rule_id"], ABSENT)
            exp = rule["expected"]
            kind = "match" if got == exp else ("false_negative" if exp == "FAIL" else
                                                 "false_positive" if got == "FAIL" else "other_mismatch")
            doc["rules"][rule["rule_id"]] = {"expected": exp, "got": got, "kind": kind}
            rule_rows.append({"document": name, "rule_id": rule["rule_id"], "expected": exp, "got": got,
                              "kind": kind, "text_layer_usable": usable})
        doc["extra_rules_not_in_ground_truth"] = sorted(set(got_rules) - {r["rule_id"] for r in gt["validation_truth"]["rules"]})

        exp_r = gt["routing_expectation"]
        got_decision = (rec or {}).get("routing", {}).get("decision", ABSENT)
        doc["routing"] = {"expectation_status": exp_r["expectation_status"], "expected": exp_r["decision"],
                          "expected_reasons": exp_r["reason_codes"], "got": got_decision,
                          "got_reasons": (rec or {}).get("routing", {}).get("reason_codes", []),
                          "match": (got_decision == exp_r["decision"]) if exp_r["decision"] else None}
        routing_rows.append(doc["routing"] | {"document": name})
        per_doc.append(doc)

    def rules_summary(rows):
        kinds = Counter(r["kind"] for r in rows)
        return {"accuracy": _ratio(kinds["match"], len(rows)), "false_negatives": kinds["false_negative"],
                "false_positives": kinds["false_positive"], "other_mismatches": kinds["other_mismatch"]}

    def field_summary(docs):
        values = [f for d in docs for f in d["fields"].values() if f["value_match"] is not None]
        statuses = [f for d in docs for f in d["fields"].values()]
        return {"value_exact_match": _ratio(sum(f["value_match"] for f in values), len(values)),
                "status_match": _ratio(sum(f["status_match"] for f in statuses), len(statuses))}

    with_text = [d for d in per_doc if d["text_layer_usable"]]
    defined = [r for r in routing_rows if r["expectation_status"] == "DEFINED"]
    defined_rules = all_defined_extractor_rules()
    return {
        "run_id": manifest["run_id"], "pipeline_version": manifest["pipeline_version"],
        "ground_truth_version": next(iter(gts.values()))["ground_truth_version"],
        "extraction": {
            "event_type_accuracy": {"all_documents": _ratio(sum(d["event_type"]["match"] for d in per_doc), len(per_doc)),
                                    "with_text_layer": _ratio(sum(d["event_type"]["match"] for d in with_text), len(with_text))},
            "fields": {"all_documents": field_summary(per_doc), "with_text_layer": field_summary(with_text)},
            "absence_detection": {k: _ratio(v[0], v[1]) for k, v in sorted(absence.items())},
            "invented_values": invented,
            "per_field": {k: {"value": _ratio(v["value_match"], v["value_expected"]),
                              "status": _ratio(v["status_match"], v["status_total"])} for k, v in field_stats.items()},
        },
        "validation": {"all_documents": rules_summary(rule_rows),
                       "with_text_layer": rules_summary([r for r in rule_rows if r["text_layer_usable"]]),
                       "mismatches": [r for r in rule_rows if r["kind"] != "match"]},
        "routing": {"defined_expectations": _ratio(sum(bool(r["match"]) for r in defined), len(defined)),
                    "rows": routing_rows},
        "operational": {"documents_processed": manifest["summary"]["documents"],
                        "without_usable_text_layer": manifest["summary"]["without_usable_text_layer"],
                        "errors": manifest["summary"]["errors"],
                        "total_duration_ms": manifest["summary"]["total_duration_us"] / 1000,
                        "decisions": manifest["summary"]["decisions"]},
        "extractor_rule_coverage": {
            "documents_per_rule": {rid: sorted(docs) for rid, docs in sorted(rule_docs.items())},
            "single_document_rules": sorted(rid for rid, docs in rule_docs.items() if len(docs) == 1),
            "never_fired": sorted(defined_rules - set(rule_docs)),
        },
        "per_document": per_doc,
    }
