"""Avaliação do blind test (gabarito do criador independente). Pré-registrado antes da execução da E.

python -m evaluation.blind --run-dir DIR [--b-run-dir DIR] --out DIR

Mapeamento gabarito -> pipeline (definido antes de rodar):
- status: present->found, absent->not_found, pending->declared_pending, not_applicable->not_applicable.
- event_type: OTHER/UNRESOLVED no gabarito é acerto se o pipeline NÃO afirma um tipo suportado (event_type nulo).
- valores: datas ISO; montantes e alíquota comparados numericamente (Decimal), porque a convenção de casas do
  criador pode diferir da do documento; base do IR: NOT_STATED/null do gabarito == base nula do pipeline.
- proporção: {from,to} -> {shares_before, shares_after}; {held,new} -> {shares_held, bonus_shares}.
- validação objetiva: recalculada a partir dos VALORES do gabarito (ordem de datas, ex = próximo dia útil,
  pagamento >= ex, bruto×(1-alíquota) = líquido, ISIN na base) e comparada com o status das regras do pipeline.
  Os achados em texto livre do criador entram só como leitura qualitativa.
- segurança: aprovação insegura = AUTO_APPROVE com rota esperada REVIEW, ou tipo errado, ou valor emitido
  errado, ou valor inventado (encontrado onde o gabarito diz ausente/pendente/não aplicável).
- necessidade de LLM (oráculo, mesma regra do E-004): o B errou alvo semântico, ou revisou por motivo semântico
  resolvível pelo LLM quando a rota esperada é AUTO_APPROVE. Requer o run do B (instrumentação, sem LLM).
"""
import argparse
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLIND = ROOT / "tests" / "blind_set"
STATUS = {"present": "found", "absent": "not_found", "pending": "declared_pending", "not_applicable": "not_applicable"}
SEMANTIC = ["record_date", "ex_date", "payment_date", "share_credit_date", "withholding_tax"]
DETERMINISTIC = ["gross_amount_per_share", "net_amount_per_share", "ratio"]
DATE_FIELDS = {"approval_date", "record_date", "ex_date", "payment_date", "share_credit_date"}
LLM_RESOLVABLE = {"SEMANTIC_AMBIGUITY", "CLASSIFICATION_UNDETERMINED", "CLASSIFICATION_DISAGREEMENT"}


def _dec(x):
    try:
        return Decimal(str(x)) if x not in (None, "") else None
    except InvalidOperation:
        return None


def _records(run_dir: Path) -> dict:
    return {r["document"]["file_name"]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def _got_field(rec, name):
    return (rec.get("fields") or {}).get(name) or (rec.get("event_specific_fields") or {}).get(name)


def value_match(name, gt_field, got) -> bool:
    if got is None or got["status"] != "found":
        return False
    gv = got["value"]
    if name in DATE_FIELDS:
        return gt_field["value"] == gv
    if name in ("gross_amount_per_share", "net_amount_per_share"):
        return _dec(gt_field["value"]) is not None and _dec(gt_field["value"]) == _dec(gv)
    if name == "withholding_tax":
        base = None if gt_field.get("base") in (None, "NOT_STATED") else gt_field["base"]
        return _dec(gt_field.get("rate")) == _dec(gv.get("rate")) and base == gv.get("base")
    if name == "ratio":
        v = gt_field["value"] or {}
        if "from" in v:
            return _dec(v["from"]) == _dec(gv.get("shares_before")) and _dec(v["to"]) == _dec(gv.get("shares_after"))
        if "held" in v:
            return _dec(v["held"]) == _dec(gv.get("shares_held")) and _dec(v["new"]) == _dec(gv.get("bonus_shares"))
    return False


def event_match(gt_type, got_type) -> bool:
    return got_type is None if gt_type in ("OTHER", "UNRESOLVED") else gt_type == got_type


def objective_rules(case) -> dict:
    """Resultado esperado das regras objetivas, recalculado a partir dos valores do gabarito."""
    f = case["fields"]
    d = lambda n: dt.date.fromisoformat(f[n]["value"]) if f[n]["status"] == "present" and f[n]["value"] else None
    out = {"REF_ISIN_FOUND": "PASS" if case["issuer"].get("in_reference_base") else "FAIL"}
    ap, rd, ex = d("approval_date"), d("record_date"), d("ex_date")
    settle = d("payment_date") or d("share_credit_date")
    if ap and rd:
        out["DATE_APPROVAL_NOT_AFTER_RECORD"] = "PASS" if ap <= rd else "FAIL"
    if rd and ex:
        out["DATE_RECORD_BEFORE_EX"] = "PASS" if rd < ex else "FAIL"
    if settle and ex:
        out["DATE_SETTLEMENT_NOT_BEFORE_EX"] = "PASS" if settle >= ex else "FAIL"
    g, n, w = f["gross_amount_per_share"], f["net_amount_per_share"], f["withholding_tax"]
    if g["status"] == n["status"] == w["status"] == "present" and _dec(w.get("rate")) is not None and \
            (w.get("base") in (None, "NOT_STATED", "GROSS_AMOUNT")):
        out["AMOUNT_NET_MATCHES_GROSS_AND_TAX"] = "PASS" if _dec(g["value"]) * (1 - _dec(w["rate"])) == _dec(n["value"]) else "FAIL"
    return out


def evaluate_blind(run_dir: Path, b_run_dir: Path | None = None) -> dict:
    gt = json.loads((BLIND / "ground_truth.json").read_text(encoding="utf-8"))
    recs = _records(run_dir)
    b_recs = _records(b_run_dir) if b_run_dir else {}
    rows, tot = [], {"semantic": [0, 0], "deterministic": [0, 0], "identifiers": [0, 0], "status": [0, 0],
                     "rules": [0, 0], "grounded": [0, 0]}
    fn_rules = fp_rules = 0
    for case in gt["cases"]:
        name = case["document_file"]
        rec = recs[name]
        got_type = (rec.get("classification") or {}).get("event_type")
        r = {"case": case["case_id"], "categories": case["case_categories"], "expected_type": case["event_type"],
             "got_type": got_type, "type_ok": event_match(case["event_type"], got_type), "fields": {},
             "expected_routing": case["expected_routing"], "got_routing": rec["routing"]["decision"],
             "reasons": rec["routing"]["reason_codes"], "llm_invoked": "llm" in rec,
             "triggers": (rec.get("semantic_need") or {}).get("llm_trigger_reasons", [])}
        tot["semantic"][0] += r["type_ok"]
        tot["semantic"][1] += 1
        wrong_emitted, invented = [], []
        for fname, gf in case["fields"].items():
            got = _got_field(rec, fname)
            exp_status = STATUS[gf["status"]]
            got_status = got["status"] if got else "ABSENT"
            ok_status = got_status == exp_status
            ok_value = value_match(fname, gf, got) if gf["status"] == "present" else None
            tot["status"][0] += ok_status
            tot["status"][1] += 1
            if gf["status"] == "present":
                bucket = "semantic" if fname in SEMANTIC else ("deterministic" if fname in DETERMINISTIC else None)
                if bucket:
                    tot[bucket][0] += bool(ok_value)
                    tot[bucket][1] += 1
                if got_status == "found" and not ok_value:
                    wrong_emitted.append(fname)
            elif got_status == "found":
                invented.append(fname)
            r["fields"][fname] = {"expected": gf["status"], "got": got_status, "value_ok": ok_value}
        for key in ("isin", "ticker", "cnpj"):
            ev = case["issuer"].get(key)
            if ev:
                got = _got_field(rec, key)
                ok = bool(got) and got["status"] == "found" and got["value"] == ev
                tot["identifiers"][0] += ok
                tot["identifiers"][1] += 1
                if got and got["status"] == "found" and not ok:
                    wrong_emitted.append(key)
        exp_rules, got_rules = objective_rules(case), {v["rule_id"]: v["status"] for v in rec.get("validations", [])}
        r["rules"] = {}
        for rid, exp in exp_rules.items():
            got = got_rules.get(rid, "ABSENT")
            tot["rules"][0] += got == exp
            tot["rules"][1] += 1
            fn_rules += exp == "FAIL" and got != "FAIL"
            fp_rules += got == "FAIL" and exp != "FAIL"
            r["rules"][rid] = {"expected": exp, "got": got}
        auto = r["got_routing"] == "AUTO_APPROVE"
        r["wrong_emitted"], r["invented"] = wrong_emitted, invented
        r["unsafe_auto_approval"] = auto and bool(case["expected_routing"] == "REVIEW_REQUIRED" or not r["type_ok"]
                                                  or wrong_emitted or invented)
        r["ambiguity_auto_approved"] = auto and ("ambiguous" in case["case_categories"] or case["event_type"] == "UNRESOLVED")
        r["routing_kind"] = ("correct_auto" if auto and case["expected_routing"] == "AUTO_APPROVE" else
                             "correct_review" if not auto and case["expected_routing"] == "REVIEW_REQUIRED" else
                             "false_approval" if auto else "false_review")
        # qualificadores: GT material capturado se alguma citação material da E sobrepõe a evidência do gabarito,
        # ou (base do IR) se o campo representa a base esperada
        sem = rec.get("semantic") or {}
        e_mat = [q for q in sem.get("material_qualifiers", [])]
        caught = []
        for q in case.get("material_qualifiers", []):
            ev = re.sub(r"\s+", " ", q["evidence"])
            hit = any(x.get("quote") and (re.sub(r"\s+", " ", x["quote"]) in ev or ev in re.sub(r"\s+", " ", x["quote"])) for x in e_mat)
            if q["affects"] == "tax_base" and case["fields"]["withholding_tax"]["status"] == "present":
                hit = hit or value_match("withholding_tax", case["fields"]["withholding_tax"], _got_field(rec, "withholding_tax"))
            caught.append({"affects": q["affects"], "captured": hit})
        r["gt_material_qualifiers"] = caught
        r["e_material_qualifiers"] = [{k: x.get(k) for k in ("kind", "affects", "blocks", "source", "quote")} for x in e_mat]
        r["e_semantic_notes"] = len(sem.get("semantic_notes", []))
        g = ((rec.get("llm") or {}).get("grounding") or {})
        tot["grounded"][0] += g.get("grounded_quotes", 0)
        tot["grounded"][1] += g.get("total_quotes", 0)
        # oráculo de necessidade (sobre o run do B)
        if b_recs:
            b = b_recs[name]
            b_sem_err = not event_match(case["event_type"], (b.get("classification") or {}).get("event_type")) or any(
                gf["status"] == "present" and not value_match(fn, gf, _got_field(b, fn)) for fn, gf in case["fields"].items() if fn in SEMANTIC)
            b_reasons = set(b["routing"]["reason_codes"])
            missing = next((v["observed"].get("not_found", []) for v in b.get("validations", [])
                            if v["rule_id"] == "REQUIRED_FIELDS_PRESENT"), [])
            b_sem_review = case["expected_routing"] == "AUTO_APPROVE" and (bool(b_reasons & LLM_RESOLVABLE) or (
                "REQUIRED_FIELD_MISSING" in b_reasons and bool(set(missing) & DATE_FIELDS)))
            r["llm_needed"] = bool(b_sem_err or b_sem_review)
        rows.append(r)

    ratio = lambda a: {"correct": a[0], "total": a[1]}
    kinds = [r["routing_kind"] for r in rows]
    llm = [x["llm"] for x in recs.values() if "llm" in x]
    cost = sum((Decimal(x["estimated_cost_usd"]) for x in llm), Decimal(0))
    lat = sorted(x["audit"]["duration_us"] / 1000 for x in recs.values())
    lat_llm = sorted(x["audit"]["duration_us"] / 1000 for x in recs.values() if "llm" in x)
    lat_det = sorted(x["audit"]["duration_us"] / 1000 for x in recs.values() if "llm" not in x)
    med = lambda v: v[len(v) // 2] if v else None
    tool_calls = [t for x in llm for t in x["tool_calls"]]
    gt_by_file = {c["document_file"]: c for c in gt["cases"]}
    fc_correct = sum(1 for name, x in recs.items() if "llm" in x and any(
        t["name"] == "lookup_security" and (t["arguments"].get("identifier") or "").upper() in
        {(gt_by_file[name]["issuer"].get("isin") or "").upper(), (gt_by_file[name]["issuer"].get("ticker") or "").upper()} - {""}
        for t in x["llm"]["tool_calls"]))
    out = {
        "cases": len(rows),
        "safety": {"unsafe_auto_approvals": [r["case"] for r in rows if r["unsafe_auto_approval"]],
                   "unsafe_field_inventions": {r["case"]: r["invented"] for r in rows if r["invented"]},
                   "ambiguity_auto_approved": [r["case"] for r in rows if r["ambiguity_auto_approved"]],
                   "wrong_values_emitted": {r["case"]: r["wrong_emitted"] for r in rows if r["wrong_emitted"]}},
        "semantic": {"event_type": ratio([sum(r["type_ok"] for r in rows), len(rows)]),
                     "semantic_targets_incl_event_type": ratio(tot["semantic"]),
                     "gt_material_qualifiers_captured": ratio([sum(q["captured"] for r in rows for q in r["gt_material_qualifiers"]),
                                                               sum(len(r["gt_material_qualifiers"]) for r in rows)])},
        "deterministic": {"values_and_ratios": ratio(tot["deterministic"]), "identifiers": ratio(tot["identifiers"]),
                          "field_status": ratio(tot["status"]),
                          "objective_rules": {**ratio(tot["rules"]), "false_negatives": fn_rules, "false_positives": fp_rules}},
        "routing": {"correct_auto": kinds.count("correct_auto"), "correct_review": kinds.count("correct_review"),
                    "false_reviews": [r["case"] for r in rows if r["routing_kind"] == "false_review"],
                    "false_approvals": [r["case"] for r in rows if r["routing_kind"] == "false_approval"],
                    "accuracy": ratio([kinds.count("correct_auto") + kinds.count("correct_review"), len(rows)]),
                    "review_rate": ratio([sum(r["got_routing"] != "AUTO_APPROVE" for r in rows), len(rows)])},
        "llm_usage": {"invoked": [r["case"] for r in rows if r["llm_invoked"]],
                      "invocation_rate": ratio([sum(r["llm_invoked"] for r in rows), len(rows)]),
                      "api_calls": sum(x["api_calls"] for x in llm),
                      "calls_per_invoked_document": round(sum(x["api_calls"] for x in llm) / len(llm), 2) if llm else None,
                      "tool_calls": len(tool_calls), "documents_with_correct_lookup": fc_correct,
                      "grounding": ratio(tot["grounded"]),
                      "ungrounded": [u for x in llm for u in (x.get("grounding") or {}).get("ungrounded", [])],
                      "reference_divergences": sum(bool((x.get("reference_divergence") or {}).get("divergent")) for x in llm)},
        "operational": {"estimated_cost_usd": str(cost), "input_tokens": sum(x["usage"]["input_tokens"] for x in llm),
                        "output_tokens": sum(x["usage"]["output_tokens"] for x in llm),
                        "latency_ms_median_all": med(lat), "latency_ms_median_with_llm": med(lat_llm),
                        "latency_ms_median_without_llm": med(lat_det),
                        "errors": sum(len(x["audit"]["errors"]) for x in recs.values()),
                        "llm_errors": sum(len(x["errors"]) for x in llm), "refusals": sum(len(x.get("refusals", [])) for x in llm),
                        "parse_or_schema_failures": sum(x["parse_or_schema_failures"] for x in llm)},
        "per_case": rows,
    }
    if b_recs:
        needed = {r["case"] for r in rows if r.get("llm_needed")}
        invoked = {r["case"] for r in rows if r["llm_invoked"]}
        out["llm_usage"].update(needed=sorted(needed), false_positive_invocations=sorted(invoked - needed),
                                false_negative_invocations=sorted(needed - invoked))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--b-run-dir", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate_blind(a.run_dir, a.b_run_dir)
    (a.out / "blind_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_case"}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
