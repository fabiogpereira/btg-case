"""Avaliação do E-004: B × C × D (qualidade e segurança) + eficiência do LLM sob demanda (H-25) e fusão v2 (H-26).

python -m evaluation.e004 --out DIR

Oráculo de necessidade (pré-registrado, sobre artefatos congelados do B no E-003):
  um documento PRECISAVA de LLM se o B (melhor determinístico)
    (a) errou algum alvo semântico (tipo de evento, IR com base, papéis de data), ou
    (b) foi para revisão por motivo semântico resolvível pelo LLM (SEMANTIC_AMBIGUITY, CLASSIFICATION_UNDETERMINED,
        CLASSIFICATION_DISAGREEMENT, ou REQUIRED_FIELD_MISSING de papel de data) quando a expectativa era AUTO_APPROVE.
  Invocação falso-positiva = D chamou sem necessidade; falso-negativa = precisava e D não chamou.
"""
import argparse
import json
import statistics
from decimal import Decimal
from pathlib import Path

from .challenge import evaluate_challenge
from .compare import SEMANTIC_FIELDS, evaluate
from .llm_metrics import consistency, expected_ids_challenge, expected_ids_original, function_calling

ROOT = Path(__file__).resolve().parents[2]
E003 = ROOT / "outputs" / "experiments" / "E-003_semantic"
E004 = ROOT / "outputs" / "experiments" / "E-004_hybrid"
GT_ORIG = ROOT / "tests" / "ground_truth"
GT_CH = ROOT / "tests" / "challenge_set"
LLM_RESOLVABLE_REASONS = {"SEMANTIC_AMBIGUITY", "CLASSIFICATION_UNDETERMINED", "CLASSIFICATION_DISAGREEMENT"}
DATE_ROLES = {"record_date", "ex_date", "payment_date", "share_credit_date"}


def _records(run_dir: Path) -> dict:
    return {r["document"]["sha256"]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def _semantic_review(rec) -> bool:
    reasons = set(rec["routing"]["reason_codes"])
    if reasons & LLM_RESOLVABLE_REASONS:
        return True
    if "REQUIRED_FIELD_MISSING" in reasons:
        missing = next((v["observed"].get("not_found", []) for v in rec.get("validations", [])
                        if v["rule_id"] == "REQUIRED_FIELDS_PRESENT"), [])
        return bool(set(missing) & DATE_ROLES)
    return False


def need_oracle_original() -> dict:
    m = evaluate(GT_ORIG, E003 / "original_B")
    recs = _records(E003 / "original_B")
    out = {}
    for d in m["per_document"]:
        if not d["text_layer_usable"]:
            continue
        wrong = [k for k, f in d["fields"].items() if k in SEMANTIC_FIELDS and f["expected_status"] in ("found", "declared_pending")
                 and not (f["status_match"] and f["value_match"] is not False)]
        if not d["event_type"]["match"]:
            wrong.append("event_type")
        false_sem_review = d["routing"]["expected"] == "AUTO_APPROVE" and _semantic_review(recs[d["sha256"]])
        out[d["sha256"]] = {"document": d["document"], "needed": bool(wrong or false_sem_review),
                            "b_semantic_errors": wrong, "b_false_semantic_review": false_sem_review}
    return out


def need_oracle_challenge() -> dict:
    m = evaluate_challenge(GT_CH, E003 / "challenge_B")
    gt = json.loads((GT_CH / "ground_truth.json").read_text(encoding="utf-8"))
    recs = _records(E003 / "challenge_B")
    out = {}
    for case, row in zip(gt["cases"], m["cases"]):
        wrong = [t["target"] for t in row["targets"] if not t["correct"]]
        false_sem_review = case["routing"]["decision"] == "AUTO_APPROVE" and _semantic_review(recs[case["sha256"]])
        out[case["sha256"]] = {"document": case["id"], "needed": bool(wrong or false_sem_review),
                               "b_semantic_errors": wrong, "b_false_semantic_review": false_sem_review}
    return out


def _latency_stats(values_us):
    if not values_us:
        return None
    ms = sorted(v / 1000 for v in values_us)
    return {"n": len(ms), "mean_ms": round(statistics.fmean(ms), 1), "p50_ms": round(statistics.median(ms), 1),
            "max_ms": round(ms[-1], 1)}


def efficiency(run_dir: Path, oracle: dict, expected_ids: dict) -> dict:
    recs = _records(run_dir)
    eligible = {sha: r for sha, r in recs.items() if (r["document"].get("text_layer") or {}).get("usable")}
    invoked = {sha for sha, r in eligible.items() if "llm" in r}
    needed = {sha for sha, o in oracle.items() if o["needed"]}
    cost = sum((Decimal(r["llm"]["estimated_cost_usd"]) for r in recs.values() if "llm" in r), Decimal(0))
    tool_calls = sum(len(r["llm"]["tool_calls"]) for r in recs.values() if "llm" in r)
    api_calls = sum(r["llm"]["api_calls"] for r in recs.values() if "llm" in r)
    e2e = {sha: r["audit"]["duration_us"] for sha, r in recs.items()}
    name = lambda sha: oracle.get(sha, {}).get("document") or recs[sha]["document"]["file_name"]
    fc = function_calling(run_dir, {sha: expected_ids[sha] for sha in invoked if sha in expected_ids})
    return {
        "total_documents": len(recs), "eligible_documents": len(eligible),
        "invoked_documents": len(invoked),
        "invocation_rate_eligible": f"{len(invoked)}/{len(eligible)}",
        "correctly_invoked": sorted(name(s) for s in invoked & needed),
        "correctly_skipped": sorted(name(s) for s in (set(eligible) - invoked) - needed),
        "false_positive_invocations": sorted(name(s) for s in invoked - needed),
        "false_negative_invocations": sorted(name(s) for s in needed - invoked),
        "trigger_reasons": {name(s): recs[s]["semantic_need"]["llm_trigger_reasons"] for s in eligible
                            if recs[s].get("semantic_need")},
        "llm_api_calls": api_calls, "tool_calls": tool_calls,
        "tool_calls_per_processed_document": round(tool_calls / len(recs), 3) if recs else None,
        "tool_calls_per_llm_document": round(tool_calls / len(invoked), 3) if invoked else None,
        "estimated_cost_usd": str(cost),
        "cost_per_input_document_usd": str(cost / len(recs)) if recs else None,
        "cost_per_llm_document_usd": str(cost / len(invoked)) if invoked else None,
        "latency_end_to_end_all": _latency_stats(list(e2e.values())),
        "latency_end_to_end_with_llm": _latency_stats([e2e[s] for s in invoked]),
        "latency_end_to_end_without_llm": _latency_stats([e2e[s] for s in e2e if s not in invoked]),
        "function_calling_invoked_docs": fc,
    }


def quality(variant_dirs_orig: dict, variant_dirs_ch: dict) -> dict:
    out = {"original": {}, "challenge": {}}
    for v, d in variant_dirs_orig.items():
        m = evaluate(GT_ORIG, d)
        out["original"][v] = {
            "event_type": m["extraction"]["event_type_accuracy"]["with_text_layer"],
            "semantic_targets": m["semantic"]["semantic_targets"]["with_text_layer"],
            "value_exact": m["extraction"]["fields"]["with_text_layer"]["value_exact_match"],
            "validation": m["validation"]["with_text_layer"],
            "routing_defined": m["routing"]["defined_expectations"], "review_rate": m["routing"]["review_rate"],
            "unsafe_auto_approvals": [u["document"] for u in m["semantic"]["unsafe_auto_approvals"]],
            "invented_values": len(m["extraction"]["invented_values"]),
            "routing_rows": m["routing"]["rows"]}
    for v, d in variant_dirs_ch.items():
        m = evaluate_challenge(GT_CH, d)
        out["challenge"][v] = {k: m[k] for k in (
            "semantic_accuracy", "negation_accuracy", "conditional_expression_accuracy", "date_role_mapping_accuracy",
            "misleading_keywords_accuracy", "event_description_accuracy", "false_confident_interpretations",
            "wrong_but_flagged", "unsafe_auto_approvals", "routing_defined", "review_rate")}
        out["challenge"][v]["cases"] = [{"case": c["case"], "correct": [t["correct"] for t in c["targets"]],
                                         "decision": c["decision"], "reasons": c["reason_codes"]} for c in m["cases"]]
    return out


def c_baseline_efficiency(run_dir: Path) -> dict:
    recs = _records(run_dir)
    cost = sum((Decimal(r["llm"]["estimated_cost_usd"]) for r in recs.values() if "llm" in r), Decimal(0))
    invoked = [r for r in recs.values() if "llm" in r]
    return {"total_documents": len(recs), "invoked_documents": len(invoked), "estimated_cost_usd": str(cost),
            "cost_per_input_document_usd": str(cost / len(recs)),
            "llm_api_calls": sum(r["llm"]["api_calls"] for r in invoked),
            "tool_calls": sum(len(r["llm"]["tool_calls"]) for r in invoked),
            "latency_end_to_end_all": _latency_stats([r["audit"]["duration_us"] for r in recs.values()])}


def invocation_consistency(run1: Path, run2: Path) -> dict:
    a, b = _records(run1), _records(run2)
    shas = sorted(set(a) & set(b))
    inv = [("llm" in a[s]) == ("llm" in b[s]) for s in shas]
    dec = [a[s]["routing"]["decision"] == b[s]["routing"]["decision"] for s in shas]
    return {"documents": len(shas), "invocation_decision_consistent": sum(inv), "routing_decision_consistent": sum(dec),
            "llm_docs": consistency(run1, run2)}


def routing_analysis(dataset: str, ids: list[str]) -> list[dict]:
    """Casos de revisão do C (E-003): o que B, C e D fizeram e por quê."""
    folder = {"original": ("original_B", "original_C", "original_D"), "challenge": ("challenge_B", "challenge_C", "challenge_D")}[dataset]
    b, c = _records(E003 / folder[0]), _records(E003 / folder[1])
    d = _records(E004 / folder[2])
    rows = []
    for sha, rc in c.items():
        name = rc["document"]["file_name"]
        if not any(name.startswith(i) for i in ids):
            continue
        rd = d[sha]
        rows.append({
            "document": name,
            "B": {"decision": b[sha]["routing"]["decision"], "reasons": b[sha]["routing"]["reason_codes"],
                  "event_type": (b[sha].get("classification") or {}).get("event_type")},
            "C": {"decision": rc["routing"]["decision"], "reasons": rc["routing"]["reason_codes"],
                  "explanations": rc["routing"]["explanations"],
                  "llm_event": rc["llm"]["interpretation"]["event"]["type"],
                  "llm_tax": {k: rc["llm"]["interpretation"]["withholding_tax"][k] for k in ("status", "rate_as_written", "base")},
                  "llm_qualifiers": rc["llm"]["interpretation"]["withholding_tax"]["qualifiers"]},
            "D": {"decision": rd["routing"]["decision"], "reasons": rd["routing"]["reason_codes"],
                  "llm_invoked": "llm" in rd, "triggers": (rd.get("semantic_need") or {}).get("llm_trigger_reasons"),
                  "resolutions": (rd.get("semantic") or {}).get("resolutions"),
                  "qualifiers_v2": [{k: q[k] for k in ("qualifier_type", "affects", "materiality", "blocks", "quote", "source")}
                                    for q in (rd.get("semantic") or {}).get("qualifiers_v2", [])]},
        })
    return rows


def _r(x):
    return "—" if not x or not x.get("total") else f"{x['correct']}/{x['total']}"


def render(res: dict) -> str:
    q, L = res["quality"], ["# E-004 — B × C × D (hybrid on demand)", "",
                            "B e C: artefatos congelados do E-003. D: execução 1 do E-004. Dataset original é conjunto de "
                            "**desenvolvimento** (não out-of-sample); challenge set é **ciente do autor** e seus resultados do E-003 "
                            "eram conhecidos no desenho da D (disclosure no evaluation log).", ""]
    for ds, rows in (("original", [("Tipo de evento", "event_type"), ("Campos semânticos", "semantic_targets"),
                                   ("Valor exato", "value_exact"), ("Roteamento DEFINED", "routing_defined"),
                                   ("Taxa de revisão", "review_rate")]),
                     ("challenge", [("Acurácia semântica", "semantic_accuracy"), ("Papel de data", "date_role_mapping_accuracy"),
                                    ("Negação", "negation_accuracy"), ("Qualificador / IR condicional", "conditional_expression_accuracy"),
                                    ("Palavras enganosas", "misleading_keywords_accuracy"), ("Descrição do evento", "event_description_accuracy"),
                                    ("Roteamento DEFINED", "routing_defined"), ("Taxa de revisão", "review_rate")])):
        vs = list(q[ds])
        L += [f"## {ds}", "", "| Métrica | " + " | ".join(vs) + " |", "|---|" + "---|" * len(vs)]
        for label, key in rows:
            L.append(f"| {label} | " + " | ".join(_r(q[ds][v][key]) for v in vs) + " |")
        if ds == "original":
            L.append("| Regras de validação | " + " | ".join(_r(q[ds][v]["validation"]["accuracy"]) for v in vs) + " |")
            L.append("| **Aprovações inseguras** | " + " | ".join(f"**{len(q[ds][v]['unsafe_auto_approvals'])}** {q[ds][v]['unsafe_auto_approvals'] or ''}" for v in vs) + " |")
            L.append("| Valores inventados | " + " | ".join(str(q[ds][v]["invented_values"]) for v in vs) + " |")
        else:
            L.append("| Falsamente confiantes | " + " | ".join(str(q[ds][v]["false_confident_interpretations"]) for v in vs) + " |")
            L.append("| **Aprovações inseguras** | " + " | ".join(f"**{len(q[ds][v]['unsafe_auto_approvals'])}** {q[ds][v]['unsafe_auto_approvals'] or ''}" for v in vs) + " |")
        L.append("")
    for ds in ("original", "challenge"):
        e, c = res["efficiency"][ds], res["c_efficiency"][ds]
        L += [f"## Eficiência — {ds}", "", "| | C (sempre) | D (sob demanda) |", "|---|---|---|",
              f"| Documentos / elegíveis | {c['total_documents']} | {e['total_documents']} / {e['eligible_documents']} |",
              f"| Documentos com LLM | {c['invoked_documents']} | {e['invoked_documents']} ({e['invocation_rate_eligible']}) |",
              f"| Chamadas de API / tool calls | {c['llm_api_calls']} / {c['tool_calls']} | {e['llm_api_calls']} / {e['tool_calls']} |",
              f"| Custo total (US$) | {Decimal(c['estimated_cost_usd']):.4f} | {Decimal(e['estimated_cost_usd']):.4f} |",
              f"| Custo por documento de entrada (US$) | {Decimal(c['cost_per_input_document_usd']):.4f} | {Decimal(e['cost_per_input_document_usd']):.4f} |",
              f"| Custo por documento com LLM (US$) | — | {Decimal(e['cost_per_llm_document_usd']):.4f} |" if e["cost_per_llm_document_usd"] else "| Custo por documento com LLM | — | — |",
              f"| Latência fim a fim média / p50 (ms) | {c['latency_end_to_end_all']['mean_ms']} / {c['latency_end_to_end_all']['p50_ms']} | {e['latency_end_to_end_all']['mean_ms']} / {e['latency_end_to_end_all']['p50_ms']} |",
              f"| Latência D com LLM média / p50 (ms) | — | {(e['latency_end_to_end_with_llm'] or {}).get('mean_ms')} / {(e['latency_end_to_end_with_llm'] or {}).get('p50_ms')} |",
              f"| Latência D sem LLM média / p50 (ms) | — | {(e['latency_end_to_end_without_llm'] or {}).get('mean_ms')} / {(e['latency_end_to_end_without_llm'] or {}).get('p50_ms')} |",
              f"| Tool calls por documento processado / por documento com LLM | — | {e['tool_calls_per_processed_document']} / {e['tool_calls_per_llm_document']} |",
              "", f"- Invocadas corretamente: {', '.join(e['correctly_invoked']) or '—'}",
              f"- Puladas corretamente: {', '.join(e['correctly_skipped']) or '—'}",
              f"- **Invocações falso-positivas:** {', '.join(e['false_positive_invocations']) or '—'}",
              f"- **Invocações falso-negativas:** {', '.join(e['false_negative_invocations']) or '—'}",
              "- Gatilhos por documento: " + "; ".join(f"{k}: {', '.join(v) or '—'}" for k, v in e["trigger_reasons"].items()),
              f"- Function calling (só documentos com LLM): {json.dumps({k: v for k, v in e['function_calling_invoked_docs'].items() if k not in ('details', 'missing_in')}, ensure_ascii=False)}", ""]
        cons = res.get("consistency", {}).get(ds)
        if cons:
            ld = cons["llm_docs"]
            L += [f"Consistência D execução 1 × 2 ({ds}): decisão de invocar {cons['invocation_decision_consistent']}/{cons['documents']}; "
                  f"roteamento {cons['routing_decision_consistent']}/{cons['documents']}; nos documentos com LLM: "
                  + ", ".join(f"{k} {ld[k]['consistent']}/{ld[k]['total']}" for k in ("event_type", "semantic_fields", "llm_interpretation",
                                                                                       "routing_decision", "tool_call_count", "tool_arguments")), ""]
    return "\n".join(L) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=E004 / "comparison")
    p.add_argument("--with-run2", action="store_true")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    oracle = {"original": need_oracle_original(), "challenge": need_oracle_challenge()}
    ids = {"original": expected_ids_original(), "challenge": expected_ids_challenge()}
    res = {
        "need_oracle": oracle,
        "quality": quality({"B": E003 / "original_B", "C": E003 / "original_C", "D": E004 / "original_D"},
                           {"B": E003 / "challenge_B", "C": E003 / "challenge_C", "D": E004 / "challenge_D"}),
        "efficiency": {ds: efficiency(E004 / f"{ds}_D", oracle[ds], ids[ds]) for ds in ("original", "challenge")},
        "c_efficiency": {ds: c_baseline_efficiency(E003 / f"{ds}_C") for ds in ("original", "challenge")},
        "routing_analysis": {"original": routing_analysis("original", ["01_", "02_", "03_"]),
                             "challenge": routing_analysis("challenge", ["CH-01", "CH-06", "CH-09", "CH-10", "CH-11"])},
    }
    if a.with_run2:
        res["consistency"] = {ds: invocation_consistency(E004 / f"{ds}_D", E004 / f"{ds}_D_run2") for ds in ("original", "challenge")}
    (a.out / "e004_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (a.out / "e004_report.md").write_text(render(res), encoding="utf-8")
    print(f"written: {a.out}")


if __name__ == "__main__":
    main()
