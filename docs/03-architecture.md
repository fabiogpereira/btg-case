# 03 — Arquitetura (baseline proposto, NÃO final)

> Este documento é uma **hipótese de arquitetura**. Nada aqui é decisão até ser testado (`04-evaluation-log.md`) e registrado em `DECISIONS.md`.

---

## 1. Princípio de desenho

Cada etapa tem **uma responsabilidade**, **entradas/saídas explícitas** e **um tipo de raciocínio** (determinístico ou probabilístico). A parte probabilística fica isolada e cercada por verificações determinísticas antes e depois.

```
                       ┌──────────────────── audit trail (manifest do run + proveniência por campo) ────────────────────┐
                       │                                                                                                  │
PDF ──► [1] ingestão ──► [2] detecção de camada de texto ──┬─► [3a] texto nativo ─────────┐                              │
         hash, metadados                                   └─► [3b] fallback: OCR/visão ──┤                              │
                                                                                          ▼                              │
                                          [4] interpretação/extração ──► [5] grounding ──► [6] normalização ──► [7] validações/tools
                                              (regras e/ou LLM)          (evidência       (datas, Decimal,        (golden, datas,
                                                                          existe na fonte?) proporções)            valores, schema)
                                                                                                                         │
                                                  [10] saída JSON + relatório ◄── [9] roteamento ◄── [8] confiança ◄─────┘
                                                                                  (auto / revisão    (campo e registro,
                                                                                   + motivo)          separadas)
```

| Etapa | Responsabilidade | Natureza | Hipóteses |
|---|---|---|---|
| 1. Ingestão | Ler arquivo, calcular SHA-256, metadados (páginas, produtor, fontes, imagens). Nome do arquivo só como rótulo, nunca como sinal. | Determinística | H-21 |
| 2. Detecção de texto | Decidir se há camada de texto utilizável. | Determinística (limiar) | H-03 |
| 3a. Texto nativo | Extrair texto por página (pypdf). | Determinística | H-01 |
| 3b. Fallback | Só se (2) negar: OCR local **ou** visão de LLM (em aberto). | Probabilística | H-02, H-02b |
| 4. Interpretação | Classificar tipo de evento; mapear campos e papéis de data; separar valor principal de auxiliares; devolver **trecho de evidência** por campo. | **Em aberto**: regras vs LLM vs híbrido | H-04, H-05, H-08, H-10 |
| 5. Grounding | Verificar que cada trecho de evidência existe literalmente no texto-fonte e contém o valor. Campo sem grounding não é aceito como está. | Determinística | H-06 |
| 6. Normalização | "R$ 0,4275000000" → Decimal; "28 de maio de 2026" / "28/05/2026" → ISO; proporções → par (de, para). Mantém sempre o valor **como no documento** ao lado do normalizado. | Determinística | H-07, H-09 |
| 7. Validações (tools) | Golden lookup (ISIN, ticker, CNPJ, razão social, classe); regras temporais (seg–sex, D-006); bruto × líquido; proporção; schema condicional por tipo. DV de ISIN/CNPJ no máximo informativo (D-003). **Todas executadas pelo orchestrator**; o LLM também chama ao menos a tool de referência via function calling (D-002). | Determinística | H-11 a H-15 |
| 8. Confiança | Por campo (sinais da extração) e por registro (validações + campos críticos). Categórica e com motivo. | Determinística (regras explícitas) | H-16, H-17 |
| 9. Roteamento | `AUTO_APPROVED` / `APPROVED_WITH_PENDING` / `HUMAN_REVIEW` (nomes provisórios), com códigos de motivo. | Determinística | H-18 |
| 10. Saída | 1 JSON por documento + relatório de exceções + manifest do run. | Determinística | H-19 |

**Onde há IA nesta proposta:** no máximo nas etapas 3b e 4. Todo o resto é código.

## 2. Estratégia de evolução (não construir tudo de uma vez)

1. **Gabarito manual** dos 8 docs (expected outputs) → condição para medir qualquer coisa. **Feito:** `tests/ground_truth/` (v1.0).
2. **Baseline v0 — só determinístico:** etapas 1, 2, 3a, 4 por regras, 5–10. Doc 07 sai como `HUMAN_REVIEW` com motivo "sem camada de texto" (comportamento seguro e honesto). Mede o piso e mostra onde as regras falham (esperado: doc 03, generalização).
3. **Avaliar** contra o gabarito + variações perturbadas (rótulos/sinônimos/ordem) para medir sobreajuste.
4. **Melhorias direcionadas** somente nos modos de falha observados:
   - classificação/papéis de data → testar LLM (H-05, H-08);
   - doc escaneado → testar OCR local vs visão (H-02b).
5. **Arquitetura final** = o que sobreviveu às medições, registrado em `DECISIONS.md`.

## 2.1 Baseline A — o que foi realmente implementado (E-002)

> Experimento, **não** arquitetura final. Sem LLM, OCR, visão, function calling, calendário de feriados ou uso do nome do arquivo.

| Etapa | Módulo | Natureza | Observação |
|---|---|---|---|
| Ingestão + SHA-256 | `ingestion.py` | determinística | nome do arquivo só como metadado |
| Camada de texto | `ingestion.py` | determinística | usável se ≥ 100 caracteres alfanuméricos/página; senão, `NO_USABLE_TEXT_LAYER` e o documento para aqui |
| Extração de candidatos | `extraction.py` | determinística | rótulos literais, padrões e frases-âncora; cada regra tem `rule_id`; só coleta, não decide |
| Classificação | `classification.py` | determinística | léxico do domínio sobre o conteúdo **sem o título**; precedência JCP > DIVIDEND; ambíguo → indeterminado |
| Normalização / resolução | `normalization.py`, `schema.py` | determinística | Decimal da string, datas ISO, `source_label`, ausência tipada por tipo de evento, conflitos preservados como alternativas |
| Confiança | `confidence.py` | determinística | HIGH/MEDIUM/LOW com motivos (âncora, conflito, derivação, corroboração) |
| Validação | `validation.py`, `reference.py` | determinística | 17 regras + lookup exato por ISIN (D-012) |
| Roteamento | `routing.py` | determinística | AUTO_APPROVE só sem motivo bloqueante; nunca REJECT |
| Audit / saída | `audit.py`, `pipeline.py` | determinística | registro JSON por documento, `exceptions_report.md`, `run_manifest.json` |
| Avaliação | `src/evaluation/` | fora do pipeline | único código que lê o gabarito (D-014) |

Como rodar: ver `README.md`. Resultados e failure modes: `docs/04-evaluation-log.md` (E-002).

## 2.2 Evolução do modelo de confiança (D-015)

O E-002 mostrou que "achei no lugar certo" não é "entendi o que diz". A confiança passou a ter três dimensões por campo, sem agregação:

| Dimensão | Pergunta | Quem produz | Valores |
|---|---|---|---|
| extraction | O valor foi localizado e lido corretamente? | `confidence.py` (âncora, conflito, derivação) | HIGH / MEDIUM / LOW |
| semantic | O significado foi capturado por inteiro (papel, qualificadores, negação, condição)? | B: `semantic_patch.py` · C: `semantic_llm.py` | HIGH / MEDIUM / LOW / UNRESOLVED / NOT_ASSESSED |
| validation | Alguma regra determinística cruzou o valor com outro dado? | `confidence_model.validation_view` sobre os resultados do validation engine | CROSS_VALIDATED / CONTRADICTED / WARNED / UNVALIDATED |

O roteamento das variantes B e C passa por **gates explícitos** (`confidence_model.route_gated`), cada um com seus motivos. Qualquer BLOCK manda o registro para revisão:

```
EXTRACTION_POSSIBLE -> REQUIRED_INFORMATION -> SEMANTIC_INTERPRETATION -> DETERMINISTIC_VALIDATION -> REFERENCE_VALIDATION -> BLOCKING_ERRORS
```

## 2.3 Variantes do E-003

Todas compartilham ingestão, extração de candidatos, normalização, validation engine e referência. Só muda a camada semântica.

**A — Baseline A.** Caminho de código idêntico ao do E-002 (teste de regressão byte a byte contra os registros versionados).

**B — patch semântico determinístico** (`semantic_patch.py`, cerca de 200 linhas):
- a classificação descarta sinais de tipo precedidos de "não/nem/sem" na mesma oração;
- se a frase do sinal declara que a natureza será definida depois, a classificação fica UNRESOLVED e o tipo fica nulo;
- qualificadores na janela de cada valor extraído (a frase, limitada por pontuação e por início de linha de tabela):
  - THRESHOLD e HOLDER_EXEMPTION têm interpretação fixa (base do IR = `EXCESS_OVER_THRESHOLD`; exceção por titular não muda a base) → semântica HIGH;
  - negação, condição, adiamento ou exceção genérica → semântica LOW (vai para revisão);
- não mapeia rótulos de data alternativos (fora do escopo).

**C — intérprete semântico por LLM** (`semantic_llm.py` + `llm/`):

```
texto do documento --> LLM (prompt v1, saída JSON estruturada, tool lookup_security via function calling)
                       |-- tipo de evento + evidências + menções enganosas
                       |-- papéis de data (valor "como escrito" + evidência)
                       |-- IR: taxa como escrita, base, qualificadores
                       '-- checagem de referência reportada
     --> grounding determinístico: toda citação localizada literalmente; valor contido na citação;
         data e taxa parseadas por código (o LLM nunca converte nem calcula)
     --> fusão com o determinístico:
         acordo -> HIGH | só o LLM (determinístico não achou) -> MEDIUM (não bloqueia)
         desacordo / ambíguo / não grounded / falha -> LOW ou UNRESOLVED (bloqueia)
     --> validation engine executa TODAS as regras (independe das tools chamadas pelo LLM)
     --> divergência entre tool/relato do LLM e REF_ISIN_FOUND é registrada; o engine prevalece
```

O LLM não calcula, não aprova, não substitui o lookup nem as validações, e não preenche informação ausente com conhecimento externo.

## 3. Esboço do registro de saída (a validar, não é o schema final)

Ideia de estrutura, para discutir o que o operador precisa ver:

```
record
├── document        { file_name, sha256, pages, text_layer: native|none, extraction_method }
├── event           { type, subtype_as_declared, classification_evidence[], conflicts[] }
├── fields
│   └── <campo>     { status: found|not_found|not_applicable|declared_pending,
│                     raw_value, normalized_value, evidence: {text, page, section: table|body},
│                     method, grounded: bool, confidence: HIGH|MEDIUM|LOW, confidence_reasons[] }
├── reference_check { matched_by, golden_row, field_comparisons[] }
├── validations[]   { rule_id, rule_version, result: pass|fail|not_evaluated, detail }
├── record_status   { decision, reason_codes[], human_actions_required[] }
└── audit           { run_id, pipeline_version, model, prompt_version, timestamps, errors[], retries }
```

## 4. Decisões em aberto

| ID | Decisão | Opções | Status |
|---|---|---|---|
| OD-01 | Quem executa a interpretação (etapa 4)? | regras · LLM · híbrido (regras para identificadores/formatos, LLM para semântica) | Aberta (H-04, H-05) |
| OD-02 | Como atender "tool / function calling" (R3)? | — | **Decidida → D-002**: LLM usa ao menos uma tool de referência; orchestrator executa todas as validações obrigatórias |
| OD-03 | Fallback do escaneado | OCR local (Tesseract) · visão de LLM · ambos com comparação · só revisão humana | **Adiada deliberadamente** (H-02b, Q-07) |
| OD-04 | Provider/modelo | a definir | **Adiada deliberadamente** (Q-03, H-22) |
| OD-05 | Escala de confiança | categórica · numérica | Aberta (H-17) |
| OD-06 | Política para pagamento "A definir" | — | **Decidida → D-005**: `declared_pending` + registro `REVIEW_REQUIRED` |
| OD-07 | Política para emissor fora do golden | — | **Decidida → D-008**: `REFERENCE_NOT_FOUND` → `REVIEW_REQUIRED` |
| OD-08 | Política para conflito título × corpo com classificação corroborada | aprovar com alerta · revisão | Aberta (Q-10); gabarito usa revisão provisória |
| OD-09 | Calendário de dias úteis | — | **Decidida → D-006**: seg–sex, sem feriados B3 |
| OD-10 | Formato do relatório de exceções | Markdown · CSV · ambos | Aberta (A11) |
| OD-11 | Validação de DV (ISIN/CNPJ) | — | **Decidida → D-003**: não bloqueante; no máximo informativa |
| OD-12 | Roteamento de escaneado sem falha de conteúdo | aprovar · revisar se campo sem checagem cruzada | Aberta (Q-11); "revisar sempre" descartado por D-011 |

## 5. O que deliberadamente NÃO está no baseline (e por quê)

| Não incluído | Motivo |
|---|---|
| Multi-agent / frameworks de agente | Nenhum modo de falha observado exige orquestração entre agentes; aumenta custo, variabilidade e dificulta depuração ao vivo. |
| RAG / vector DB | A única base de referência tem 12 linhas e é consultada por chave exata. |
| OCR/visão em todos os arquivos | 7/8 têm texto nativo fiel; OCR só adicionaria erro. |
| Fuzzy matching de emissor | Identidade errada é o pior erro possível; não encontrado → revisão. |
| Filas, microserviços, banco adicional | Lote de 8 arquivos; escala é discussão de produção, não requisito do case. |
| Correção automática de inconsistências | Não sabemos qual valor está errado; corrigir seria inventar. |
| Score numérico de confiança | Sem dados para calibrar; seria precisão falsa. |
