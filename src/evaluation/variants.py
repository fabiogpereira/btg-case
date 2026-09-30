"""Comparação A/B/C (E-003): dataset original e challenge set, lado a lado, sem misturar métricas.

python -m evaluation.variants --original A=DIR B=DIR C=DIR --challenge A=DIR B=DIR C=DIR        [--c-repeat-original DIR --c-repeat-challenge DIR] --out DIR

A segunda execução de C (--c-repeat-*) serve só para consistência entre execuções; as métricas
de qualidade usam a primeira.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .challenge import evaluate_challenge
from .compare import evaluate
from .llm_metrics import consistency, expected_ids_challenge, expected_ids_original, function_calling

ROOT = Path(__file__).resolve().parents[2]


def _r(x):
    return "—" if not x or not x["total"] else f"{x['correct']}/{x['total']}"


def _pairs(values):
    return dict(v.split("=", 1) for v in values)


def _llm_details(run_dir: Path) -> dict | None:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if "llm" not in manifest["summary"]:
        return None
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json"))]
    llms = [r["llm"] for r in recs if "llm" in r]
    grounded = sum((x.get("grounding") or {}).get("grounded_quotes", 0) for x in llms)
    total = sum((x.get("grounding") or {}).get("total_quotes", 0) for x in llms)
    docs_with_tool = sum(any(t["name"] == "lookup_security" for t in x["tool_calls"]) for x in llms)
    return {**manifest["summary"]["llm"], "config": manifest["config"]["llm"],
            "grounded_quotes": grounded, "total_quotes": total,
            "documents_with_lookup_tool_call": docs_with_tool,
            "ungrounded": [{"document": r["document"]["file_name"], **u} for r in recs if "llm" in r
                           for u in ((r["llm"].get("grounding") or {}).get("ungrounded") or [])],
            "tool_latency_us": [t["latency_us"] for x in llms for t in x["tool_calls"]],
            "per_document_latency_ms": [x["latency_ms"] for x in llms]}


def compare(original: dict, challenge: dict, c_repeat: dict | None = None) -> dict:
    out = {"original": {}, "challenge": {}, "llm": {}}
    for v, d in original.items():
        m = evaluate(ROOT / "tests" / "ground_truth", Path(d))
        out["original"][v] = {
            "run_id": m["run_id"],
            "event_type": m["extraction"]["event_type_accuracy"]["with_text_layer"],
            "semantic_targets": m["semantic"]["semantic_targets"]["with_text_layer"],
            "value_exact": m["extraction"]["fields"]["with_text_layer"]["value_exact_match"],
            "field_status": m["extraction"]["fields"]["with_text_layer"]["status_match"],
            "validation": m["validation"]["with_text_layer"],
            "unsafe_auto_approvals": m["semantic"]["unsafe_auto_approvals"],
            "invented_values": len(m["extraction"]["invented_values"]),
            "review_rate": m["routing"]["review_rate"],
            "routing_defined": m["routing"]["defined_expectations"],
            "routing_rows": m["routing"]["rows"],
            "total_duration_ms": m["operational"]["total_duration_ms"],
            "errors": m["operational"]["errors"],
        }
        llm = _llm_details(Path(d))
        if llm:
            out["llm"].setdefault(v, {})["original"] = llm
    for v, d in challenge.items():
        out["challenge"][v] = evaluate_challenge(ROOT / "tests" / "challenge_set", Path(d))
        llm = _llm_details(Path(d))
        if llm:
            out["llm"].setdefault(v, {})["challenge"] = llm
    expected = {"original": expected_ids_original(), "challenge": expected_ids_challenge()}
    runs = {"original": original, "challenge": challenge}
    for v, parts in out["llm"].items():
        for ds in parts:
            parts[ds]["function_calling"] = function_calling(Path(runs[ds][v]), expected[ds])
            parts[ds]["protocol_fixed_config"] = parts[ds]["config"]["fallbacks"] == "off"
            repeat = (c_repeat or {}).get(ds)
            if repeat and v == "C":
                parts[ds]["run_to_run_consistency"] = consistency(Path(runs[ds][v]), Path(repeat))
                parts[ds]["repeat_function_calling"] = function_calling(Path(repeat), expected[ds])
    return out


def render(c: dict) -> str:
    vs = list(c["original"])
    L = ["# E-003 — Comparação A / B / C", "",
         "Dataset original e challenge set são avaliados **separadamente**; as métricas não se misturam.", "",
         "## Dataset original (7 documentos com camada de texto; doc 07 sem texto em todas as variantes)", "",
         "| Métrica | " + " | ".join(vs) + " |", "|---|" + "---|" * len(vs)]
    o = c["original"]
    rows = [("Tipo de evento", lambda x: _r(x["event_type"])),
            ("Campos semânticos (tipo, IR, papéis de data)", lambda x: _r(x["semantic_targets"])),
            ("Valor exato de campo", lambda x: _r(x["value_exact"])),
            ("Status de campo", lambda x: _r(x["field_status"])),
            ("Regras de validação corretas", lambda x: _r(x["validation"]["accuracy"])),
            ("Falsos negativos / positivos de validação",
             lambda x: f"{x['validation']['false_negatives']} / {x['validation']['false_positives']}"),
            ("**Aprovações automáticas inseguras**",
             lambda x: f"**{len(x['unsafe_auto_approvals'])}**" + (f" ({', '.join(u['document'][:2] for u in x['unsafe_auto_approvals'])})" if x['unsafe_auto_approvals'] else "")),
            ("Valores inventados", lambda x: str(x["invented_values"])),
            ("Taxa de revisão (8 docs)", lambda x: _r(x["review_rate"])),
            ("Roteamento DEFINED correto", lambda x: _r(x["routing_defined"])),
            ("Tempo de processamento (ms)", lambda x: f"{x['total_duration_ms']:.0f}")]
    for label, fn in rows:
        L.append(f"| {label} | " + " | ".join(fn(o[v]) for v in vs) + " |")
    L += ["", "Roteamento por documento:", "", "| Documento | Expectativa | " + " | ".join(vs) + " |", "|---|---|" + "---|" * len(vs)]
    for i, row in enumerate(o[vs[0]]["routing_rows"]):
        exp = f"{row['expected'] or '—'} ({row['expectation_status']})"
        cells = []
        for v in vs:
            r = o[v]["routing_rows"][i]
            cells.append(f"{r['got']} {'/'.join(r['got_reasons'])}".strip())
        L.append(f"| {row['document'][:40]} | {exp} | " + " | ".join(cells) + " |")

    ch = c["challenge"]
    cvs = list(ch)
    L += ["", "## Challenge set sintético (11 casos)", "", "| Métrica | " + " | ".join(cvs) + " |", "|---|" + "---|" * len(cvs)]
    crow = [("Acurácia semântica (alvos)", "semantic_accuracy"), ("Negação", "negation_accuracy"),
            ("Expressão condicional (IR)", "conditional_expression_accuracy"),
            ("Mapeamento de papel de data", "date_role_mapping_accuracy"),
            ("Palavras enganosas", "misleading_keywords_accuracy"), ("Descrição do evento", "event_description_accuracy")]
    for label, key in crow:
        L.append(f"| {label} | " + " | ".join(_r(ch[v][key]) for v in cvs) + " |")
    L.append("| **Interpretações falsamente confiantes** | " + " | ".join(f"**{ch[v]['false_confident_interpretations']}**" for v in cvs) + " |")
    L.append("| Erradas mas sinalizadas (revisão) | " + " | ".join(str(ch[v]["wrong_but_flagged"]) for v in cvs) + " |")
    L.append("| **Aprovações automáticas inseguras** | " + " | ".join(
        f"**{len(ch[v]['unsafe_auto_approvals'])}**" + (f" ({', '.join(ch[v]['unsafe_auto_approvals'])})" if ch[v]['unsafe_auto_approvals'] else "")
        for v in cvs) + " |")
    L.append("| Roteamento DEFINED correto | " + " | ".join(_r(ch[v]["routing_defined"]) for v in cvs) + " |")
    L.append("| Taxa de revisão | " + " | ".join(_r(ch[v]["review_rate"]) for v in cvs) + " |")
    L += ["", "Por caso (✅ alvo correto · ❌ errado; decisão):", "", "| Caso | Categorias | " + " | ".join(cvs) + " |",
          "|---|---|" + "---|" * len(cvs)]
    for i, case in enumerate(ch[cvs[0]]["cases"]):
        cells = []
        for v in cvs:
            r = ch[v]["cases"][i]
            marks = "".join("✅" if t["correct"] else "❌" for t in r["targets"])
            cells.append(f"{marks} {r['decision'].replace('_REQUIRED', '').replace('AUTO_', '')}")
        L.append(f"| {case['case']} | {', '.join(case['categories'])} | " + " | ".join(cells) + " |")

    for v, parts in c["llm"].items():
        for ds, x in parts.items():
            cfg = x["config"]
            L += ["", f"## LLM — variante {v}, {ds}", "",
                  f"- Provedor/modelo solicitado: `{cfg['provider']}` / `{cfg['model']}` (effort `{cfg['effort']}`, fallbacks `{cfg['fallbacks']}`); modelos que responderam: {', '.join(x['served_models']) or '—'}",
                  f"- Prompt: `{cfg['prompt_version']}` (fingerprint `{cfg['prompt_fingerprint']}`)",
                  f"- Documentos: {x['documents_with_llm']} · chamadas de API: {x['api_calls']} · tool calls: {x['tool_calls']} (documentos com `lookup_security`: {x['documents_with_lookup_tool_call']})",
                  f"- Tokens: entrada {x['input_tokens']:,} · saída {x['output_tokens']:,} · custo estimado US$ {Decimal(x['estimated_cost_usd']):.4f}",
                  f"- Latência LLM total: {x['llm_latency_ms'] / 1000:.1f} s (por documento: mín {min(x['per_document_latency_ms'] or [0]) / 1000:.1f} s, máx {max(x['per_document_latency_ms'] or [0]) / 1000:.1f} s)",
                  f"- Falhas de parse/schema: {x['parse_or_schema_failures']} · erros: {x['errors']} · divergências de referência (tool × validation engine): {x['reference_divergences']}",
                  f"- Grounding: {x['grounded_quotes']}/{x['total_quotes']} trechos localizados literalmente" + (
                      "; não localizados: " + "; ".join(f"{u['document']} {u['where']}: \"{u['quote'][:60]}\"" for u in x["ungrounded"]) if x["ungrounded"] else ""),
                  f"- Respostas vindas do cache (replay): {x['replayed_documents']}",
                  f"- Recusas: {x.get('refusals', 0)} · modelo servido ≠ solicitado: {x.get('served_model_mismatches', 0)} · "
                  f"protocolo (configuração fixa, fallback off): {'OK' if x['protocol_fixed_config'] else 'VIOLADO'}"]
            fc = x["function_calling"]
            L += ["", f"Function calling ({ds}):", "",
                  "| Métrica | Valor |", "|---|---|",
                  f"| Total de tool calls | {fc['total_tool_calls']} |",
                  f"| Documentos com tool call | {fc['documents_with_tool_call']}/{fc['documents_expected']} |",
                  f"| Chamadas corretas | {fc['correct_calls']} |",
                  f"| Chamadas desnecessárias | {fc['unnecessary_calls']} |",
                  f"| Chamadas esperadas que não ocorreram | {fc['expected_calls_missing']}" + (f" ({', '.join(fc['missing_in'])})" if fc['missing_in'] else "") + " |",
                  f"| Argumentos incorretos | {fc['incorrect_arguments']} |"]
            cons = x.get("run_to_run_consistency")
            if cons:
                L += ["", f"Consistência entre as duas execuções ({ds}, {cons['documents_compared']} documentos):", "",
                      "| Dimensão | Consistentes |", "|---|---|"]
                labels = {"event_type": "Tipo de evento", "semantic_fields": "Campos semanticamente interpretados (valor + confiança)",
                          "llm_interpretation": "Interpretação bruta do LLM (tipo, datas como escritas, IR)",
                          "routing_decision": "Decisão de roteamento", "routing_reasons": "Motivos de roteamento",
                          "tool_call_count": "Número de tool calls", "tool_arguments": "Argumentos das tool calls"}
                L += [f"| {labels[k]} | {cons[k]['consistent']}/{cons[k]['total']} |" for k in labels]
                for dd in cons["inconsistent_documents"]:
                    L.append(f"- {dd['document']}: inconsistente em {', '.join(dd['inconsistent'])}")
    return "\n".join(L) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--original", nargs="+", required=True, help="VARIANTE=DIR_DO_RUN")
    p.add_argument("--challenge", nargs="+", required=True, help="VARIANTE=DIR_DO_RUN")
    p.add_argument("--c-repeat-original", type=Path, default=None)
    p.add_argument("--c-repeat-challenge", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    result = compare(_pairs(a.original), _pairs(a.challenge),
                     {"original": a.c_repeat_original, "challenge": a.c_repeat_challenge})
    (a.out / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.out / "comparison_report.md").write_text(render(result), encoding="utf-8")
    print(f"written: {a.out}")


if __name__ == "__main__":
    main()
