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
