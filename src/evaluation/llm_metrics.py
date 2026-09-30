"""Métricas específicas da variante C (E-003): function calling e consistência entre execuções.

Function calling — por documento com camada de texto espera-se exatamente UMA chamada correta a
`lookup_security` com o ISIN (tipo ISIN) ou o ticker (tipo TICKER) do título do aviso:
- correta: primeira chamada com o identificador do documento;
- desnecessária: chamada correta repetida no mesmo documento, ou tool desconhecida;
- argumento incorreto: `lookup_security` com identificador que não é o do documento (ou tipo trocado);
- esperada e ausente: documento com texto sem nenhuma chamada correta.
Os identificadores esperados vêm do gabarito original (isin/ticker) ou, no challenge set, do texto
do caso (rótulos "ISIN" e "Código de negociação"), sem alterar o gabarito congelado.

Consistência — duas execuções independentes (a segunda sem ler o cache) comparadas por documento.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _records(run_dir: Path) -> dict:
    return {r["document"]["sha256"]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def expected_ids_original() -> dict:
    gt_dir = ROOT / "tests" / "ground_truth"
    index = json.loads((gt_dir / "index.json").read_text(encoding="utf-8"))
    out = {}
    for e in index["documents"]:
        gt = json.loads((gt_dir / e["ground_truth_file"]).read_text(encoding="utf-8"))
        f = gt["document_truth"]["fields"]
        if gt["document"]["text_layer"] == "native":
            out[e["sha256"]] = {"isin": f["isin"]["value"], "ticker": f["ticker"]["value"]}
    return out


def expected_ids_challenge() -> dict:
    cs = ROOT / "tests" / "challenge_set"
    gt = json.loads((cs / "ground_truth.json").read_text(encoding="utf-8"))
    out = {}
    for case in gt["cases"]:
        text = (cs / case["file"]).read_text(encoding="utf-8")
        isin = re.search(r"ISIN ([A-Z]{2}[A-Z0-9]{9}\d)", text)
        ticker = re.search(r"Código de negociação ([A-Z]{4}\d{1,2})", text)
        out[case["sha256"]] = {"isin": isin.group(1) if isin else None, "ticker": ticker.group(1) if ticker else None}
    return out


def function_calling(run_dir: Path, expected: dict) -> dict:
    recs = _records(run_dir)
    total = correct = unnecessary = incorrect = 0
    docs_called, missing, details = [], [], []
    for sha, exp in expected.items():
        rec = recs.get(sha, {})
        calls = (rec.get("llm") or {}).get("tool_calls", [])
        name = rec.get("document", {}).get("file_name", sha[:12])
        total += len(calls)
        if calls:
            docs_called.append(name)
        got_correct = False
        for c in calls:
            args = c.get("arguments") or {}
            ident = (args.get("identifier") or "").strip().upper()
            kind = args.get("identifier_type")
            ok = c["name"] == "lookup_security" and (
                (kind == "ISIN" and ident == exp["isin"]) or (kind == "TICKER" and ident == exp["ticker"]))
            if ok and not got_correct:
                correct += 1
                got_correct = True
            elif ok or c["name"] != "lookup_security":
                unnecessary += 1
                details.append({"document": name, "problem": "unnecessary", "call": c["name"], "arguments": args})
            else:
                incorrect += 1
                details.append({"document": name, "problem": "incorrect_arguments", "arguments": args, "expected": exp})
        if not got_correct:
            missing.append(name)
    return {"documents_expected": len(expected), "total_tool_calls": total, "documents_with_tool_call": len(docs_called),
            "correct_calls": correct, "unnecessary_calls": unnecessary, "incorrect_arguments": incorrect,
            "expected_calls_missing": len(missing), "missing_in": missing, "details": details}


def _semantic_snapshot(rec: dict) -> dict:
    fields = {**(rec.get("fields") or {}), **(rec.get("event_specific_fields") or {})}
    sem = (rec.get("semantic") or {}).get("fields", {})
    return {name: {"status": fields.get(name, {}).get("status"), "value": fields.get(name, {}).get("value"),
                   "semantic": a.get("confidence")} for name, a in sorted(sem.items())}


def _interpretation_snapshot(rec: dict) -> dict | None:
    it = (rec.get("llm") or {}).get("interpretation")
    if not it:
        return None
    return {"event_type": it["event"]["type"],
            "dates": sorted((d["role"], d["status"], d["value_as_written"]) for d in it["dates"]),
            "withholding": (it["withholding_tax"]["status"], it["withholding_tax"]["rate_as_written"],
                            it["withholding_tax"]["base"]),
            "reference": it["security_reference"]["found_in_reference"]}


def consistency(run1: Path, run2: Path) -> dict:
    a, b = _records(run1), _records(run2)
    shas = sorted(set(a) & set(b))
    dims = {"event_type": [], "semantic_fields": [], "llm_interpretation": [], "routing_decision": [],
            "routing_reasons": [], "tool_call_count": [], "tool_arguments": []}
    diffs = []
    for sha in shas:
        r1, r2 = a[sha], b[sha]
        if not (r1.get("llm") or r2.get("llm")):
            continue                                            # sem texto: sem LLM nas duas execuções
        name = r1["document"]["file_name"]
        calls1 = [(c["name"], json.dumps(c["arguments"], sort_keys=True)) for c in r1["llm"]["tool_calls"]]
        calls2 = [(c["name"], json.dumps(c["arguments"], sort_keys=True)) for c in r2["llm"]["tool_calls"]]
        checks = {
            "event_type": (r1.get("classification") or {}).get("event_type") == (r2.get("classification") or {}).get("event_type"),
            "semantic_fields": _semantic_snapshot(r1) == _semantic_snapshot(r2),
            "llm_interpretation": _interpretation_snapshot(r1) == _interpretation_snapshot(r2),
            "routing_decision": r1["routing"]["decision"] == r2["routing"]["decision"],
            "routing_reasons": sorted(r1["routing"]["reason_codes"]) == sorted(r2["routing"]["reason_codes"]),
            "tool_call_count": len(calls1) == len(calls2),
            "tool_arguments": calls1 == calls2,
        }
        for k, ok in checks.items():
            dims[k].append(ok)
        if not all(checks.values()):
            diffs.append({"document": name, "inconsistent": [k for k, ok in checks.items() if not ok],
                          "run1": {"event_type": (r1.get("classification") or {}).get("event_type"),
                                   "decision": r1["routing"]["decision"], "reasons": r1["routing"]["reason_codes"],
                                   "interpretation": _interpretation_snapshot(r1), "tool_calls": calls1},
                          "run2": {"event_type": (r2.get("classification") or {}).get("event_type"),
                                   "decision": r2["routing"]["decision"], "reasons": r2["routing"]["reason_codes"],
                                   "interpretation": _interpretation_snapshot(r2), "tool_calls": calls2}})
    return {"documents_compared": len(dims["event_type"]),
            **{k: {"consistent": sum(v), "total": len(v)} for k, v in dims.items()},
            "inconsistent_documents": diffs}
