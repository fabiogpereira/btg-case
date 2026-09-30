# DECISIONS — Architecture Decision Log

Registra apenas **decisões tomadas**. Hipóteses ficam em `docs/02-hypotheses.md` até serem testadas.
Cada decisão técnica aponta para a hipótese/experimento que a sustenta, ou declara explicitamente que é uma decisão de princípio/política.

Formato:
```
## D-XXX — Título
- Data:
- Status: ACCEPTED | SUPERSEDED by D-YYY | REVOKED
- Tipo: processo | princípio | política de negócio | técnica (com evidência)
- Contexto:
- Decisão:
- Evidência:
- Alternativas consideradas:
- Consequências / trade-offs:
```

---

## D-000 — Material original do case em `case/`, somente leitura

- **Data:** 2026-09-29
- **Status:** ACCEPTED — material confirmado pelo usuário em 2026-09-29 (Q-02 resolvida).
- **Tipo:** processo
- **Contexto:** O usuário definiu `/case` como source of truth. O diretório não existia; o material foi localizado em `Downloads/Case_AI_Dev_-_Envio.zip`.
- **Decisão:** Extrair o zip sem modificação para `case/`, preservando a estrutura original (`case/Case AI Dev - Envio/{documents,enunciado,golden_records}`). Registrar SHA-256 de cada arquivo em `docs/01-document-map.md`. Nenhum arquivo é criado, alterado ou renomeado dentro de `case/`.
- **Evidência:** Instrução do usuário; confirmação do material.
- **Alternativas consideradas:** Achatar a pasta raiz do zip (`case/documents/...`) — rejeitado para não alterar a estrutura original.
- **Consequências:** Caminhos com espaços (`Case AI Dev - Envio`, `golden records.csv`) precisam ser tratados no código. Os nomes divergem do enunciado (`documentos/`, `golden_records.csv`).
- **Adendo (2026-09-29, checkpoint git):** o `core.autocrlf` do ambiente tratava os PDFs do ReportLab (quase ASCII) como texto e converteria fins de linha num clone, alterando os bytes e os SHA-256. O `.gitattributes` marca `case/** -text -diff` e `*.pdf binary`. Verificado: os blobs versionados são byte a byte idênticos aos originais.

## D-001 — Trabalho orientado por hipóteses, com documentação separada por natureza

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo
- **Contexto:** O case avalia critério e julgamento, não só resultado.
- **Decisão:** Separar entendimento (`docs/00`), evidência por documento (`docs/01`), hipóteses (`docs/02`), arquitetura em evolução (`docs/03`), experimentos (`docs/04`) e decisões (este arquivo). O README do entregável resumirá as decisões e trade-offs (exigência do enunciado) a partir deste log.
- **Evidência:** Decisão de processo.
- **Consequências:** Toda decisão técnica futura precisa de hipótese + experimento antes de entrar aqui.

## D-002 — Function calling híbrido: o LLM usa tool de referência, mas a segurança não depende dele

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** princípio + interpretação de requisito (resolve Q-01 / OD-02)
- **Contexto:** O enunciado pede validação contra `golden_records.csv` e regras de coerência "usando tool / function calling" (R3). Nosso princípio é que validações financeiras são determinísticas e não podem depender de o modelo decidir chamar algo.
- **Decisão:**
  1. Validadores são implementados **uma vez** como funções determinísticas puras, expostas também com schema de tool.
  2. Na etapa em que houver LLM, o modelo **deve efetivamente usar ao menos uma tool determinística** de consulta/validação de referência (ex.: lookup no golden records), via function calling real do provider.
  3. O **orchestrator executa todas as validações financeiras obrigatórias** (referência, datas, bruto × líquido, proporção, schema) de forma determinística, **independentemente** de o LLM ter chamado alguma tool.
  4. Os resultados das tools chamadas pelo LLM são registrados no audit trail, mas o que vale para confiança e roteamento é o resultado executado pelo orchestrator. Divergência entre os dois é registrada.
- **Evidência:** Decisão de princípio. H-15 permanece para medir se o LLM omite chamadas ou diverge do orchestrator.
- **Alternativas consideradas:**
  - Só o código chama as tools (sem function calling pelo LLM) — atende o princípio, mas corre o risco de não atender a letra do R3.
  - Só o LLM chama as tools (loop agêntico) — atende a letra, mas a segurança passaria a depender do modelo.
- **Consequências / trade-offs:** Uma chamada de tool pelo LLM que é, em parte, redundante com o orchestrator (custo marginal pequeno). Em troca: requisito atendido, segurança garantida por código e uma métrica de "o LLM chamou as tools certas?" disponível para auditoria.
- **Reforço (2026-09-29):** se uma validação/tool invocada pelo LLM divergir do validation engine obrigatório, **prevalece o validation engine**, e a divergência é registrada no audit trail (valor do LLM, valor do engine, regra). O **Baseline A não tem LLM nem function calling**; esta decisão vale a partir do primeiro experimento com LLM.

## D-003 — Dígito verificador de CNPJ/ISIN não é regra bloqueante

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** técnica (com evidência) — deliberada
- **Contexto:** O enunciado declara que CNPJs e ISINs são fictícios. Na exploração (E-000), 10/12 ISINs e 10/12 CNPJs do golden records falham no dígito verificador, assim como o ISIN do doc 08. O algoritmo de ISIN foi validado com 4 ISINs reais.
- **Decisão:** O checksum de CNPJ/ISIN **não** é regra bloqueante e **não** afeta confiança nem roteamento. Se for implementado, será apenas informativo e desligável por configuração. A identidade do emissor é validada por **correspondência exata com o golden records** (fonte autoritativa do case).
- **Evidência:** E-000; H-12.
- **Alternativas consideradas:** Regra bloqueante — rejeitada: bloquearia 7/8 documentos por um artefato do dataset sintético, e isso ensinaria o operador a ignorar alertas.
- **Consequências / trade-offs:** Em produção com identificadores reais, o checksum seria um bom validador barato de erro de leitura (especialmente em documentos escaneados) e deveria ser reativado. Registrado como item de "o que não fizemos e por quê" no README.

## D-004 — Nome do arquivo nunca é evidência

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** princípio
- **Contexto:** Os nomes dos PDFs do lote antecipam o problema de cada doc (`_sem_data`, `_datas`, `_SCAN`, `_proventos`, `_jcp`). Em produção não existe essa pista, e ela pode estar errada.
- **Decisão:** O nome do arquivo é usado **somente** para identificação e audit trail. Não é entrada para extração, classificação, confiança ou roteamento, nem para construir o gabarito. A chave de identidade do documento é o **SHA-256** do conteúdo.
- **Evidência:** Decisão de princípio. H-21 permanece como **teste de conformidade** (renomear os arquivos não pode alterar nenhum resultado).
- **Consequências:** Nenhum prompt recebe o nome do arquivo. O gabarito em `tests/ground_truth/` identifica os documentos pelo hash.

## D-005 — "A definir" é informação explicitamente pendente, não falha de extração

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** política de negócio (resolve Q-05 / OD-06)
- **Contexto:** O doc 04 declara a data de pagamento como "A definir (vide aviso complementar)".
- **Decisão:**
  1. O campo recebe status `declared_pending`, com a evidência literal. **Não** é `not_found` e nunca recebe valor inferido.
  2. A extração desse campo é **bem-sucedida** (o que o documento diz foi capturado corretamente) e pode ter confiança alta.
  3. O **registro** exige revisão/acompanhamento humano, pois downstream não pode agendar o pagamento. Motivo: `PAYMENT_DATE_PENDING`.
  4. Regras que dependem do campo pendente ficam `not_evaluated`, não `fail`.
- **Evidência:** Decisão de política do usuário.
- **Consequências:** O schema separa explicitamente o status de extração do campo e o status do registro (consistente com H-16).

## D-006 — Sem calendário de feriados B3 no baseline

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** técnica — escopo (resolve Q-08 / OD-09)
- **Contexto:** Regras temporais podem usar dia útil. Nenhum documento do lote tem data de mercado (data com, ex, pagamento) caindo em feriado B3; só datas de reunião (que não são datas de mercado).
- **Decisão:** O baseline usa **dias da semana (seg–sex)** como aproximação de dia útil. Calendário B3 só será adicionado se surgir evidência de necessidade (falso positivo/negativo observado).
- **Evidência:** E-000 (nenhuma data de mercado em feriado no lote).
- **Consequências / trade-offs:** Uma data ex legítima logo após um feriado seria sinalizada indevidamente pela regra "ex = próximo dia útil após a data com". Limitação documentada; em produção, o calendário B3 é uma dependência barata e recomendada.

## D-007 — Aritmética decimal para valores financeiros, taxas e proporções

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** técnica — arquitetural
- **Contexto:** Os avisos trazem valores com até 10 casas decimais (R$ 0,1434196500), alíquotas ("17,5%") e proporções ("1 para 20 (5%)"). O enunciado pede validar a consistência entre bruto e líquido. Ponto flutuante binário não representa esses valores exatamente, e arredondamento arbitrário mascara erros de leitura ou cria falsos alarmes.
- **Decisão:**
  1. Valores financeiros, taxas e proporções usam `decimal.Decimal`, construído a partir da **string** da fonte. Nunca `float`, em nenhuma etapa: extração, normalização, validação ou serialização.
  2. A precisão declarada na fonte é preservada ("0,4275000000" → `Decimal("0.4275000000")`; "10%" → `Decimal("0.10")`). Na saída, o valor é serializado como string e mantém todas as casas.
  3. Não assumimos um número fixo de casas (2, 6, 8, 10) nem política de arredondamento (`ROUND_HALF_EVEN`, `ROUND_HALF_UP` etc.). O material do case não define nenhuma. Rounding, quantization e tolerance só entram como **regras de negócio explícitas e documentadas**.
  4. As operações aritméticas das validações rodam num contexto Decimal que **sinaliza qualquer resultado inexato** (`Inexact`), para que nada seja arredondado em silêncio. Comparações de razão usam multiplicação cruzada em vez de divisão.
  5. Ao comparar um valor calculado com um declarado, a `comparison_precision` é a quantidade de casas do **valor declarado**:
     - calculado == declarado (igualdade numérica exata) → `PASS`;
     - diferença **menor que uma unidade** da última casa declarada (o declarado pode ter sido arredondado ou truncado por regra desconhecida) → `NOT_EVALUATED`, motivo `ROUNDING_RULE_UNDEFINED`. É uma limitação registrada, não um sucesso nem uma falha;
     - diferença **maior ou igual a uma unidade** da última casa declarada → `FAIL`.
  6. O resultado da validação registra `declared_value`, `calculated_value`, `comparison_precision`, `rounding_rule` (hoje sempre `null`) e o resultado.
- **Evidência:** Decisão do usuário. E-000/E-001: os 4 pares bruto/líquido do lote fecham exatamente em Decimal.
- **Alternativas consideradas:** float com tolerância (ex.: 1e-9) — rejeitado: a tolerância seria arbitrária e esconderia erro de dígito em valores pequenos. Arredondar para 2 casas — rejeitado: destrói a precisão de valores por ação.
- **Consequências / trade-offs:** Quando um emissor arredondar o líquido por regra própria, o resultado será `NOT_EVALUATED` (inconclusivo) até alguém definir a regra de negócio. Preferimos inconclusivo explícito a um PASS por conveniência.

## D-008 — Emissor fora do golden records → `REFERENCE_NOT_FOUND` → revisão, nunca rejeição

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** política de negócio (resolve Q-06 / OD-07)
- **Decisão:** Quando o ISIN extraído não tem correspondência exata no golden records, a validação gera o motivo `REFERENCE_NOT_FOUND`, que **bloqueia a aprovação automática**. O roteamento é `REVIEW_REQUIRED`, **não** `REJECT`: a ausência na base de referência não prova que o documento é inválido (a base pode estar desatualizada ou o emissor pode ser novo). Nunca usamos fuzzy match para "achar" um emissor parecido.
- **Evidência:** Decisão do usuário; doc 08.
- **Consequências:** O Baseline A não emite `REJECT` para nenhum caso do lote. `REJECT` fica reservado a um critério objetivo ainda não definido.

## D-009 — Ground truth separado em três camadas de verdade

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo / avaliação
- **Decisão:** O gabarito separa `document_truth` (o que o documento diz), `validation_truth` (resultado objetivo das regras) e `routing_expectation` (decisão operacional, com `expectation_status` = `DEFINED` | `PROVISIONAL` | `POLICY_DEPENDENT`). As métricas de extração e validação nunca dependem de política ainda não definida. Divergências de roteamento contra expectativa provisória são registradas, mas não contadas como erro.
- **Evidência:** Decisão do usuário.
- **Consequências:** Uma mudança de política altera apenas `routing_expectation`, e as métricas de extração/validação continuam comparáveis entre experimentos.

## D-010 — Normalização semântica preserva o rótulo original da fonte

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** princípio de auditabilidade
- **Decisão:** Todo campo extraído e normalizado para um campo comum do schema (ex.: "Data-base do grupamento" → `record_date`) carrega o nome normalizado, o `source_label` original (quando existe), o valor bruto (`raw`), o valor normalizado e a evidência literal. O operador consegue ver o mapeamento sem reabrir o documento.
- **Evidência:** Decisão do usuário; docs 06 e 08.

## D-011 — Método de extração, sozinho, não é motivo de roteamento

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** princípio
- **Decisão:** Um documento escaneado (ou extraído por qualquer método) não vai para revisão só por causa do método. O roteamento decorre da evidência e da confiança obtidas e do resultado das validações. Quando **nenhum** método disponível consegue extrair o conteúdo (ex.: sem camada de texto e sem fallback), o motivo é `NO_USABLE_TEXT_LAYER`: falha de extração, não "é scan". O roteamento definitivo do doc 07 fica `POLICY_DEPENDENT` até os experimentos de OCR/visão.
- **Evidência:** Decisão do usuário.

## D-012 — Modelo de resultado de validação e severidade

- **Data:** 2026-09-29
- **Status:** ACCEPTED (severidades revisáveis conforme a política evoluir)
- **Tipo:** técnica — arquitetural
- **Contexto:** A implementação do validation engine (Baseline A) exigiu fixar a semântica dos resultados e quais falhas bloqueiam.
- **Decisão:**
  1. O validation engine é separado da extração. Recebe o registro candidato normalizado e devolve, por regra: `rule_id`, `status` (`PASS` | `FAIL` | `NOT_EVALUATED`), `severity` (`ERROR` | `WARNING`), valores observados e mensagem.
  2. Se falta um dado de que a regra depende (não encontrado, pendente, não aplicável ou sem linha de referência), o resultado é `NOT_EVALUATED` com a dependência nomeada. **Nunca `FAIL`.**
  3. Grupos de regras que não se aplicam ao tipo de evento (valores para eventos em ações; proporção para eventos em dinheiro) não são executados e ficam listados em `rule_groups_not_applicable`.
  4. Só `FAIL` com severidade `ERROR` bloqueia a aprovação automática. `WARNING` fica registrado, mas não bloqueia.
  5. Severidades atuais:
     - `DATE_EX_NEXT_WEEKDAY_AFTER_RECORD` = `WARNING`, porque sem calendário de feriados (D-006) daria falso alarme após feriados;
     - `REF_ISSUER_NAME_CONSISTENT` = `WARNING`, porque a grafia da razão social varia legitimamente e a identidade é garantida por ISIN + ticker + CNPJ;
     - todas as demais = `ERROR`.
  6. `CLASSIFICATION_TITLE_CONSISTENT` = `ERROR` reflete a política **provisória** do doc 03 (Q-10).
- **Evidência:** E-002 (nenhum falso negativo de validação; nenhum FAIL indevido por dependência ausente); `tests/test_validation.py`.
- **Consequências:** O roteamento lê só `status` + `severity`; mudar uma política significa mudar uma severidade, não reescrever a regra.

## D-013 — Campo não suportado pelo extrator é declarado, não reportado como `not_found`

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** princípio de honestidade da saída
- **Contexto:** O Baseline A não extrai `fraction_adjustment_period`. Reportá-lo como `not_found` afirmaria falsamente que o documento não traz a informação. Da mesma forma, um documento sem camada de texto não foi lido e, portanto, não permite afirmar ausência de nenhum campo.
- **Decisão:** Campos que o extrator não suporta ficam em `extraction.unsupported_fields` e não aparecem como `not_found`. Documento sem extração possível sai com `fields: {}` e `extraction.status = NOT_POSSIBLE`, sem nenhuma afirmação sobre o conteúdo.
- **Evidência:** E-002; `tests/test_pipeline.py`.

## D-014 — Avaliação separada do pipeline; artefatos de experimento versionados

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo / avaliação
- **Decisão:**
  1. O harness de avaliação (`src/evaluation/`) é o único código que lê o gabarito; o pipeline (`src/corporate_actions/`) nunca o lê.
  2. Runs ad hoc vão para `outputs/runs/` (ignorado pelo git). Runs que sustentam um experimento registrado vão para `outputs/experiments/<E-xxx>/`, versionados junto com o relatório de avaliação.
  3. As métricas são reportadas por camada (extração, validação, roteamento, operacional), sem métrica única agregada, e separando "todos os documentos" de "documentos com camada de texto".
- **Evidência:** E-002.

## D-015 — Confiança em três dimensões e roteamento por gates explícitos

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** técnica — arquitetural
- **Contexto:** O E-002 mostrou um valor localizado corretamente, mas interpretado de forma incompleta (IR condicional do doc 01), que recebeu confiança HIGH e foi aprovado automaticamente. Confiança de extração alta não implica confiança semântica alta.
- **Decisão:**
  1. Por campo, quando aplicável, três dimensões separadas:
     - **extraction** (o valor foi localizado e lido corretamente?): HIGH/MEDIUM/LOW;
     - **semantic** (papel, qualificadores, negação e condição foram capturados?): HIGH / MEDIUM / LOW / UNRESOLVED / NOT_ASSESSED;
     - **validation** (alguma regra determinística cruzou o valor?): CROSS_VALIDATED / CONTRADICTED / WARNED / UNVALIDATED.
  2. A classificação do evento também tem confiança semântica própria.
  3. **Não existe fórmula agregada.** O roteamento passa por gates independentes, e qualquer BLOCK manda o registro para revisão com o motivo do gate. Os gates são:
     - `EXTRACTION_POSSIBLE`;
     - `REQUIRED_INFORMATION` (ausente, pendente, extração LOW);
     - `SEMANTIC_INTERPRETATION` (LOW/UNRESOLVED em classificação ou em campo emitido; falha do intérprete);
     - `DETERMINISTIC_VALIDATION`;
     - `REFERENCE_VALIDATION`;
     - `BLOCKING_ERRORS`.
  4. `NOT_ASSESSED` não bloqueia. Uma dimensão não avaliada não é evidência de problema, mas também não é evidência de acerto, e aparece como tal na saída.
  5. O Baseline A continua com o roteamento original (E-002, inalterado). As variantes B e C usam os gates.
- **Evidência:** E-002 (failure mode silencioso); decisão do usuário.
- **Módulo:** `src/corporate_actions/confidence_model.py`.

## D-016 — Camada de LLM atrás de interface mínima; provedor e modelo por configuração

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** técnica
- **Decisão:**
  1. O pipeline só conhece `LLMProvider.structured_call(system, user, tools, schema)`.
  2. Provedor e modelo vêm de `LLM_PROVIDER` / `LLM_MODEL` / `LLM_EFFORT` (ambiente ou `.env`, ignorado pelo git; modelo em `.env.example`).
  3. Adicionar um provedor significa escrever um módulo adaptador e uma linha em `llm/registry.py`. Hoje só o adaptador Anthropic (SDK oficial) está implementado.
  4. O custo é estimado em Decimal exato a partir de uma tabela de preços por modelo. Latências são registradas em inteiros (D-007: nenhum float na saída).
  5. As respostas do LLM são gravadas em cache/replay, por hash de provedor + modelo + effort + prompt + documento, para reprodutibilidade e auditoria (H-20). O cache não guarda o prompt nem o texto do documento.
- **Evidência:** decisão do usuário (troca simples de provedor/modelo).

## D-017 — Challenge set sintético separado; protocolo desenvolvimento × teste

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo / avaliação
- **Decisão:**
  1. O challenge set (`tests/challenge_set/`) tem arquivos, gabarito, métricas e relatórios próprios. **Nunca** se mistura com as métricas do dataset original.
  2. A origem de cada caso é registrada (sintético, escrito à mão, não derivado da saída de nenhuma variante).
  3. **Protocolo:** os documentos originais são o conjunto de desenvolvimento; o challenge set é o conjunto de teste. Ajustes nas variantes só podem ser motivados por falhas vistas nos documentos originais ou nos testes unitários. Um failure mode visto apenas no challenge set é registrado, não corrigido. O prompt da variante C fica congelado (v1) antes da primeira execução.
- **Evidência:** decisão do usuário (não misturar métricas); necessidade de uma medida de generalização não contaminada.
- **Limite reconhecido (2026-09-29):** challenge set, patch B e prompt de C têm o mesmo autor e foram escritos na mesma sessão. Isso deixa o challenge set **ciente do autor**, não cego. As sobreposições conhecidas estão listadas no disclosure do E-003 (`docs/04-evaluation-log.md`). Os rótulos literais que tinham vazado para o rascunho do prompt foram removidos antes do congelamento e de qualquer execução. Um holdout cego, escrito por outra pessoa, fica como próximo passo recomendado.
- **Dataset original × B (2026-09-29):** os docs 01 (alvo de desenho), 02 e 04 (correções da janela de qualificadores) foram usados no desenvolvimento do B. As métricas do B no dataset original não são estimativa out-of-sample.

## D-018 — Experimentos de LLM com configuração fixa: fallback de modelo desligado

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo / avaliação
- **Contexto:** O fallback de recusa do lado do servidor faria outro modelo responder quando o modelo avaliado recusa, misturando duas configurações num mesmo resultado.
- **Decisão:**
  1. No E-003 (e em qualquer experimento de qualidade), `LLM_FALLBACKS=off`. O padrão do código também passou a ser `off`.
  2. A recusa é registrada como resultado (`llm.refusals`, com categoria), sem nova tentativa. O registro vai para revisão (`SEMANTIC_INTERPRETER_FAILED`), e as validações obrigatórias rodam mesmo assim.
  3. O relatório verifica o protocolo (configuração fixa) e registra se o modelo servido difere do solicitado.
  4. O fallback pode ser avaliado depois, em separado, como mecanismo de **resiliência operacional**, com métricas próprias (taxa de recusa, custo, divergência entre modelos).
- **Evidência:** decisão do usuário.

## D-019 — E-003 congelado antes da execução do LLM

- **Data:** 2026-09-29
- **Status:** ACCEPTED
- **Tipo:** processo
- **Decisão:** código de A/B/C, avaliação, gabarito v2.1, challenge set v1.0 e prompt v1 (`cf27c1d6164099c5`) estão congelados por hash em `outputs/experiments/E-003_semantic/FREEZE.json`. `tests/test_e003_freeze.py` falha se qualquer arquivo congelado mudar. A única exceção pré-registrada é uma correção de compatibilidade de API no adaptador, antes de qualquer saída semântica; ela gera `freeze_version` 2 e é registrada no evaluation log.


## D-020 — Congelamento do E-003 passa a ser comportamental (tag + regressão)

- **Data:** 2026-09-30
- **Status:** ACCEPTED
- **Tipo:** processo
- **Contexto:** O freeze por hash do E-003 travava `pipeline.py`, que precisa de um ramo aditivo para a variante D.
- **Decisão:** O estado exato do E-003 fica na tag git `e003-final`. `tests/test_e003_regression.py` exige que A, B e C reproduzam exatamente os registros oficiais do E-003; a C por replay do cache, sem API, e qualquer cache miss falha. O hash continua valendo para tudo, exceto `pipeline.py` e `__main__.py`. Os artefatos do E-003 não são alterados.
- **Evidência:** 57/57 registros reproduzidos antes e depois do ramo da D.

## D-021 — E-004 congelado antes do run oficial da variante D

- **Data:** 2026-09-30
- **Status:** ACCEPTED
- **Tipo:** processo
- **Decisão:** O código da D (detector, política de qualificadores v2, fusão v2), o prompt v2 (`a1007b649ea5c243`), a avaliação (`evaluation/e004.py`, com o oráculo de necessidade pré-registrado), os gabaritos e o challenge set estão congelados por hash em `outputs/experiments/E-004_hybrid/FREEZE.json` (`tests/test_e004_freeze.py`). A configuração é fixa: `claude-opus-5`, effort medium, fallback off.


## D-022 — Congelamento do E-004 passa a ser comportamental (tag + regressão)

- **Data:** 2026-09-30
- **Status:** ACCEPTED
- **Tipo:** processo
- **Decisão:** Mesmo mecanismo da D-020. O estado do E-004 fica na tag `e004-final`. `tests/test_e004_regression.py` exige que a D reproduza os 19 registros oficiais por replay. O hash continua valendo para tudo, exceto `pipeline.py` e `__main__.py`, que recebem o ramo aditivo da variante E.

## D-023 — E-005 congelado antes do run oficial da variante E

- **Data:** 2026-09-30
- **Status:** ACCEPTED
- **Tipo:** processo
- **Decisão:** Prompt v3 (`e6bd3105dc7c8c84`), `qualifiers_v3.py`, o ramo `_semantic_e`, a avaliação `evaluation/e005.py` (com os critérios de sucesso pré-registrados), os gabaritos e o challenge set estão congelados em `outputs/experiments/E-005_qualifiers_v3/FREEZE.json` (`tests/test_e005_freeze.py`). A configuração é a mesma da D, com fallback off.

---

## Decisões deliberadamente adiadas (não são decisões)

- **Provider/modelo de LLM** (OD-04 / Q-03) — adiado por instrução do usuário.
- **OCR local vs visão de LLM** para o documento escaneado (OD-03 / H-02b) — adiado por instrução do usuário.
- **Política de roteamento** para conflito título × corpo (OD-08 / Q-10) — provisória: `REVIEW_REQUIRED`.
- **Política de confiança para documentos extraídos por fallback** (OD-12 / Q-11) — depende dos experimentos de OCR/visão.
