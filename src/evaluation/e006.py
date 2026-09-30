"""Avaliação do E-006 (variante F × candidata E). PRÉ-REGISTRADA antes do run oficial de F.

python -m evaluation.e006 --f-dir outputs/experiments/E-006_hardened --out outputs/experiments/E-006_hardened/evaluation

Conjuntos (nenhum é out-of-sample para F):
- original: regression/development set (gabarito tests/ground_truth v2.1);
- challenge: regression set (tests/challenge_set v1.0, só alvos semânticos);
- blind-derived regression set: o antigo blind set (BT-001). Já foi visto e motivou o E-006 — NÃO é blind test para F.

Duas definições de segurança, mantidas separadas (não se reescreve a história):
- `unsafe_auto_approval` (E-003..E-005 e BT-001): calculada pelos avaliadores originais (compare/challenge/blind),
  sem alteração.
- `unsafe_auto_approval_enhanced` (E-006 em diante; evolução POST-HOC motivada pelo BT-001). Um AUTO_APPROVE é
  inseguro se tiver qualquer um dos componentes:
  1. field_hallucination: tipo de evento errado; valor emitido diferente do gabarito; valor encontrado onde o
     gabarito diz ausente/pendente/não aplicável;
  2. material_ambiguity_approved / other_expected_review_approved: rota esperada REVIEW (expectativa DEFINED);
  3. material_validation_failure_approved: alguma regra objetiva que o gabarito espera FAIL;
  4. material_information_omission: campo material presente no gabarito (datas de data-base/ex/pagamento/crédito,
     valores bruto/líquido, tributação, proporção) sem representação no registro; declaração de pendência não
     representada; qualificador material do gabarito não representado. Isenção de IR conta como representada
     somente por `tax_treatment.kind` EXEMPT/NO_WITHHOLDING_DECLARED (nunca por alíquota zero inventada);
  5. unsupported_material_semantic_conflict: gabarito OTHER/UNRESOLVED, categoria internal_inconsistency, ou
     contradição registrada pelo próprio pipeline.
  A E é recalculada com essa definição sobre os registros oficiais congelados (E-005 run 1; BT-001 run 2), rotulada
  como avaliação post-hoc.

Qualificador material do gabarito (blind-derived) é representado se: uma citação material do registro sobrepõe a
evidência do gabarito; ou (tax_base) o IR bate em taxa e base; ou (beneficiary_tax_treatment) há exceção por
beneficiário registrada (tax_treatment.beneficiary_exceptions na F; nota "beneficiary exception" no IR na E);
ou (tax_rate) o tratamento é CONDITIONAL_MULTIPLE_RATES; ou (event_nature) o tipo de evento está correto;
ou (dates) a regra de ordem de datas falha no registro. Nota semântica (não material) NÃO representa qualificador material.
"""
import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

from .blind import BLIND, STATUS, event_match, objective_rules, value_match as blind_value_match
from .blind import evaluate_blind
from .challenge import evaluate_challenge
from .compare import evaluate as evaluate_original, load_ground_truth
from .e004 import GT_CH, GT_ORIG, _latency_stats, need_oracle_challenge, need_oracle_original

ROOT = Path(__file__).resolve().parents[2]
E005 = ROOT / "outputs" / "experiments" / "E-005_qualifiers_v3"
BT = ROOT / "outputs" / "experiments" / "BT-001_blind_E"
E_RUNS = {"original": E005 / "original_E", "challenge": E005 / "challenge_E", "blind_derived": BT / "blind_E_run2"}
F_SUBDIRS = {"original": "original_F", "challenge": "challenge_F", "blind_derived": "blind_derived_F"}
MATERIAL = ["record_date", "ex_date", "payment_date", "share_credit_date", "gross_amount_per_share",
            "net_amount_per_share", "withholding_tax", "ratio"]
EXEMPT_KINDS = {"EXEMPT", "NO_WITHHOLDING_DECLARED"}
AMBIGUITY_REASONS = re.compile(r"SEMANTIC|CLASSIFICATION|QUALIFIER")


def _records(run_dir: Path, key: str) -> dict:
    return {r["document"][key]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _field(rec, name):
    return (rec.get("fields") or {}).get(name) or (rec.get("event_specific_fields") or {}).get(name)


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _tax_exempt_represented(rec) -> bool:
    tt = (rec.get("fields") or {}).get("tax_treatment")
    return bool(tt) and tt["status"] == "found" and tt["value"]["kind"] in EXEMPT_KINDS


# --- visões do gabarito (um formato comum para os três conjuntos) -------------------------------------

def truth_original() -> dict:
    out = {}
    for sha, gt in load_ground_truth(GT_ORIG).items():
        t, r = gt["document_truth"], gt["routing_expectation"]
        fields = {k: {"status": v["status"], "value": v["value"]} for k, v in {**t["fields"], **t["event_specific_fields"]}.items()}
        out[sha] = {"id": gt["document"]["file_name"], "event_type": t["classification"]["event_type"],
                    "expected_routing": r["decision"], "routing_defined": r["expectation_status"] == "DEFINED",
                    "expected_reasons": r["reason_codes"], "fields": fields, "material_qualifiers": [],
                    "fail_rules": [x["rule_id"] for x in gt["validation_truth"]["rules"] if x["expected"] == "FAIL"],
                    "categories": [], "exempt": False, "match": "exact"}
    return out


def truth_challenge() -> dict:
    gt = json.loads((GT_CH / "ground_truth.json").read_text(encoding="utf-8"))
    out = {}
    for c in gt["cases"]:
        fields = {t["field"]: {"status": t["expected_status"], "value": t["expected_value"]}
                  for t in c["targets"] if t["target"] != "event_type"}
        et = next((t["expected"] for t in c["targets"] if t["target"] == "event_type"), "__not_targeted__")
        out[c["sha256"]] = {"id": c["id"], "event_type": et, "expected_routing": c["routing"]["decision"],
                            "routing_defined": c["routing"]["expectation_status"] == "DEFINED", "expected_reasons": [],
                            "fields": fields, "material_qualifiers": [], "fail_rules": [], "categories": c["categories"],
                            "exempt": False, "match": "exact"}
    return out


def truth_blind() -> dict:
    gt = json.loads((BLIND / "ground_truth.json").read_text(encoding="utf-8"))
    out = {}
    for c in gt["cases"]:
        fields = {}
        for k, v in c["fields"].items():
            fields[k] = {"status": STATUS[v["status"]], "raw": v}
        for k in ("isin", "ticker", "cnpj"):
            if c["issuer"].get(k):
                fields[k] = {"status": "found", "value": c["issuer"][k]}
        wt = c["fields"]["withholding_tax"]
        out[c["document_file"]] = {"id": c["case_id"], "event_type": c["event_type"], "expected_routing": c["expected_routing"],
                                   "routing_defined": True, "expected_reasons": [], "fields": fields,
                                   "material_qualifiers": c["material_qualifiers"],
                                   "fail_rules": [k for k, v in objective_rules(c).items() if v == "FAIL"],
                                   "categories": c["case_categories"], "match": "blind",
                                   "exempt": wt["status"] == "present" and (wt.get("base") == "EXEMPT" or Decimal(wt.get("rate") or "1") == 0)}
    return out


def _value_ok(truth, name, gf, got) -> bool:
    if truth["match"] == "blind":
        if "raw" in gf:
            return blind_value_match(name, gf["raw"], got)
        return bool(got) and got["status"] == "found" and got["value"] == gf["value"]
    return bool(got) and got["status"] == "found" and got["value"] == gf["value"]


def _qualifier_represented(q, rec, truth) -> bool:
    ev = _norm(q["evidence"])
    quotes = [_norm(x.get("quote")) for x in (rec.get("semantic") or {}).get("material_qualifiers", []) if x.get("quote")]
    if any(x and (x in ev or ev in x) for x in quotes):
        return True
    a = q["affects"]
    wt, tt = _field(rec, "withholding_tax"), (rec.get("fields") or {}).get("tax_treatment")
    if a == "tax_base":
        return "withholding_tax" in truth["fields"] and _value_ok(truth, "withholding_tax", truth["fields"]["withholding_tax"], wt)
    if a == "beneficiary_tax_treatment":
        return bool(tt and tt["status"] == "found" and tt["value"]["beneficiary_exceptions"]) or \
            bool(wt and any("beneficiary exception" in n for n in wt.get("notes", [])))
    if a == "tax_rate":
        return bool(tt and tt["status"] == "found" and tt["value"]["kind"] == "CONDITIONAL_MULTIPLE_RATES")
    if a == "event_nature":
        return event_match(truth["event_type"], (rec.get("classification") or {}).get("event_type"))
    if a == "dates":
        return any(v["status"] == "FAIL" and v["rule_id"].startswith("DATE_") for v in rec.get("validations", []))
    return False


def enhanced_components(rec, truth) -> dict:
    """Componentes da definição enhanced para UM registro (calculados sempre; só contam como unsafe se AUTO_APPROVE)."""
    got_type = (rec.get("classification") or {}).get("event_type")
    comp = {"field_hallucination": [], "material_ambiguity_approved": False, "other_expected_review_approved": False,
            "material_validation_failure_approved": [], "material_information_omission": [],
            "unsupported_material_semantic_conflict": []}
    if truth["event_type"] != "__not_targeted__" and not (
            event_match(truth["event_type"], got_type) if truth["match"] == "blind" else truth["event_type"] == got_type):
        comp["field_hallucination"].append("event_type")
    for name, gf in truth["fields"].items():
        got = _field(rec, name)
        got_status = got["status"] if got else "ABSENT"
        if gf["status"] == "found":
            if name == "withholding_tax" and truth["exempt"]:
                if got_status == "found":
                    comp["field_hallucination"].append("withholding_tax:numeric_rate_for_exempt")
                elif not _tax_exempt_represented(rec):
                    comp["material_information_omission"].append("tax_treatment:exemption")
            elif got_status == "found":
                if not _value_ok(truth, name, gf, got):
                    comp["field_hallucination"].append(f"{name}:wrong_value")
            elif name in MATERIAL:
                comp["material_information_omission"].append(f"{name}:{got_status}")
        elif gf["status"] == "declared_pending":
            if got_status == "found":
                comp["field_hallucination"].append(f"{name}:value_for_pending")
            elif name in MATERIAL and got_status != "declared_pending":
                comp["material_information_omission"].append(f"{name}:pending_not_represented")
        elif got_status == "found":
            comp["field_hallucination"].append(f"{name}:invented")
    for q in truth["material_qualifiers"]:
        if not _qualifier_represented(q, rec, truth):
            comp["material_information_omission"].append(f"qualifier:{q['affects']}")
    if truth["routing_defined"] and truth["expected_routing"] == "REVIEW_REQUIRED":
        ambiguous = ("ambiguous" in truth["categories"] or truth["event_type"] == "UNRESOLVED"
                     or any(AMBIGUITY_REASONS.search(r) for r in truth["expected_reasons"]))
        comp["material_ambiguity_approved" if ambiguous else "other_expected_review_approved"] = True
    comp["material_validation_failure_approved"] = list(truth["fail_rules"])
    if truth["event_type"] in ("OTHER", "UNRESOLVED"):
        comp["unsupported_material_semantic_conflict"].append(f"ground_truth_event_type:{truth['event_type']}")
    if "internal_inconsistency" in truth["categories"]:
        comp["unsupported_material_semantic_conflict"].append("ground_truth:internal_inconsistency")
    for c in (rec.get("semantic") or {}).get("contradictions", []):
        comp["unsupported_material_semantic_conflict"].append(f"pipeline:{c['code']}")
    return comp


def _any(comp) -> bool:
    return any(bool(v) for v in comp.values())


def deterministic_coverage(rec, truth) -> tuple[int, int]:
    """Campos materiais/identificadores presentes no gabarito cujo valor correto veio de regra determinística."""
    n = d = 0
    for name, gf in truth["fields"].items():
        if gf["status"] != "found" or (name == "withholding_tax" and truth["exempt"]):
            continue
        if name not in MATERIAL and name not in ("isin", "ticker", "cnpj", "issuer_name", "approval_date"):
            continue
        d += 1
        got = _field(rec, name)
        if _value_ok(truth, name, gf, got) and not any(r.startswith("llm.") for r in got.get("extraction_rules", [])):
            n += 1
    if truth["exempt"]:
        d += 1
        tt = (rec.get("fields") or {}).get("tax_treatment")
        n += _tax_exempt_represented(rec) and not any(r.startswith("llm.") for r in tt.get("extraction_rules", []))
    return n, d


# --- avaliação de um run -------------------------------------------------------------------------------

def evaluate_run(dataset: str, run_dir: Path) -> dict:
    truths, key = {"original": (truth_original(), "sha256"), "challenge": (truth_challenge(), "sha256"),
                   "blind_derived": (truth_blind(), "file_name")}[dataset]
    recs = _records(run_dir, key)
    rows, det = [], [0, 0]
    for k, truth in truths.items():
        rec = recs[k]
        auto = rec["routing"]["decision"] == "AUTO_APPROVE"
        comp = enhanced_components(rec, truth)
        n, d = deterministic_coverage(rec, truth)
        det[0] += n
        det[1] += d
        exp = truth["expected_routing"]
        kind = ("correct_auto" if auto and exp == "AUTO_APPROVE" else "correct_review" if not auto and exp != "AUTO_APPROVE"
                else "false_approval" if auto else "false_review")
        rows.append({"id": truth["id"], "decision": rec["routing"]["decision"], "reason_codes": rec["routing"]["reason_codes"],
                     "expected_routing": exp, "routing_defined": truth["routing_defined"], "routing_kind": kind,
                     "llm_invoked": "llm" in rec, "components_if_approved": comp if auto else None,
                     "latent_components": comp, "unsafe_enhanced": auto and _any(comp),
                     "tax_treatment": ((rec.get("fields") or {}).get("tax_treatment") or {}).get("value"),
                     "coverage_blocking": [i for i in (rec.get("semantic") or {}).get("material_coverage", []) if i["blocks"]],
                     "contradictions": (rec.get("semantic") or {}).get("contradictions", []),
                     "event_status": (rec.get("semantic") or {}).get("event_status")})
    ratio = lambda a, b: {"correct": a, "total": b}
    defined = [r for r in rows if r["routing_defined"]]
    llm = [r["llm"] for r in recs.values() if "llm" in r]
    cost = sum((Decimal(x["estimated_cost_usd"]) for x in llm), Decimal(0))
    dur = {k: r["audit"]["duration_us"] for k, r in recs.items()}
    unsafe = [r for r in rows if r["unsafe_enhanced"]]
    comp_count = lambda name: [r["id"] for r in rows if r["components_if_approved"] and r["components_if_approved"][name]]
    return {
        "dataset": dataset, "run_dir": _rel(run_dir), "documents": len(rows),
        "safety_enhanced": {
            "unsafe_auto_approvals_enhanced": [r["id"] for r in unsafe],
            "material_omissions_approved": comp_count("material_information_omission"),
            "hallucinations_approved": comp_count("field_hallucination"),
            "unresolved_ambiguity_approved": comp_count("material_ambiguity_approved"),
            "validation_failures_approved": comp_count("material_validation_failure_approved"),
            "contradictions_approved": comp_count("unsupported_material_semantic_conflict"),
            "other_expected_review_approved": comp_count("other_expected_review_approved"),
            "detail": {r["id"]: {k: v for k, v in r["components_if_approved"].items() if v} for r in unsafe},
        },
        "routing": {"accuracy_defined": ratio(sum(r["routing_kind"] in ("correct_auto", "correct_review") for r in defined), len(defined)),
                    "accuracy_all": ratio(sum(r["routing_kind"] in ("correct_auto", "correct_review") for r in rows), len(rows)),
                    "false_approvals": [r["id"] for r in rows if r["routing_kind"] == "false_approval"],
                    "false_reviews": [r["id"] for r in rows if r["routing_kind"] == "false_review"],
                    "review_rate": ratio(sum(r["decision"] != "AUTO_APPROVE" for r in rows), len(rows))},
        "deterministic_extraction_coverage": ratio(*det),
        "llm": {"invoked": [r["id"] for r in rows if r["llm_invoked"]],
                "invocation_rate": ratio(sum(r["llm_invoked"] for r in rows), len(rows)),
                "api_calls": sum(x["api_calls"] for x in llm),
                "replayed_documents": sum(bool(x.get("replayed")) for x in llm),
                "input_tokens": sum(x["usage"]["input_tokens"] for x in llm),
                "output_tokens": sum(x["usage"]["output_tokens"] for x in llm),
                "estimated_cost_usd": str(cost)},
        "latency": {"end_to_end_all": _latency_stats(list(dur.values())),
                    "with_llm": _latency_stats([dur[k] for k, r in recs.items() if "llm" in r]),
                    "without_llm": _latency_stats([dur[k] for k, r in recs.items() if "llm" not in r])},
        "errors": sum(len(r["audit"]["errors"]) for r in recs.values()),
        "per_document": rows,
    }


def legacy_metrics(dataset: str, run_dir: Path) -> dict:
    """Avaliadores originais, sem alteração (definição antiga de unsafe + acurácias semântica/validação)."""
    if dataset == "original":
        m = evaluate_original(GT_ORIG, run_dir)
        return {"unsafe_auto_approvals_legacy": [u["document"] for u in m["semantic"]["unsafe_auto_approvals"]],
                "semantic_accuracy": m["semantic"]["semantic_targets"]["with_text_layer"],
                "validation_accuracy": m["validation"]["with_text_layer"]["accuracy"],
                "validation_false_negatives": m["validation"]["with_text_layer"]["false_negatives"],
                "validation_false_positives": m["validation"]["with_text_layer"]["false_positives"],
                "field_values": m["extraction"]["fields"]["with_text_layer"]["value_exact_match"],
                "invented_values": len(m["extraction"]["invented_values"])}
    if dataset == "challenge":
        m = evaluate_challenge(GT_CH, run_dir)
        return {"unsafe_auto_approvals_legacy": m["unsafe_auto_approvals"], "semantic_accuracy": m["semantic_accuracy"],
                "false_confident_interpretations": m["false_confident_interpretations"]}
    m = evaluate_blind(run_dir, BT / "blind_B_instrumentation")
    return {"unsafe_auto_approvals_legacy": m["safety"]["unsafe_auto_approvals"],
            "semantic_accuracy": m["semantic"]["semantic_targets_incl_event_type"],
            "validation_accuracy": m["deterministic"]["objective_rules"],
            "field_values": m["deterministic"]["values_and_ratios"], "identifiers": m["deterministic"]["identifiers"],
            "gt_material_qualifiers_captured": m["semantic"]["gt_material_qualifiers_captured"],
            "grounding": m["llm_usage"]["grounding"],
            "need_oracle": {k: m["llm_usage"].get(k) for k in ("needed", "false_positive_invocations", "false_negative_invocations")}}


def need_oracle(dataset: str, run_dir: Path) -> dict | None:
    """Oráculo de necessidade do E-004 (sobre o B), inalterado. O detector de contradição da F é um gatilho novo que
    o oráculo não conhece: invocações por ele aparecem como falso-positivo do oráculo e são listadas à parte."""
    if dataset == "blind_derived":
        return None
    oracle = need_oracle_original() if dataset == "original" else need_oracle_challenge()
    recs = _records(run_dir, "sha256")
    eligible = {k for k, r in recs.items() if (r["document"].get("text_layer") or {}).get("usable")}
    invoked = {k for k in eligible if "llm" in recs[k]}
    needed = {k for k, o in oracle.items() if o["needed"]}
    name = lambda k: oracle[k]["document"]
    return {"needed": sorted(name(k) for k in needed), "false_positive_invocations": sorted(name(k) for k in invoked - needed),
            "false_negative_invocations": sorted(name(k) for k in needed - invoked)}


# --- checagens específicas (por classe de falha, definidas por propriedades do gabarito) --------------------

def class_checks(f_rows: dict, f_recs: dict, truths: dict) -> dict:
    out = {}
    exempt = [t["id"] for t in truths.values() if t["exempt"]]
    out["tax_exemption_represented"] = {i: f_rows[i]["tax_treatment"] is not None and f_rows[i]["tax_treatment"]["kind"] in EXEMPT_KINDS
                                        for i in exempt}
    dotted = {}
    for k, t in truths.items():
        for name, gf in t["fields"].items():
            ev = (gf.get("raw") or {}).get("evidence") or ""
            if gf["status"] == "found" and re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", ev):
                dotted[f"{t['id']}:{name}"] = _value_ok(t, name, gf, _field(f_recs[k], name))
    out["dot_separated_dates_parsed"] = dotted
    out["share_event_ratio_extracted"] = {t["id"]: _value_ok(t, "ratio", t["fields"]["ratio"], _field(f_recs[k], "ratio"))
                                          for k, t in truths.items() if t["fields"].get("ratio", {}).get("status") == "found"}
    multi = {}
    for k, rec in f_recs.items():
        d = (rec.get("semantic") or {}).get("issuer_resolution") or {}
        if d.get("decision") not in (None, "V1_RESOLUTION"):
            multi[truths[k]["id"]] = {"decision": d["decision"], "routing": rec["routing"]["decision"],
                                      "issuer": (_field(rec, "issuer_name") or {}).get("value")}
    out["multiple_company_issuer"] = multi
    out["event_tax_contradiction_detected"] = {t["id"]: {"contradictions": [c["code"] for c in f_rows[t["id"]]["contradictions"]],
                                                         "routing": f_rows[t["id"]]["decision"]}
                                               for t in truths.values() if t["event_type"] == "UNRESOLVED"}
    out["revocation_not_approvable"] = {t["id"]: {"routing": f_rows[t["id"]]["decision"],
                                                  "reason": "UNSUPPORTED_EVENT_REVOCATION" in f_rows[t["id"]]["reason_codes"]}
                                        for t in truths.values() if t["event_type"] == "OTHER"}
    return out


def success_criteria(res: dict) -> dict:
    """Critérios pré-registrados (E-006, seção 16 do pedido), com limiares numéricos fixados antes do run."""
    F, E = res["F"], res["E"]
    ds = list(F)
    fr = lambda v, d: len(v[d]["routing"]["false_reviews"])
    cost = lambda v: sum(Decimal(v[d]["llm"]["estimated_cost_usd"]) for d in ds)
    e_cost_orig_ch = sum(Decimal(E[d]["llm"]["estimated_cost_usd"]) for d in ds)
    return {
        "1_enhanced_unsafe_zero": all(not F[d]["safety_enhanced"]["unsafe_auto_approvals_enhanced"] for d in ds),
        "2_no_material_omission_approved": all(not F[d]["safety_enhanced"]["material_omissions_approved"] for d in ds),
        "3_no_safety_regression": all(not res["legacy"]["F"][d]["unsafe_auto_approvals_legacy"] for d in ds) and all(
            len(F[d]["safety_enhanced"]["unsafe_auto_approvals_enhanced"]) <= len(E[d]["safety_enhanced"]["unsafe_auto_approvals_enhanced"]) for d in ds),
        "4_routing_not_materially_worse": all(fr(F, d) <= fr(E, d) + 1 for d in ds),
        "6_cost_acceptable": cost(F) <= e_cost_orig_ch * Decimal("1.25"),
        "6_latency_acceptable": all(
            (F[d]["latency"]["with_llm"] or {}).get("p50_ms", 0) <= 1.5 * ((E[d]["latency"]["with_llm"] or {}).get("p50_ms") or 1e18)
            for d in ds if F[d]["latency"]["with_llm"] and E[d]["latency"]["with_llm"]),
        "thresholds": {"4": "false reviews de F <= false reviews de E + 1, em cada conjunto",
                       "6_cost": "custo total de F nos 3 conjuntos <= 1,25 x custo da E nos mesmos conjuntos",
                       "6_latency": "p50 de documentos com LLM <= 1,5 x o da E, em cada conjunto",
                       "5_7": "qualitativos (generalização e simplicidade): avaliados no log, não aqui"},
    }


def evaluate_all(f_dir: Path) -> dict:
    res = {"E": {}, "F": {}, "legacy": {"E": {}, "F": {}}, "need_oracle": {"E": {}, "F": {}},
           "notes": {"E": "post-hoc: registros oficiais congelados (E-005 run 1; BT-001 run 2) reavaliados com a definição enhanced",
                     "blind_derived": "blind-derived regression set: não é blind/out-of-sample para F"}}
    for ds, e_dir in E_RUNS.items():
        f_run = f_dir / F_SUBDIRS[ds]
        for v, run in (("E", e_dir), ("F", f_run)):
            res[v][ds] = evaluate_run(ds, run)
            res["legacy"][v][ds] = legacy_metrics(ds, run)
            res["need_oracle"][v][ds] = need_oracle(ds, run)
    truths = truth_blind()
    f_recs = _records(f_dir / F_SUBDIRS["blind_derived"], "file_name")
    f_rows = {r["id"]: r for r in res["F"]["blind_derived"]["per_document"]}
    res["class_checks_blind_derived"] = class_checks(f_rows, f_recs, truths)
    res["success_criteria"] = success_criteria(res)
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--f-dir", type=Path, default=ROOT / "outputs" / "experiments" / "E-006_hardened")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate_all(a.f_dir)
    (a.out / "e006_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary = {v: {ds: {"unsafe_enhanced": m["safety_enhanced"]["unsafe_auto_approvals_enhanced"],
                        "omissions": m["safety_enhanced"]["material_omissions_approved"],
                        "routing": m["routing"]["accuracy_defined"], "review_rate": m["routing"]["review_rate"],
                        "false_reviews": m["routing"]["false_reviews"], "llm": m["llm"]["invocation_rate"],
                        "cost": m["llm"]["estimated_cost_usd"]} for ds, m in res[v].items()} for v in ("E", "F")}
    print(json.dumps({"summary": summary, "success_criteria": res["success_criteria"]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
