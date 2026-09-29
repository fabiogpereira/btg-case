# Avaliação — run `20260929T231551Z-d79d833d`

Pipeline `baseline-a/0.1.0` · gabarito v2.0

## Extração

| Métrica | Todos os documentos | Com camada de texto |
|---|---|---|
| Tipo de evento | 7/8 (87.5%) | 7/7 (100.0%) |
| Valor exato (campos com valor no gabarito) | 76/93 (81.7%) | 76/80 (95.0%) |
| Status do campo | 99/115 (86.1%) | 99/101 (98.0%) |

**Detecção de ausência / pendência** (status correto quando o gabarito diz que não há valor):

- `declared_pending`: 1/1 (100.0%)
- `not_applicable`: 17/18 (94.4%)
- `not_found`: 3/3 (100.0%)

**Valores inventados** (run encontrou valor onde o gabarito diz que não há): 0


**Por campo** (valor exato / status):

| Campo | Valor | Status |
|---|---|---|
| `issuer_name` | 7/8 (87.5%) | 7/8 (87.5%) |
| `cnpj` | 7/8 (87.5%) | 7/8 (87.5%) |
| `isin` | 7/8 (87.5%) | 7/8 (87.5%) |
| `ticker` | 7/8 (87.5%) | 7/8 (87.5%) |
| `share_class` | 5/6 (83.3%) | 7/8 (87.5%) |
| `approval_date` | 7/8 (87.5%) | 7/8 (87.5%) |
| `record_date` | 7/8 (87.5%) | 7/8 (87.5%) |
| `ex_date` | 6/8 (75.0%) | 6/8 (75.0%) |
| `payment_date` | 4/5 (80.0%) | 7/8 (87.5%) |
| `gross_amount_per_share` | 5/6 (83.3%) | 7/8 (87.5%) |
| `net_amount_per_share` | 3/4 (75.0%) | 7/8 (87.5%) |
| `withholding_tax` | 2/5 (40.0%) | 7/8 (87.5%) |
| `currency` | 5/6 (83.3%) | 7/8 (87.5%) |
| `ratio` | 2/2 (100.0%) | 7/8 (87.5%) |
| `fraction_adjustment_period` | 0/1 (0.0%) | 0/1 (0.0%) |
| `share_credit_date` | 1/1 (100.0%) | 1/1 (100.0%) |
| `tax_cost_per_share` | 1/1 (100.0%) | 1/1 (100.0%) |

## Validação

| Métrica | Todos | Com camada de texto |
|---|---|---|
| Acerto por regra | 101/119 (84.9%) | 101/104 (97.1%) |
| Falsos negativos | 0 | 0 |
| Falsos positivos | 1 | 1 |
| Outras divergências (PASS↔NOT_EVALUATED, ausente) | 17 | 2 |

Divergências (excluindo o documento sem camada de texto):

- 06_petroquimica_litoral_grupamento.pdf · `REQUIRED_FIELDS_PRESENT`: esperado PASS, obtido FAIL (false_positive)
- 06_petroquimica_litoral_grupamento.pdf · `DATE_RECORD_BEFORE_EX`: esperado PASS, obtido NOT_EVALUATED (other_mismatch)
- 06_petroquimica_litoral_grupamento.pdf · `DATE_EX_NEXT_WEEKDAY_AFTER_RECORD`: esperado PASS, obtido NOT_EVALUATED (other_mismatch)

## Roteamento

Expectativas DEFINED: 5/6 (83.3%)

| Documento | Expectativa | Esperado | Obtido | Motivos obtidos | Acerto |
|---|---|---|---|---|---|
| 01_energetica_vale_tiete_dividendo.pdf | DEFINED | AUTO_APPROVE | AUTO_APPROVE | — | ✅ |
| 02_banco_meridional_jcp.pdf | DEFINED | AUTO_APPROVE | AUTO_APPROVE | — | ✅ |
| 03_siderurgica_paranaense_proventos.pdf | PROVISIONAL | REVIEW_REQUIRED | REVIEW_REQUIRED | CLASSIFICATION_TITLE_CONFLICT | (coincide — não conta) |
| 04_rede_varejo_jcp_sem_data.pdf | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED | PAYMENT_DATE_PENDING | ✅ |
| 05_aurora_saneamento_dividendo_datas.pdf | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED | DATE_INCONSISTENCY | ✅ |
| 06_petroquimica_litoral_grupamento.pdf | DEFINED | AUTO_APPROVE | REVIEW_REQUIRED | REQUIRED_FIELD_MISSING | ❌ |
| 07_telecom_norte_jcp_SCAN.pdf | POLICY_DEPENDENT | — | REVIEW_REQUIRED | NO_USABLE_TEXT_LAYER | (sem expectativa — não conta) |
| 08_construtora_horizonte_bonificacao.pdf | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED | REFERENCE_NOT_FOUND | ✅ |

## Operacional

- Documentos processados: 8
- Sem camada de texto utilizável: 1
- Erros: 0
- Tempo total de processamento: 72.4 ms
- Decisões: {'AUTO_APPROVE': 2, 'REVIEW_REQUIRED': 6}

## Por documento

| Documento | Tipo (esp./obt.) | Valores exatos | Status de campo | Regras | Roteamento |
|---|---|---|---|---|---|
| 01_energetica_vale_tiete_dividendo.pdf | DIVIDEND / DIVIDEND | 11/12 | 14/14 | 15/15 | AUTO_APPROVE |
| 02_banco_meridional_jcp.pdf | JCP / JCP | 13/13 | 14/14 | 15/15 | AUTO_APPROVE |
| 03_siderurgica_paranaense_proventos.pdf | JCP / JCP | 12/13 | 14/14 | 15/15 | REVIEW_REQUIRED |
| 04_rede_varejo_jcp_sem_data.pdf | JCP / JCP | 12/12 | 14/14 | 15/15 | REVIEW_REQUIRED |
| 05_aurora_saneamento_dividendo_datas.pdf | DIVIDEND / DIVIDEND | 11/11 | 14/14 | 15/15 | REVIEW_REQUIRED |
| 06_petroquimica_litoral_grupamento.pdf | REVERSE_SPLIT / REVERSE_SPLIT | 7/9 | 13/15 | 11/14 | REVIEW_REQUIRED |
| 07_telecom_norte_jcp_SCAN.pdf | JCP / None | 0/13 | 0/14 | 0/15 | REVIEW_REQUIRED |
| 08_construtora_horizonte_bonificacao.pdf | BONUS_SHARES / BONUS_SHARES | 10/10 | 16/16 | 15/15 | REVIEW_REQUIRED |

## Cobertura das regras do extrator (sinal de sobreajuste)

| Regra | Nº de documentos |
|---|---|
| `approval_date.label_data_aprovacao` | 2 |
| `approval_date.phrase_meeting` | 7 |
| `cnpj.label_cnpj` | 7 |
| `currency.derived_from_gross_symbol` | 5 |
| `event.bonus_acoes_bonificadas` | 1 |
| `event.bonus_bonificacao` | 1 |
| `event.dividend_dividendo` | 4 |
| `event.jcp_juros_capital_proprio` | 2 |
| `event.jcp_lei_9249` | 1 |
| `event.jcp_remuneracao_capital_proprio` | 1 |
| `event.jcp_sigla` | 2 |
| `event.reverse_split_grupamento` | 1 |
| `event.reverse_split_inplit` | 1 |
| `ex_date.label_data_ex` | 6 |
| `gross.label_valor_bruto` | 5 |
| `isin.label_isin` | 7 |
| `issuer_name.pattern_company_sa` | 7 |
| `net.label_valor_liquido` | 3 |
| `payment_date.label_data_pagamento` | 4 |
| `payment_date.label_data_pagamento.pending` | 1 |
| `ratio.label_proporcao_colon` | 1 |
| `ratio.phrase_bonus_new_per_held` | 1 |
| `ratio.phrase_existing_to_new` | 1 |
| `record_date.label_data_base` | 7 |
| `share_class.phrase_por_acao` | 5 |
| `share_credit_date.label_credito_acoes` | 1 |
| `tax_cost.label_custo_atribuido` | 1 |
| `ticker.label_codigo_negociacao` | 7 |
| `withholding.label_imposto_renda` | 3 |
| `withholding.label_irrf` | 2 |

Regras que disparam em um único documento: `event.bonus_acoes_bonificadas`, `event.bonus_bonificacao`, `event.jcp_lei_9249`, `event.jcp_remuneracao_capital_proprio`, `event.reverse_split_grupamento`, `event.reverse_split_inplit`, `payment_date.label_data_pagamento.pending`, `ratio.label_proporcao_colon`, `ratio.phrase_bonus_new_per_held`, `ratio.phrase_existing_to_new`, `share_credit_date.label_credito_acoes`, `tax_cost.label_custo_atribuido`

Observação: com 1 documento por tipo de evento no lote, regras específicas de tipo tendem a cobrir 1 documento por construção; o sinal de sobreajuste relevante são regras genéricas (datas, valores, identificadores) com cobertura 1.

Regras definidas que não contribuíram para nenhum valor resolvido (não dispararam, ou foram suplantadas por uma regra de rótulo na mesma ocorrência): `cnpj.pattern`, `event.split_desdobramento`, `isin.pattern`, `record_date.label_data_com`, `ticker.pattern`
