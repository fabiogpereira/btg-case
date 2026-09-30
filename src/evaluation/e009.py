"""E-009 — correção de pontilhado (variante I) e comparação controlada OCR local × vision no doc 07.
PRÉ-REGISTRADO antes da regressão e antes de qualquer execução das duas percepções.

python -m evaluation.e009 regress-run  --out outputs/experiments/E-009_ocr_vs_vision/regression
python -m evaluation.e009 regress-eval --out outputs/experiments/E-009_ocr_vs_vision/regression/evaluation
python -m evaluation.e009 perceive --arm A --out outputs/experiments/E-009_ocr_vs_vision/arm_A_ocr
python -m evaluation.e009 perceive --arm B --out outputs/experiments/E-009_ocr_vs_vision/arm_B_vision
python -m evaluation.e009 compare --out outputs/experiments/E-009_ocr_vs_vision/comparison

Parte 1 (regressão I × H, replay sem rede): critérios = enhanced unsafe 0; bindings errados 0; identidade inalterada;
original sem regressão material (mesmos campos e roteamento); bindings corretos perdidos I <= H. Se 1–3 falharem: parar.

Parte 2 (doc 07): a ÚNICA variável é a percepção. Mesmo documento, mesma pipeline I congelada, mesma configuração do LLM
semântico da pipeline (claude-opus-5, fallback off, cache novo e comum aos dois braços; se o detector pedir o LLM,
a chamada acontece igual para os dois braços). A = Tesseract (E-008, mesmos parâmetros). B = vision (claude-opus-5,
prompt de transcrição literal congelado, sem dados de referência). Sem combinar, votar ou corrigir um pelo outro.
Métricas por braço: `e008_ocr.evaluate` (texto, tokens críticos como escritos, campos, segurança, binding, identidade,
validação, roteamento, operacional) + tipo de evento + palavras que o braço produziu e que não existem na transcrição
humana (possível conteúdo inventado) + tokens marcados como incertos.

Regra de decisão (pré-registrada):
- braço seguro = 0 valores de campo diferentes do gabarito, 0 dígitos alterados em token crítico escrito, 0 identidade
  errada, 0 bindings errados, 0 aprovações inseguras (enhanced);
- ganho de B = campos críticos exatos em B que não são exatos em A;
- se B não for seguro -> vision rejeitado nesta configuração;
- se A seguro e (B sem ganho ou B inseguro) -> "OCR local (+ REVIEW quando faltar identificador)";
- se A seguro, B seguro, ganho não vazio e custo de vision por documento <= US$ 0,10 -> "OCR local + vision apenas como
  fallback secundário" (só quando o OCR deixar campo obrigatório ausente);
- se A inseguro e B seguro -> "vision" (para documentos sem camada de texto).
Nunca escolher vision só porque lê mais campos: a regra exige segurança dos dois lados e ganho em campo crítico.
"""
import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

from .e007 import DATASETS, ReplayProvider, _records, evaluate_variant, truths
from .e008 import binding_v2_stats
from .e008_ocr import CASE, TRANSCRIPTION, _norm, evaluate as evaluate_perception

ROOT = Path(__file__).resolve().parents[2]
E8R = ROOT / "outputs" / "experiments" / "E-008_pre_ocr_ocr" / "regression"
E9 = ROOT / "outputs" / "experiments" / "E-009_ocr_vs_vision"
DOC07 = CASE / "documents" / "07_telecom_norte_jcp_SCAN.pdf"


# --- parte 1: regressão ------------------------------------------------------------------------------

def regress_run(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    for name, (docs, golden, cache, _) in DATASETS.items():
        provider = ReplayProvider()
        m = run_batch(docs, golden, out / f"{name}_I", run_id=f"e009-replay-{name}", variant="I",
                      semantic_ctx=SemanticContext(provider, ResponseCache(cache)))
        print(name, m["summary"]["decisions"], "cache_misses:", provider.misses)


def regress_eval(i_dir: Path) -> dict:
    res = {"H": {}, "I": {}, "identity_changes": {}, "routing_changes": {}, "field_changes_original": []}
    for name in DATASETS:
        h_dir, idir = E8R / f"{name}_H", i_dir / f"{name}_I"
        for v, d in (("H", h_dir), ("I", idir)):
            res[v][name] = evaluate_variant(name, d)
            res[v][name]["binding"] = {**binding_v2_stats(name, d),
                                       "wrong_bindings_any_routing": res[v][name]["binding"]["wrong_bindings_any_routing"]}
        tr, key = truths(name)
        h_recs, i_recs = _records(h_dir, key), _records(idir, key)
        for k, truth in tr.items():
            sig = lambda r: ((r.get("identity") or {}).get("identity_method"),
                             ((r.get("identity") or {}).get("matched_reference") or {}).get("isin"), (r.get("identity") or {}).get("reason_code"))
            if sig(h_recs[k]) != sig(i_recs[k]):
                res["identity_changes"].setdefault(name, []).append({"id": truth["id"], "H": sig(h_recs[k]), "I": sig(i_recs[k])})
            hr, ir = h_recs[k]["routing"], i_recs[k]["routing"]
            if (hr["decision"], hr["reason_codes"]) != (ir["decision"], ir["reason_codes"]):
                res["routing_changes"].setdefault(name, []).append({"id": truth["id"], "H": [hr["decision"], hr["reason_codes"]],
                                                                   "I": [ir["decision"], ir["reason_codes"]]})
            val = lambda r: {n: (v["status"], v.get("value")) for s in ("fields", "event_specific_fields") for n, v in (r.get(s) or {}).items()}
            if val(h_recs[k]) != val(i_recs[k]):
                res.setdefault("field_changes", {}).setdefault(name, []).append(truth["id"])
                if name == "original":
                    res["field_changes_original"].append(truth["id"])
    I, H = res["I"], res["H"]
    res["success_criteria"] = {
        "1_enhanced_unsafe_zero": all(not I[d]["safety"]["unsafe_auto_approvals_enhanced"] for d in I),
        "2_wrong_bindings_zero": all(not I[d]["binding"]["wrong_bindings_any_routing"] for d in I),
        "3_identity_unchanged": not res["identity_changes"],
        "4_no_material_regression_original": not res["field_changes_original"] and "original" not in res["routing_changes"],
        "5_correct_bindings_lost_not_worse": all(len(I[d]["binding"]["correct_bindings_lost"]) <= len(H[d]["binding"]["correct_bindings_lost"])
                                                 for d in I)}
    res["stop_and_warn"] = not all(res["success_criteria"][k] for k in ("1_enhanced_unsafe_zero", "2_wrong_bindings_zero", "3_identity_unchanged"))
    return res


# --- parte 2: percepção ------------------------------------------------------------------------------

def perceive(arm: str, out: Path):
    """Doc 07 pela pipeline I congelada com a percepção do braço. LLM semântico da pipeline: mesma configuração e
    mesmo cache novo para os dois braços."""
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.llm.config import llm_config_from_env
    from corporate_actions.llm.registry import get_provider
    from corporate_actions.models import to_jsonable
    from corporate_actions.pipeline import SemanticContext, process_document
    from corporate_actions.reference import load_golden_records
    config = llm_config_from_env()
    assert (config.model, config.effort, config.fallbacks) == ("claude-opus-5", "medium", "off"), "configuração diferente da congelada"
    if arm == "A":
        from perception.ocr_local import TesseractOCR
        fallback = TesseractOCR(artifacts_dir=out / "artifacts")
    else:
        from perception.vision_transcriber import VisionTranscriber
        fallback = VisionTranscriber(cache_dir=E9 / "vision_cache_run1", artifacts_dir=out / "artifacts")
    ctx = SemanticContext(get_provider(config), ResponseCache(E9 / "pipeline_llm_cache_run1"))
    rec = to_jsonable(process_document(DOC07, load_golden_records(CASE / "golden_records" / "golden records.csv"),
                                       f"e009-arm-{arm}", "I", ctx, text_fallback=fallback))
    (out / "records").mkdir(parents=True, exist_ok=True)
    (out / "records" / f"{DOC07.stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "config.json").write_text(json.dumps({"arm": arm, "perception": fallback.describe(), "pipeline_variant": "I",
                                                  "pipeline_llm": {"model": config.model, "effort": config.effort, "fallbacks": config.fallbacks}},
                                                 ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(arm, rec["routing"]["decision"], rec["routing"]["reason_codes"])


def arm_view(arm_dir: Path) -> dict:
    r = evaluate_perception(arm_dir)
    rec = next(json.loads(p.read_text(encoding="utf-8")) for p in (arm_dir / "records").glob("*.json"))
    fb = rec["document"].get("text_fallback") or {}
    text = _norm(" ".join((ROOT / a["raw_text_path"]).read_text(encoding="utf-8") for a in fb.get("page_artifacts", [])))
    human = set(_norm(TRANSCRIPTION.read_text(encoding="utf-8")).split())
    llm = rec.get("llm") or {}
    r["extra"] = {"event_type": (rec.get("classification") or {}).get("event_type"),
                  "words_not_in_human_transcription": sorted({w for w in text.split() if w not in human}),
                  "uncertain_tokens": fb.get("uncertain_tokens"),
                  "perception_cost_usd": str(fb.get("estimated_cost_usd", "0")), "perception_usage": fb.get("usage"),
                  "perception_duration_ms": fb.get("duration_ms"),
                  "pipeline_llm": {"invoked": bool(llm), "api_calls": llm.get("api_calls", 0),
                                   "cost_usd": llm.get("estimated_cost_usd", "0"), "triggers": (rec.get("semantic_need") or {}).get("llm_trigger_reasons")}}
    return r


def is_safe(v) -> bool:
    return (not any(f["result"] == "DIFFERENT" for f in v["fields"].values())
            and not any(t.get("digit_positions_changed") for t in v["critical_tokens_as_written"].values() if not t["exact"]
                        and t.get("closest_ocr") and re.search(r"\d", t["expected"]))
            and not v["safety"]["wrong_identity"] and not v["safety"]["wrong_bindings"]
            and not v["safety"]["unsafe_auto_approval_enhanced"])


def compare(a_dir: Path, b_dir: Path) -> dict:
    A, B = arm_view(a_dir), arm_view(b_dir)
    exact = lambda v: {n for n, f in v["fields"].items() if f["result"] == "EXACT"}
    gain = sorted(exact(B) - exact(A))
    loss = sorted(exact(A) - exact(B))
    vision_cost = Decimal(B["extra"]["perception_cost_usd"] or "0")
    a_safe, b_safe = is_safe(A), is_safe(B)
    if not b_safe and a_safe:
        decision = "OCR_LOCAL (+ REVIEW quando faltar identificador); vision rejeitado nesta configuração"
    elif a_safe and b_safe and gain and vision_cost <= Decimal("0.10"):
        decision = "OCR_LOCAL + VISION apenas como fallback secundário"
    elif a_safe:
        decision = "OCR_LOCAL (+ REVIEW quando faltar identificador)"
    elif b_safe:
        decision = "VISION"
    else:
        decision = "NENHUM seguro nesta configuração: manter NO_USABLE_TEXT_LAYER -> revisão"
    rows = {n: {"expected": A["fields"][n]["expected"], "A_ocr": [A["fields"][n]["result"], A["fields"][n]["got"]],
                "B_vision": [B["fields"][n]["result"], B["fields"][n]["got"]]} for n in A["fields"]}
    return {"A": A, "B": B, "fields_side_by_side": rows, "gain_B_over_A": gain, "loss_B_vs_A": loss,
            "A_safe": a_safe, "B_safe": b_safe, "vision_cost_usd": str(vision_cost), "decision_by_preregistered_rule": decision}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["regress-run", "regress-eval", "perceive", "compare"])
    p.add_argument("--arm", choices=["A", "B"])
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "regress-run":
        regress_run(a.out)
    elif a.cmd == "perceive":
        perceive(a.arm, a.out)
    else:
        a.out.mkdir(parents=True, exist_ok=True)
        if a.cmd == "regress-eval":
            res = regress_eval(E9 / "regression")
            name = "e009_regression.json"
        else:
            res = compare(E9 / "arm_A_ocr", E9 / "arm_B_vision")
            name = "e009_comparison.json"
        (a.out / name).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        keys = ("success_criteria", "stop_and_warn", "routing_changes", "identity_changes") if a.cmd == "regress-eval" else \
            ("fields_side_by_side", "gain_B_over_A", "loss_B_vs_A", "A_safe", "B_safe", "vision_cost_usd", "decision_by_preregistered_rule")
        print(json.dumps({k: res.get(k) for k in keys}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
