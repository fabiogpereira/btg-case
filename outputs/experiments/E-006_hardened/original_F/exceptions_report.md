# Relatório de exceções — run `20260930T020833Z-df91ac24`

Pipeline `baseline-a/0.1.0+candidate-hardened/0.1`. Documentos processados: 8. Aprovados automaticamente: 2. Para revisão: 6.

| Documento | SHA-256 | Decisão | Motivos | Regras com falha |
|---|---|---|---|---|
| 03_siderurgica_paranaense_proventos.pdf | `a21a294ac3ed` | REVIEW_REQUIRED | CLASSIFICATION_TITLE_CONFLICT | CLASSIFICATION_TITLE_CONSISTENT |
| 04_rede_varejo_jcp_sem_data.pdf | `37f846a73cb5` | REVIEW_REQUIRED | PAYMENT_DATE_PENDING | REQUIRED_FIELDS_NOT_PENDING |
| 05_aurora_saneamento_dividendo_datas.pdf | `925b6eb09fbc` | REVIEW_REQUIRED | DATE_INCONSISTENCY | DATE_SETTLEMENT_NOT_BEFORE_EX |
| 06_petroquimica_litoral_grupamento.pdf | `147d83f038f6` | REVIEW_REQUIRED | REQUIRED_FIELD_MISSING, MATERIAL_INFORMATION_NOT_REPRESENTED | REQUIRED_FIELDS_PRESENT |
| 07_telecom_norte_jcp_SCAN.pdf | `cf4af08dd23f` | REVIEW_REQUIRED | NO_USABLE_TEXT_LAYER | — |
| 08_construtora_horizonte_bonificacao.pdf | `a509637f4b25` | REVIEW_REQUIRED | REFERENCE_NOT_FOUND | REF_ISIN_FOUND |

Detalhe de cada motivo em `records/<documento>.json` → `routing.explanations` e `validations`.
