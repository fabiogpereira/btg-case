"""E-008 (parte 1) — regressão pré-OCR da variante H (G + binding v2). PRÉ-REGISTRADO antes da regressão.

python -m evaluation.e008 run  --out outputs/experiments/E-008_pre_ocr_ocr/regression
python -m evaluation.e008 eval --out outputs/experiments/E-008_pre_ocr_ocr/regression/evaluation

Replay sem rede nos quatro regression sets (mesmos caches e provedor do E-007). Comparação H × G, com G = registros
oficiais da regressão do E-007. Métricas do E-007 (`e007.evaluate_variant`), com uma diferença: par rótulo -> valor
SUPERSEDED (preterido por rótulo mais próximo) não é "rejeição" nem "binding correto perdido".

Critérios (pré-registrados; se 1–3 falharem, parar e avisar o usuário):
1. enhanced unsafe = 0 em todos os conjuntos;
2. bindings errados (qualquer roteamento) = 0 em todos os conjuntos;
3. identidade inalterada: por documento, mesmo método, mesma linha casada e mesmo reason code que a G;
4. nenhuma regressão material no original: mesmos campos e mesmo roteamento da G;
5. bindings corretos perdidos da H <= G em cada conjunto.
Mudanças de roteamento restantes são listadas com a causa (fail-safe explicável ou não).
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .e007 import DATASETS, ReplayProvider, _gt_value, _norm_raw, _records, evaluate_variant, truths

ROOT = Path(__file__).resolve().parents[2]
E7 = ROOT / "outputs" / "experiments" / "E-007_pre_ocr"


def run_regression(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    for name, (docs, golden, cache, _) in DATASETS.items():
        provider = ReplayProvider()
        manifest = run_batch(docs, golden, out / f"{name}_H", run_id=f"e008-replay-{name}", variant="H",
                             semantic_ctx=SemanticContext(provider, ResponseCache(cache)))
        print(name, manifest["summary"]["decisions"], "cache_misses:", provider.misses)


def _final_value(rec, name):
    f = (rec.get("fields") or {}).get(name) or (rec.get("event_specific_fields") or {}).get(name) or {}
    if f.get("status") != "found":
        return None
    if name.endswith("_date"):
        return f["value"]
    return Decimal(str(f["value"]["rate"] if name == "withholding_tax" else f["value"]))


def binding_v2_stats(dataset, run_dir) -> dict:
    tr, key = truths(dataset)
    recs = _records(run_dir, key)
    out = {"bound": 0, "superseded": 0, "rejected": {}, "wrong_bindings_prevented": {}, "correct_bindings_lost": {}}
    for k, truth in tr.items():
        for b in recs[k].get("binding", []):
            if b["decision"] == "BOUND":
                out["bound"] += 1
            elif b["decision"] == "SUPERSEDED":
                out["superseded"] += 1
            else:
                out["rejected"][b["reason"]] = out["rejected"].get(b["reason"], 0) + 1
                gtv = _gt_value(truth, b["field"])
                if gtv is None:
                    continue
                if _norm_raw(b["field"], b["raw"]) != gtv:
                    out["wrong_bindings_prevented"].setdefault(truth["id"], []).append(f"{b['field']}={b['raw']}")
                elif _final_value(recs[k], b["field"]) != gtv:   # o valor correto não ficou representado por outro par
                    out["correct_bindings_lost"].setdefault(truth["id"], []).append(f"{b['field']}={b['raw']}")
    return out


def evaluate_all(h_dir: Path) -> dict:
    res = {"G": {}, "H": {}, "identity_changes": {}, "routing_changes": {}, "field_changes_original": []}
    for name, (_, _, _, _) in DATASETS.items():
        g_dir, hd = E7 / f"{name}_G", h_dir / f"{name}_H"
        res["G"][name] = evaluate_variant(name, g_dir)
        res["H"][name] = evaluate_variant(name, hd)
        res["H"][name]["binding"] = {**binding_v2_stats(name, hd),
                                     "wrong_bindings_any_routing": res["H"][name]["binding"]["wrong_bindings_any_routing"]}
        tr, key = truths(name)
        g_recs, h_recs = _records(g_dir, key), _records(hd, key)
        for k, truth in tr.items():
            gi, hi = g_recs[k].get("identity") or {}, h_recs[k].get("identity") or {}
            sig = lambda i: (i.get("identity_method"), (i.get("matched_reference") or {}).get("isin"), i.get("reason_code"))
            if sig(gi) != sig(hi):
                res["identity_changes"].setdefault(name, []).append({"id": truth["id"], "G": sig(gi), "H": sig(hi)})
            gr, hr = g_recs[k]["routing"], h_recs[k]["routing"]
            if (gr["decision"], gr["reason_codes"]) != (hr["decision"], hr["reason_codes"]):
                res["routing_changes"].setdefault(name, []).append(
                    {"id": truth["id"], "G": [gr["decision"], gr["reason_codes"]], "H": [hr["decision"], hr["reason_codes"]]})
            if name == "original":
                val = lambda r: {n: (v["status"], v.get("value")) for s in ("fields", "event_specific_fields")
                                 for n, v in (r.get(s) or {}).items()}
                if val(g_recs[k]) != val(h_recs[k]):
                    res["field_changes_original"].append(truth["id"])
    H, G = res["H"], res["G"]
    ds = list(H)
    res["success_criteria"] = {
        "1_enhanced_unsafe_zero": all(not H[d]["safety"]["unsafe_auto_approvals_enhanced"] for d in ds),
        "2_wrong_bindings_zero": all(not H[d]["binding"]["wrong_bindings_any_routing"] for d in ds),
        "3_identity_unchanged": not res["identity_changes"],
        "4_no_material_regression_original": not res["field_changes_original"] and "original" not in res["routing_changes"],
        "5_correct_bindings_lost_not_worse": all(len(H[d]["binding"]["correct_bindings_lost"]) <= len(G[d]["binding"]["correct_bindings_lost"])
                                                 for d in ds),
    }
    res["stop_and_warn"] = not all(res["success_criteria"][k] for k in ("1_enhanced_unsafe_zero", "2_wrong_bindings_zero",
                                                                         "3_identity_unchanged"))
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "eval"])
    p.add_argument("--h-dir", type=Path, default=ROOT / "outputs" / "experiments" / "E-008_pre_ocr_ocr" / "regression")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "run":
        run_regression(a.out)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate_all(a.h_dir)
    (a.out / "e008_regression.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary = {v: {d: {"unsafe": m["safety"]["unsafe_auto_approvals_enhanced"], "wrong_bindings": m["binding"]["wrong_bindings_any_routing"],
                       "lost": m["binding"]["correct_bindings_lost"], "routing": m["utility"]["accuracy_defined"],
                       "review_rate": m["utility"]["review_rate"], "false_reviews": m["utility"]["false_reviews"],
                       "cache_misses": m["cache_misses"]} for d, m in res[v].items()} for v in ("G", "H")}
    print(json.dumps({"summary": summary, "routing_changes": res["routing_changes"], "identity_changes": res["identity_changes"],
                      "success_criteria": res["success_criteria"], "stop_and_warn": res["stop_and_warn"]},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
