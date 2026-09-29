"""CLI: python -m evaluation --run-dir DIR [--ground-truth DIR] [--out DIR]

Grava evaluation.json (métricas completas) e evaluation_report.md (resumo legível).
"""
import argparse
import json
from pathlib import Path

from .compare import evaluate

ROOT = Path(__file__).resolve().parents[2]


def _r(x):
    return f"{x['correct']}/{x['total']} ({x['pct']}%)" if x["total"] else "—"


def render(m: dict) -> str:
    ex, va, ro, op = m["extraction"], m["validation"], m["routing"], m["operational"]
    L = [f"# Avaliação — run `{m['run_id']}`", "",
         f"Pipeline `{m['pipeline_version']}` · gabarito v{m['ground_truth_version']}", "",
         "## Extração", "",
         "| Métrica | Todos os documentos | Com camada de texto |", "|---|---|---|",
         f"| Tipo de evento | {_r(ex['event_type_accuracy']['all_documents'])} | {_r(ex['event_type_accuracy']['with_text_layer'])} |",
         f"| Valor exato (campos com valor no gabarito) | {_r(ex['fields']['all_documents']['value_exact_match'])} | {_r(ex['fields']['with_text_layer']['value_exact_match'])} |",
         f"| Status do campo | {_r(ex['fields']['all_documents']['status_match'])} | {_r(ex['fields']['with_text_layer']['status_match'])} |",
         "", "**Detecção de ausência / pendência** (status correto quando o gabarito diz que não há valor):", ""]
    L += [f"- `{k}`: {_r(v)}" for k, v in ex["absence_detection"].items()]
    L += ["", f"**Valores inventados** (run encontrou valor onde o gabarito diz que não há): {len(ex['invented_values'])}", ""]
    L += [f"- {i['document']} · `{i['field']}` (gabarito `{i['expected_status']}`) → `{i['got_value']}`" for i in ex["invented_values"]]
    L += ["", "**Por campo** (valor exato / status):", "", "| Campo | Valor | Status |", "|---|---|---|"]
    L += [f"| `{k}` | {_r(v['value'])} | {_r(v['status'])} |" for k, v in ex["per_field"].items()]
    L += ["", "## Validação", "", "| Métrica | Todos | Com camada de texto |", "|---|---|---|",
          f"| Acerto por regra | {_r(va['all_documents']['accuracy'])} | {_r(va['with_text_layer']['accuracy'])} |",
          f"| Falsos negativos | {va['all_documents']['false_negatives']} | {va['with_text_layer']['false_negatives']} |",
          f"| Falsos positivos | {va['all_documents']['false_positives']} | {va['with_text_layer']['false_positives']} |",
          f"| Outras divergências (PASS↔NOT_EVALUATED, ausente) | {va['all_documents']['other_mismatches']} | {va['with_text_layer']['other_mismatches']} |",
          "", "Divergências (excluindo o documento sem camada de texto):", ""]
    L += [f"- {x['document']} · `{x['rule_id']}`: esperado {x['expected']}, obtido {x['got']} ({x['kind']})"
          for x in va["mismatches"] if x["text_layer_usable"]]
    L += ["", "## Roteamento", "", f"Expectativas DEFINED: {_r(ro['defined_expectations'])}", "",
          "| Documento | Expectativa | Esperado | Obtido | Motivos obtidos | Acerto |", "|---|---|---|---|---|---|"]
    for r in ro["rows"]:
        ok = {True: "✅", False: "❌", None: "n/a"}[r["match"]] if r["expectation_status"] == "DEFINED" else \
            f"({'coincide' if r['match'] else 'diverge' if r['match'] is False else 'sem expectativa'} — não conta)"
        L.append(f"| {r['document']} | {r['expectation_status']} | {r['expected'] or '—'} | {r['got']} | "
                 f"{', '.join(r['got_reasons']) or '—'} | {ok} |")
    L += ["", "## Operacional", "",
          f"- Documentos processados: {op['documents_processed']}",
          f"- Sem camada de texto utilizável: {op['without_usable_text_layer']}",
          f"- Erros: {op['errors']}",
          f"- Tempo total de processamento: {op['total_duration_ms']:.1f} ms",
          f"- Decisões: {op['decisions']}", "",
          "## Por documento", "", "| Documento | Tipo (esp./obt.) | Valores exatos | Status de campo | Regras | Roteamento |",
          "|---|---|---|---|---|---|"]
    for d in m["per_document"]:
        vals = [f for f in d["fields"].values() if f["value_match"] is not None]
        sts = list(d["fields"].values())
        rules = list(d["rules"].values())
        L.append(f"| {d['document']} | {d['event_type']['expected']} / {d['event_type']['got']} | "
                 f"{sum(f['value_match'] for f in vals)}/{len(vals)} | {sum(f['status_match'] for f in sts)}/{len(sts)} | "
                 f"{sum(r['kind'] == 'match' for r in rules)}/{len(rules)} | {d['routing']['got']} |")
    cov = m["extractor_rule_coverage"]
    L += ["", "## Cobertura das regras do extrator (sinal de sobreajuste)", "",
          "| Regra | Nº de documentos |", "|---|---|"]
    L += [f"| `{rid}` | {len(docs)} |" for rid, docs in cov["documents_per_rule"].items()]
    L += ["", f"Regras que disparam em um único documento: {', '.join(f'`{r}`' for r in cov['single_document_rules']) or '—'}",
          "", "Observação: com 1 documento por tipo de evento no lote, regras específicas de tipo tendem a cobrir 1 documento por construção; o sinal de sobreajuste relevante são regras genéricas (datas, valores, identificadores) com cobertura 1.", "", f"Regras definidas que não contribuíram para nenhum valor resolvido (não dispararam, ou foram suplantadas por uma regra de rótulo na mesma ocorrência): {', '.join(f'`{r}`' for r in cov['never_fired']) or '—'}", ""]
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="Compara um run com o gabarito manual")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, default=ROOT / "tests" / "ground_truth")
    p.add_argument("--out", type=Path, default=None, help="default: <run-dir>/evaluation")
    a = p.parse_args()
    out = a.out or a.run_dir / "evaluation"
    out.mkdir(parents=True, exist_ok=True)
    metrics = evaluate(a.ground_truth, a.run_dir)
    (out / "evaluation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "evaluation_report.md").write_text(render(metrics), encoding="utf-8")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
