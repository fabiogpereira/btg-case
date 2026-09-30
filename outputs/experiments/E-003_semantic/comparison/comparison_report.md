# E-003 — Comparação A / B / C

Dataset original e challenge set são avaliados **separadamente**; as métricas não se misturam.

## Dataset original (7 documentos com camada de texto; doc 07 sem texto em todas as variantes)

| Métrica | A | B | C |
|---|---|---|---|
| Tipo de evento | 7/7 | 7/7 | 7/7 |
| Campos semânticos (tipo, IR, papéis de data) | 28/31 | 29/31 | 31/31 |
| Valor exato de campo | 76/80 | 77/80 | 79/80 |
| Status de campo | 99/101 | 99/101 | 100/101 |
| Regras de validação corretas | 101/104 | 101/104 | 104/104 |
| Falsos negativos / positivos de validação | 0 / 1 | 0 / 1 | 0 / 0 |
| **Aprovações automáticas inseguras** | **1** (01) | **0** | **0** |
| Valores inventados | 0 | 0 | 0 |
| Taxa de revisão (8 docs) | 6/8 | 6/8 | 7/8 |
| Roteamento DEFINED correto | 5/6 | 5/6 | 4/6 |
| Tempo de processamento (ms) | 75 | 83 | 83187 |

Roteamento por documento:

| Documento | Expectativa | A | B | C |
|---|---|---|---|---|
| 01_energetica_vale_tiete_dividendo.pdf | AUTO_APPROVE (DEFINED) | AUTO_APPROVE | AUTO_APPROVE | REVIEW_REQUIRED SEMANTIC_AMBIGUITY |
| 02_banco_meridional_jcp.pdf | AUTO_APPROVE (DEFINED) | AUTO_APPROVE | AUTO_APPROVE | REVIEW_REQUIRED SEMANTIC_AMBIGUITY |
| 03_siderurgica_paranaense_proventos.pdf | REVIEW_REQUIRED (PROVISIONAL) | REVIEW_REQUIRED CLASSIFICATION_TITLE_CONFLICT | REVIEW_REQUIRED CLASSIFICATION_TITLE_CONFLICT | REVIEW_REQUIRED SEMANTIC_AMBIGUITY/CLASSIFICATION_TITLE_CONFLICT |
| 04_rede_varejo_jcp_sem_data.pdf | REVIEW_REQUIRED (DEFINED) | REVIEW_REQUIRED PAYMENT_DATE_PENDING | REVIEW_REQUIRED PAYMENT_DATE_PENDING | REVIEW_REQUIRED PAYMENT_DATE_PENDING |
| 05_aurora_saneamento_dividendo_datas.pdf | REVIEW_REQUIRED (DEFINED) | REVIEW_REQUIRED DATE_INCONSISTENCY | REVIEW_REQUIRED DATE_INCONSISTENCY | REVIEW_REQUIRED DATE_INCONSISTENCY |
| 06_petroquimica_litoral_grupamento.pdf | AUTO_APPROVE (DEFINED) | REVIEW_REQUIRED REQUIRED_FIELD_MISSING | REVIEW_REQUIRED REQUIRED_FIELD_MISSING | AUTO_APPROVE |
| 07_telecom_norte_jcp_SCAN.pdf | — (POLICY_DEPENDENT) | REVIEW_REQUIRED NO_USABLE_TEXT_LAYER | REVIEW_REQUIRED NO_USABLE_TEXT_LAYER | REVIEW_REQUIRED NO_USABLE_TEXT_LAYER |
| 08_construtora_horizonte_bonificacao.pdf | REVIEW_REQUIRED (DEFINED) | REVIEW_REQUIRED REFERENCE_NOT_FOUND | REVIEW_REQUIRED REFERENCE_NOT_FOUND | REVIEW_REQUIRED REFERENCE_NOT_FOUND |

## Challenge set sintético (11 casos)

| Métrica | A | B | C |
|---|---|---|---|
| Acurácia semântica (alvos) | 6/21 | 10/21 | 21/21 |
| Negação | 1/4 | 3/4 | 4/4 |
| Expressão condicional (IR) | 5/6 | 6/6 | 6/6 |
| Mapeamento de papel de data | 0/8 | 0/8 | 8/8 |
| Palavras enganosas | 5/8 | 6/8 | 8/8 |
| Descrição do evento | 0/3 | 2/3 | 3/3 |
| **Interpretações falsamente confiantes** | **1** | **0** | **0** |
| Erradas mas sinalizadas (revisão) | 14 | 11 | 0 |
| **Aprovações automáticas inseguras** | **1** (CH-05) | **0** | **0** |
| Roteamento DEFINED correto | 3/7 | 4/7 | 5/7 |
| Taxa de revisão | 9/11 | 8/11 | 4/11 |

Por caso (✅ alvo correto · ❌ errado; decisão):

| Caso | Categorias | A | B | C |
|---|---|---|---|---|
| CH-01 | negation, event_description | ❌ REVIEW | ✅ APPROVE | ✅ REVIEW |
| CH-02 | negation, misleading_keywords | ❌ REVIEW | ✅ APPROVE | ✅ APPROVE |
| CH-03 | event_description | ❌ REVIEW | ❌ REVIEW | ✅ APPROVE |
| CH-04 | misleading_keywords | ❌ REVIEW | ❌ REVIEW | ✅ APPROVE |
| CH-05 | conditional_tax | ✅❌ APPROVE | ✅✅ APPROVE | ✅✅ APPROVE |
| CH-06 | conditional_tax, misleading_keywords | ✅✅✅✅ APPROVE | ✅✅✅✅ REVIEW | ✅✅✅✅ APPROVE |
| CH-07 | alternative_date_labels | ❌❌❌ REVIEW | ❌❌❌ REVIEW | ✅✅✅ APPROVE |
| CH-08 | alternative_date_labels | ❌❌ REVIEW | ❌❌ REVIEW | ✅✅ APPROVE |
| CH-09 | alternative_date_labels | ❌❌❌ REVIEW | ❌❌❌ REVIEW | ✅✅✅ REVIEW |
| CH-10 | negation, misleading_keywords | ❌✅ REVIEW | ❌✅ REVIEW | ✅✅ REVIEW |
| CH-11 | event_description, unresolvable | ❌ REVIEW | ✅ REVIEW | ✅ REVIEW |

## LLM — variante C, original

- Provedor/modelo solicitado: `anthropic` / `claude-opus-5` (effort `medium`, fallbacks `off`); modelos que responderam: claude-opus-5
- Prompt: `semantic-interpreter/v1` (fingerprint `cf27c1d6164099c5`)
- Documentos: 7 · chamadas de API: 14 · tool calls: 8 (documentos com `lookup_security`: 7)
- Tokens: entrada 55,031 · saída 5,445 · custo estimado US$ 0.4113
- Latência LLM total: 82.7 s (por documento: mín 9.3 s, máx 15.5 s)
- Falhas de parse/schema: 0 · erros: 0 · divergências de referência (tool × validation engine): 0
- Grounding: 65/65 trechos localizados literalmente
- Respostas vindas do cache (replay): 0
- Recusas: 0 · modelo servido ≠ solicitado: 0 · protocolo (configuração fixa, fallback off): OK

Function calling (original):

| Métrica | Valor |
|---|---|
| Total de tool calls | 8 |
| Documentos com tool call | 7/7 |
| Chamadas corretas | 7 |
| Chamadas desnecessárias | 1 |
| Chamadas esperadas que não ocorreram | 0 |
| Argumentos incorretos | 0 |

Consistência entre as duas execuções (original, 7 documentos):

| Dimensão | Consistentes |
|---|---|
| Tipo de evento | 7/7 |
| Campos semanticamente interpretados (valor + confiança) | 7/7 |
| Interpretação bruta do LLM (tipo, datas como escritas, IR) | 5/7 |
| Decisão de roteamento | 7/7 |
| Motivos de roteamento | 7/7 |
| Número de tool calls | 5/7 |
| Argumentos das tool calls | 5/7 |
- 04_rede_varejo_jcp_sem_data.pdf: inconsistente em llm_interpretation
- 02_banco_meridional_jcp.pdf: inconsistente em llm_interpretation, tool_call_count, tool_arguments
- 01_energetica_vale_tiete_dividendo.pdf: inconsistente em tool_call_count, tool_arguments

## LLM — variante C, challenge

- Provedor/modelo solicitado: `anthropic` / `claude-opus-5` (effort `medium`, fallbacks `off`); modelos que responderam: claude-opus-5
- Prompt: `semantic-interpreter/v1` (fingerprint `cf27c1d6164099c5`)
- Documentos: 11 · chamadas de API: 22 · tool calls: 11 (documentos com `lookup_security`: 11)
- Tokens: entrada 80,384 · saída 7,672 · custo estimado US$ 0.5937
- Latência LLM total: 117.0 s (por documento: mín 9.4 s, máx 14.0 s)
- Falhas de parse/schema: 0 · erros: 0 · divergências de referência (tool × validation engine): 0
- Grounding: 85/85 trechos localizados literalmente
- Respostas vindas do cache (replay): 0
- Recusas: 0 · modelo servido ≠ solicitado: 0 · protocolo (configuração fixa, fallback off): OK

Function calling (challenge):

| Métrica | Valor |
|---|---|
| Total de tool calls | 11 |
| Documentos com tool call | 11/11 |
| Chamadas corretas | 11 |
| Chamadas desnecessárias | 0 |
| Chamadas esperadas que não ocorreram | 0 |
| Argumentos incorretos | 0 |

Consistência entre as duas execuções (challenge, 11 documentos):

| Dimensão | Consistentes |
|---|---|
| Tipo de evento | 11/11 |
| Campos semanticamente interpretados (valor + confiança) | 11/11 |
| Interpretação bruta do LLM (tipo, datas como escritas, IR) | 11/11 |
| Decisão de roteamento | 11/11 |
| Motivos de roteamento | 11/11 |
| Número de tool calls | 11/11 |
| Argumentos das tool calls | 11/11 |
