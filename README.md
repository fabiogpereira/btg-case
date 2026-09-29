# Corporate Actions Extraction — Technical Case (AI Developer, Asset Servicing)

> **Status: Fase 0 — entendimento do problema.** Ainda não há código executável.

Transforma avisos de eventos corporativos (PDFs nativos e escaneados) em registros estruturados, validados contra uma base de referência, com confiança por campo, roteamento de incerteza para revisão humana e trilha de auditoria.

## Onde está cada coisa

| Caminho | Conteúdo |
|---|---|
| `case/` | Material original do case (somente leitura) |
| `docs/00-problem-understanding.md` | Problema, requisitos, riscos, perguntas em aberto |
| `docs/01-document-map.md` | Análise de cada documento do lote |
| `docs/02-hypotheses.md` | Hipóteses e status |
| `docs/03-architecture.md` | Arquitetura baseline proposta e decisões em aberto |
| `docs/04-evaluation-log.md` | Experimentos e resultados |
| `DECISIONS.md` | Decisões tomadas (ADL) |
| `src/`, `tests/`, `outputs/` | Código, testes e saídas (a construir) |

## A preencher antes da entrega (exigências do enunciado)

- [ ] Instruções de execução
- [ ] Decisões de arquitetura
- [ ] O que decidimos **não** fazer e por quê (trade-offs)
- [ ] Premissas assumidas (critério de baixa confiança, regras de coerência)
- [ ] Saída gerada sobre o lote (JSONs + relatório de exceções) em `outputs/`
