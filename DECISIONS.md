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

---

## Decisões deliberadamente adiadas (não são decisões)

- **Provider/modelo de LLM** (OD-04 / Q-03) — adiado por instrução do usuário.
- **OCR local vs visão de LLM** para o documento escaneado (OD-03 / H-02b) — adiado por instrução do usuário.
- **Política de roteamento** para conflito título × corpo (OD-08 / Q-10) — provisória: `REVIEW_REQUIRED`.
- **Política de confiança para documentos extraídos por fallback** (OD-12 / Q-11) — depende dos experimentos de OCR/visão.
