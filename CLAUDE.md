# CLAUDE.md — Guia de trabalho deste repositório

Technical case para **AI Developer — Asset Servicing (BTG Pactual)**.
Tarefa do case: transformar avisos de eventos corporativos (PDFs heterogêneos) em registros estruturados, validados, com confiança, roteamento de incerteza e auditabilidade.

Este arquivo orienta qualquer agente/pessoa que trabalhe aqui. Ler antes de qualquer mudança.

---

## 0. Fase atual

**Entrega técnica.** A solução final é a variante K (tag `final-integration`; arquitetura em D-036); o README descreve a
entrega. Implementação encerrada: não alterar lógica, prompts, validadores, roteamento, OCR ou vision sem autorização.
Gabarito manual em `tests/ground_truth/` (formato em `tests/ground_truth/README.md`). Qualquer mudança no gabarito exige incrementar `ground_truth_version` e justificar.
Cada experimento (E-003 em diante) está congelado por hash e/ou por replay dos registros oficiais (`tests/test_e0*_freeze.py`,
`tests/test_e0*_regression.py`); experimentos de LLM usam configuração fixa, com fallback desligado (D-018).
Histórico e decisões: `docs/04-evaluation-log.md` e `DECISIONS.md`.

---

## 1. Source of truth: `case/`

- O material original está em `case/Case AI Dev - Envio/` (extraído sem modificação de `Case_AI_Dev_-_Envio.zip`; hashes SHA-256 em `docs/01-document-map.md`).
- `case/` é **somente leitura**:
  - não editar, renomear, sobrescrever, "limpar", converter ou reorganizar;
  - não criar arquivos dentro de `case/` (nem derivados, nem caches);
  - toda análise, artefato intermediário e saída ficam **fora** de `case/`.
- Em caso de conflito entre este arquivo / prompts e o enunciado do case, **o enunciado vence**. Sinalizar a contradição ao usuário antes de prosseguir.
- Nomes reais dos caminhos (diferem do enunciado): `documents/` (enunciado diz `documentos/`) e `golden_records/golden records.csv` (com espaço; enunciado diz `golden_records.csv`).

## 2. Estrutura do repositório

```
CLAUDE.md          este guia
README.md          entregável do case: como rodar + decisões + o que NÃO fizemos (trade-offs)
DECISIONS.md       Architecture Decision Log (só decisões tomadas; hipóteses NÃO entram aqui)
docs/
  00-problem-understanding.md   problema, requisitos, riscos (fato vs interpretação vs hipótese)
  01-document-map.md            análise documento a documento
  02-hypotheses.md              hipóteses com status (UNTESTED/TESTING/CONFIRMED/REJECTED/MODIFIED)
  03-architecture.md            baseline proposto + decisões em aberto
  04-evaluation-log.md          experimentos e resultados
src/               código
tests/             testes
outputs/           saídas geradas (JSONs por documento + relatório de exceções + manifest de run)
case/              material original — SOMENTE LEITURA
```

## 3. Princípios obrigatórios

1. **Problem-first, not AI-first.** Começar pelo problema de negócio e pelo erro que custa caro, não pela tecnologia.
2. **Determinístico quando o problema é determinístico.** Lookup, regex, comparação, aritmética, validação de schema, regra temporal e regra de negócio explícita são código, não LLM.
3. **LLM só onde há benefício claro e demonstrado**: interpretação semântica, normalização de linguagem heterogênea, classificação ambígua, extração com layout muito variável. Toda entrada de LLM no fluxo precisa de hipótese registrada em `docs/02-hypotheses.md`.
4. **Output probabilístico nunca é verdade automática.** Todo valor vindo de LLM/OCR/visão passa por verificação determinística (grounding no texto-fonte, formato, regras) antes de ser aceito.
5. **Ausente continua ausente.** Nunca inventar, inferir silenciosamente ou "completar" valores para satisfazer o schema. Distinguir explicitamente:
   - `not_found` — o valor não consta no documento (se isso é um problema depende de o campo ser obrigatório para o tipo de evento);
   - `not_applicable` — o campo não se aplica ao tipo de evento (ex.: moeda em grupamento);
   - `declared_pending` — o documento declara que o valor será definido depois (ex.: "A definir"). É **extração bem-sucedida**; o registro exige revisão (D-005).
   - Dado do golden records **não** preenche campo extraído: vai para a checagem de referência, separado.
6. **Nunca corrigir silenciosamente uma inconsistência.** Se o documento é incoerente, o registro reflete o documento e a inconsistência vira exceção para revisão humana.
7. **Duas confianças distintas:**
   - confiança **do campo** (a extração está correta em relação ao documento?);
   - confiança/status **do registro** (o registro pode seguir downstream?).
   Uma extração pode estar correta e o registro ser inválido por regra de negócio.
8. **Confiança derivada de sinais observáveis** (método de extração, grounding, validações, concordância entre fontes), não de autoavaliação do modelo. Critério documentado e explicável.
9. **Human review é um destino de primeira classe**, com motivo explícito e código de razão — não um fallback genérico.
10. **Auditabilidade é requisito de arquitetura.** Cada execução deve permitir reconstruir: documento processado (nome + hash), `run_id`, versão do pipeline, método de extração, modelo e versão de prompt (quando houver), validadores executados e resultados, confiança, motivo da decisão final, erros/retries.
11. **Não logar conteúdo sensível desnecessariamente.** Logar hashes, IDs, trechos mínimos de evidência necessários à auditoria; não despejar documentos inteiros nem prompts/respostas completos em logs gerais.
12. **Aritmética decimal (D-007).** Valores, taxas e proporções em `Decimal` construído a partir da string da fonte, nunca `float`. Preservar a precisão declarada; sem arredondamento, quantização ou tolerância que não seja regra de negócio documentada. Comparação calculado × declarado usa a precisão do declarado (exato → PASS; diferença abaixo da última casa → NOT_EVALUATED `ROUNDING_RULE_UNDEFINED`; senão → FAIL).
13. **Nome do arquivo não é evidência (D-004).** Serve só para identificação e audit trail. Nunca entra em prompt, extração, classificação, confiança, roteamento ou gabarito. Identidade do documento = SHA-256.
14. **O título do documento não determina o tipo de evento.** Classificar pelo conteúdo (ex.: doc 03 tem título "Dividendos" e conteúdo de JCP).
15. **Function calling híbrido (D-002).** O LLM usa de fato ao menos uma tool determinística de referência, mas o orchestrator executa **todas** as validações obrigatórias. A segurança nunca depende de o modelo decidir chamar uma tool.
16. **Checksum de CNPJ/ISIN não bloqueia (D-003).** Identificadores do dataset são fictícios. Identidade é validada por correspondência exata com o golden records.
17. **Sem calendário B3 no baseline (D-006).** Dia útil = seg–sex até haver evidência em contrário.
18. **Referência não encontrada (D-008)** → `REFERENCE_NOT_FOUND` → `REVIEW_REQUIRED`, nunca `REJECT` nem fuzzy match.
19. **Três camadas de verdade (D-009):** document truth, validation truth e routing expectation. Métricas de extração/validação nunca dependem de política ainda não definida.
20. **Rótulo original preservado (D-010)** em toda normalização semântica (`source_label` + `raw` + valor + evidência).
21. **Método de extração não é motivo de roteamento (D-011).** Scan não vai para revisão por ser scan; vai por falta de evidência ou de confiança.
22. **Regra sem dado de entrada é `NOT_EVALUATED`, nunca `FAIL`.** "Não aplicável" e "não encontrado" são estados diferentes.

## 4. Método de trabalho (por hipótese)

Sequência obrigatória:

```
problem understanding → hypotheses → baseline → evaluation → failure modes → targeted improvements → final architecture
```

Para cada decisão relevante:
1. registrar a hipótese em `docs/02-hypotheses.md` (por que importa, como testar, sinal esperado);
2. implementar a versão mais simples;
3. medir e registrar em `docs/04-evaluation-log.md`;
4. decidir manter / modificar / remover;
5. só então registrar em `DECISIONS.md`.

Antes de adicionar complexidade: **qual problema concreto, observado, ela resolve?** Sem evidência, não entra.

## 5. Não introduzir sem evidência de necessidade

Multi-agent · RAG · vector database · OCR em todos os arquivos · visão multimodal em todos os arquivos · filas · microserviços · frameworks de agentes · banco de dados adicional · fuzzy matching de identidade de emissor.

## 6. Requisitos do enunciado que restringem o desenho (não esquecer)

- "agente **code-first**"; validação contra golden records e regras "usando **tool / function calling**" → atendido conforme D-002.
- Saída: **um JSON por documento + relatório de exceções curto**; operador deve auditar cada valor **sem reabrir o documento**.
- README com decisões de arquitetura e **o que decidimos não fazer e por quê**.
- Haverá sessão ao vivo de 45 min para **estender e depurar o próprio código** → código pequeno, legível, modular, com testes rápidos.

## 7. Critério de simplicidade

O autor precisa conseguir responder em entrevista, para qualquer trecho:
por que IA aqui? por que não ali? por que OCR / por que não? como a confiança é calculada? o que acontece quando falha? como sabemos que uma mudança melhorou? como auditar? quanto custa? como escalar? como reduzir risco?

Se um trecho não é defensável nessas perguntas, simplificar ou remover.

## 8. Convenções

- Documentação em português; identificadores de código e chaves de JSON em inglês.
- Python (3.13 disponível localmente). Dependências mínimas e justificadas.
- Segredos (API keys) apenas via variável de ambiente; nunca em código, logs ou outputs.
- Em docs, marcar a natureza da afirmação: **[FATO]** (vem do case), **[INTERPRETAÇÃO]** (nossa leitura), **[HIPÓTESE]** (não testada).
