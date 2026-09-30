"""E-008 (parte 2) — H1: OCR local no doc 07. PRÉ-REGISTRADO antes da primeira execução do OCR.

python -m evaluation.e008_ocr run  --out outputs/experiments/E-008_pre_ocr_ocr/ocr_h1
python -m evaluation.e008_ocr eval --out outputs/experiments/E-008_pre_ocr_ocr/ocr_h1/evaluation

Pergunta: uma solução local e barata de OCR recupera o doc 07 com qualidade suficiente para alimentar a MESMA
pipeline candidata (H, congelada) sem criar novos riscos?

Execução: case original inteiro com a H congelada + `text_fallback=TesseractOCR` (baseline, sem otimização). O OCR só
roda onde a camada nativa não é utilizável (decisão do pipeline, nunca do nome do arquivo). LLM por replay sem rede
(mesmo cache do E-006): se o doc 07 exigir o LLM, é cache miss, fica registrado, e nenhuma chamada de API é feita sem
autorização do usuário.

Métricas (pré-registradas):
- texto: caracteres, linhas, palavras, confiança média e palavras de baixa confiança do Tesseract; caracteres
  estranhos; similaridade de caracteres e cobertura de palavras contra a transcrição visual humana congelada
  (tests/ground_truth/transcriptions/doc07_visual_transcription.txt);
- tokens críticos como escritos no documento (valor bruto/líquido, alíquota, datas, ISIN, ticker, CNPJ, razão social):
  presença exata no texto OCR; quando ausente, o token OCR mais parecido e as posições de dígito alteradas;
- campos críticos do registro × gabarito v2.1: recuperado exato / ausente / valor diferente;
- segurança: enhanced (`e006.enhanced_components`), alucinações, omissões materiais, bindings errados, identidade
  errada, alteração silenciosa (valor diferente do gabarito num campo sem confiança LOW, em registro aprovado);
- binding: mantidos, rejeitados, preteridos, campos ambíguos (valores divergentes);
- pipeline: tipo de evento, regras de validação × gabarito, roteamento, recuperabilidade das evidências do gabarito;
- operacional: duração do render/OCR, latência do pipeline, chamadas de API, dependências;
- não regressão: os outros 7 documentos (camada nativa) iguais à regressão pré-OCR da H.

Critérios de sucesso H1: (1) doc 07 processado ponta a ponta (extração COMPLETED, método OCR_LOCAL); (2) nenhum campo
financeiro crítico alterado silenciosamente; (3) enhanced unsafe = 0; (4) bindings errados = 0; (5) identidade correta
ou fail-safe (UNRESOLVED com revisão); (6) roteamento justificável (REVIEW com motivos registrados, ou AUTO com todos os
campos críticos exatos); (7) custo marginal ~0 (0 chamadas de API); (8) setup reproduzível (qualitativo).
Recomendar vision SOMENTE se: erro de dígito em token crítico; ou >= 2 campos críticos perdidos; ou pipeline sem
operar (sem tipo de evento / extração impossível); ou recuperabilidade de evidências < 80%; ou revisão obrigatória
causada pela percepção num documento visualmente claro.
"""
import argparse
import difflib
import json
import re
from pathlib import Path

from .e006 import _field, enhanced_components, truth_original
from .e007 import ReplayProvider, wrong_bindings

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "case" / "Case AI Dev - Envio"
E6_CACHE = ROOT / "outputs" / "experiments" / "E-006_hardened" / "llm_cache_run1"
H_REGRESSION = ROOT / "outputs" / "experiments" / "E-008_pre_ocr_ocr" / "regression" / "original_H"
GT07 = ROOT / "tests" / "ground_truth" / "doc07.json"
TRANSCRIPTION = ROOT / "tests" / "ground_truth" / "transcriptions" / "doc07_visual_transcription.txt"
CRITICAL = ["issuer_name", "cnpj", "isin", "ticker", "approval_date", "record_date", "ex_date", "payment_date",
            "gross_amount_per_share", "net_amount_per_share", "withholding_tax"]
EXPECTED_CHARS = r"[\wÀ-ÿ\s.,:;!?%$()/\\\-–—\"“”'‘’ºª§&@#*+=\[\]|]"


def run(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    from perception.ocr_local import TesseractOCR
    provider = ReplayProvider()
    ocr = TesseractOCR(artifacts_dir=out / "ocr_artifacts")
    manifest = run_batch(CASE / "documents", CASE / "golden_records" / "golden records.csv", out / "original_H_ocr",
                         run_id="e008-ocr-h1", variant="H", semantic_ctx=SemanticContext(provider, ResponseCache(E6_CACHE)),
                         text_fallback=ocr)
    print(manifest["summary"]["decisions"], "cache_misses:", provider.misses, "ocr:", manifest["config"]["ocr"])


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _digit_diff(expected, got):
    return [i for i, (a, b) in enumerate(zip(expected, got)) if a != b and (a.isdigit() or b.isdigit())] + \
        ([f"len {len(expected)}!={len(got)}"] if len(expected) != len(got) else [])


def token_check(raw, text, tokens):
    if _norm(raw) in text:
        return {"expected": raw, "exact": True}
    n = len(raw.split())
    grams = [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]
    best = difflib.get_close_matches(raw, grams, n=1, cutoff=0.5)
    return {"expected": raw, "exact": False, "closest_ocr": best[0] if best else None,
            "digit_positions_changed": _digit_diff(raw, best[0]) if best else None}


def evaluate(run_dir: Path) -> dict:
    gt = json.loads(GT07.read_text(encoding="utf-8"))
    sha = gt["document"]["sha256"]
    truth = truth_original()[sha]
    recs = {r["document"]["sha256"]: r for r in (json.loads(p.read_text(encoding="utf-8"))
                                                 for p in sorted((run_dir / "records").glob("*.json")))}
    rec = recs[sha]
    fb = rec["document"].get("text_fallback") or {}
    page_texts = [(ROOT / a["raw_text_path"]).read_text(encoding="utf-8") for a in fb.get("page_artifacts", [])
                  if a.get("raw_text_path")]
    ocr_text = _norm(" ".join(page_texts))
    tokens = ocr_text.split()
    transcription = _norm(TRANSCRIPTION.read_text(encoding="utf-8"))
    tr_words = transcription.split()
    ocr_words = set(tokens)
    text = {"chars": len(ocr_text), "lines": sum(len([l for l in t.splitlines() if l.strip()]) for t in page_texts),
            "words": len(tokens), "mean_word_confidence": fb.get("mean_word_confidence"),
            "low_confidence_words": fb.get("low_confidence_words"),
            "low_confidence_numeric_tokens": fb.get("low_confidence_numeric_tokens"),
            "unexpected_chars": sorted({c for c in ocr_text if not re.fullmatch(EXPECTED_CHARS, c)}),
            "char_similarity_vs_transcription": round(difflib.SequenceMatcher(None, transcription, ocr_text, autojunk=False).ratio(), 4),
            "transcription_words_found": {"found": sum(w in ocr_words for w in tr_words), "total": len(tr_words)},
            "transcription_chars": len(transcription)}
    fields = {**truth["fields"]}
    raw_tokens = {}
    all_fields = {**gt["document_truth"]["fields"], **gt["document_truth"]["event_specific_fields"]}
    for name in CRITICAL:
        raw = all_fields[name].get("raw")
        if raw:
            raw_tokens[name] = token_check(raw, ocr_text, tokens)
    evid = [e for f in all_fields.values() for e in (f.get("evidence") or [])] + gt["document_truth"]["classification"]["evidence"]
    evidence = {"found": sum(_norm(e) in ocr_text for e in evid), "total": len(evid),
                "missing": [e for e in evid if _norm(e) not in ocr_text]}
    field_rows = {}
    for name in CRITICAL:
        exp, got = fields[name], _field(rec, name)
        got_status = got["status"] if got else "ABSENT"
        ok = got_status == "found" and got["value"] == exp["value"]
        field_rows[name] = {"expected": exp["value"], "got": got.get("value") if got else None, "status": got_status,
                            "result": "EXACT" if ok else ("MISSING" if got_status != "found" else "DIFFERENT"),
                            "confidence": got.get("confidence") if got else None,
                            "rules": got.get("extraction_rules") if got else None}
    auto = rec["routing"]["decision"] == "AUTO_APPROVE"
    comp = enhanced_components(rec, truth)
    silent = [n for n, r in field_rows.items() if r["result"] == "DIFFERENT" and r["confidence"] != "LOW" and auto]
    ident = rec.get("identity") or {}
    row = ident.get("matched_reference")
    wrong_identity = bool(row) and row.get("isin") != fields["isin"]["value"]
    binding = rec.get("binding", [])
    ambiguous = [n for n, f in {**rec.get("fields", {}), **rec.get("event_specific_fields", {})}.items()
                 if f.get("status") == "found" and f.get("distinct_values", 1) > 1]
    val_truth = {r["rule_id"]: r["expected"] for r in gt["validation_truth"]["rules"]}
    val_got = {v["rule_id"]: v["status"] for v in rec.get("validations", [])}
    others = {}
    for k, r in recs.items():
        if k == sha:
            continue
        ref = json.loads((H_REGRESSION / "records" / f"{Path(r['document']['file_name']).stem}.json").read_text(encoding="utf-8"))
        same = (r["routing"]["decision"], r["routing"]["reason_codes"], {n: (v["status"], v.get("value")) for n, v in r["fields"].items()}) == \
               (ref["routing"]["decision"], ref["routing"]["reason_codes"], {n: (v["status"], v.get("value")) for n, v in ref["fields"].items()})
        others[r["document"]["file_name"]] = {"fallback_used": "text_fallback" in r["document"], "same_as_pre_ocr_regression": same}
    llm = rec.get("llm") or {}
    critical_lost = [n for n, r in field_rows.items() if r["result"] != "EXACT"]
    digit_errors = {n: t for n, t in raw_tokens.items() if not t["exact"] and t.get("digit_positions_changed")}
    res = {
        "document": {"file_name": rec["document"]["file_name"], "sha256": sha, "identity_hash_is_pdf": rec["document"]["sha256"] == sha},
        "fallback": {k: fb.get(k) for k in ("trigger", "extraction_method", "engine", "engine_version", "lang", "model_sha256",
                                            "oem", "psm", "dpi", "renderer", "pages", "duration_ms", "usable", "page_artifacts")},
        "text": text, "critical_tokens_as_written": raw_tokens, "evidence_recoverability": evidence,
        "fields": field_rows,
        "safety": {"unsafe_auto_approval_enhanced": auto and any(bool(v) for v in comp.values()),
                   "components_if_approved": {k: v for k, v in comp.items() if v} if auto else None,
                   "latent_components": {k: v for k, v in comp.items() if v},
                   "hallucinations": comp["field_hallucination"], "material_omissions": comp["material_information_omission"],
                   "silently_altered_fields": silent, "wrong_bindings": wrong_bindings(rec, truth),
                   "wrong_identity": wrong_identity},
        "binding": {"bound": sum(b["decision"] == "BOUND" for b in binding), "rejected": [b for b in binding if b["decision"] == "REJECTED"],
                    "superseded": sum(b["decision"] == "SUPERSEDED" for b in binding), "ambiguous_fields": ambiguous},
        "identity": ident,
        "pipeline": {"extraction": rec.get("extraction"), "event_type": (rec.get("classification") or {}).get("event_type"),
                     "validations": {rid: {"expected": val_truth.get(rid), "got": st} for rid, st in val_got.items()},
                     "validation_mismatches": {rid: {"expected": e, "got": val_got.get(rid, "ABSENT")} for rid, e in val_truth.items()
                                               if val_got.get(rid, "ABSENT") != e},
                     "routing": rec["routing"]["decision"], "reason_codes": rec["routing"]["reason_codes"],
                     "explanations": rec["routing"]["explanations"], "llm_invoked": bool(llm),
                     "llm_triggers": (rec.get("semantic_need") or {}).get("llm_trigger_reasons"),
                     "llm_errors": llm.get("errors", [])},
        "operational": {"ocr_duration_ms": fb.get("duration_ms"), "pipeline_duration_ms": rec["audit"]["duration_us"] // 1000,
                        "api_calls": llm.get("api_calls", 0), "cache_miss": any("replay_cache_miss" in e for e in llm.get("errors", [])),
                        "marginal_cost_usd": "0"},
        "native_documents_unchanged": others,
    }
    res["success_criteria"] = {
        "1_end_to_end": (rec.get("extraction") or {}).get("status") == "COMPLETED" and (rec.get("extraction") or {}).get("method") == "OCR_LOCAL",
        "2_no_silent_critical_alteration": not silent,
        "3_enhanced_unsafe_zero": not res["safety"]["unsafe_auto_approval_enhanced"],
        "4_wrong_bindings_zero": not res["safety"]["wrong_bindings"],
        "5_identity_correct_or_fail_safe": (ident.get("identity_method") != "UNRESOLVED" and not wrong_identity)
                                           or (ident.get("identity_method") == "UNRESOLVED" and not auto),
        "6_routing_justifiable": (not auto and bool(rec["routing"]["reason_codes"])) or (auto and not critical_lost),
        "7_marginal_cost_zero": llm.get("api_calls", 0) == 0,
        "native_documents_unchanged": all(o["same_as_pre_ocr_regression"] and not o["fallback_used"] for o in others.values()),
    }
    res["vision_triggers"] = {"digit_error_in_critical_token": digit_errors,
                              "critical_fields_lost_ge_2": critical_lost if len(critical_lost) >= 2 else [],
                              "pipeline_cannot_operate": not res["success_criteria"]["1_end_to_end"] or res["pipeline"]["event_type"] is None,
                              "evidence_recoverability_below_80pct": evidence["found"] < 0.8 * evidence["total"]}
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "eval"])
    p.add_argument("--run-dir", type=Path, default=ROOT / "outputs" / "experiments" / "E-008_pre_ocr_ocr" / "ocr_h1" / "original_H_ocr")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "run":
        run(a.out)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate(a.run_dir)
    (a.out / "ocr_h1_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("success_criteria", "vision_triggers")}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
