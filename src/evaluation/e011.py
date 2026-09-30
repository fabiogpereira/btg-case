"""E-011 — integração final (variante K). Avaliação definida antes do run final.

python -m evaluation.e011 regress-run  --out outputs/experiments/E-011_final_integration/regression
python -m evaluation.e011 regress-eval --out outputs/experiments/E-011_final_integration/regression/evaluation
python -m corporate_actions --variant K --out outputs/experiments/E-011_final_integration/final_run \
    --llm-cache outputs/experiments/E-011_final_integration/final_run/llm_cache \
    --vision-cache outputs/experiments/E-011_final_integration/final_run/vision_cache
python -m evaluation.e011 final-eval  --out outputs/experiments/E-011_final_integration/final_run/evaluation

- Regressão K × J (replay, quatro conjuntos, texto nativo): mesmos campos, roteamento, identidade e bindings; K só
  acrescenta `perception` e `run_summary`. Qualquer outra diferença é regressão.
- Run final: os 8 PDFs do case, com a solução final (percepção automática, LLM semântico real, caches novos).
  Por documento: caminho de percepção, LLM semântico chamado?, vision chamado?, roteamento, latência, custo.
  Agregado: % nativo / OCR / vision, % LLM semântico, custo total e médio, latência total, taxa de revisão.
  Segurança contra o gabarito v2.1: enhanced unsafe, omissões aprovadas, bindings errados, identidade errada.
  O lote do case NÃO é distribuição de produção.
- Critérios de conclusão (seção 18 do pedido), verificáveis aqui: 8 documentos ponta a ponta sem erro técnico; doc 07
  por OCR -> vision auditável; unsafe 0; bindings errados 0; aprovação com identidade errada 0; omissão material aprovada
  0; nenhuma aprovação sem validações determinísticas executadas; custo e latência registrados.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .e007 import DATASETS, ReplayProvider, _records, evaluate_variant, truths

ROOT = Path(__file__).resolve().parents[2]
E10R = ROOT / "outputs" / "experiments" / "E-010_vision_stability_uncertainty" / "regression"
E11 = ROOT / "outputs" / "experiments" / "E-011_final_integration"
MANDATORY_GROUPS = {"REF_", "REQUIRED_FIELDS_PRESENT", "CLASSIFICATION_DETERMINED", "DATE_"}


def regress_run(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    for name, (docs, golden, cache, _) in DATASETS.items():
        provider = ReplayProvider()
        m = run_batch(docs, golden, out / f"{name}_K", run_id=f"e011-replay-{name}", variant="K",
                      semantic_ctx=SemanticContext(provider, ResponseCache(cache)))
        print(name, m["summary"]["decisions"], "cache_misses:", provider.misses)


def _core(r):
    val = {n: (v["status"], v.get("value")) for s in ("fields", "event_specific_fields") for n, v in (r.get(s) or {}).items()}
    ident = ((r.get("identity") or {}).get("identity_method"), ((r.get("identity") or {}).get("matched_reference") or {}).get("isin"))
    binding = [(b["field"], b["raw"], b["decision"], b["reason"]) for b in r.get("binding", [])]
    return val, (r["routing"]["decision"], r["routing"]["reason_codes"]), ident, binding, [v["rule_id"] + ":" + v["status"] for v in r.get("validations", [])]


def regress_eval(k_dir: Path) -> dict:
    res = {"J": {}, "K": {}, "differences": {}}
    for name in DATASETS:
        jd, kd = E10R / f"{name}_J", k_dir / f"{name}_K"
        res["J"][name], res["K"][name] = evaluate_variant(name, jd), evaluate_variant(name, kd)
        tr, key = truths(name)
        j, k = _records(jd, key), _records(kd, key)
        for doc, truth in tr.items():
            if _core(j[doc]) != _core(k[doc]):
                res["differences"].setdefault(name, []).append(truth["id"])
            if "perception" not in k[doc] or "run_summary" not in k[doc]:
                res["differences"].setdefault(name, []).append(f"{truth['id']}:missing_final_sections")
    K = res["K"]
    res["checks"] = {"unsafe_zero": all(not K[d]["safety"]["unsafe_auto_approvals_enhanced"] for d in K),
                     "wrong_bindings_zero": all(not K[d]["binding"]["wrong_bindings_any_routing"] for d in K),
                     "wrong_identity_approvals_zero": all(not K[d]["safety"]["wrong_identity_approvals"] for d in K),
                     "material_omissions_approved_zero": all(not K[d]["safety"]["material_omissions_approved"] for d in K),
                     "identical_to_J": not res["differences"]}
    return res


def final_eval(run_dir: Path) -> dict:
    tr, _ = truths("original")
    recs = _records(run_dir, "sha256")
    base = evaluate_variant("original", run_dir)
    rows = []
    for sha, rec in sorted(recs.items(), key=lambda kv: kv[1]["document"]["file_name"]):
        s = rec["run_summary"]
        validations = [v["rule_id"] for v in rec.get("validations", [])]
        rows.append({"document": rec["document"]["file_name"], "perception_path": s["perception_path"],
                     "perception_decision": (rec.get("perception") or {}).get("decision"),
                     "ocr_called": s["ocr_called"], "vision_called": s["vision_called"],
                     "semantic_llm_called": s["semantic_llm_called"], "semantic_triggers": s["semantic_llm_trigger_reasons"],
                     "tool_calls": s["tool_calls"], "decision": s["decision"], "reason_codes": s["reason_codes"],
                     "latency_ms": s["duration_ms"]["total"], "cost_usd": s["estimated_cost_usd"],
                     "uncertainty": {n: {k: f[k] for k in ("corroboration_status", "corroboration_source", "blocking_reason")}
                                     for n, f in ((rec.get("perception_uncertainty") or {}).get("fields") or {}).items() if f["vision_uncertain"]},
                     "mandatory_validations_executed": all(any(v.startswith(g) for v in validations) for g in MANDATORY_GROUPS)
                     if rec.get("extraction", {}).get("status") == "COMPLETED" else None,
                     "errors": s["errors"]})
    n = len(rows)
    paths = [r["perception_path"] for r in rows]
    total = sum((Decimal(r["cost_usd"]["total"]) for r in rows), Decimal(0))
    doc07 = next(r for r in rows if r["document"].startswith("07_"))
    approved = [r for r in rows if r["decision"] == "AUTO_APPROVE"]
    agg = {"documents": n, "native_pct": round(100 * paths.count("NATIVE_TEXT") / n, 1), "ocr_pct": round(100 * sum(r["ocr_called"] for r in rows) / n, 1),
           "vision_fallback_pct": round(100 * paths.count("VISION_FALLBACK") / n, 1),
           "semantic_llm_pct": round(100 * sum(r["semantic_llm_called"] for r in rows) / n, 1),
           "total_cost_usd": str(total), "avg_cost_per_document_usd": str(total / n),
           "cost_by_role_usd": {"perception": str(sum((Decimal(r["cost_usd"]["perception"]) for r in rows), Decimal(0))),
                                "semantic_llm": str(sum((Decimal(r["cost_usd"]["semantic_llm"]) for r in rows), Decimal(0)))},
           "total_latency_ms": sum(r["latency_ms"] for r in rows), "review_rate": f"{sum(r['decision'] != 'AUTO_APPROVE' for r in rows)}/{n}",
           "note": "lote fornecido pelo case; não é distribuição de produção"}
    safety = {**{k: v for k, v in base["safety"].items() if k != "detail"},
              "wrong_bindings_any_routing": base["binding"]["wrong_bindings_any_routing"],
              "routing_vs_ground_truth": base["utility"]}
    checks = {"1_end_to_end_all_8": n == 8 and all(not r["errors"] for r in rows),
              "2_doc07_ocr_then_vision_audited": doc07["ocr_called"] and doc07["perception_path"] == "VISION_FALLBACK"
                                                 and bool((doc07["perception_decision"] or {}).get("fallback_reasons")),
              "3_unsafe_zero": not safety["unsafe_auto_approvals_enhanced"],
              "4_wrong_bindings_zero": not safety["wrong_bindings_any_routing"],
              "5_wrong_identity_approval_zero": not safety["wrong_identity_approvals"],
              "6_material_omissions_approved_zero": not safety["material_omissions_approved"],
              "7_approvals_only_with_mandatory_validations": all(r["mandatory_validations_executed"] for r in approved),
              "10_cost_and_latency_recorded": all(r["cost_usd"] and r["latency_ms"] is not None for r in rows)}
    return {"per_document": rows, "aggregate": agg, "safety": safety, "checks": checks}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["regress-run", "regress-eval", "final-eval"])
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "regress-run":
        regress_run(a.out)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "regress-eval":
        res, name, keys = regress_eval(E11 / "regression"), "e011_regression.json", ("checks", "differences")
    else:
        res, name, keys = final_eval(E11 / "final_run"), "e011_final.json", ("aggregate", "checks")
    (a.out / name).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in keys}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
