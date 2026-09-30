"""E-010 — estabilidade do vision (2ª execução independente) e política de incerteza crítica (variante J).
PRÉ-REGISTRADO antes da regressão da J e antes da 2ª execução do vision.

python -m evaluation.e010 regress-run  --out outputs/experiments/E-010_vision_stability_uncertainty/regression
python -m evaluation.e010 regress-eval --out outputs/experiments/E-010_vision_stability_uncertainty/regression/evaluation
python -m evaluation.e010 vision-run2  --out outputs/experiments/E-010_vision_stability_uncertainty/vision_run2_I
python -m evaluation.e010 policy-run   --out outputs/experiments/E-010_vision_stability_uncertainty/policy_J
python -m evaluation.e010 report       --out outputs/experiments/E-010_vision_stability_uncertainty/evaluation

- Regressão J × I (replay sem rede, quatro conjuntos): mesmos critérios do E-009. Mudança de roteamento precisa ser
  explicada pela nova regra (J só age quando a percepção declara tokens incertos; texto nativo e OCR local não declaram).
- 2ª execução do vision: configuração congelada do E-009 (mesmo modelo, prompt, fingerprint, DPI, sem ferramentas,
  sem referência, fallback off), cache NOVO; passada pela MESMA pipeline I do E-009 (LLM semântico com cache novo).
- Estabilidade run 1 × run 2 (via pipeline I): concordância exata por campo crítico; concordância de dígitos nos
  tokens críticos como escritos; similaridade do texto bruto; concordância dos tokens incertos; concordância de
  roteamento.
- Política (J) nas duas transcrições, por replay (sem nova chamada): campos exatos, incertos, corroborados, não
  corroborados, validação, roteamento, diferença em relação ao E-009.

Critério de prontidão (pré-registrado):
- R1 regressão J × I aprovada; R2 run 2 sem dígito errado em token crítico e sem valor de campo errado;
- R3 campos críticos idênticos entre run 1 e run 2; R4 J nas duas execuções: 0 aprovação insegura e todo campo crítico
  incerto corroborado ou bloqueando; R5 mesmo roteamento sob a J nas duas execuções.
- R1, R2 ou R4 falhando -> "INVESTIGAR ANTES"; todos atendidos -> "PRONTO PARA INTEGRAÇÃO FINAL";
  só R3/R5 falhando (variação fail-safe) -> "PRONTO COM RESSALVA (variação fail-safe; medir em mais scans)".
"""
import argparse
import difflib
import json
from pathlib import Path

from .e007 import DATASETS, ReplayProvider, _records, evaluate_variant, truths
from .e008 import binding_v2_stats
from .e008_ocr import CASE, _norm, evaluate as evaluate_perception

ROOT = Path(__file__).resolve().parents[2]
E9 = ROOT / "outputs" / "experiments" / "E-009_ocr_vs_vision"
E10 = ROOT / "outputs" / "experiments" / "E-010_vision_stability_uncertainty"
DOC07 = CASE / "documents" / "07_telecom_norte_jcp_SCAN.pdf"
RUNS = {"run1": {"vision_cache": E9 / "vision_cache_run1", "pipeline_cache": E9 / "pipeline_llm_cache_run1", "I_dir": E9 / "arm_B_vision"},
        "run2": {"vision_cache": E10 / "vision_cache_run2", "pipeline_cache": E10 / "pipeline_llm_cache_run2", "I_dir": E10 / "vision_run2_I"}}


def regress_run(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    for name, (docs, golden, cache, _) in DATASETS.items():
        provider = ReplayProvider()
        m = run_batch(docs, golden, out / f"{name}_J", run_id=f"e010-replay-{name}", variant="J",
                      semantic_ctx=SemanticContext(provider, ResponseCache(cache)))
        print(name, m["summary"]["decisions"], "cache_misses:", provider.misses)


def regress_eval(j_dir: Path) -> dict:
    res = {"I": {}, "J": {}, "identity_changes": {}, "routing_changes": {}, "field_changes": {}}
    for name in DATASETS:
        i_dir, jd = E9 / "regression" / f"{name}_I", j_dir / f"{name}_J"
        for v, d in (("I", i_dir), ("J", jd)):
            res[v][name] = evaluate_variant(name, d)
            res[v][name]["binding"] = {**binding_v2_stats(name, d), "wrong_bindings_any_routing": res[v][name]["binding"]["wrong_bindings_any_routing"]}
        tr, key = truths(name)
        i_recs, j_recs = _records(i_dir, key), _records(jd, key)
        for k, truth in tr.items():
            ident = lambda r: ((r.get("identity") or {}).get("identity_method"), ((r.get("identity") or {}).get("matched_reference") or {}).get("isin"))
            if ident(i_recs[k]) != ident(j_recs[k]):
                res["identity_changes"].setdefault(name, []).append(truth["id"])
            if (i_recs[k]["routing"]["decision"], i_recs[k]["routing"]["reason_codes"]) != (j_recs[k]["routing"]["decision"], j_recs[k]["routing"]["reason_codes"]):
                res["routing_changes"].setdefault(name, []).append({"id": truth["id"], "I": i_recs[k]["routing"]["reason_codes"],
                                                                   "J": j_recs[k]["routing"]["reason_codes"],
                                                                   "uncertainty": j_recs[k].get("perception_uncertainty")})
            val = lambda r: {n: (v["status"], v.get("value")) for s in ("fields", "event_specific_fields") for n, v in (r.get(s) or {}).items()}
            if val(i_recs[k]) != val(j_recs[k]):
                res["field_changes"].setdefault(name, []).append(truth["id"])
    J = res["J"]
    res["success_criteria"] = {
        "1_enhanced_unsafe_zero": all(not J[d]["safety"]["unsafe_auto_approvals_enhanced"] for d in J),
        "2_wrong_bindings_zero": all(not J[d]["binding"]["wrong_bindings_any_routing"] for d in J),
        "3_identity_unchanged": not res["identity_changes"],
        "4_no_material_regression_original": "original" not in res["field_changes"] and "original" not in res["routing_changes"],
        "5_no_unexplained_routing_change": all(c["uncertainty"] for cs in res["routing_changes"].values() for c in cs)}
    res["passes"] = all(res["success_criteria"].values())
    return res


def _process(variant, vision_cache, pipeline_cache, allow_vision_api, live_llm, artifacts):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.llm.config import llm_config_from_env
    from corporate_actions.llm.registry import get_provider
    from corporate_actions.models import to_jsonable
    from corporate_actions.pipeline import SemanticContext, process_document
    from corporate_actions.reference import load_golden_records
    from perception.vision_transcriber import VisionTranscriber
    config = llm_config_from_env()
    assert (config.model, config.effort, config.fallbacks) == ("claude-opus-5", "medium", "off"), "configuração diferente da congelada"
    provider = get_provider(config) if live_llm else ReplayProvider()
    vision = VisionTranscriber(cache_dir=vision_cache, artifacts_dir=artifacts, allow_api=allow_vision_api)
    rec = to_jsonable(process_document(DOC07, load_golden_records(CASE / "golden_records" / "golden records.csv"),
                                       f"e010-{variant}", variant, SemanticContext(provider, ResponseCache(pipeline_cache)),
                                       text_fallback=vision))
    return rec, vision


def _write(out, rec, extra):
    (out / "records").mkdir(parents=True, exist_ok=True)
    (out / "records" / f"{DOC07.stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "config.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def vision_run2(out: Path):
    """2ª execução oficial: cache de vision NOVO (chamada real), mesma pipeline I, LLM semântico com cache novo."""
    assert not RUNS["run2"]["vision_cache"].exists(), "cache da run 2 já existe: não repetir a execução oficial"
    rec, vision = _process("I", RUNS["run2"]["vision_cache"], RUNS["run2"]["pipeline_cache"], True, True, out / "artifacts")
    _write(out, rec, {"run": "run2", "vision": vision.describe(), "vision_api_calls": vision.api_calls, "pipeline_variant": "I"})
    print("run2 via I:", rec["routing"]["decision"], rec["routing"]["reason_codes"], "vision api calls:", vision.api_calls)


def policy_run(out: Path):
    """Política J nas duas transcrições, por replay (vision e LLM semântico sem rede)."""
    for run, cfg in RUNS.items():
        rec, vision = _process("J", cfg["vision_cache"], cfg["pipeline_cache"], False, False, out / run / "artifacts")
        _write(out / run, rec, {"run": run, "vision": vision.describe(), "vision_api_calls": vision.api_calls, "pipeline_variant": "J"})
        print(run, "via J:", rec["routing"]["decision"], rec["routing"]["reason_codes"])


def _text(rec):
    fb = rec["document"].get("text_fallback") or {}
    return "\n".join((ROOT / a["raw_text_path"]).read_text(encoding="utf-8") for a in fb.get("page_artifacts", []))


def report(out: Path) -> dict:
    view = {run: evaluate_perception(cfg["I_dir"]) for run, cfg in RUNS.items()}
    recs = {run: next(json.loads(p.read_text(encoding="utf-8")) for p in (cfg["I_dir"] / "records").glob("*.json")) for run, cfg in RUNS.items()}
    texts = {run: _text(r) for run, r in recs.items()}
    unc = {run: sorted(t["token"] for t in (r["document"]["text_fallback"].get("uncertain_tokens") or [])) for run, r in recs.items()}
    fields = {n: {"run1": view["run1"]["fields"][n]["got"], "run2": view["run2"]["fields"][n]["got"],
                  "agree": view["run1"]["fields"][n]["got"] == view["run2"]["fields"][n]["got"],
                  "run1_vs_gt": view["run1"]["fields"][n]["result"], "run2_vs_gt": view["run2"]["fields"][n]["result"]}
              for n in view["run1"]["fields"]}
    fields["event_type"] = {"run1": (recs["run1"].get("classification") or {}).get("event_type"),
                            "run2": (recs["run2"].get("classification") or {}).get("event_type")}
    fields["event_type"]["agree"] = fields["event_type"]["run1"] == fields["event_type"]["run2"]
    tokens = {n: {"run1": view["run1"]["critical_tokens_as_written"][n]["exact"], "run2": view["run2"]["critical_tokens_as_written"][n]["exact"]}
              for n in view["run1"]["critical_tokens_as_written"]}
    digits = {run: {"digits_total": sum(sum(c.isdigit() for c in t["expected"]) for t in view[run]["critical_tokens_as_written"].values()),
                    "digit_errors": {n: t.get("digit_positions_changed") for n, t in view[run]["critical_tokens_as_written"].items()
                                     if not t["exact"] and t.get("digit_positions_changed")}} for run in RUNS}
    s1, s2 = set(unc["run1"]), set(unc["run2"])
    policy = {}
    for run in RUNS:
        pdir = out.parent / "policy_J" / run
        r = next(json.loads(p.read_text(encoding="utf-8")) for p in (pdir / "records").glob("*.json"))
        pv = evaluate_perception(pdir)
        pu = r.get("perception_uncertainty") or {}
        policy[run] = {"routing": r["routing"]["decision"], "reason_codes": r["routing"]["reason_codes"],
                       "explanations": r["routing"]["explanations"],
                       "uncertain_fields": {n: {k: f[k] for k in ("uncertain_tokens", "critical_field", "corroboration_status",
                                                                    "corroboration_source", "reference_value", "blocking_reason")}
                                            for n, f in pu.get("fields", {}).items() if f["vision_uncertain"]},
                       "event_type_uncertainty": pu.get("event_type"),
                       "non_critical_uncertain_tokens": pu.get("non_critical_uncertain_tokens"),
                       "ignored_tokens": pu.get("ignored_non_alphanumeric_tokens"), "unlocated": pu.get("unlocated_uncertain_tokens"),
                       "fields_exact": sorted(n for n, f in pv["fields"].items() if f["result"] == "EXACT"),
                       "validation_mismatches": pv["pipeline"]["validation_mismatches"],
                       "unsafe_auto_approval_enhanced": pv["safety"]["unsafe_auto_approval_enhanced"],
                       "wrong_bindings": pv["safety"]["wrong_bindings"], "wrong_identity": pv["safety"]["wrong_identity"],
                       "llm_errors": pv["pipeline"]["llm_errors"]}
    regression = json.loads((out.parent / "regression" / "evaluation" / "e010_regression.json").read_text(encoding="utf-8"))
    r1 = regression["passes"]
    r2 = not digits["run2"]["digit_errors"] and not any(f["run2_vs_gt"] == "DIFFERENT" for n, f in fields.items() if n != "event_type")
    r3 = all(f["agree"] for f in fields.values())
    r4 = all(not p["unsafe_auto_approval_enhanced"] and all(u["corroboration_status"] == "EXACT_MATCH" or u["blocking_reason"]
                                                           for u in p["uncertain_fields"].values() if u["critical_field"])
             for p in policy.values())
    r5 = policy["run1"]["routing"] == policy["run2"]["routing"]
    decision = ("INVESTIGAR ANTES" if not (r1 and r2 and r4) else "PRONTO PARA INTEGRAÇÃO FINAL" if (r3 and r5)
                else "PRONTO COM RESSALVA (variação fail-safe; medir em mais scans)")
    usage = {run: recs[run]["document"]["text_fallback"].get("usage") for run in RUNS}
    cost = {run: str(recs[run]["document"]["text_fallback"].get("estimated_cost_usd")) for run in RUNS}
    latency = {run: recs[run]["document"]["text_fallback"].get("duration_ms") for run in RUNS}
    return {"fields": fields, "critical_tokens_exact": tokens, "digits": digits,
            "raw_text": {"char_similarity_run1_run2": round(difflib.SequenceMatcher(None, _norm(texts["run1"]), _norm(texts["run2"]), autojunk=False).ratio(), 4),
                         "identical": texts["run1"] == texts["run2"],
                         "line_diff": [l for l in difflib.unified_diff(texts["run1"].splitlines(), texts["run2"].splitlines(), "run1", "run2", lineterm="", n=0)]},
            "uncertainty": {"run1": unc["run1"], "run2": unc["run2"], "common": sorted(s1 & s2), "only_run1": sorted(s1 - s2),
                            "only_run2": sorted(s2 - s1), "jaccard": round(len(s1 & s2) / len(s1 | s2), 3) if s1 | s2 else 1.0},
            "routing_via_I": {run: [recs[run]["routing"]["decision"], recs[run]["routing"]["reason_codes"]] for run in RUNS},
            "policy_J": policy, "vision_usage": usage, "vision_cost_usd": cost, "vision_latency_ms": latency,
            "readiness": {"R1_regression": r1, "R2_run2_no_digit_or_value_error": r2, "R3_critical_fields_identical": r3,
                          "R4_policy_safe_both_runs": r4, "R5_same_routing_under_J": r5, "decision": decision}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["regress-run", "regress-eval", "vision-run2", "policy-run", "report"])
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "regress-run":
        regress_run(a.out)
    elif a.cmd == "vision-run2":
        vision_run2(a.out)
    elif a.cmd == "policy-run":
        policy_run(a.out)
    else:
        a.out.mkdir(parents=True, exist_ok=True)
        res, name = (regress_eval(E10 / "regression"), "e010_regression.json") if a.cmd == "regress-eval" else (report(a.out), "e010_report.json")
        (a.out / name).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        keys = ("success_criteria", "passes", "routing_changes", "identity_changes", "field_changes") if a.cmd == "regress-eval" else ("readiness",)
        print(json.dumps({k: res.get(k) for k in keys}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
