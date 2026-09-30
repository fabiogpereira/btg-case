# E-004 — B × C × D (hybrid on demand)

B e C: artefatos congelados do E-003. D: execução 1 do E-004. Dataset original é conjunto de **desenvolvimento** (não out-of-sample); challenge set é **ciente do autor** e seus resultados do E-003 eram conhecidos no desenho da D (disclosure no evaluation log).

## original

| Métrica | B | C | D |
|---|---|---|---|
| Tipo de evento | 7/7 | 7/7 | 7/7 |
| Campos semânticos | 29/31 | 31/31 | 30/31 |
| Valor exato | 77/80 | 79/80 | 78/80 |
| Roteamento DEFINED | 5/6 | 4/6 | 5/6 |
| Taxa de revisão | 6/8 | 7/8 | 6/8 |
| Regras de validação | 101/104 | 104/104 | 104/104 |
| **Aprovações inseguras** | **0**  | **0**  | **0**  |
| Valores inventados | 0 | 0 | 0 |

## challenge

| Métrica | B | C | D |
|---|---|---|---|
| Acurácia semântica | 10/21 | 21/21 | 21/21 |
| Papel de data | 0/8 | 8/8 | 8/8 |
| Negação | 3/4 | 4/4 | 4/4 |
| Qualificador / IR condicional | 6/6 | 6/6 | 6/6 |
| Palavras enganosas | 6/8 | 8/8 | 8/8 |
| Descrição do evento | 2/3 | 3/3 | 3/3 |
| Roteamento DEFINED | 4/7 | 5/7 | 7/7 |
| Taxa de revisão | 8/11 | 4/11 | 5/11 |
| Falsamente confiantes | 0 | 0 | 0 |
| **Aprovações inseguras** | **0**  | **0**  | **0**  |

## Eficiência — original

| | C (sempre) | D (sob demanda) |
|---|---|---|
| Documentos / elegíveis | 8 | 8 / 7 |
| Documentos com LLM | 7 | 1 (1/7) |
| Chamadas de API / tool calls | 14 / 8 | 2 / 1 |
| Custo total (US$) | 0.4113 | 0.0733 |
| Custo por documento de entrada (US$) | 0.0514 | 0.0092 |
| Custo por documento com LLM (US$) | — | 0.0733 |
| Latência fim a fim média / p50 (ms) | 10398.4 / 9697.3 | 2205.9 / 13.2 |
| Latência D com LLM média / p50 (ms) | — | 17552.9 / 17552.9 |
| Latência D sem LLM média / p50 (ms) | — | 13.4 / 12.0 |
| Tool calls por documento processado / por documento com LLM | — | 0.125 / 1.0 |

- Invocadas corretamente: 06_petroquimica_litoral_grupamento.pdf
- Puladas corretamente: 01_energetica_vale_tiete_dividendo.pdf, 02_banco_meridional_jcp.pdf, 04_rede_varejo_jcp_sem_data.pdf, 05_aurora_saneamento_dividendo_datas.pdf, 08_construtora_horizonte_bonificacao.pdf
- **Invocações falso-positivas:** —
- **Invocações falso-negativas:** 03_siderurgica_paranaense_proventos.pdf
- Gatilhos por documento: 01_energetica_vale_tiete_dividendo.pdf: —; 02_banco_meridional_jcp.pdf: —; 03_siderurgica_paranaense_proventos.pdf: —; 04_rede_varejo_jcp_sem_data.pdf: —; 05_aurora_saneamento_dividendo_datas.pdf: —; 06_petroquimica_litoral_grupamento.pdf: REQUIRED_DATE_ROLE_UNMAPPED; 08_construtora_horizonte_bonificacao.pdf: —
- Function calling (só documentos com LLM): {"documents_expected": 1, "total_tool_calls": 1, "documents_with_tool_call": 1, "correct_calls": 1, "unnecessary_calls": 0, "incorrect_arguments": 0, "expected_calls_missing": 0}

Consistência D execução 1 × 2 (original): decisão de invocar 8/8; roteamento 8/8; nos documentos com LLM: event_type 1/1, semantic_fields 1/1, llm_interpretation 1/1, routing_decision 1/1, tool_call_count 1/1, tool_arguments 1/1

## Eficiência — challenge

| | C (sempre) | D (sob demanda) |
|---|---|---|
| Documentos / elegíveis | 11 | 11 / 11 |
| Documentos com LLM | 11 | 10 (10/11) |
| Chamadas de API / tool calls | 22 / 11 | 20 / 10 |
| Custo total (US$) | 0.5937 | 0.6413 |
| Custo por documento de entrada (US$) | 0.0540 | 0.0583 |
| Custo por documento com LLM (US$) | — | 0.0641 |
| Latência fim a fim média / p50 (ms) | 10644.7 / 10377.8 | 11214.6 / 11734.5 |
| Latência D com LLM média / p50 (ms) | — | 12335.8 / 11815.6 |
| Latência D sem LLM média / p50 (ms) | — | 3.0 / 3.0 |
| Tool calls por documento processado / por documento com LLM | — | 0.909 / 1.0 |

- Invocadas corretamente: CH-03, CH-04, CH-06, CH-07, CH-08, CH-09, CH-10
- Puladas corretamente: CH-05
- **Invocações falso-positivas:** CH-01, CH-02, CH-11
- **Invocações falso-negativas:** —
- Gatilhos por documento: CH-01: NEGATION_DECIDED_CLASSIFICATION; CH-02: NEGATION_DECIDED_CLASSIFICATION; CH-03: CLASSIFICATION_UNSUPPORTED; CH-04: EVENT_SIGNALS_CONFLICT, CLASSIFICATION_UNSUPPORTED; CH-05: —; CH-06: UNINTERPRETED_QUALIFIER; CH-07: REQUIRED_DATE_ROLE_UNMAPPED; CH-08: REQUIRED_DATE_ROLE_UNMAPPED; CH-09: REQUIRED_DATE_ROLE_UNMAPPED; CH-10: EVENT_SIGNALS_CONFLICT; CH-11: UNINTERPRETED_QUALIFIER
- Function calling (só documentos com LLM): {"documents_expected": 10, "total_tool_calls": 10, "documents_with_tool_call": 10, "correct_calls": 10, "unnecessary_calls": 0, "incorrect_arguments": 0, "expected_calls_missing": 0}

Consistência D execução 1 × 2 (challenge): decisão de invocar 11/11; roteamento 10/11; nos documentos com LLM: event_type 10/10, semantic_fields 10/10, llm_interpretation 10/10, routing_decision 9/10, tool_call_count 9/10, tool_arguments 9/10

