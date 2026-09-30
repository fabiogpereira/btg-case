# Relatório de exceções — run `20260930T000818Z-fd2fca1a`

Pipeline `baseline-a/0.1.0+semantic-llm/0.1`. Documentos processados: 11. Aprovados automaticamente: 7. Para revisão: 4.

| Documento | SHA-256 | Decisão | Motivos | Regras com falha |
|---|---|---|---|---|
| CH-01.txt | `0948936feb0b` | REVIEW_REQUIRED | CLASSIFICATION_DISAGREEMENT | — |
| CH-09.txt | `410d545bb7d8` | REVIEW_REQUIRED | LOW_EXTRACTION_CONFIDENCE | — |
| CH-10.txt | `d66be6ca69d4` | REVIEW_REQUIRED | CLASSIFICATION_DISAGREEMENT | — |
| CH-11.txt | `2d3f885861cb` | REVIEW_REQUIRED | SEMANTIC_AMBIGUITY, CLASSIFICATION_UNDETERMINED | CLASSIFICATION_DETERMINED |

Detalhe de cada motivo em `records/<documento>.json` → `routing.explanations` e `validations`.
