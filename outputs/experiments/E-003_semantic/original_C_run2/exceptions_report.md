# Relatório de exceções — run `20260930T001024Z-e41c436b`

Pipeline `baseline-a/0.1.0+semantic-llm/0.1`. Documentos processados: 8. Aprovados automaticamente: 1. Para revisão: 7.

| Documento | SHA-256 | Decisão | Motivos | Regras com falha |
|---|---|---|---|---|
| 01_energetica_vale_tiete_dividendo.pdf | `e49afdf81d2a` | REVIEW_REQUIRED | SEMANTIC_AMBIGUITY | — |
| 02_banco_meridional_jcp.pdf | `64e0787afd32` | REVIEW_REQUIRED | SEMANTIC_AMBIGUITY | — |
| 03_siderurgica_paranaense_proventos.pdf | `a21a294ac3ed` | REVIEW_REQUIRED | SEMANTIC_AMBIGUITY, CLASSIFICATION_TITLE_CONFLICT | CLASSIFICATION_TITLE_CONSISTENT |
| 04_rede_varejo_jcp_sem_data.pdf | `37f846a73cb5` | REVIEW_REQUIRED | PAYMENT_DATE_PENDING | REQUIRED_FIELDS_NOT_PENDING |
| 05_aurora_saneamento_dividendo_datas.pdf | `925b6eb09fbc` | REVIEW_REQUIRED | DATE_INCONSISTENCY | DATE_SETTLEMENT_NOT_BEFORE_EX |
| 07_telecom_norte_jcp_SCAN.pdf | `cf4af08dd23f` | REVIEW_REQUIRED | NO_USABLE_TEXT_LAYER | — |
| 08_construtora_horizonte_bonificacao.pdf | `a509637f4b25` | REVIEW_REQUIRED | REFERENCE_NOT_FOUND | REF_ISIN_FOUND |

Detalhe de cada motivo em `records/<documento>.json` → `routing.explanations` e `validations`.
