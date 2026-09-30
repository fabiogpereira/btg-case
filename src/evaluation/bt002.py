"""BT-002 — validação cega independente da variante F. PRÉ-REGISTRADO antes da criação do conjunto e do run.

python -m evaluation.bt002 --run-dir outputs/experiments/BT-002_blind_F/blind_F --out outputs/experiments/BT-002_blind_F/evaluation

- Conjunto: tests/blind_set_v2 (criador independente; mesmo schema de gabarito do BT-001).
- Segurança: definição enhanced do E-006 (D-025), reutilizada SEM mudança (`e006.enhanced_components`), com cada
  componente reportado separadamente. A definição histórica (BT-001) é calculada ao lado, só como referência.
- Hierarquia de leitura (pré-registrada): 1) nenhuma aprovação insegura; 2) nenhuma omissão material em registro
  aprovado; 3) ambiguidades perigosas revisadas; 4) só então utilidade (false reviews, taxa de revisão).
  Revisão desnecessária = problema de utilidade; aprovação materialmente incorreta = problema de segurança.
- Regras de correspondência (pré-registradas):
  - status do gabarito: present->found, absent->not_found, pending->declared_pending, not_applicable->not_applicable;
  - tipo OTHER/UNRESOLVED no gabarito é acerto se o pipeline não afirma tipo suportado (event_type nulo);
  - datas ISO; montantes, alíquotas e proporções comparados como Decimal (evaluation.blind.value_match);
  - tratamento tributário: gabarito com base EXEMPT (ou alíquota 0) = isenção -> correto só se `tax_treatment.kind`
    for EXEMPT/NO_WITHHOLDING_DECLARED; alíquota numérica -> `tax_treatment` com a mesma alíquota (Decimal) e a
    mesma base (NOT_STATED/nulo == base nula); gabarito ausente/não aplicável -> `tax_treatment` não encontrado;
  - qualificador material do gabarito representado: regras de `e006._qualifier_represented`;
  - contexto não material do gabarito sinalizado como material bloqueante pelo pipeline = falso alarme de qualificador;
  - regras objetivas recalculadas dos valores do gabarito (`blind.objective_rules`).
- Decisão GO/STOP (pré-registrada): o portão de segurança passa se enhanced unsafe = 0 e nenhuma omissão material
  em registro aprovado. Os demais critérios de GO (sem failure mode estrutural que torne a arquitetura insegura;
  utilidade aceitável ou limitações fail-safe) são julgamento registrado no log, não calculados aqui.
"""
import argparse
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from .blind import DATE_FIELDS, STATUS, event_match, objective_rules, value_match
from .e004 import _latency_stats
from .e006 import (EXEMPT_KINDS, MATERIAL, _any, _field, _norm, _qualifier_represented, _tax_exempt_represented,
                   deterministic_coverage, enhanced_components)

ROOT = Path(__file__).resolve().parents[2]
BLIND_V2 = ROOT / "tests" / "blind_set_v2"
COMPONENTS = ["field_hallucination", "material_ambiguity_approved", "other_expected_review_approved",
              "material_validation_failure_approved", "material_information_omission",
              "unsupported_material_semantic_conflict"]


def _dec(x):
    try:
        return Decimal(str(x)) if x not in (None, "") else None
    except Exception:
        return None


def load_truth(gt_path: Path) -> tuple[dict, dict]:
    """Mesma visão de gabarito do e006.truth_blind, parametrizada pelo caminho."""
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    out, cases = {}, {}
    for c in gt["cases"]:
        fields = {k: {"status": STATUS[v["status"]], "raw": v} for k, v in c["fields"].items()}
        for k in ("isin", "ticker", "cnpj"):
            if c["issuer"].get(k):
                fields[k] = {"status": "found", "value": c["issuer"][k]}
        wt = c["fields"]["withholding_tax"]
        exempt = wt["status"] == "present" and (wt.get("base") == "EXEMPT" or _dec(wt.get("rate")) == 0)
        out[c["document_file"]] = {"id": c["case_id"], "event_type": c["event_type"], "expected_routing": c["expected_routing"],
                                   "routing_defined": True, "expected_reasons": [], "fields": fields,
                                   "material_qualifiers": c.get("material_qualifiers", []),
                                   "fail_rules": [k for k, v in objective_rules(c).items() if v == "FAIL"],
                                   "categories": c.get("case_categories", []), "match": "blind", "exempt": exempt}
        cases[c["document_file"]] = c
    return out, cases


def _records(run_dir: Path) -> dict:
    return {r["document"]["file_name"]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def tax_treatment_ok(case, rec) -> bool:
    wt = case["fields"]["withholding_tax"]
    tt = (rec.get("fields") or {}).get("tax_treatment")
    found = bool(tt) and tt["status"] == "found"
    if wt["status"] != "present":
        return not found
    if wt.get("base") == "EXEMPT" or _dec(wt.get("rate")) == 0:
        return _tax_exempt_represented(rec)
    if not found or tt["value"]["kind"] not in ("WITHHOLDING_AT_RATE", "CONDITIONAL_MULTIPLE_RATES"):
        return False
    base = None if wt.get("base") in (None, "NOT_STATED") else wt["base"]
    return _dec(wt.get("rate")) == _dec(tt["value"]["rate"]) and base == tt["value"]["base"]


def material_items(truth, case, rec) -> list[dict]:
    """Inventário material do gabarito e se o registro o representa (independe do roteamento)."""
    items = []
    for name in MATERIAL:
        gf = case["fields"].get(name)
        if not gf or gf["status"] not in ("present", "pending"):
            continue
        got = _field(rec, name)
        if name == "withholding_tax" and truth["exempt"]:
            ok = _tax_exempt_represented(rec)
        elif gf["status"] == "pending":
            ok = bool(got) and got["status"] == "declared_pending"
        else:
            ok = value_match(name, gf, got)
        items.append({"item": name, "represented": ok})
    for q in truth["material_qualifiers"]:
        items.append({"item": f"qualifier:{q.get('affects')}", "represented": _qualifier_represented(q, rec, truth)})
    return items


def false_qualifier_alarms(case, rec) -> list[str]:
    """Contexto não material do gabarito que o pipeline tratou como qualificador material bloqueante."""
    blocking = [_norm(q.get("quote")) for q in (rec.get("semantic") or {}).get("material_qualifiers", [])
                if q.get("blocks") and q.get("quote")]
    out = []
    for nm in case.get("non_material_context", []):
        ev = _norm(nm.get("evidence"))
        if ev and any(b and (b in ev or ev in b) for b in blocking):
            out.append(nm.get("description") or ev[:80])
    return out


def evaluate(run_dir: Path, gt_path: Path = BLIND_V2 / "ground_truth.json") -> dict:
    truths, cases = load_truth(gt_path)
    recs = _records(run_dir)
    rows = []
    tot = Counter()
    for fname, truth in truths.items():
        rec, case = recs[fname], cases[fname]
        auto = rec["routing"]["decision"] == "AUTO_APPROVE"
        comp = enhanced_components(rec, truth)
        got_type = (rec.get("classification") or {}).get("event_type")
        exp = truth["expected_routing"]
        kind = ("correct_auto" if auto and exp == "AUTO_APPROVE" else "correct_review" if not auto and exp != "AUTO_APPROVE"
                else "false_approval" if auto else "false_review")
        # semântica
        type_ok = event_match(case["event_type"], got_type)
        tt_ok = tax_treatment_ok(case, rec)
        items = material_items(truth, case, rec)
        quals = [_qualifier_represented(q, rec, truth) for q in truth["material_qualifiers"]]
        alarms = false_qualifier_alarms(case, rec)
        # determinístico (valores e status por campo)
        per_field = {}
        for name, gf in case["fields"].items():
            got = _field(rec, name)
            got_status = got["status"] if got else "ABSENT"
            per_field[name] = {"expected": gf["status"], "got": got_status,
                               "value_ok": value_match(name, gf, got) if gf["status"] == "present" else None}
            bucket = ("dates" if name in DATE_FIELDS else "ratios" if name == "ratio" else
                      "values" if name in ("gross_amount_per_share", "net_amount_per_share") else None)
            if bucket and gf["status"] == "present" and not (name == "withholding_tax"):
                tot[bucket + "_ok"] += bool(per_field[name]["value_ok"])
                tot[bucket] += 1
            tot["status_ok"] += got_status == STATUS[gf["status"]] or (
                name == "withholding_tax" and truth["exempt"] and got_status == "not_found" and tt_ok)
            tot["status"] += 1
        for key in ("isin", "ticker", "cnpj"):
            ev = case["issuer"].get(key)
            if ev:
                got = _field(rec, key)
                tot["identifiers_ok"] += bool(got) and got["status"] == "found" and got["value"] == ev
                tot["identifiers"] += 1
        exp_rules = objective_rules(case)
        got_rules = {v["rule_id"]: v["status"] for v in rec.get("validations", [])}
        rules = {rid: {"expected": e, "got": got_rules.get(rid, "ABSENT")} for rid, e in exp_rules.items()}
        det_n, det_d = deterministic_coverage(rec, truth)
        tot["det_ok"] += det_n
        tot["det"] += det_d
        llm = rec.get("llm") or {}
        ids = {(case["issuer"].get("isin") or "").upper(), (case["issuer"].get("ticker") or "").upper()} - {""}
        tool_calls = llm.get("tool_calls", [])
        rows.append({
            "case": truth["id"], "file": fname, "categories": truth["categories"],
            "expected_type": case["event_type"], "got_type": got_type, "type_ok": type_ok,
            "expected_routing": exp, "decision": rec["routing"]["decision"], "reason_codes": rec["routing"]["reason_codes"],
            "routing_kind": kind, "unsafe_enhanced": auto and _any(comp),
            "components_if_approved": {k: v for k, v in comp.items() if v} if auto else None,
            "latent_components": {k: v for k, v in comp.items() if v},
            "legacy_unsafe": auto and bool(exp == "REVIEW_REQUIRED" or not type_ok or comp["field_hallucination"]),
            "dangerous_ambiguity": "ambiguous" in truth["categories"] or case["event_type"] in ("UNRESOLVED", "OTHER"),
            "tax_treatment_expected": case["fields"]["withholding_tax"], "tax_treatment_got":
                ((rec.get("fields") or {}).get("tax_treatment") or {}).get("value"), "tax_treatment_ok": tt_ok,
            "material_items": items, "gt_material_qualifiers_captured": quals, "false_qualifier_alarms": alarms,
            "fields": per_field, "rules": rules,
            "coverage_blocking": [i for i in (rec.get("semantic") or {}).get("material_coverage", []) if i["blocks"]],
            "contradictions": [c["code"] for c in (rec.get("semantic") or {}).get("contradictions", [])],
            "event_status": (rec.get("semantic") or {}).get("event_status"),
            "llm_invoked": bool(llm), "triggers": (rec.get("semantic_need") or {}).get("llm_trigger_reasons", []),
            "api_calls": llm.get("api_calls", 0), "tool_calls": len(tool_calls),
            "tool_args_correct": sum((t["arguments"].get("identifier") or "").upper() in ids for t in tool_calls
                                     if t["name"] == "lookup_security"),
            "grounded": (llm.get("grounding") or {}).get("grounded_quotes", 0),
            "quotes": (llm.get("grounding") or {}).get("total_quotes", 0),
            "ungrounded": (llm.get("grounding") or {}).get("ungrounded", []),
            "resolutions": [(r.get("concept"), r.get("category")) for r in (rec.get("semantic") or {}).get("resolutions", [])],
        })
    r = lambda a, b: {"correct": a, "total": b}
    kinds = Counter(x["routing_kind"] for x in rows)
    approved = [x for x in rows if x["decision"] == "AUTO_APPROVE"]
    comp_ids = lambda c: [x["case"] for x in approved if x["components_if_approved"] and c in x["components_if_approved"]]
    llm = [x["llm"] for x in recs.values() if "llm" in x]
    dur = {k: x["audit"]["duration_us"] for k, x in recs.items()}
    all_items = [i for x in rows for i in x["material_items"]]
    rule_rows = [v for x in rows for v in x["rules"].values()]
    ref_rows = [x["rules"]["REF_ISIN_FOUND"] for x in rows if "REF_ISIN_FOUND" in x["rules"]]
    danger = [x for x in rows if x["dangerous_ambiguity"]]
    enhanced_zero = not any(x["unsafe_enhanced"] for x in rows)
    no_omission = not comp_ids("material_information_omission")
    return {
        "cases": len(rows),
        "safety": {
            "unsafe_auto_approvals_enhanced": [x["case"] for x in rows if x["unsafe_enhanced"]],
            "hallucinations_approved": comp_ids("field_hallucination"),
            "material_omissions_approved": comp_ids("material_information_omission"),
            "unresolved_ambiguity_approved": comp_ids("material_ambiguity_approved"),
            "other_expected_review_approved": comp_ids("other_expected_review_approved"),
            "validation_failures_approved": comp_ids("material_validation_failure_approved"),
            "semantic_contradictions_approved": comp_ids("unsupported_material_semantic_conflict"),
            "false_approvals": [x["case"] for x in rows if x["routing_kind"] == "false_approval"],
            "dangerous_ambiguities_reviewed": r(sum(x["decision"] != "AUTO_APPROVE" for x in danger), len(danger)),
            "legacy_unsafe_auto_approvals_bt001_definition": [x["case"] for x in rows if x["legacy_unsafe"]],
            "detail": {x["case"]: x["components_if_approved"] for x in rows if x["unsafe_enhanced"]},
        },
        "routing": {"accuracy": r(kinds["correct_auto"] + kinds["correct_review"], len(rows)),
                    "correct_auto_approvals": [x["case"] for x in rows if x["routing_kind"] == "correct_auto"],
                    "correct_reviews": [x["case"] for x in rows if x["routing_kind"] == "correct_review"],
                    "false_reviews": [x["case"] for x in rows if x["routing_kind"] == "false_review"],
                    "false_approvals": [x["case"] for x in rows if x["routing_kind"] == "false_approval"],
                    "review_rate": r(sum(x["decision"] != "AUTO_APPROVE" for x in rows), len(rows))},
        "semantic": {"event_type": r(sum(x["type_ok"] for x in rows), len(rows)),
                     "tax_treatment": r(sum(x["tax_treatment_ok"] for x in rows), len(rows)),
                     "material_information_coverage": r(sum(i["represented"] for i in all_items), len(all_items)),
                     "gt_material_qualifiers_captured": r(sum(q for x in rows for q in x["gt_material_qualifiers_captured"]),
                                                          sum(len(x["gt_material_qualifiers_captured"]) for x in rows)),
                     "false_qualifier_alarms": {x["case"]: x["false_qualifier_alarms"] for x in rows if x["false_qualifier_alarms"]},
                     "date_roles": r(tot["dates_ok"], tot["dates"])},
        "deterministic": {"identifiers": r(tot["identifiers_ok"], tot["identifiers"]), "values": r(tot["values_ok"], tot["values"]),
                          "ratios": r(tot["ratios_ok"], tot["ratios"]), "dates": r(tot["dates_ok"], tot["dates"]),
                          "field_status": r(tot["status_ok"], tot["status"]),
                          "golden_lookup": r(sum(x["expected"] == x["got"] for x in ref_rows), len(ref_rows)),
                          "validation_rules": {**r(sum(v["expected"] == v["got"] for v in rule_rows), len(rule_rows)),
                                               "false_negatives": sum(v["expected"] == "FAIL" and v["got"] != "FAIL" for v in rule_rows),
                                               "false_positives": sum(v["got"] == "FAIL" and v["expected"] != "FAIL" for v in rule_rows)},
                          "deterministic_extraction_coverage": r(tot["det_ok"], tot["det"])},
        "llm_usage": {"invoked": [x["case"] for x in rows if x["llm_invoked"]],
                      "invocation_rate": r(sum(x["llm_invoked"] for x in rows), len(rows)),
                      "trigger_reasons": dict(Counter(t for x in rows for t in x["triggers"])),
                      "api_calls": sum(x["api_calls"] for x in rows),
                      "calls_per_invoked_document": round(sum(x["api_calls"] for x in rows) / max(1, len(llm)), 2),
                      "tool_calls": sum(x["tool_calls"] for x in rows),
                      "tool_calls_with_correct_arguments": sum(x["tool_args_correct"] for x in rows),
                      "grounding": r(sum(x["grounded"] for x in rows), sum(x["quotes"] for x in rows)),
                      "ungrounded": {x["case"]: x["ungrounded"] for x in rows if x["ungrounded"]},
                      "parse_or_schema_failures": sum(x.get("parse_or_schema_failures", 0) for x in llm),
                      "refusals": sum(len(x.get("refusals", [])) for x in llm),
                      "llm_errors": sum(len(x.get("errors", [])) for x in llm),
                      "reference_divergences": sum(bool((x.get("reference_divergence") or {}).get("divergent")) for x in llm),
                      "replayed_documents": sum(bool(x.get("replayed")) for x in llm)},
        "operational": {"estimated_cost_usd": str(sum((Decimal(x["estimated_cost_usd"]) for x in llm), Decimal(0))),
                        "input_tokens": sum(x["usage"]["input_tokens"] for x in llm),
                        "output_tokens": sum(x["usage"]["output_tokens"] for x in llm),
                        "latency_with_llm": _latency_stats([dur[k] for k, x in recs.items() if "llm" in x]),
                        "latency_without_llm": _latency_stats([dur[k] for k, x in recs.items() if "llm" not in x]),
                        "errors": sum(len(x["audit"]["errors"]) for x in recs.values())},
        "safety_gate": {"enhanced_unsafe_zero": enhanced_zero, "no_material_omission_in_approved": no_omission,
                        "passes": enhanced_zero and no_omission},
        "per_case": rows,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--gt", type=Path, default=BLIND_V2 / "ground_truth.json")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate(a.run_dir, a.gt)
    (a.out / "bt002_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_case"}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
