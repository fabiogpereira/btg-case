"""Avaliação do E-005 (H-27, qualificadores v3): D (E-004) × E, dataset original e challenge set separados.

python -m evaluation.e005 --out DIR

Métricas pré-registradas específicas de qualificadores:
- contagem: qualificadores devolvidos pelo LLM (material × não material/nota) e quantos bloqueiam;
- bloqueio por qualificador: documento cujo roteamento foi bloqueado por um qualificador (código
  MATERIAL_QUALIFIER_* em `semantic.blocking` ou na semântica de algum campo). É "justificado" se a
  expectativa de roteamento do gabarito é REVIEW_REQUIRED; senão é bloqueio falso;
- estabilidade: execução 1 × 2 da E; "semanticamente estável" = mesmo conjunto (kind/affects/target/bloqueia)
  de qualificadores materiais e mesmo roteamento, ainda que o texto das notas varie.
Critérios de sucesso (do enunciado do E-005) avaliados automaticamente onde possível.
"""
import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from .e004 import efficiency, need_oracle_challenge, need_oracle_original, quality
from .llm_metrics import expected_ids_challenge, expected_ids_original

ROOT = Path(__file__).resolve().parents[2]
E004 = ROOT / "outputs" / "experiments" / "E-004_hybrid"
E005 = ROOT / "outputs" / "experiments" / "E-005_qualifiers_v3"


def _records(run_dir: Path) -> dict:
    return {r["document"]["file_name"]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def _expected_routing() -> dict:
    out = {}
    idx = json.loads((ROOT / "tests" / "ground_truth" / "index.json").read_text(encoding="utf-8"))
    for e in idx["documents"]:
        gt = json.loads((ROOT / "tests" / "ground_truth" / e["ground_truth_file"]).read_text(encoding="utf-8"))
        out[gt["document"]["file_name"]] = gt["routing_expectation"]["decision"]
    ch = json.loads((ROOT / "tests" / "challenge_set" / "ground_truth.json").read_text(encoding="utf-8"))
    for c in ch["cases"]:
        out[c["file"].split("/")[-1]] = c["routing"]["decision"]
    return out


def qualifiers_of(rec: dict, variant: str) -> dict:
    """Visão comum D/E: qualificadores devolvidos pelo LLM (fonte llm) e se bloqueiam."""
    sem = rec.get("semantic") or {}
    if variant == "D":
        items = [q for q in sem.get("qualifiers_v2", []) if q.get("source") == "llm"]
        material = [q for q in items if q["materiality"] != "NOT_MATERIAL"]
        nonmat = [q for q in items if q["materiality"] == "NOT_MATERIAL"]
        key = lambda q: (q["qualifier_type"], q["affects"], q["blocks"])
    else:
        material = [q for q in sem.get("material_qualifiers", []) if q.get("source") == "llm"]
        nonmat = [q for q in sem.get("semantic_notes", []) if q.get("source") == "llm"]
        key = lambda q: (q["kind"], q["affects"], q["target_field"], q["blocks"])
    return {"material": material, "non_material": nonmat, "blocking": [q for q in material if q["blocks"]],
            "material_signature": sorted(map(key, material)),
            "scope_guard_rejected": [q for q in nonmat if q.get("kind") == "scope_guard_rejected"]}


def qualifier_blocked(rec: dict) -> list[str]:
    sem = rec.get("semantic") or {}
    codes = [b for b in sem.get("blocking", []) if b.startswith("MATERIAL_QUALIFIER")]
    for name, a in (sem.get("fields") or {}).items():
        codes += [f"{name}:{r}" for r in a.get("reasons", []) if r.startswith("MATERIAL_QUALIFIER")]
    return codes if rec["routing"]["decision"] == "REVIEW_REQUIRED" else []


def qualifier_metrics(run_dir: Path, variant: str, expected: dict) -> dict:
    recs = _records(run_dir)
    llm_docs = [r for r in recs.values() if "llm" in r]
    counts = Counter()
    blocks = []
    for name, r in recs.items():
        q = qualifiers_of(r, variant)
        counts["material"] += len(q["material"])
        counts["non_material"] += len(q["non_material"])
        counts["blocking"] += len(q["blocking"])
        counts["scope_guard_rejected"] += len(q["scope_guard_rejected"])
        codes = qualifier_blocked(r)
        if codes:
            blocks.append({"document": name, "codes": codes, "expected": expected.get(name),
                           "justified": expected.get(name) == "REVIEW_REQUIRED"})
    return {"llm_documents": len(llm_docs), "qualifiers_total": counts["material"] + counts["non_material"],
            "material": counts["material"], "non_material_or_notes": counts["non_material"],
            "blocking": counts["blocking"], "scope_guard_rejected": counts["scope_guard_rejected"],
            "documents_blocked_by_qualifier": blocks,
            "false_qualifier_blocks": [b["document"] for b in blocks if not b["justified"]]}


def stability(run1: Path, run2: Path, variant: str) -> dict:
    a, b = _records(run1), _records(run2)
    rows, sem_stable, routing_same, raw_same = [], 0, 0, 0
    docs = [n for n in sorted(a) if "llm" in a[n] or "llm" in b.get(n, {})]
    for n in docs:
        qa, qb = qualifiers_of(a[n], variant), qualifiers_of(b[n], variant)
        same_mat = qa["material_signature"] == qb["material_signature"]
        same_route = a[n]["routing"]["decision"] == b[n]["routing"]["decision"]
        same_raw = [q["quote"] for q in qa["material"] + qa["non_material"]] == [q["quote"] for q in qb["material"] + qb["non_material"]]
        sem_stable += same_mat and same_route
        routing_same += same_route
        raw_same += same_raw
        if not (same_mat and same_route):
            rows.append({"document": n, "run1": {"material": qa["material_signature"], "decision": a[n]["routing"]["decision"]},
                         "run2": {"material": qb["material_signature"], "decision": b[n]["routing"]["decision"]}})
    return {"llm_documents": len(docs), "semantically_stable": sem_stable, "routing_same": routing_same,
            "raw_qualifier_text_same": raw_same, "unstable": rows}


def cost_tokens(run_dir: Path) -> dict:
    recs = list(_records(run_dir).values())
    llm = [r["llm"] for r in recs if "llm" in r]
    cost = sum((Decimal(x["estimated_cost_usd"]) for x in llm), Decimal(0))
    n = len(llm) or 1
    lat = [r["audit"]["duration_us"] / 1000 for r in recs if "llm" in r]
    return {"llm_documents": len(llm), "estimated_cost_usd": str(cost), "cost_per_llm_document_usd": str(cost / n),
            "cost_per_input_document_usd": str(cost / len(recs)),
            "input_tokens_per_llm_document": round(sum(x["usage"]["input_tokens"] for x in llm) / n),
            "output_tokens_per_llm_document": round(sum(x["usage"]["output_tokens"] for x in llm) / n),
            "mean_latency_llm_documents_ms": round(sum(lat) / len(lat), 1) if lat else None}


def case_view(rec: dict, variant: str) -> dict:
    q = qualifiers_of(rec, variant)
    sem = rec.get("semantic") or {}
    return {"decision": rec["routing"]["decision"], "reasons": rec["routing"]["reason_codes"],
            "llm_invoked": "llm" in rec,
            "material": [{k: x.get(k) for k in ("kind", "qualifier_type", "affects", "target_field", "blocks", "representation", "quote")}
                         for x in q["material"]],
            "notes": [{k: x.get(k) for k in ("kind", "qualifier_type", "affects", "quote")} for x in q["non_material"]],
            "ex_date": (rec.get("fields") or {}).get("ex_date", {}).get("value"),
            "resolutions": [(r["concept"], r["category"]) for r in sem.get("resolutions", []) if r["category"] != "AGREEMENT"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=E005 / "comparison")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    expected = _expected_routing()
    oracle = {"original": need_oracle_original(), "challenge": need_oracle_challenge()}
    ids = {"original": expected_ids_original(), "challenge": expected_ids_challenge()}
    d = {ds: E004 / f"{ds}_D" for ds in ("original", "challenge")}
    e = {ds: E005 / f"{ds}_E" for ds in ("original", "challenge")}
    res = {
        "quality": quality({"D": d["original"], "E": e["original"]}, {"D": d["challenge"], "E": e["challenge"]}),
        "efficiency": {ds: {"D": efficiency(d[ds], oracle[ds], ids[ds]), "E": efficiency(e[ds], oracle[ds], ids[ds])}
                       for ds in ("original", "challenge")},
        "qualifiers": {ds: {"D": qualifier_metrics(d[ds], "D", expected), "E": qualifier_metrics(e[ds], "E", expected)}
                       for ds in ("original", "challenge")},
        "stability": {ds: {"D": stability(d[ds], E004 / f"{ds}_D_run2", "D"), "E": stability(e[ds], E005 / f"{ds}_E_run2", "E")}
                      for ds in ("original", "challenge")},
        "cost": {ds: {"D": cost_tokens(d[ds]), "E": cost_tokens(e[ds])} for ds in ("original", "challenge")},
        "cases": {},
    }
    for ds, names in (("original", None), ("challenge", None)):
        dr, er, dr2, er2 = _records(d[ds]), _records(e[ds]), _records(E004 / f"{ds}_D_run2"), _records(E005 / f"{ds}_E_run2")
        for n in sorted(er):
            if "llm" in er[n] or "llm" in dr[n] or qualifier_blocked(dr[n]) or qualifier_blocked(er[n]):
                res["cases"][n] = {"expected": expected.get(n), "D_run1": case_view(dr[n], "D"), "D_run2": case_view(dr2[n], "D"),
                                   "E_run1": case_view(er[n], "E"), "E_run2": case_view(er2[n], "E")}
    q = res["quality"]
    doc06 = res["cases"].get("06_petroquimica_litoral_grupamento.pdf", {})
    ch07 = res["cases"].get("CH-07.txt", {})
    unsafe_e = q["original"]["E"]["unsafe_auto_approvals"] + q["challenge"]["E"]["unsafe_auto_approvals"]
    unsafe_d = q["original"]["D"]["unsafe_auto_approvals"] + q["challenge"]["D"]["unsafe_auto_approvals"]
    rr = lambda v: sum(q[ds][v]["review_rate"]["correct"] for ds in ("original", "challenge"))
    res["success_criteria"] = {
        "1_unsafe_auto_approvals_zero": not unsafe_e,
        "2_doc06_not_reviewed_for_operational_reason": bool(doc06) and all(
            not any("MATERIAL_QUALIFIER" in c for c in doc06[k]["reasons"]) and doc06[k]["decision"] == "AUTO_APPROVE"
            for k in ("E_run1", "E_run2")),
        "3_ch07_routing_stable": bool(ch07) and ch07["E_run1"]["decision"] == ch07["E_run2"]["decision"],
        "4_no_previously_safe_case_now_unsafe": not (set(unsafe_e) - set(unsafe_d)) and not unsafe_e,
        "5_review_rate_not_higher": {"D": rr("D"), "E": rr("E"), "ok": rr("E") <= rr("D")},
        "6_explainability": "qualitativo — ver evaluation log",
    }
    (a.out / "e005_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("success_criteria",)}, ensure_ascii=False, indent=2))
    print(f"written: {a.out}")


if __name__ == "__main__":
    main()
