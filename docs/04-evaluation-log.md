# 04 — Evaluation Log

Registro cronológico de experimentos. Cada entrada testa uma ou mais hipóteses de `02-hypotheses.md`.
Resultados negativos também entram — são tão informativos quanto os positivos.

## Template

```
## E-XXX — Título curto
- Data:
- Hypothesis tested: H-xx
- Change: o que foi alterado em relação ao estado anterior (commit/versão do pipeline)
- Dataset/documents: quais docs (originais, variações perturbadas, injeções de erro)
- Metrics/signals: o que foi medido e como (contra o gabarito)
- Result: números e observações
- Conclusion: confirma / refuta / inconclusivo — e por quê
- Next action:
```

## Métricas de referência (propostas, a validar)

| Métrica | Definição | Por que |
|---|---|---|
| Acurácia por campo | campos com valor normalizado = gabarito / campos esperados | Qualidade de extração |
| Acurácia de ausência | campos com estado de ausência correto (`not_found`/`not_applicable`/`declared_pending`) | "Ausente continua ausente" |
| Valores inventados | campos preenchidos sem evidência no documento | Deve ser **0** — métrica de bloqueio |
| Acurácia de classificação | tipo de evento correto / 8 | R2 |
| Roteamento correto | decisão do registro = esperada no gabarito | R5 |
| Precisão do auto-approve | registros aprovados automaticamente que estão de fato corretos | Custo assimétrico do erro |
| Especificidade dos motivos | exceções com código de motivo correto | Operador sabe o que fazer |
| Reprodutibilidade | diff entre 2 runs idênticos | Auditoria |
| Custo / latência | tokens e segundos por documento | "Quanto custa?" |

Pré-requisito: **gabarito manual** dos 8 docs (a construir, revisado pelo usuário).

---

## E-000 — Exploração inicial do material (não é experimento formal)

- **Data:** 2026-09-29
- **Hypothesis tested:** nenhuma formalmente; levantamento de evidências para H-01, H-12, H-13, H-14.
- **Change:** nenhum código no repositório. Scripts descartáveis de leitura (pypdf 6.16.1, Python 3.13.1), executados sobre `case/` em modo somente leitura.
- **Dataset/documents:** 8 PDFs + golden records.
- **Metrics/signals / Result:**
  - Camada de texto: 7/8 docs com texto; doc 07 com 0 caracteres e 1 imagem JPEG 1654×2339 (lido visualmente por inspeção humana).
  - Golden: 7/8 docs com match exato de ISIN, ticker, CNPJ e razão social; doc 08 sem match.
  - Dígito verificador: algoritmo ISIN correto em 4 ISINs reais; falha em 10/12 ISINs do golden e no ISIN do doc 08. CNPJ: falha em 10/12 do golden.
  - Bruto × líquido (JCP): 4/4 exatos em Decimal com IRRF 17,5%.
  - Datas: ex = próximo dia útil após data com em todos os proventos; doc 05 com pagamento anterior à data com; reuniões em sábado (06, 07) e em feriado B3 (08).
- **Conclusion:** Evidência preliminar favorável a H-01, H-12, H-13 e H-14. Não substitui os testes formais.
- **Next action:** construir o gabarito manual; aguardar autorização para o baseline v0.

## E-001 — Verificação de integridade do gabarito v1.0

- **Data:** 2026-09-29
- **Hypothesis tested:** nenhuma do pipeline; controle de qualidade do próprio gabarito (`tests/ground_truth/`).
- **Change:** criação do gabarito manual v1.0 (8 documentos + transcrição visual do doc 07).
- **Dataset/documents:** 8 PDFs; golden records.
- **Metrics/signals:** script descartável (fora do repo) que verifica: (1) SHA-256 de cada gabarito corresponde a um PDF do lote; (2) todo trecho de `evidence`, `classification.evidence` e `traps` é substring literal do texto normalizado (pypdf nos nativos, transcrição no doc 07); (3) `raw` literal nos nativos; (4) consistência entre status e valor/evidência; (5) recálculo, a partir dos próprios valores do gabarito, dos resultados esperados das regras `REF_*`, `DATE_*`, `AMOUNT_*` e `RATIO_*`.
- **Result:** 0 erros; 147 trechos literais conferidos; 90 expectativas de regra recalculadas e coerentes. Não recalculadas: `REQUIRED_FIELDS_PRESENT`, `CLASSIFICATION_TITLE_CONSISTENT` e as `REF_*` `not_evaluated` do doc 08.
- **Conclusion:** o gabarito é internamente consistente e ancorado no texto dos documentos. **Limite:** a transcrição do doc 07 é leitura humana e não é verificável contra camada de texto. A revisão do conteúdo pelo usuário continua pendente.
- **Next action:** revisão do gabarito pelo usuário (sobretudo os pontos provisórios Q-06, Q-10, Q-11); depois, baseline v0. O script de integridade pode virar `tests/test_ground_truth_integrity.py` quando o baseline for autorizado.

## E-002 — Baseline A: pipeline 100% determinístico

- **Data:** 2026-09-29
- **Run:** `20260929T231551Z-d79d833d` · pipeline `baseline-a/0.1.0` · gabarito v2.0 · commit base `661dfa7`
- **Artefatos:** `outputs/experiments/E-002_baseline_a/` (`records/`, `run_manifest.json`, `exceptions_report.md`, `evaluation/evaluation_report.md`, `evaluation/evaluation.json`)
- **Hypotheses tested:** H-01, H-03, H-04, H-07, H-08 (parcial), H-09, H-11, H-13, H-14, H-16, H-17 (parcial), H-18 (parcial), H-21.
- **Pergunta:** quanto do problema se resolve de forma determinística, barata e previsível antes de qualquer componente probabilístico?
- **Change:** primeira implementação. Ingestão (SHA-256) → detecção de camada de texto (≥ 100 caracteres alfanuméricos/página) → texto nativo (pypdf) → extração por rótulos/padrões/frases-âncora → classificação por léxico do domínio (sem o título) com uma regra de precedência documentada (JCP > DIVIDEND) → normalização (Decimal, datas ISO, `source_label`) → confiança categórica por sinais objetivos → validation engine separado (17 regras) → roteamento → audit trail + manifest. Sem LLM, OCR, visão, calendário de feriados ou uso do nome do arquivo.
- **Regra de desenho do extrator:** o léxico só contém rótulos que nomeiam literalmente o campo. Mapeamentos que exigem interpretação ficaram fora de propósito (ex.: "Início da negociação grupada" → `ex_date`).
- **Dataset/documents:** os 8 documentos originais; 4 variações escritas à mão como testes de limite (`tests/test_known_limits.py`, xfail estrito).

### Resultado

**Extração**

| Métrica | 8 documentos | 7 com camada de texto |
|---|---|---|
| Tipo de evento | 7/8 | **7/7** |
| Valor exato | 76/93 (81,7%) | **76/80 (95,0%)** |
| Status do campo | 99/115 (86,1%) | **99/101 (98,0%)** |
| Ausência/pendência | `declared_pending` 1/1 · `not_applicable` 17/18 · `not_found` 3/3 | todos corretos |
| **Valores inventados** | **0** | **0** |

Os 4 valores errados nos documentos com texto:
1. **doc 01 `withholding_tax`:** o IR condicional do dividendo ("10% sobre a parcela que exceder R$ 50 mil/mês por beneficiário") saiu como `{rate: 0.10, base: null}`, com **confiança HIGH**, num registro **AUTO_APPROVE**. **Erro semântico silencioso num registro aprovado** — o failure mode mais importante do experimento.
2. **doc 03 `withholding_tax`:** base não capturada (não é literal no texto). Benigno: a regra bruto×líquido passa.
3. **doc 06 `ex_date`:** não encontrada. O rótulo "Início da negociação grupada" exige mapeamento semântico. Falha segura: vai para revisão.
4. **doc 06 `fraction_adjustment_period`:** não suportado pelo extrator (declarado em `extraction.unsupported_fields`, não reportado como `not_found`).

**Validação** (119 expectativas de regra; 104 nos documentos com texto)

| Métrica | 8 documentos | 7 com texto |
|---|---|---|
| Acerto por regra | 101/119 | **101/104** |
| Falsos negativos (gabarito FAIL, run não FAIL) | 0 | **0** |
| Falsos positivos | 1 | 1 — doc 06 `REQUIRED_FIELDS_PRESENT` (consequência da `ex_date` não extraída) |
| Outras divergências | 17 (15 = doc 07 sem regras executadas) | 2 — doc 06, regras de data `NOT_EVALUATED` por falta de `ex_date` (nunca FAIL indevido) |

**Roteamento**

| Doc | Expectativa | Esperado | Obtido | Motivo |
|---|---|---|---|---|
| 01 | DEFINED | AUTO_APPROVE | AUTO_APPROVE ✅ | — (com o erro silencioso de IR acima) |
| 02 | DEFINED | AUTO_APPROVE | AUTO_APPROVE ✅ | — |
| 03 | PROVISIONAL | REVIEW_REQUIRED | REVIEW_REQUIRED (coincide) | `CLASSIFICATION_TITLE_CONFLICT` |
| 04 | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED ✅ | `PAYMENT_DATE_PENDING` |
| 05 | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED ✅ | `DATE_INCONSISTENCY` |
| 06 | DEFINED | AUTO_APPROVE | **REVIEW_REQUIRED ❌** | `REQUIRED_FIELD_MISSING` (ex_date) |
| 07 | POLICY_DEPENDENT | — | REVIEW_REQUIRED (não conta) | `NO_USABLE_TEXT_LAYER` |
| 08 | DEFINED | REVIEW_REQUIRED | REVIEW_REQUIRED ✅ | `REFERENCE_NOT_FOUND` |

Expectativas DEFINED: **5/6**. O único erro é conservador (revisão desnecessária), não uma aprovação indevida.

**Classificação:** 7/7 nos documentos com texto, incluindo o doc 03 (JCP com título "Dividendos"). **Mas** em 2 de 7 (docs 02 e 03) o acerto dependeu da regra de precedência JCP > DIVIDEND (confiança MEDIUM). O caso de negação ("não haverá JCP") classifica errado (xfail).

**Confiança:** dos 77 campos comuns com valor ou pendência nos documentos com texto, 70 receberam HIGH e 7 MEDIUM (todos `issuer_name`, padrão sem âncora); nenhum LOW. Os 2 valores com base de IR errada estavam em HIGH. **A confiança por âncora não detecta perda semântica**: diz "achei no lugar certo", não "entendi o que diz".

**Operacional:** 8 documentos, 1 sem camada de texto, 0 erros, 72 ms de processamento total (~9 ms/documento, sem contar a inicialização do Python), custo marginal zero. Testes: 121 passam + 4 xfail estritos (limites conhecidos).

**Cobertura de regras:** as regras genéricas de datas, valores e identificadores cobrem de 3 a 7 documentos. As 12 regras que cobrem um único documento são de tipo de evento, e no lote há 1 documento por tipo, então esse sinal de sobreajuste é **fraco com este lote**.

### Conclusão

- **O determinístico resolve bem o que é determinístico:** identificadores, datas rotuladas, valores, aritmética, referência, regras temporais, pendência e ausência. Zero valores inventados, zero falsos negativos de validação e nenhuma aprovação indevida por regra.
- **O limite aparece onde é preciso *entender*, não *localizar*:**
  - (a) semântica condicional do IR (doc 01, silenciosa);
  - (b) mapeamento de rótulos para papéis (doc 06, segura);
  - (c) classificação que depende de uma regra de precedência frágil a negação (docs 02 e 03).
- **Documento sem camada de texto:** o baseline falha de forma explícita e segura (`NO_USABLE_TEXT_LAYER`).
- **Resultado a não superestimar:** 7 dos 8 documentos usam o mesmo template. O 95% de valores exatos é um teto otimista para avisos heterogêneos. A generalização não foi medida sistematicamente, só com 4 casos anedóticos, todos falhando como esperado.

### Next action

Nenhuma melhoria implementada (por instrução). Próximo experimento recomendado em `docs/02-hypotheses.md` (H-05/H-08, com H-23 como controle de segurança).

## E-003 — Interpretação semântica: A × B × C (pré-registro; experimento congelado)

- **Data do congelamento:** 2026-09-29 · base `c5b241a` + mudanças não commitadas · manifesto `outputs/experiments/E-003_semantic/FREEZE.json` (51 arquivos com SHA-256, fins de linha normalizados), verificado por `tests/test_e003_freeze.py`
- **Status:** A e B executados; **C pendente** (nenhuma chamada ao modelo foi feita até o congelamento).
- **Hipóteses:** H-05, H-06, H-08 (c, d), H-10, H-15, H-17, H-20, H-22, H-23, H-24.
- **Pergunta:** um componente semântico melhora os failure modes do E-002 de forma justificável, sem substituir validações determinísticas?

### Variantes

| Variante | Versão | O que muda |
|---|---|---|
| A | `baseline-a/0.1.0` | nada (idêntico ao E-002; regressão automática) |
| B | `+semantic-patch/0.1` | negação na classificação, adiamento da natureza, qualificadores (THRESHOLD, HOLDER_EXEMPTION interpretados; demais → LOW) |
| C | `+semantic-llm/0.1` | intérprete por LLM, grounded, com function calling (`lookup_security`); prompt `semantic-interpreter/v1`, fingerprint `cf27c1d6164099c5` |

### Configuração fixa de C (D-018)

Os valores vêm de `.env`, e o relatório verifica se o run obedeceu:
- `LLM_PROVIDER=anthropic`
- `LLM_MODEL=claude-opus-5`
- `LLM_EFFORT=medium`
- `LLM_MAX_TOKENS=8000`
- **`LLM_FALLBACKS=off`**: recusa é resultado registrado, nunca respondida por outro modelo.

Uma nova tentativa só acontece em falha de parse/schema. Recusa e erro de API não geram nova tentativa. O SDK faz até 2 retries de transporte (408/409/429/5xx, conexão).

### Protocolo de execução de C (pré-registrado)

```bash
E=outputs/experiments/E-003_semantic
# Execução 1 (grava cache)
python -m corporate_actions --variant C --out $E/original_C --llm-cache $E/llm_cache_run1
python -m corporate_actions --variant C --documents tests/challenge_set/cases --out $E/challenge_C --llm-cache $E/llm_cache_run1
# Execução 2: independente, sem ler cache (só para consistência)
python -m corporate_actions --variant C --out $E/original_C_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
python -m corporate_actions --variant C --documents tests/challenge_set/cases --out $E/challenge_C_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
# Comparação
python -m evaluation.variants --original A=$E/original_A B=$E/original_B C=$E/original_C \
  --challenge A=$E/challenge_A B=$E/challenge_B C=$E/challenge_C \
  --c-repeat-original $E/original_C_run2 --c-repeat-challenge $E/challenge_C_run2 --out $E/comparison
```

- **Métricas de qualidade:** vêm da execução 1. A execução 2 serve apenas para a consistência.
- **Correção técnica permitida:** se a primeira chamada falhar por incompatibilidade de API (erro 4xx antes de qualquer saída semântica), a correção fica restrita ao adaptador `llm/anthropic_provider.py`. Ela gera `freeze_version` 2 e é registrada aqui.
- **Nenhuma outra mudança** em A, B, C, prompt, gabarito, challenge set ou avaliação a partir de resultados.

### Métricas pré-registradas

- **Dataset original** (7 documentos com texto):
  - tipo de evento;
  - campos semânticos (tipo, IR com base, papéis de data);
  - valor exato;
  - status de campo;
  - validação (acerto, falsos negativos, falsos positivos);
  - **aprovações automáticas inseguras**;
  - valores inventados;
  - taxa de revisão;
  - roteamento DEFINED.
- **Challenge set** (11 casos, 21 alvos, métricas separadas):
  - acurácia semântica;
  - negação;
  - expressão condicional;
  - papel de data;
  - palavras enganosas;
  - descrição do evento;
  - **interpretações falsamente confiantes**;
  - erradas mas sinalizadas;
  - aprovações automáticas inseguras;
  - roteamento DEFINED;
  - taxa de revisão.
- **Execução do LLM (C):**
  - modelo solicitado e servido;
  - versão e fingerprint do prompt;
  - chamadas de API;
  - tokens;
  - custo estimado (Decimal);
  - latência;
  - falhas de parse/schema;
  - recusas;
  - grounding (trechos localizados / total);
  - divergências de referência (tool × validation engine).
- **Function calling:**
  - total de tool calls;
  - documentos com chamada;
  - chamadas corretas;
  - chamadas desnecessárias;
  - chamadas esperadas ausentes;
  - argumentos incorretos.
  - O esperado é 1 chamada por documento com texto, com o ISIN ou ticker do aviso (do gabarito original ou do texto do caso).
- **Consistência entre execuções** (C1 × C2):
  - tipo de evento;
  - campos semanticamente interpretados (valor + confiança);
  - interpretação bruta do LLM;
  - decisão e motivos de roteamento;
  - número de tool calls;
  - argumentos das tool calls.

### Disclosure metodológico (limites de validade)

1. **O dataset original não é out-of-sample para B.** O B foi desenhado a partir do failure mode do **doc 01** (E-002). A janela de qualificadores foi corrigida duas vezes durante o desenvolvimento, por falhas vistas nos **docs 02 e 04**:
   - iteração 1: a janela de ±80 caracteres cortava "imunes ou isentos" (doc 02) e vazava "A definir" para as datas (doc 04);
   - iteração 2: a janela ainda vazava entre as linhas da tabela curta do doc 04.
   As métricas do B no dataset original são, portanto, **métricas de desenvolvimento**, não estimativa de generalização. O mesmo vale em parte para C: o prompt usa conceitos e rótulos dos documentos originais (ex.: "imputado ao dividendo obrigatório", "ressalvados os acionistas imunes ou isentos", "data com", "data-base").
2. **Observação prévia do challenge set.** Um preview de A e B sobre o challenge set foi executado **antes** da iteração 2 do B. A iteração 2 foi motivada pelo doc 04 (original) e é genérica (limite de janela por início de linha de tabela). Mesmo assim, ela aconteceu depois de o autor ter visto resultados do challenge set. O failure mode do B visto só no challenge set (**CH-06**: exceção do IR atribuída à data de aprovação na mesma frase) foi **deliberadamente não corrigido**.
3. **Mesmo autor para challenge set e variantes.** O challenge set, o patch B e o prompt de C foram escritos pelo mesmo agente, na mesma sessão. Portanto:
   - o léxico de THRESHOLD do B contém "apenas sobre" e "que ultrapassarem", que também aparecem no **CH-05**; e "nem" (negação) aparece no **CH-02**;
   - o rascunho do prompt de C continha rótulos literais do **CH-07/CH-08** ("último dia com direito", "ex-direito", "posição acionária de", "negociadas grupadas a partir de") e a citação "não haverá". Eles **foram removidos antes do congelamento e antes de qualquer execução**, e substituídos por definições de papel sem rótulos do challenge set;
   - o challenge set mede, portanto, generalização **com conhecimento do autor**, não uma holdout cega. Um conjunto cego escrito por outra pessoa (ou por um agente sem acesso ao código) seria a medida mais forte; está proposto como próximo passo, não feito.
4. **Amostra pequena.** 7 documentos originais com texto e 11 casos sintéticos (21 alvos). As diferenças entre variantes devem ser lidas caso a caso, não como taxas estáveis.

### Incidente pré-execução → `freeze_version` 2 (2026-09-29)

- **O que houve:** a primeira chamada da execução 1 (`original_C`) retornou HTTP 400 **antes de qualquer saída do modelo**. A chave de API não está associada a um workspace, e a API exige o header `anthropic-workspace-id`.
- **Enquadramento:** exceção pré-registrada (incompatibilidade de API, sem nenhuma saída semântica observada).
- **Correções** (hashes em `FREEZE.json`, `changes_from_previous`):
  1. `llm/anthropic_provider.py` envia `anthropic-workspace-id` quando `ANTHROPIC_WORKSPACE_ID` está definido. O valor vem do `.env` e nunca é registrado.
  2. `llm/cache.py` não grava resposta sem nenhuma chamada bem-sucedida. O erro tinha sido gravado e seria reproduzido em replay.
  3. `pipeline.py`: o audit não quebra mais quando nenhum modelo respondeu. Antes, um `IndexError` derrubava o lote em vez de registrar a falha como resultado (`SEMANTIC_INTERPRETER_FAILED`).
- **Teste de regressão:** `test_api_failure_is_recorded_without_crashing_or_caching`.
- **Inalterados:** prompt (`cf27c1d6164099c5`), schema, B, avaliação, gabaritos e challenge set. A mudança no `pipeline.py` só afeta o caminho com LLM; os runs oficiais de A e B continuam válidos.
- **Run descartado:** o `original_C` que falhou (0 respostas do modelo) foi apagado, junto com o cache.

### Resultado (execução de C em 2026-09-30, freeze v2)

**Runs.**

| Conjunto | Execução 1 | Execução 2 (consistência) |
|---|---|---|
| Original | `20260930T000643Z-a90cb473` | `20260930T001024Z-e41c436b` |
| Challenge | `20260930T000818Z-fd2fca1a` | `20260930T001142Z-779d6649` |

- **Custo total:** US$ 2,01, nas 4 execuções de C.
- **Relatório completo:** `outputs/experiments/E-003_semantic/comparison/comparison_report.md`.

**Dataset original** (7 documentos com texto; **métricas de desenvolvimento para B**, ver disclosure):

| Métrica | A | B | C |
|---|---|---|---|
| Tipo de evento | 7/7 | 7/7 | 7/7 |
| Campos semânticos (tipo, IR com base, papéis de data) | 28/31 | 29/31 | **31/31** |
| Valor exato | 76/80 | 77/80 | 79/80 |
| Regras de validação | 101/104 | 101/104 | **104/104** |
| **Aprovações automáticas inseguras** | **1** (doc 01) | **0** | **0** |
| Valores inventados | 0 | 0 | 0 |
| Taxa de revisão | 6/8 | 6/8 | 7/8 |
| Roteamento DEFINED | 5/6 | 5/6 | **4/6** |
| Tempo | 75 ms | 83 ms | 83 s |

- **C resolve o doc 06:** "Início da negociação grupada" → `ex_date`, e o documento vai para AUTO_APPROVE.
- **C manda para revisão sem necessidade os docs 01 e 02** (e o 03, que já ia para revisão por outro motivo), por `SEMANTIC_AMBIGUITY`: ver failure mode C-1.

**Challenge set** (11 casos, 21 alvos; **ciente do autor**, ver disclosure):

| Métrica | A | B | C |
|---|---|---|---|
| Acurácia semântica | 6/21 | 10/21 | **21/21** |
| Negação | 1/4 | 3/4 | 4/4 |
| Expressão condicional | 5/6 | 6/6 | 6/6 |
| Papel de data | 0/8 | 0/8 | **8/8** |
| Palavras enganosas | 5/8 | 6/8 | 8/8 |
| Descrição do evento | 0/3 | 2/3 | 3/3 |
| **Falsamente confiantes** | **1** | **0** | **0** |
| **Aprovações automáticas inseguras** | **1** (CH-05) | **0** | **0** |
| Roteamento DEFINED | 3/7 | 4/7 | 5/7 |
| Taxa de revisão | 9/11 | 8/11 | 4/11 |

**LLM (C).**
- **Configuração:** `claude-opus-5`, effort medium, fallback off. O modelo servido foi sempre o solicitado.
- **Chamadas:** 0 recusas, 0 erros, 0 falhas de parse/schema. 2 chamadas de API por documento (rodada da tool + resposta final).

| | Original | Challenge |
|---|---|---|
| Custo por documento | ~US$ 0,059 | ~US$ 0,054 |
| Latência por documento | ~11,8 s (9,3–15,5 s) | ~10,6 s (9,4–14,0 s) |
| Tokens por documento (entrada / saída) | ~7,9k / ~0,8k | ~7,3k / ~0,7k |

**Grounding:** 150/150 trechos localizados literalmente (65 no original, 85 no challenge). Nenhuma interpretação foi descartada por falta de evidência nas execuções reais. O caminho de rejeição foi testado apenas offline.

**Function calling:**

| | Original | Challenge |
|---|---|---|
| Tool calls | 8 | 11 |
| Documentos com chamada | 7/7 | 11/11 |
| Corretas | 7 | 11 |
| Desnecessárias | 1 (doc 02: ticker consultado além do ISIN) | 0 |
| Esperadas ausentes | 0 | 0 |
| Argumentos incorretos | 0 | 0 |
| Divergências tool × validation engine | 0 | 0 |

**Consistência entre execuções:**

| Dimensão | Original | Challenge |
|---|---|---|
| Tipo de evento | 7/7 | 11/11 |
| Campos semanticamente interpretados | 7/7 | 11/11 |
| Decisão de roteamento | 7/7 | 11/11 |
| Motivos de roteamento | 7/7 | 11/11 |
| Interpretação bruta | **5/7** | 11/11 |
| Número / argumentos de tool calls | **5/7** | 11/11 |

- **Interpretação bruta, doc 04:** datas "como escritas" citadas por extenso numa execução e numéricas na outra. Os valores normalizados são idênticos.
- **Tool calls, docs 01 e 02:** consulta extra por ticker em uma das execuções.

### Failure modes observados

- **C-1 (C, novo, conservador): alarme falso por qualificador CONDITION.** O LLM marcou como CONDITION trechos que não condicionam a alíquota:
  - doc 01 e doc 02: "legislação vigente a partir de 1º de janeiro de 2026" (vigência da lei);
  - doc 03: "no momento do pagamento ou crédito, o que ocorrer primeiro" (momento da retenção).

  A regra de fusão (`merge_withholding`: qualquer CONDITION/DEFERRAL → LOW) bloqueou os três, **mesmo com a base do IR correta nos três**. O falso alarme é estável nas duas execuções. Ele é o motivo de C ter ficado em 4/6 no roteamento DEFINED. A causa está na combinação da **política de fusão** com a **definição ampla de CONDITION no prompt**, não na leitura do LLM.
- **C-2 (C, por desenho): desacordo manda para revisão mesmo quando o LLM acerta.** Em CH-01 e CH-10, o determinístico erra por precedência (JCP) e o LLM acerta (DIVIDEND). A regra de desacordo bloqueia (seguro, mas custa automação).
- **C-3 (todas as variantes): conflito de valor bruto no extrator determinístico (CH-09).** O rótulo "valor bruto" em prosa ("... sobre o valor bruto, resultando em valor líquido de R$ ...") captura o líquido como segundo candidato do bruto, e a confiança de extração vai para LOW (revisão). Fica fora do escopo do LLM, porque valores são determinísticos.
- **C-4 (C): variação de chamadas de tool** (consulta extra por ticker). Não tem efeito na decisão, mas mostra que a presença e a forma da tool call não são determinísticas. Isso reforça a D-002: a validação não pode depender delas.
- **B-1 (B): atribuição de qualificador por frase (CH-06).** A exceção do IR foi atribuída à data de aprovação da mesma frase: revisão desnecessária. Visto só no challenge set; não corrigido (D-017).
- **B-2 (B):** não mapeia papéis de data (0/8) nem descrições sem palavra-chave (CH-03, CH-04). Essas faltas estavam previstas no escopo do B.
- **Custo operacional de C:** cerca de 1.000× a latência do determinístico (s × ms) e cerca de US$ 0,055 por documento.

### Respostas às perguntas do experimento

1. **O LLM elimina o failure mode perigoso?** Sim. 0 aprovações inseguras e 0 interpretações falsamente confiantes nos dois conjuntos. No doc 01 e no CH-05, a base `EXCESS_OVER_THRESHOLD` foi extraída corretamente. No doc 01, porém, o registro foi para revisão por C-1.
2. **O patch determinístico também elimina?** Sim, no failure mode observado: doc 01 e CH-05 interpretados, e o doc 01 aprovado. Isso ocorre sem LLM, com 83 ms e custo zero. **Ressalva:** o léxico do B foi escrito conhecendo o doc 01 e se sobrepõe ao CH-05 ("apenas sobre", "ultrapassarem").
3. **Qual generaliza melhor?** C, com 21/21 contra 10/21 no challenge set, sobretudo em papéis de data (8/8 contra 0/8) e em descrição do evento. É uma medida ciente do autor, não cega.
4. **Qual introduz novos erros?**
   - C: alarmes falsos por CONDITION (docs 01 e 02) e revisões por desacordo (CH-01, CH-10);
   - B: um alarme falso por atribuição de qualificador (CH-06).
   - Nenhum dos dois introduziu aprovação insegura nem valor inventado.
5. **Impacto em custo e latência:**

   | | B | C |
   |---|---|---|
   | Custo por documento | ~0 | ~US$ 0,055 |
   | Latência por documento | ~10 ms | ~11 s |

   A 10 mil avisos por mês, C custaria cerca de US$ 550/mês nesta configuração, antes de otimizações (cache de prompt, effort, chamar o LLM só quando necessário).
6. **O LLM permaneceu grounded?** Sim: 150/150 trechos literais, 0 divergências de referência, 0 falhas de schema. As diferenças entre execuções ficaram na forma (extenso × numérico, tool extra), não no conteúdo normalizado.
7. **Onde o determinístico deve continuar preferido?**
   - Identificadores, valores e aritmética, referência, datas com rótulo literal (acordo em todos os casos) e regras de validação;
   - qualificadores de padrão conhecido (B resolveu o caso crítico sem custo);
   - e o fluxo em que o template é uniforme: 7/8 documentos do lote, em que A/B já acertam tudo o que é localizável.

### Conclusão

- **O LLM agrega valor real e grounded** em mapeamento semântico (papéis de data, descrição do evento, negação, referências enganosas), onde o determinístico falha de forma estrutural.
- **O LLM não é necessário para o failure mode perigoso do E-002**: um patch determinístico pequeno resolve.
- **A política de fusão de C é conservadora demais** com qualificadores (C-1). Há duas saídas testáveis: uma definição mais estreita de CONDITION no prompt (v2), ou bloquear só quando o qualificador altera a base ou a taxa. Nenhuma mudança foi feita, porque o experimento está congelado.

### Next action (proposta, não executada)

**E-004**, se autorizado:
- (a) holdout **cego** escrito por outra pessoa ou por um agente sem acesso ao código;
- (b) política de fusão v2 para qualificadores (só bloquear quando alteram a base ou a taxa, ou a definição estreita de CONDITION no prompt v2);
- (c) **LLM sob demanda**: chamar C só quando o determinístico indica necessidade (campo obrigatório ausente, classificação por precedência ou ambígua, qualificador detectado), medindo custo, latência e segurança contra C sempre ligado (H-25).

## E-004 — LLM sob demanda (H-25) e fusão v2 (H-26): B × C × D (pré-registro; congelado)

- **Checkpoint anterior:** tag `e003-final` → `c64fc61`.
- **Congelamento:** `outputs/experiments/E-004_hybrid/FREEZE.json` (54 arquivos, prompt `semantic-interpreter/v2` fingerprint `a1007b649ea5c243`), verificado por `tests/test_e004_freeze.py`, antes de qualquer execução oficial da D.
- **E-003 preservado:** os artefatos não foram tocados. A, B e C continuam reproduzindo exatamente os registros oficiais do E-003; a C por replay do cache, sem API (`tests/test_e003_regression.py`, 57 casos). Só `pipeline.py` e `__main__.py` evoluíram, com um ramo aditivo (D-020).
- **Baselines de comparação:** B e C são os runs congelados do E-003 (não re-executados).

### Variante D — `hybrid_on_demand` (`baseline-a/0.1.0+hybrid-on-demand/0.1`)

```
documento -> extração + classificação determinística (A + patch B: negação, adiamento, qualificadores conhecidos)
          -> detector de necessidade (determinístico, com reason codes e etapa de origem)
          -> [LLM v2 somente se llm_required]  (function calling lookup_security disponível)
          -> grounding (toda citação literal; valor contido na citação; parse por código)
          -> fusão v2 (sem score)  -> validações obrigatórias -> gates -> audit
```

**Detector de necessidade.** Gatilhos (aciona o LLM):

| Código | Etapa | Quando |
|---|---|---|
| `EVENT_SIGNALS_CONFLICT` | classify | sinais de mais de um tipo (precedência ou ambíguo), sem explicação conhecida |
| `CLASSIFICATION_UNSUPPORTED` | classify | o determinístico não classifica (sem sinais ou ambíguo) e o aviso não adia a natureza |
| `NEGATION_DECIDED_CLASSIFICATION` | classify | sem a heurística de negação, o tipo seria outro: a decisão depende dela |
| `REQUIRED_DATE_ROLE_UNMAPPED` | extract | papel de data obrigatório ausente **e** há datas no texto sem papel atribuído (exclui a data de fechamento "Cidade (UF), ...") |
| `UNINTERPRETED_QUALIFIER` | semantic_patch | o patch B achou um qualificador que não sabe interpretar num campo emitido |

Sinais registrados que **não** acionam o LLM, com o motivo:

| Sinal | Por que não aciona |
|---|---|
| `EVENT_SIGNALS_CONFLICT_EXPLAINED` | menções a dividendo só no contexto "imputado ao dividendo obrigatório" de um JCP |
| `EVENT_NATURE_DEFERRED` | o aviso adia a natureza: revisão garantida, o LLM não muda o desfecho |
| `NEGATION_NOT_DECISIVE` | a negação não mudou a classificação |
| `REQUIRED_DATE_MISSING_NO_TEXT_EVIDENCE` | não há texto a interpretar |
| `DECLARED_PENDING` | pendência declarada no próprio aviso |
| `EXTRACTION_CONFLICT_OUT_OF_LLM_SCOPE` | conflito em valores ou identificadores, que não são escopo do LLM |
| `TAX_BASE_NOT_STATED` | base não literal; sem texto novo; a taxa é validada por bruto×líquido |
| `UNSUPPORTED_FIELD_NOT_REQUIRED` | campo não suportado, mas não obrigatório para o tipo |

**Qualificadores v2.** O LLM descreve cada qualificador: `qualifier_type`, `affects`, `effect` e citação literal. O código decide pela tabela `QUALIFIER_POLICY`:

| Tipo | Materialidade | Bloqueia? |
|---|---|---|
| tax_base_condition | material | só se a base não estiver representada (`EXCESS_OVER_THRESHOLD`) |
| tax_rate_condition | material | sim |
| beneficiary_exception | material para aplicação tributária | não (vira nota) |
| event_eligibility_condition | material | sim |
| legal_context / timing_context / informational_context | não material | não |
| other / unresolved | desconhecida | sim |

Tipo não material que declara afetar algo material (base, taxa, elegibilidade, natureza, valores) é tratado como **inconsistente** e bloqueia: o LLM não consegue rebaixar um efeito material só pelo rótulo. Qualificador sem citação localizada é descartado. Os qualificadores do patch B são projetados no mesmo modelo.

**Fusão v2** (por conceito, com categoria auditável em `semantic.resolutions`):

| Categoria | Condição | Resultado |
|---|---|---|
| AGREEMENT | evidência positiva dos dois lados, concordante | HIGH |
| DETERMINISTIC_UNSUPPORTED / LLM_ONLY_GROUNDED | o determinístico não tem suporte (tipo não classificado, papel de data sem rótulo, base não literal, qualificador não interpretado) e o LLM está grounded | valor aceito com semântica MEDIUM |
| HEURISTIC_RESOLVED | a classificação do determinístico veio de heurística (precedência ou negação) e o LLM diverge | aceito **só se** todo sinal do tipo escolhido pela heurística foi explicado pelo LLM como menção enganosa, com citação que o cobre; senão, TRUE_DISAGREEMENT |
| TRUE_DISAGREEMENT | evidências positivas incompatíveis | LOW → revisão |
| LLM_UNRESOLVED | o LLM declara ambiguidade | UNRESOLVED → revisão (nunca aprovação silenciosa); data ambígua com rótulo determinístico positivo fica MEDIUM |
| LLM_UNGROUNDED(_IGNORED) | citação não localizada | descartado; se o determinístico é positivo, mantém o determinístico |

**Política LLM-only:** um valor sustentado só pelo LLM precisa, além do grounding e do parse, **passar em todas as regras que o cruzam, inclusive as de severidade WARNING**. Qualquer FAIL gera `LLM_ONLY_VALUE_NOT_CORROBORATED` e bloqueia.

**Invariantes preservados:**
- nada inventado;
- grounding literal obrigatório;
- lookup, cálculos e validações determinísticos;
- roteamento em código;
- nada crítico depende de tool call;
- Decimal inalterado;
- ambiguidade não resolvida nunca é aprovada.

### Oráculo de necessidade (pré-registrado, sobre os artefatos congelados do B no E-003)

Precisava de LLM: o B errou um alvo semântico, ou mandou para revisão por motivo semântico resolvível pelo LLM quando o esperado era AUTO_APPROVE.
- **Original:** doc 03 (base do IR não literal) e doc 06 (`ex_date`).
- **Challenge:** CH-03, CH-04, CH-06, CH-07, CH-08, CH-09, CH-10.

**Falso negativo esperado por desenho:** o doc 03 conta como "precisava", mas `TAX_BASE_NOT_STATED` deliberadamente não aciona o LLM. A base do gabarito é inferida pela aritmética, não por texto, e a regra bruto×líquido já valida a alíquota. Será reportado como falso negativo.

### Configuração congelada e protocolo

- **Configuração:** `anthropic` / `claude-opus-5` / effort `medium` / `LLM_FALLBACKS=off` / 8000 max tokens.
- **Protocolo:**

```bash
E=outputs/experiments/E-004_hybrid
python -m corporate_actions --variant D --out $E/original_D --llm-cache $E/llm_cache_run1
python -m corporate_actions --variant D --documents tests/challenge_set/cases --out $E/challenge_D --llm-cache $E/llm_cache_run1
python -m corporate_actions --variant D --out $E/original_D_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
python -m corporate_actions --variant D --documents tests/challenge_set/cases --out $E/challenge_D_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
python -m evaluation.e004 --with-run2
```

Depois da primeira saída semântica oficial: nenhuma mudança em D, prompt, políticas, limiares ou challenge set. Falhas viram resultado ou hipótese futura.

### Disclosure

1. **Original é desenvolvimento.** A D foi desenvolvida olhando só os documentos originais (checagem sem LLM real, com provedor falso). O reconhecimento de "imputação ao dividendo obrigatório" foi motivado pelos docs 02 e 03.
2. **Resultados do E-003 no challenge set eram conhecidos.** A fusão v2 e o detector foram desenhados sabendo os failure modes da C (C-1: CONDITION; C-2: desacordo em CH-01 e CH-10) e do B (CH-06), por pedido explícito desta etapa. Nenhum run da D, nem só do detector, foi feito sobre o challenge set antes do congelamento. Ainda assim, o challenge set **não é independente** da D. O holdout cego continua sendo o próximo passo.
3. **Prompt v2:** exemplos só dos documentos originais: "sobre a parcela que exceder", "ressalvados os acionistas ... imunes ou isentos", "conforme legislação vigente", "no momento do pagamento ou crédito".

### Resultado (execução da D em 2026-09-30, freeze v1, sem nenhuma alteração após a primeira saída)

**Runs.**

| Conjunto | Execução 1 | Execução 2 (consistência) |
|---|---|---|
| Original | `20260930T004418Z-0861ea71` | `20260930T004654Z-ed7ce642` |
| Challenge | `20260930T004438Z-ce9f1072` | `20260930T004710Z-5571a787` |

- **Execução:** 0 erros, 0 recusas, 0 falhas de parse/schema. O modelo servido foi sempre `claude-opus-5`.
- **Custo:** US$ 1,44 nas 4 execuções da D.
- **Relatório completo:** `outputs/experiments/E-004_hybrid/comparison/e004_report.md` (+ `e004_results.json`, com o oráculo e a análise de roteamento).

**Qualidade e segurança — original** (conjunto de desenvolvimento):

| | B | C | D |
|---|---|---|---|
| Campos semânticos | 29/31 | 31/31 | 30/31 |
| Valor exato | 77/80 | 79/80 | 78/80 |
| Regras de validação | 101/104 | 104/104 | 104/104 |
| Roteamento DEFINED | 5/6 | 4/6 | 5/6 |
| Taxa de revisão | 6/8 | 7/8 | 6/8 |
| **Aprovações inseguras** | 0 | 0 | **0** |

**Qualidade e segurança — challenge set** (ciente do autor):

| | B | C | D |
|---|---|---|---|
| Acurácia semântica | 10/21 | 21/21 | **21/21** |
| Papel de data | 0/8 | 8/8 | 8/8 |
| Negação | 3/4 | 4/4 | 4/4 |
| Qualificador / IR condicional | 6/6 | 6/6 | 6/6 |
| Roteamento DEFINED | 4/7 | 5/7 | **7/7** |
| Taxa de revisão | 8/11 | 4/11 | 5/11 |
| Falsamente confiantes | 0 | 0 | 0 |
| **Aprovações inseguras** | 0 | 0 | **0** |

**Eficiência (H-25):**

| | C original | D original | C challenge | D challenge |
|---|---|---|---|---|
| Documentos com LLM | 7/7 | **1/7** | 11/11 | 10/11 |
| Chamadas de API / tool calls | 14 / 8 | 2 / 1 | 22 / 11 | 20 / 10 |
| Custo total (US$) | 0,4113 | **0,0733** (−82%) | 0,5937 | 0,6413 (+8%) |
| Custo por documento de entrada (US$) | 0,0514 | **0,0092** | 0,0540 | 0,0583 |
| Latência fim a fim média / p50 | 10,4 s / 9,7 s | **2,2 s / 13 ms** | 10,6 s / 10,4 s | 11,2 s / 11,7 s |
| Latência D sem LLM (média) | — | 13 ms | — | 3 ms |
| Latência D com LLM (média) | — | 17,6 s | — | 12,3 s |
| Tool calls por documento processado / com LLM | — | 0,125 / 1,0 | — | 0,909 / 1,0 |

- **Tokens:** o prompt v2 usa ~+1,1k tokens de entrada (taxonomia) e ~+0,2k de saída (qualificadores) por documento com LLM; cerca de 15% mais caro por chamada que o v1.
- **Function calling (só documentos com LLM):** 11/11 chamadas corretas; 0 desnecessárias, 0 ausentes, 0 argumentos incorretos, 0 divergências com o validation engine.
- **Oráculo de invocação:**

| | Original | Challenge |
|---|---|---|
| Corretas | doc 06 | CH-03, 04, 06, 07, 08, 09, 10 |
| Puladas corretamente | 01, 02, 04, 05, 08 | CH-05 |
| **Falso-positivas** | — | **CH-01, CH-02** (gatilho de negação decisiva, por desenho), **CH-11** (o B atribuiu o adiamento à data de aprovação) |
| **Falso-negativas** | **doc 03** (base do IR não literal; previsto no pré-registro) | — |

**Estabilidade (D1 × D2):**
- decisão de invocar o LLM: 19/19;
- tipo de evento e campos semânticos: 11/11 nos documentos com LLM;
- **roteamento: 18/19** (CH-07 mudou; ver D-2).

### Análise dos false reviews do C

| Documento | B (determinístico) | C (E-003): interpretação e motivo | D: tratamento | Justificável sem reduzir segurança? |
|---|---|---|---|---|
| doc 01 | AUTO; base `EXCESS_OVER_THRESHOLD` por padrão conhecido | Base correta; "legislação vigente a partir de ..." marcada CONDITION → LOW | LLM **não chamado** (nenhum gatilho); AUTO | Sim: o qualificador material foi interpretado por código, e o contexto legal não altera o registro |
| doc 02 | AUTO; exceção por titular interpretada; conflito JCP×dividendo por precedência | Base GROSS correta; "conforme legislação vigente" = CONDITION → LOW | Conflito reconhecido como imputação ao dividendo obrigatório → **não chamado**; AUTO | Sim: a menção a dividendo é a imputação legal do JCP, não outro evento |
| doc 03 | REVIEW (conflito título × conteúdo) | "no momento do pagamento ou crédito" = CONDITION → LOW + conflito de título | Não chamado; REVIEW só pelo conflito de título (política Q-10) | Sim para o roteamento. A base do IR fica nula (falso negativo de invocação) |
| CH-01 | AUTO (negação filtrada → DIVIDEND) | Desacordo (determinístico A = JCP) → REVIEW | Chamado (negação decisiva) → **AGREEMENT** com o B → AUTO | Sim: dois intérpretes independentes concordam, com evidência literal |
| CH-06 | REVIEW (exceção do IR atribuída à data de aprovação) | AUTO | Chamado (qualificador não interpretado) → data confirmada (DETERMINISTIC_UNSUPPORTED); exceção por titular não bloqueia → AUTO | Sim: o LLM separou os escopos; a validação passa |
| CH-09 | REVIEW (conflito no valor bruto) | REVIEW (mesmo conflito) | Datas mapeadas (LLM_ONLY_GROUNDED), mas REVIEW continua pelo conflito de valor (fora do escopo do LLM) + qualificadores | O REVIEW está correto: o conflito de valor é real no extrator |
| CH-10 | REVIEW (precedência → JCP, errado) | Desacordo → REVIEW | Chamado (conflito de sinais) → LLM = DIVIDEND e explicou a menção ao JCP passado com citação que cobre o sinal → **HEURISTIC_RESOLVED** → AUTO | Sim: a heurística cede só com explicação literal de todos os sinais perdedores |
| CH-11 | REVIEW (adiamento) | REVIEW | REVIEW (adiamento + `event_eligibility_condition`) | Sim |

### Failure modes novos

- **D-1 (qualificadores: rotulagem genérica bloqueante).** No doc 06, o LLM descreveu o ajuste de frações e o leilão das sobras como `other/amounts` (execução 1) e `event_eligibility_condition` (execução 2). As duas bloqueiam, e o doc 06 vai para revisão **mesmo com a `ex_date` mapeada corretamente**. A taxonomia não tem categoria para procedimento operacional do evento (tratamento de frações).
- **D-2 (instabilidade de `affects` + salvaguarda de inconsistência).** No CH-07, execução 1, o LLM listou o próprio rótulo do valor bruto como qualificador `informational_context` com `affects=amounts`. A regra "não material que afeta algo material bloqueia" disparou; na execução 2 veio `affects=none`. É **a única instabilidade de roteamento (1/19)**. O LLM também lista como qualificador coisas que não são qualificadores.
- **D-3 (falso positivo por atribuição do B).** No CH-11, o adiamento da natureza foi atribuído à data de aprovação da mesma frase: gatilho `UNINTERPRETED_QUALIFIER`. Desfecho correto, mas com custo.
- **D-4 (falso positivo por desenho).** Negação decisiva (CH-01, CH-02): o determinístico acertava, mas a decisão tributária dependia de uma heurística de escopo de negação. Custo aceito por segurança.
- **D-5 (falso negativo por desenho).** Doc 03, base do IR não literal.
- **D-6 (custo por chamada).** O v2 é ~15% mais caro por documento com LLM. Num conjunto quase todo semântico (challenge set: 10/11 documentos com LLM), a D custa **mais** que a C.

### H-25 e H-26

- **H-25 — CONFIRMED, condicionada à distribuição.** No lote real (7 documentos com texto), a D chamou o LLM em 1/7, com custo −82% e p50 de latência de 9,7 s para 13 ms, **sem aprovação insegura** e com qualidade ≥ B (semântica 30/31, validação 104/104). Onde quase todo documento precisa de semântica (challenge set), não há economia. Falso-positivos: 3/11 no challenge set (2 por desenho). Falso-negativo: 1 (por desenho).
- **H-26 — MODIFIED.**
  - A **fusão v2** (acordo, determinístico sem suporte, heurística resolvida com cobertura, conflito real) funcionou: corrigiu os false reviews da C no CH-01 e no CH-10, manteve o CH-06 e evitou os alarmes dos docs 01 e 02. O roteamento DEFINED no challenge set foi a 7/7.
  - O **modelo de qualificadores v2**, porém, introduziu novos false reviews (D-1, D-2) e 1 instabilidade de roteamento. A separação "o LLM descreve, o código decide" é válida; a taxonomia e a extração de qualificadores precisam de refinamento.

### Conclusão e recomendação

**Arquitetura candidata: D.**
- **Base:** determinístico (A + patch B) como primeira linha, sempre.
- **LLM:** só com gatilho objetivo; function calling de referência mantido; fusão v2.
- **Autoridade:** validações e roteamento em código.

No lote real, isso entrega a qualidade semântica perto da C, com custo e latência perto do determinístico.

**Antes de adotar:**
- (a) **qualificadores v3**: só registrar como qualificador o que modifica valor, base, taxa, elegibilidade ou natureza **deste** registro; categoria própria (não bloqueante) para procedimento operacional, como frações; tornar a salvaguarda de `affects` robusta à variação (ex.: exigir que o `affects` material seja coerente com o campo citado);
- (b) medir tudo num **holdout cego**;
- (c) prompt caching do system prompt (maior parte da entrada) para reduzir o custo por chamada.

Nenhuma dessas mudanças foi feita: o E-004 está congelado, e a próxima etapa depende de autorização.

### Errata do E-004 (registrada em 2026-09-30, durante o E-005)

A análise do E-004 **subnotificou** os bloqueios falsos por qualificador na D. Os artefatos não mudam; só a leitura.

- **O que o log dizia:** os failure modes novos da D eram o doc 06 (frações) e o CH-07 (instabilidade).
- **O que os registros mostram:** na execução 1, a D também mandou para revisão **CH-03, CH-08 e CH-09** por qualificadores v2:

  | Caso | Qualificador bloqueante | Tipo atribuído |
  |---|---|---|
  | CH-03 | "limitados à variação ... TJLP" | `informational_context` com `affects=amounts` (inconsistente) |
  | CH-03 | "de 17,5% sobre o valor bruto" | `tax_base_condition` |
  | CH-08 | "Será considerada a posição acionária do dia ..." | `event_eligibility_condition` |
  | CH-09 | "Farão jus ao provento os acionistas ..." | `event_eligibility_condition` |

- **Por que passou despercebido:** esses casos têm expectativa PROVISIONAL e não entram no "roteamento DEFINED 7/7".
- **Consequência:** a C (E-003) aprovava CH-03, CH-07 e CH-08, que a D mandou para revisão (a taxa de revisão 5/11 da D inclui esses casos). A afirmação de que a D "corrigiu os false reviews da C" continua verdadeira para CH-01 e CH-10, mas a D **criou** false reviews novos no challenge set.
- **Efeito sobre as hipóteses:** H-26 continua MODIFIED; o problema dos qualificadores era maior do que o reportado.

## E-005 — Qualificadores v3 (H-27): D × E (pré-registro; congelado)

- **Checkpoint anterior:** tag `e004-final` → `5d5fb83`.
- **E-004 preservado:** a D reproduz os 19 registros oficiais do E-004 por replay do cache (`tests/test_e004_regression.py`). A, B e C continuam reproduzindo o E-003.
- **Congelamento:** `outputs/experiments/E-005_qualifiers_v3/FREEZE.json` (57 arquivos; prompt `semantic-interpreter/v3`, fingerprint `e6bd3105dc7c8c84`), verificado por `tests/test_e005_freeze.py`.
- **Configuração:** `claude-opus-5`, effort medium, fallback off, 8000 max tokens (igual à D).

### Variante E — `hybrid_qualifiers_v3`

Idêntica à D em tudo que não é qualificador: patch B, detector de necessidade, fusão v2 (acordo, sem suporte, heurística resolvida, conflito real), validation engine, gates, function calling. Muda só:

1. **Prompt v3**, com duas listas separadas:
   - `material_qualifiers` (kind: `material_condition`, `material_exception`, `unresolved`; `affects`, `target_field`, `effect`, `materiality_reason`, citação): só o que passa no **teste de remoção** ("se o trecho for removido, muda natureza, elegibilidade, direito, alíquota, base, tratamento tributário por titular, valor, proporção ou semântica de data?");
   - `semantic_notes` (`operational_instruction`, `legal_context`, `informational_context`).
   - Regra de escopo: rótulo com valor, e frase que só declara ou explica um campo já no registro (a data com definida pela posição; a base "sobre o valor bruto"), não são qualificadores.
   - Palavras como "condição", "exceto", "conforme" não tornam nada material por si.
2. **Política v3** (`qualifiers_v3.py`):
   - notas nunca bloqueiam;
   - material com citação localizada passa pela **guarda de escopo** determinística e genérica: se, removidos os trechos de evidência dos campos e as repetições entre parênteses, não sobra conteúdo, a citação é rebaixada para nota (`SCOPE_GUARD_FIELD_LABEL_OR_VALUE`);
   - material **já representado** não bloqueia:

     | `affects` | Representado quando |
     |---|---|
     | `tax_base` (condição) | base do registro = `EXCESS_OVER_THRESHOLD` |
     | `beneficiary_tax_treatment` | anotado no campo de IR |
     | `effective_dates` | campo `declared_pending` que contém a citação |

   - material não representado, ou `unresolved`, bloqueia.

**Diferença de desenho em relação ao v2:**

| | v2 | v3 |
|---|---|---|
| Tipos | 9 | 3 materiais + 3 de nota |
| Materialidade | inferida da tabela por tipo | exige justificativa (`materiality_reason`) e o teste de remoção |
| `other` genérico bloqueante | sim | não existe |
| Salvaguarda "tipo não material com `affects` material" | sim | removida: notas não têm `affects` |
| Critério de bloqueio | tipo do qualificador | "efeito material não representado no registro" |

### Mudanças feitas antes do congelamento, e por quê

- **Guarda de escopo** passou de "cobertura ≥ 80%" para "sem conteúdo fora da evidência dos campos". Motivo: o teste sintético do doc 06 ("Proporção 10:1 (dez para uma)" não era rejeitado). Um teste garante que citações com relação real anexada a um valor continuam bloqueando.
- **Regra de escopo do prompt** para frase que define um campo e para a declaração de base. Motivada pelos bloqueios falsos da D em CH-08, CH-09 e CH-03 (errata acima), e alinhada ao item "texto explicativo que apenas repete o significado do campo" da especificação do E-005.
- **Regra de representação "base do registro igual à base do LLM":** adicionada e **removida antes do congelamento**. Ela abria um buraco de segurança: com uma redação de limite não reconhecida pelo B e o LLM errando a base para GROSS_AMOUNT, o registro seria aprovado com base errada. Agora um teste de regressão garante revisão nesse cenário.

### Critérios de sucesso (pré-registrados, do enunciado)

1. `unsafe_auto_approvals` = 0;
2. o doc 06 deixa de ir para revisão por motivo operacional;
3. CH-07 com roteamento estável;
4. nenhum caso antes seguro passa a ser aprovado incorretamente;
5. a taxa de revisão cai ou fica igual;
6. a lógica fica mais simples ou mais explicável.

Se a taxa de revisão cair às custas de segurança, H-27 fica **refutada**.

### Protocolo

```bash
E=outputs/experiments/E-005_qualifiers_v3
python -m corporate_actions --variant E --out $E/original_E --llm-cache $E/llm_cache_run1
python -m corporate_actions --variant E --documents tests/challenge_set/cases --out $E/challenge_E --llm-cache $E/llm_cache_run1
python -m corporate_actions --variant E --out $E/original_E_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
python -m corporate_actions --variant E --documents tests/challenge_set/cases --out $E/challenge_E_run2 --llm-cache $E/llm_cache_run2 --no-cache-read
python -m evaluation.e005
```

Depois da primeira saída oficial: nenhuma mudança em E, prompt, política ou challenge set.

### Disclosure

- **Original é desenvolvimento.** O exemplo operacional do prompt ("how fractions are grouped and sold") é uma paráfrase do exemplo genérico da especificação, e o doc 06 tem esse tipo de texto. O resultado do doc 06 é **in-sample**.
- **Challenge set conhecido.** Os resultados da D (E-003 e E-004) eram conhecidos e motivaram a regra de escopo (CH-03, CH-07, CH-08, CH-09). Nenhum run da E foi feito sobre o challenge set antes do congelamento; ainda assim, a métrica ali **não é independente**.
- **Holdout cego** continua sendo a medida necessária antes de adotar.

### Resultado (execução da E em 2026-09-30, freeze v1, sem alterações após a primeira saída)

**Runs.**

| Conjunto | Execução 1 | Execução 2 |
|---|---|---|
| Original | `20260930T010330Z-ed058fdb` | `20260930T010604Z-573ae4dc` |
| Challenge | `20260930T010351Z-97489208` | `20260930T010619Z-dfc53744` |

- **Execução:** 0 erros, 0 recusas, 0 falhas de parse. O modelo servido foi sempre `claude-opus-5`.
- **Custo:** US$ 1,52 nas 4 execuções.
- **Resultados completos:** `outputs/experiments/E-005_qualifiers_v3/comparison/e005_results.json`.

**Original** (desenvolvimento; LLM só no doc 06, igual à D):

| | D | E |
|---|---|---|
| Campos semânticos | 30/31 | 30/31 |
| Regras de validação | 104/104 | 104/104 |
| Roteamento DEFINED | 5/6 | 5/6 |
| Taxa de revisão | 6/8 | 6/8 |
| **Aprovações inseguras** | 0 | **0** |
| Qualificadores do LLM (material / não material) | 2 / 2 | 1 / 3 |
| Qualificadores que bloqueiam | 2 | 1 |
| Bloqueios falsos por qualificador | doc 06 | doc 06 (só na execução 1) |

Os documentos corretos na D (01, 02, 04, 05, 08) têm decisão idêntica na E: não chamam o LLM e são processados da mesma forma.

**Challenge set** (ciente do autor):

| | D | E |
|---|---|---|
| Acurácia semântica | 21/21 | 21/21 |
| Qualificador / IR condicional | 6/6 | 6/6 |
| Roteamento DEFINED | 7/7 | 7/7 |
| Taxa de revisão | 5/11 | **2/11** |
| **Aprovações inseguras** | 0 | **0** |
| Falsamente confiantes | 0 | 0 |
| Qualificadores do LLM (material / não material) | 8 / 12 | 2 / 7 |
| Qualificadores que bloqueiam | 7 | 1 (CH-11, justificado) |
| Bloqueios falsos por qualificador | CH-03, CH-07, CH-08, CH-09 | **nenhum** |

- **Precisão do bloqueio por qualificador:** D 1/5, E 1/1.
- **As 2 revisões da E no challenge set:**
  - CH-11: natureza adiada, revisão esperada;
  - CH-09: conflito no valor bruto do extrator determinístico, fora do escopo dos qualificadores.

**Estabilidade (E1 × E2):**

| | D challenge | E challenge | D doc 06 | E doc 06 |
|---|---|---|---|---|
| Semanticamente estável (mesmos qualificadores materiais e roteamento) | 8/10 | **10/10** | não | não |
| Roteamento igual | 9/10 | **10/10** | sim | sim, mas por motivos diferentes |
| Texto bruto dos qualificadores igual | 7/10 | 8/10 | — | — |

- O CH-07 foi aprovado nas duas execuções da E.
- Invocação idêntica à D (mesmo detector): falsos positivos CH-01, CH-02 e CH-11; falso negativo doc 03.

**Custo e latência (execução 1):**

| | D original | E original | D challenge | E challenge |
|---|---|---|---|---|
| Custo por documento com LLM | US$ 0,073 | US$ 0,080 (+10%) | US$ 0,064 | US$ 0,068 (+6%) |
| Tokens de entrada por documento com LLM | 9,0k | 10,2k | 8,4k | 9,6k |
| Tokens de saída por documento com LLM | 1,1k | 1,2k | 0,9k | 0,8k |
| Latência média, documentos com LLM | 17,6 s | 18,8 s | 12,3 s | 13,1 s |

O prompt v3 é mais longo, pelo teste de remoção e pela regra de escopo. Sem prompt caching, como pedido.

### Doc 06 (critério 2): não atendido

Em nenhuma execução o doc 06 foi aprovado:

| Execução | O que aconteceu | Motivo da revisão |
|---|---|---|
| E1 | "As frações remanescentes ... alienadas em leilão" foi para `operational_instruction` ✅. Mas "Os acionistas que ... ficarem com frações ... terão o período ... para ajustar suas posições" foi marcado `material_condition`, `affects=entitlement`, `target=ratio` | `SEMANTIC_AMBIGUITY` (efeito material não representado). O LLM não aplicou o teste de remoção como pretendido: o período de ajuste não altera proporção, data com nem data ex |
| E2 | Os dois trechos de frações foram para `operational_instruction` ✅ (nenhum qualificador bloqueante). Mas o LLM citou a data ex como "29/06/2026" com uma evidência escrita "29 de junho de 2026" | O grounding rejeitou (`VALUE_NOT_IN_EVIDENCE`, correto e seguro), a `ex_date` ficou ausente, e o documento foi para revisão por `REQUIRED_FIELD_MISSING` |

- **Leitura:** o v3 resolveu o problema principal da D no doc 06 (a regra de leilão das frações deixou de ser `other` bloqueante nas duas execuções). O período de ajuste de frações continua no limite da definição de "direito" para o LLM, e o documento ainda falhou por um motivo novo e não relacionado (formato da data fora da citação).
- Nenhum dos dois motivos é inseguro.

### CH-07 (critério 3): atendido

| | D1 | D2 | E1 | E2 |
|---|---|---|---|---|
| Decisão | REVIEW | AUTO | AUTO | AUTO |
| O que o LLM fez | listou "Valor bruto por ação preferencial (PN) R$ 0,33" como qualificador (`informational_context`, `affects=amounts`) | não listou | não listou nenhum qualificador | idem |

- A regra de escopo do prompt bastou. A guarda determinística **não precisou atuar** em nenhuma execução (0 rejeições), então sua eficácia em dados reais continua não demonstrada. Ela está coberta só por testes unitários.

### Outros casos em que qualificador influenciou o roteamento

| Caso | Na D | Na E |
|---|---|---|
| CH-03 | "sobre o valor bruto" bloqueava como condição de base; o limite TJLP bloqueava como informativo inconsistente | TJLP virou nota; AUTO nas duas execuções |
| CH-08 | "Será considerada a posição acionária do dia ..." bloqueava como elegibilidade | Não é mais qualificador; AUTO nas duas |
| CH-09 | Frase "Farão jus ..." e "resultando em valor líquido" bloqueavam | Nenhum qualificador; a revisão restante é o conflito real de valor |
| CH-11 | Adiamento da natureza bloqueia | Idem, agora como `unresolved` / `event_nature` (justificado) |

### Critérios de sucesso pré-registrados

| # | Critério | Resultado |
|---|---|---|
| 1 | Aprovações inseguras = 0 | ✅ |
| 2 | Doc 06 sem revisão por motivo operacional | ❌ E1: período de frações marcado como direito; E2: operacional ok, mas `ex_date` rejeitada pelo grounding |
| 3 | CH-07 estável | ✅ |
| 4 | Nenhum caso seguro passou a ser aprovado incorretamente | ✅ (CH-03, CH-07, CH-08 aprovados com todos os alvos corretos) |
| 5 | Taxa de revisão cai ou fica igual | ✅ (11 → 8 no total; challenge 5 → 2; original igual) |
| 6 | Lógica mais simples ou explicável | ✅ (qualitativo) — 6 tipos em vez de 9; bloqueio definido por "efeito material não representado"; notas nunca bloqueiam. Acrescentou a guarda de escopo e a tabela de representação (3 regras) |

### Failure modes novos

- **E-1:** o conceito "direito/entitlement" é amplo demais para procedimentos de frações. O teste de remoção não foi aplicado de forma consistente pelo LLM (doc 06, E1).
- **E-2:** o LLM escreve o valor num formato diferente do da citação de evidência. O grounding rejeita corretamente e o registro vai para revisão por campo ausente. A instrução "valor exatamente como escrito" não é obedecida 100% das vezes. Esse modo existe desde a C, mas só apareceu aqui.
- **E-3:** a guarda de escopo determinística não foi exercitada em dados reais. A melhora do CH-07 veio do prompt. A guarda é uma rede de segurança não testada em produção.
- **E-4:** custo e latência por documento com LLM ~6–10% maiores (prompt mais longo).

### H-27

**MODIFIED.**
- **Confirmado:**
  - separar qualificador material de nota, somado à regra de escopo, eliminou os bloqueios falsos por rótulo, por frase que define campo e por contexto no challenge set (4 → 0);
  - a taxa de revisão caiu (5/11 → 2/11);
  - a estabilidade semântica subiu (8/10 → 10/10);
  - a segurança foi mantida (0 inseguras).
- **Não confirmado:** o critério pré-registrado para o doc 06 (procedimento de frações ainda lido como "direito" numa execução; na outra, falha por formato da data).
- **Pela regra pré-registrada**, "E só é melhor que D se" todos os critérios forem atendidos, a E **não passa formalmente**, apesar de não ser pior que a D em nenhuma métrica de qualidade ou segurança.

### Recomendação

- A E é Pareto-superior à D em qualidade, segurança, estabilidade e taxa de revisão, e só é ~6–10% mais cara por chamada. Proponho que a E **substitua a D como candidata** se você aceitar que o critério 2 não foi atingido. A decisão fica com você, porque contraria a regra pré-registrada.
- **Pendências** (não implementadas; exigem autorização):
  - (a) definir de forma operacional que tratamento e prazo de frações não alteram direito nem proporção;
  - (b) E-2: quando valor e evidência divergirem só em formato, a abordagem segura continua sendo revisão. Uma alternativa é exigir que o LLM copie o valor da própria evidência. Ambas precisam de experimento próprio;
  - (c) holdout cego.

## Candidata E congelada (D-024) — tags `e005-final` (`e13eabe`) e `candidate-E` (`e0fd841`)

H-27 continua **MODIFIED**. O critério do doc 06 não foi atingido e fica como known limitation. A adoção da E é decisão de engenharia (D-024).

## BT-001 — Blind test independente da variante E (1ª execução oficial; **incompleta por falta de crédito na API**)

### Criação e independência do blind set

- **Criador:** subagente separado (modelo Sonnet, família diferente do `claude-opus-5` avaliado), com contexto novo. Recebeu **só** o brief neutro (`tests/blind_set/BRIEF.md`): descrição do domínio, formato de arquivos e gabarito, e regras de negócio de roteamento.
- **Não recebeu:** código, prompts, challenge set, gabaritos anteriores, failure modes, doc 06, decisões ou resultados.
- **Operação:** escreveu só num diretório fora do repositório; declarou ter usado apenas a ferramenta de escrita (17 chamadas). O harness contou 18 usos de ferramenta; a diferença não é verificável.
- **Limites da independência:** é garantida por instrução e contexto novo, não por sandbox. O criador também é um modelo Claude (vieses possivelmente correlacionados, atenuados pela família diferente). O brief inclui as regras de completude e roteamento do projeto, para que o gabarito use a mesma política de negócio.
- **Conteúdo:** 14 avisos em texto (`tests/blind_set/documents/`); base de referência exclusiva (17 ativos: 13 dos avisos, 4 extras; 1 ativo de aviso propositalmente ausente); gabarito; README do criador.
- **Tipos:** DIVIDEND 4, JCP 4, BONUS_SHARES 2, REVERSE_SPLIT 1, SPLIT 1, OTHER (revogação) 1, UNRESOLVED 1. Roteamento esperado: 9 AUTO, 5 REVIEW.
- **Freeze antes de qualquer processamento:** `tests/blind_set/MANIFEST.json` (SHA-256 exato de 18 arquivos), `tests/test_blind_set_freeze.py`, commit `2319246`. O avaliador (`src/evaluation/blind.py`) foi pré-registrado no commit `48b5ebb`, antes da execução.
- **E executada exatamente como no E-005:** 0 arquivos congelados alterados, verificado contra o `FREEZE` do E-005.

### Execução

| Item | Valor |
|---|---|
| Run da E | `20260930T012932Z-4c856cb3` (`outputs/experiments/BT-001_blind_E/blind_E`) |
| Instrumentação | run do B `20260930T013131Z-5ca2ce01` (determinístico, sem LLM; só para o oráculo de necessidade) |
| Configuração | `claude-opus-5`, effort medium, fallback off, prompt v3 `e6bd3105dc7c8c84` |
| Custo incremental | US$ 0,4036 (53,4k tokens de entrada, 5,5k de saída); instrumentação B sem custo |

**Incidente operacional.** O saldo de créditos da conta Anthropic acabou durante a execução. As chamadas de **BT-10** (depois da rodada da tool), **BT-11** e **BT-12** retornaram HTTP 400 `credit balance is too low`.
- Os 3 documentos foram para revisão com `SEMANTIC_INTERPRETER_FAILED`, e as validações obrigatórias rodaram: degradação segura.
- A interpretação semântica da E **não foi medida** nesses 3 casos.
- A resposta parcial do BT-10 (1 chamada bem-sucedida) ficou gravada em `llm_cache_run1`. Qualquer reexecução deve usar cache novo.
- **Nada foi corrigido nem reexecutado.**

### Resultados (execução como está)

**Segurança:**
- **0 aprovações automáticas inseguras**; **0 ambiguidades aprovadas**; **0 aprovações falsas**.
- **Valor emitido onde o gabarito diz não aplicável:** BT-08 (revogação), com o valor bruto do evento **revogado** ("valor bruto de R$ 0,4000000000"). Está no texto, não é inventado, mas pertence a um evento cancelado. O registro foi para revisão.
- **Omissão silenciosa num registro aprovado (fora da métrica pré-registrada):** no BT-01, o aviso declara dividendos **isentos de IR**. O LLM interpretou corretamente (`EXEMPT`), mas a fusão exige alíquota numérica e descartou a interpretação. O registro foi **AUTO_APPROVE sem a isenção**. Não há valor errado emitido, mas há perda de informação tributária num registro aprovado.

**Semântica:**

| Métrica | Resultado |
|---|---|
| Tipo de evento | 12/14 (erros: BT-08 revogação → DIVIDEND; BT-13 ambíguo → DIVIDEND) |
| Alvos semânticos (tipo + papéis de data + IR) | 44/57 |
| Qualificadores materiais do gabarito capturados | 2/6 |

- 3 dos 13 alvos semânticos errados vêm dos casos sem LLM por falta de crédito.

**Determinístico:**

| Métrica | Resultado |
|---|---|
| Valores e proporções | 16/18 (BT-05: proporção de desdobramento não extraída; BT-13: valor bruto não extraído) |
| Identificadores | **41/41** |
| Regras objetivas | 39/54 (1 falso negativo: BT-13, ativo fora da base mas sem ISIN no aviso; 0 falsos positivos) |
| Status de campo | 89/126 (bruto, veja ressalva abaixo) |

**Ressalva de avaliação (pós-execução, sem alterar o avaliador):** o status de campo inclui artefatos de convenção:
- `share_credit_date` "não aplicável" no gabarito aparece como ausente no registro de eventos em dinheiro (11 casos), porque o pipeline só emite esse campo para bonificação;
- IR "não aplicável" no gabarito aparece como `not_found` no pipeline para dividendos sem menção a IR (BT-11, BT-14).

Falha real e recorrente: `approval_date` não encontrada em 10/14 avisos. A frase de aprovação usada pelo criador não casa com o padrão determinístico. O campo não é obrigatório.

**Roteamento:**

| Métrica | Resultado |
|---|---|
| Acerto | 8/14 (3 AUTO corretos, 5 REVIEW corretos) |
| Aprovações falsas | 0 |
| Revisões falsas | 6: BT-02, BT-05, BT-09, BT-10*, BT-11*, BT-12* |
| Taxa de revisão | 11/14 |

\* Casos afetados pela falta de crédito.
- **BT-02:** o B atribuiu "exceto ... imunes ou isentos" aos valores bruto e líquido. O LLM explicou a exceção (representada no IR), mas a fusão v2 não desfaz o LOW do B em campos de **valor**.
- **BT-05:** proporção de desdobramento não suportada pelo extrator, e fora do escopo do LLM.
- **BT-09:** dois valores líquidos (cenário tributário diferenciado), `CONFLICTING_VALUES` → revisão. É conservador; o gabarito aprovaria pela "generalidade dos acionistas".

**Uso do LLM:**

| Métrica | Resultado |
|---|---|
| Documentos com LLM | 8/14 |
| Chamadas por documento com LLM | 1,38 (3 incompletas) |
| Tool calls / lookups corretos | 6 / 6 |
| Divergências tool × validation engine | 0 |
| Grounding | **48/48** trechos literais |
| Falhas de parse/schema (todas pela falta de crédito) | 3 |
| Recusas | 0 |
| Falso-positivas (oráculo sobre o B) | nenhuma |
| Falso-negativas | **BT-03** (datas não obrigatórias), **BT-07** (base do IR não literal, gatilho ausente por desenho), **BT-13** (dividendo com IRRF de JCP: contradição semântica que o detector não vê) |

**Operacional:**
- Latência mediana: 12,0 s com LLM, 6 ms sem LLM, 0,5 s no geral.
- 0 erros de pipeline.

### Failure modes observados

1. **BT-1 — tratamento tributário não numérico:** isenção (`EXEMPT`) é descartada, e o registro é aprovado sem ela.
2. **BT-2 — evento que o esquema não representa** (revogação/cancelamento): o determinístico classifica pelo vocabulário (DIVIDEND) e extrai o valor do evento cancelado. O LLM diz UNRESOLVED, mas o tipo determinístico é mantido.
3. **BT-3 — contradição semântica não detectada** (tipo declarado × tratamento tributário): nenhum gatilho do detector cobre. Seguro por acaso.
4. **BT-4 — atribuição de qualificador do B a campos de valor** sem caminho de resolução na fusão.
5. **BT-5 — cobertura determinística:** frase de aprovação, proporção de desdobramento, variações de "sobre o valor bruto".
6. **BT-6 — falta de crédito na API:** degradação segura, mas o cache guardou uma resposta parcial.

### Segunda execução

**Justificável, mas por completude, não só por estabilidade.** Os 3 documentos com falha de crédito não tiveram a E avaliada, e 8/14 decisões dependem do LLM. Proposta, se autorizada e após a recarga de créditos:
- uma execução completa nova (cache novo, mesma E congelada), ~US$ 0,55;
- servir como execução oficial completa;
- comparar com a primeira nos 5 documentos que completaram, para medir estabilidade.

### Leitura

- **A segurança no sentido pré-registrado se manteve** em dados nunca vistos: 0 aprovações inseguras, 0 ambiguidades aprovadas, 48/48 citações literais.
- **A utilidade caiu bastante** (roteamento 8/14, revisão 11/14), em parte pela falta de crédito e em parte por limites de cobertura determinística.
- **O blind test expôs um risco que as métricas anteriores não capturavam:** omissão de tratamento tributário não numérico num registro aprovado (BT-01). Ele precisa virar métrica e hipótese antes de qualquer adoção.

### BT-001 — Execução 2 (completa), após a recarga de créditos

- **Run:** `20260930T013554Z-eeef7f71` (`outputs/experiments/BT-001_blind_E/blind_E_run2`). Mesma E congelada (freeze verificado), cache novo (`llm_cache_run2`, sem ler o da execução 1).
- **Execução:** 0 erros, 0 recusas, 0 falhas de parse. 8 documentos com LLM, 16 chamadas (2 por documento), 8 tool calls, todas corretas. Custo US$ 0,5883.
- **Custo incremental total do blind test:** US$ 0,99 (0,4036 + 0,5883). A instrumentação B não tem custo.
- **Avaliação:** `evaluation_run2/blind_results.json`, com o avaliador pré-registrado, sem alterações.

**Resultados da execução completa:**

| Métrica | Resultado |
|---|---|
| **Aprovações inseguras** | **0** |
| **Ambiguidades aprovadas** | **0** |
| Aprovações falsas | 0 |
| Roteamento | 8/14 (3 AUTO corretos, 5 REVIEW corretos) |
| Taxa de revisão | 11/14 |
| Tipo de evento | 12/14 |
| Alvos semânticos | 46/57 |
| Qualificadores do gabarito capturados | 2/6 |
| Valores e proporções | 16/18 |
| Identificadores | 41/41 |
| Regras objetivas | 43/54 (1 falso negativo, 0 falsos positivos) |
| Grounding | **76/76** |
| Divergências tool × engine | 0 |
| Chamada do LLM | 8/14 (falso-positivas: nenhuma; falso-negativas: BT-03, BT-07, BT-13) |
| Latência mediana com LLM / sem LLM | 12,6 s / 4 ms |

**Estabilidade (execução 1 × 2):**

| Dimensão | Resultado |
|---|---|
| Decisão de chamar o LLM | **14/14** |
| Roteamento | **14/14** |
| Tipo de evento, nos documentos com LLM | 8/8 |
| Qualificadores materiais (semanticamente estáveis) | 6/8 |

- As diferenças de qualificadores: no **BT-10**, a execução 1 foi truncada pela falta de crédito; no **BT-08**, o conjunto de qualificadores materiais mudou (surgiu `entitlement` além de `event_nature`), com o mesmo roteamento (revisão).
- A falta de crédito da execução 1 **não alterou nenhuma decisão final**: os 3 casos afetados também vão para revisão com o LLM completo.

**Por que os casos antes afetados vão para revisão (com o LLM completo):**

| Caso | Motivo |
|---|---|
| **BT-10** | "Não farão jus à bonificação as ações mantidas em tesouraria" marcado como `material_exception` / `eligibility`, e bloqueou. O gabarito o trata como contexto não material (exclusão legal padrão). |
| **BT-11** | O LLM mapeou todas as datas; o pagamento "15.10.2026" (formato com pontos) não é aceito pelo parser determinístico (`UNPARSEABLE_DATE`), o grounding rejeita e o documento vai para revisão por campo ausente. |
| **BT-12** | Duas razões sociais "... S.A." no aviso (conflito no nome do emissor → extração LOW) e uma negação atribuída pelo B ao valor líquido. |

**Failure modes confirmados com o LLM completo:**
- **Omissão da isenção (BT-01):** repetida na execução 2 (o LLM diz `EXEMPT`; a fusão descarta por falta de alíquota numérica; AUTO_APPROVE sem isenção). **Estável e determinístico**, causado pela fusão, não pelo LLM.
- **Revogação (BT-08):** o LLM diz UNRESOLVED; o registro mantém DIVIDEND e o valor revogado; vai para revisão.
- **Contradição dividendo × IRRF de JCP (BT-13):** não detectada, sem LLM; vai para revisão por outros motivos.

**Failure modes novos na execução 2:**
- **BT-7:** o parser de datas não aceita dd.mm.aaaa.
- **BT-8:** exclusão legal padrão (ações em tesouraria) tratada como exceção material.
- **BT-9:** outra entidade "S.A." no aviso gera conflito de razão social.

## E-006 — Hardening da candidata E → variante F (pré-registro; congelado)

- **Checkpoint da E antes do E-006:** tag `pre-e006` (`d5384ef`). O estado exato da E também está nas tags `e005-final` e `candidate-E`.
- **E preservada:** a E reproduz, por replay, todos os registros oficiais do E-005 (execução 1) e do BT-001 (execução 2) (`tests/test_e005_regression.py`, 33 casos). A, B, C e D continuam reproduzindo o E-003 e o E-004.
- **Congelamento:** `outputs/experiments/E-006_hardened/FREEZE.json`, verificado por `tests/test_e006_freeze.py`.
  - Cobre o código inteiro, os testes, os gabaritos dos três conjuntos, o prompt v3 (`e6bd3105dc7c8c84`) e o avaliador `evaluation/e006.py`.
  - O teste também verifica que nenhum identificador do blind-derived set (razão social, ticker, ISIN, CNPJ) aparece no código de `src/corporate_actions`.
- **Configuração:** `claude-opus-5`, effort medium, 8000 max tokens, fallback off (igual à E).

### Variante F — `candidate_hardened` (schema `semantic-record/0.4`)

F = E + os blocos abaixo. Tudo fica num ramo aditivo (`_semantic_f`, `hardening.py`, perfil `v2` via ContextVar, ativo só durante o processamento da F).

1. **Cobertura determinística (perfil v2):**
   - datas dd.mm.aaaa, dd-mm-aaaa e d/m/aaaa, normalizadas para ISO;
   - proporções: quatro formas genéricas, com quantidade por extenso (um/uma…dez) e direção preservada (`shares_before`→`shares_after`; `shares_held`/`bonus_shares`). Exemplos: "cada N ação(ões) … será(ão) desdobrada(s)/grupada(s)/convertida(s) em M" / "dará origem a" / "passará a ser representada por"; "proporção de N para M"; "proporção/fator N:M"; "para cada N ações … receberão M novas";
   - rótulo "crédito das [qualificador] ações";
   - `share_credit_date` opcional também em desdobramento e grupamento. Sem esse campo, uma data de crédito declarada não teria onde ser representada;
   - emissor principal por papel estrutural: cabeçalho, CNPJ adjacente, "(a Companhia)", "comunica/informa"; escriturador, custodiante etc. são terceiros. Alias "órgão da X S.A." é agrupado em "X S.A.". Duas entidades com papel estrutural → LOW, `ISSUER_UNRESOLVED_MULTIPLE_STRUCTURAL_CANDIDATES` → revisão. O LLM nunca escolhe o emissor.
2. **`tax_treatment`** (`fields.tax_treatment`):
   - `kind`: WITHHOLDING_AT_RATE, CONDITIONAL_MULTIPLE_RATES, EXEMPT, NO_WITHHOLDING_DECLARED; o campo fica `not_found` se não houver declaração e `not_applicable` em eventos em ações;
   - atributos: `rate`, `base`, `beneficiary_exceptions`, `conditions`, com evidência literal, regra, âncora e confiança;
   - isenção de titular ("acionistas imunes ou isentos") é exceção por beneficiário, não isenção da distribuição;
   - isenção nunca vira alíquota zero; `withholding_tax` continua sendo só alíquota numérica;
   - isenção dita pelo LLM com citação literal localizada é representada (`llm.tax_treatment_exempt`), em vez de descartada por não ter porcentagem.
3. **Gate de cobertura material** (`semantic.material_coverage`, antes do AUTO_APPROVE):
   - **inventário de itens materiais:**
     - declarações tributárias determinísticas;
     - IR numérico;
     - IR do LLM com citação localizada;
     - papéis de data do LLM (data-base, ex, pagamento, crédito);
     - qualificadores materiais do LLM;
     - candidatos de proporção;
     - revogação;
     - **inventário determinístico de datas de liquidação**, que não depende do LLM: data cuja pista de papel mais próxima, na mesma linha ou frase e sem outra data no meio, é de crédito ou pagamento;
   - liquidação no passado ("já foram pagos em") é registrada como não material, com justificativa;
   - cada item registra evidência, categoria, campo-alvo, status (REPRESENTED / UNRESOLVED_EXPLICIT / NON_MATERIAL_JUSTIFIED / NOT_REPRESENTED), justificativa e decisão de bloqueio;
   - qualquer NOT_REPRESENTED → `MATERIAL_INFORMATION_NOT_REPRESENTED` → revisão.
4. **Detector de contradições** (`semantic.contradictions`). Não decide qual lado está certo. Incompatibilidades documentadas:
   - DIVIDEND com retenção à alíquota fixa, sem condição de limite nem base de excedente: regime do JCP, porque o dividendo só é tributado acima de limite;
   - JCP isento ou sem retenção no nível da distribuição (a isenção do JCP é por titular);
   - direção da proporção incompatível com SPLIT/REVERSE_SPLIT;
   - isenção junto com alíquota numérica.

   Se existe antes do LLM, vira gatilho `SEMANTIC_CONTRADICTION` do detector de necessidade. Se persiste depois da fusão, bloqueia (`SEMANTIC_CONTRADICTION:<código>`).
5. **Revogação mínima:** linguagem de revogação ou cancelamento em contexto de evento (excluído "cancelamento de ações") → `semantic.event_status = REVOCATION_DETECTED_UNSUPPORTED` e `UNSUPPORTED_EVENT_REVOCATION` → revisão. O LLM não é chamado, porque não muda o desfecho. Não há novo tipo de evento.

### Definições de segurança (D-025) e papéis dos conjuntos (D-026)

- `unsafe_auto_approval` (histórica): avaliadores originais, inalterados.
- `unsafe_auto_approval_enhanced` (E-006 em diante; **post-hoc**, motivada pelo BT-001): alucinação, ambiguidade aprovada, falha de validação aprovada, **omissão material**, conflito semântico não suportado. A E é reavaliada com ela como leitura post-hoc.
- **Original:** regression/development. **Challenge set:** regression, inalterado. **Blind-derived regression set:** o antigo blind set; não é blind test para a F.

### Critérios de sucesso (pré-registrados; limiares fixados antes do run)

1. `unsafe_auto_approvals_enhanced` = 0 nos três conjuntos. Qualquer aprovação com omissão material = F falha;
2. 0 omissões materiais aprovadas;
3. nenhuma regressão de segurança: `unsafe` histórica = 0 na F, e enhanced da F ≤ enhanced da E, por conjunto;
4. roteamento não piora materialmente: false reviews da F ≤ false reviews da E + 1, por conjunto;
5. mudanças generalizáveis e explicáveis (qualitativo; o teste de freeze proíbe identificadores do blind-derived set no código);
6. custo total da F ≤ 1,25 × custo da E nos mesmos conjuntos; p50 dos documentos com LLM ≤ 1,5 × o da E;
7. arquitetura simples de defender (qualitativo).

### Protocolo (uma execução oficial; cache novo, todas as chamadas reais)

```bash
F=outputs/experiments/E-006_hardened
python -m corporate_actions --variant F --out $F/original_F --llm-cache $F/llm_cache_run1
python -m corporate_actions --variant F --documents tests/challenge_set/cases --out $F/challenge_F --llm-cache $F/llm_cache_run1
python -m corporate_actions --variant F --documents tests/blind_set/documents --golden tests/blind_set/golden_records.csv --out $F/blind_derived_F --llm-cache $F/llm_cache_run1
python -m evaluation.e006 --out $F/evaluation
```

Depois da primeira saída oficial, nada muda: F, prompt, regras, avaliador e conjuntos ficam como estão. Uma segunda execução só acontece se houver necessidade clara de medir estabilidade.

### Disclosure (importante)

- **Dry run nos três conjuntos durante o desenvolvimento.** A F foi executada por replay das respostas do LLM já gravadas da E (caches do E-005 e do BT-001, sem API) no original, no challenge set e no blind-derived set. As seguintes mudanças foram feitas **depois** de observar essas saídas:
  - quantidade por extenso e "dará origem a" na regra de proporção (classe vista no BT-05);
  - `share_credit_date` opcional em desdobramento e grupamento (BT-05: data de crédito sem lugar no schema);
  - inventário determinístico de datas de liquidação e rótulo "crédito das [qualificador] ações". Motivo: o dry run revelou que a **E aprovou o BT-03 sem a data de crédito das novas ações**, uma omissão material pela definição enhanced;
  - refinamentos do inventário depois de alarmes falsos: pista mais próxima decide o papel (doc 01), limite na data anterior (BT-14), liquidação passada (CH-10), "realizado" deixa de ser pista de aprovação (BT-11);
  - agrupamento de alias de emissor ("Diretoria da X S.A.", visto no BT-12).

  Nenhuma regra usa texto, nome, ticker ou identificador de um documento específico. Ainda assim, **os resultados da F nos três conjuntos são in-sample**.
- **O dry run não prevê o run oficial:** as respostas do LLM do run oficial são novas, e documentos em que a F chama o LLM e a E não chamava (ex.: gatilho de contradição) não tinham resposta gravada.
- **Leitura post-hoc da E pela definição enhanced (vista no dry run, antes do congelamento):** BT-01 (isenção descartada) e BT-03 (data de crédito descartada) seriam aprovações inseguras da E. Isso **não altera** o resultado pré-registrado do BT-001 (0 inseguras pela definição da época).

### Resultado (execução oficial única da F em 2026-09-30, freeze v1 `e006-freeze` → `e7011ef`, sem alterações após a primeira saída)

- **Runs:**
  - `outputs/experiments/E-006_hardened/original_F`, `challenge_F` e `blind_derived_F`;
  - cache novo `llm_cache_run1`, sem replay (`replayed_documents` = 0 nos três);
  - 0 erros, 0 recusas, 0 falhas de parse, 0 divergências tool × engine, modelo servido `claude-opus-5` em todas as chamadas.
- **Avaliação:** `evaluation/e006_results.json` (avaliador pré-registrado, inalterado).
- **Custo incremental do E-006:** **US$ 1,3422**, com 38 chamadas, 183.408 tokens de entrada e 17.005 de saída. Por conjunto: original 0,0744; challenge 0,6925; blind-derived 0,5753. Os dry runs foram por replay, sem custo. A E custou US$ 1,3496 nos mesmos conjuntos.

**Segurança (definição enhanced, D-025).** Os números da E são leitura **post-hoc** dos registros oficiais congelados.

| | Original E / F | Challenge E / F | Blind-derived E / F |
|---|---|---|---|
| **Aprovações inseguras (enhanced)** | 0 / **0** | 0 / **0** | **2 (BT-01, BT-03)** / **0** |
| Omissões materiais aprovadas | 0 / 0 | 0 / 0 | 2 / **0** |
| Alucinações aprovadas | 0 / 0 | 0 / 0 | 0 / 0 |
| Ambiguidade não resolvida aprovada | 0 / 0 | 0 / 0 | 0 / 0 |
| Falha de validação aprovada | 0 / 0 | — | 0 / 0 |
| Contradição aprovada | 0 / 0 | 0 / 0 | 0 / 0 |
| Aprovações falsas | 0 / 0 | 0 / 0 | 0 / 0 |
| Aprovações inseguras (definição histórica) | 0 / 0 | 0 / 0 | 0 / 0 |

As duas aprovações inseguras da E pela definição enhanced são omissões:
- **BT-01:** isenção de IR descartada na fusão;
- **BT-03:** "Data de crédito das novas ações" não reconhecida pelo rótulo.

A F aprova os dois **com** a informação representada: `tax_treatment` EXEMPT, sem alíquota; `share_credit_date` 07/10/2026.

**Utilidade**

| | Original E / F | Challenge E / F | Blind-derived E / F |
|---|---|---|---|
| Roteamento (expectativas DEFINED) | 5/6 / 5/6 | 7/7 / 7/7 | 8/14 / **9/14** |
| Taxa de revisão | 6/8 / 6/8 | 2/11 / **3/11** | 11/14 / **10/14** |
| False reviews | doc 06 / doc 06 | CH-09 / CH-03, CH-09 | BT-02, 05, 09, 10, 11, 12 / BT-02, 05, 09, 10, 12 |
| Acurácia semântica (avaliador original) | 30/31 / **29/31** | 21/21 / 21/21 | 46/57 / **49/57** |
| Validação (regras) | 104/104 / **101/104** (1 FP) | — | 43/54 / **45/54** (1 FN nas duas) |
| Valores e proporções (blind) | — | — | 16/18 / **17/18** |
| Cobertura de extração determinística | 66/79 / 66/79 | 5/13 / 5/13 | 87/115 / **92/115** |
| Invocação do LLM | 1/8 / 1/8 | 10/11 / 10/11 | 8/14 / 8/14 |
| Grounding (citações literais) | — | — | 76/76 / 74/74 |
| Latência p50 com LLM | 18,8 s / 12,4 s | 11,6 s / 10,4 s | 12,0 s / 11,5 s |
| Latência p50 sem LLM | 12 ms / 14 ms | 7 ms / 8 ms | 4 ms / 6 ms |

**Oráculo de necessidade do E-004 (inalterado; ele não conhece os gatilhos novos da F):**
- original: igual à E (falso-negativo doc 03);
- challenge: igual à E (falso-positivos CH-01, CH-02, CH-11);
- blind-derived: falso-negativos BT-03, BT-07 e BT-08; na E eram BT-03, BT-07 e BT-13.
  - BT-13 passou a ser invocado pelo gatilho `SEMANTIC_CONTRADICTION`.
  - BT-08 deixou de ser invocado **por desenho** (revogação → revisão sem LLM).
  - BT-03 agora é aprovado corretamente só pelo determinístico.

**Checagens por classe (blind-derived regression set):**

| Classe | Resultado |
|---|---|
| Isenção representada em vez de descartada | BT-01 e BT-06: `tax_treatment` EXEMPT, `rate` nulo ✔ |
| Datas com pontos | BT-11: pagamento 15.10.2026 → 2026-10-15 ✔ (AUTO_APPROVE correto) |
| Proporção de desdobramento/grupamento/bonificação | 4/4 ✔. BT-05 ("cada uma ação … dará origem a 3") agora é 1→3 |
| Emissor com várias empresas | BT-12: alias "Diretoria da X S.A." agrupado, emissor resolvido por papel estrutural, sem LOW. Continua em revisão por `SEMANTIC_AMBIGUITY` (negação atribuída pelo B ao valor líquido, como na E) |
| Contradição evento × tributação | BT-13: `EVENT_TYPE_VS_TAX_TREATMENT` detectada antes do LLM, gatilho do LLM, persistiu → revisão ✔ |
| Revogação | BT-08: `UNSUPPORTED_EVENT_REVOCATION`, `event_status = REVOCATION_DETECTED_UNSUPPORTED`, revisão ✔. O valor revogado nunca é aprovado |
| Qualificadores v3 sem regressão | Lógica idêntica à da E. Houve 1 bloqueio novo por variação do LLM (CH-03, abaixo) |

### Regressões e mudanças de roteamento em relação à E

| Caso | E → F | Causa |
|---|---|---|
| **CH-03** (challenge, PROVISIONAL AUTO) | AUTO → **REVIEW** (`SEMANTIC_AMBIGUITY`) | Nesta amostra, o LLM marcou "limitados à variação pro rata die da TJLP" como qualificador material de `amount`, não representado → bloqueio. É a política v3, **idêntica** na F. No dry run pré-congelamento, com a resposta gravada da E, a F aprovou o CH-03. É variação do LLM, não mudança de código. |
| **Doc 06** (original) | REVIEW → REVIEW (motivo muda) | O LLM escreveu datas cujo valor não está na citação (`VALUE_NOT_IN_EVIDENCE`), o mesmo failure mode da execução 2 do E-005. A data ex fica ausente (`REQUIRED_FIELD_MISSING`, e o gate registra `MATERIAL_INFORMATION_NOT_REPRESENTED`). É a origem das quedas na semântica (29/31) e na validação (1 FP em `REQUIRED_FIELDS_PRESENT`, 2 regras não avaliadas) do original. |
| **BT-05** | REVIEW → REVIEW (motivo muda) | Proporção agora extraída. Continua em revisão pela data de crédito ("… 16 de setembro de 2026, data em que as novas ações também serão creditadas"): a citação do LLM se refere à data sem contê-la, o grounding literal não aceita valor fora da citação, e o gate bloqueia. É revisão segura, e falsa pelo gabarito. |
| **BT-11** | REVIEW → **AUTO** ✔ | Data com pontos. |
| **BT-13** | REVIEW → REVIEW | Agora pelo motivo certo (contradição detectada). |
| **BT-08** | REVIEW → REVIEW | Agora com `UNSUPPORTED_EVENT_REVOCATION`. Sem LLM, o registro perde a data de aprovação que o LLM mapeava. |

### Critérios de sucesso pré-registrados

| # | Critério | Resultado |
|---|---|---|
| 1 | `unsafe_auto_approvals_enhanced` = 0 | **Atendido** (0/0/0) |
| 2 | Omissão material eliminada nos casos cobertos | **Atendido** (BT-01 e BT-03 representados; 0 omissões aprovadas) |
| 3 | Nenhuma regressão de segurança | **Atendido** (histórica 0; enhanced F ≤ E em todos os conjuntos) |
| 4 | Roteamento não piora materialmente (FR ≤ E + 1 por conjunto) | **Atendido** (original +0, challenge +1, blind-derived −1) |
| 5 | Mudanças generalizáveis e explicáveis | Atendido, qualitativo: nenhuma regra cita documento; o teste de freeze verifica a ausência de identificadores do blind-derived set. Ressalva: as regras foram refinadas vendo dry runs nos três conjuntos (disclosure) |
| 6 | Custo e latência aceitáveis | **Atendido** (custo 0,99× o da E; p50 com LLM menor nos três conjuntos) |
| 7 | Arquitetura simples de defender | Atendido, qualitativo: uma camada determinística (`hardening.py`) e um gate. Nenhum componente novo de LLM |

### Failure modes novos

1. **Referência anafórica a data** ("data em que as novas ações serão creditadas", BT-05). O grounding literal (valor dentro da citação) não aceita, e o gate bloqueia. É revisão segura, mas falsa.
2. **O inventário de datas de liquidação é heurístico** (a pista de papel mais próxima). Foi refinado em quatro alarmes falsos vistos no dry run. Redações novas podem gerar alarmes falsos (revisão), ou deixar de ver uma data (a omissão volta a depender do LLM).
3. **Alias de emissor por sufixo.** "Banco X S.A." e "X S.A." seriam tratados como a mesma entidade. Se o emissor fosse o "Banco X S.A." e uma subsidiária "X S.A." fosse citada, o nome registrado seria o da subsidiária. Risco latente, não observado; a validação de referência por ISIN/ticker/CNPJ continua ativa.
4. **Revogação sem LLM** deixa o registro revogado menos informativo (BT-08 perdeu a data de aprovação). Sem risco de aprovação.
5. **Variação do LLM nos qualificadores v3** (CH-03) e **valor fora da citação** (doc 06) continuam sendo as fontes de revisão instável. Não mudam com a F.
6. **O oráculo de necessidade do E-004 não conhece os gatilhos da F** (contradição, revogação). A métrica de invocação da F contra esse oráculo é conservadora.

### Leitura

- **Resultado principal:** a F fecha a lacuna que o BT-001 expôs. Nenhum registro é aprovado com informação material explicitamente presente e descartada, nem nos dois casos em que a E fazia isso (BT-01 e BT-03, este último descoberto no E-006).
- A utilidade melhora pouco no blind-derived set (roteamento 8 → 9/14, revisão 11 → 10/14, semântica 46 → 49/57) e fica estável no original e no challenge set. A única revisão nova é atribuível à amostragem do LLM.
- **Todos os números da F são in-sample:** os três conjuntos foram vistos em dry run durante o desenvolvimento. Nenhuma afirmação de generalização é possível sem um novo conjunto independente.
- **Recomendação:** a F atende a todos os critérios pré-registrados. Recomenda-se que substitua a E como candidata. A decisão é do usuário, como foi a D-024.
- **Segunda execução:** não foi feita. A única mudança de roteamento atribuível ao LLM (CH-03) tem contrafactual determinístico: a mesma F, com a resposta gravada da E, aprova. Uma segunda execução mediria a estabilidade da amostragem, não a F.
