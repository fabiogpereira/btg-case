# Corporate Actions Extraction — Technical Case (AI Developer, Asset Servicing)

> **Status: Baseline A (100% determinístico) implementado e avaliado — experimento E-002.** Ainda não é a arquitetura final: sem LLM, OCR ou visão por decisão deliberada, para medir primeiro o que se resolve sem componentes probabilísticos.

Transforma avisos de eventos corporativos (PDFs) em registros estruturados, validados contra uma base de referência, com confiança por campo, roteamento de incerteza para revisão humana e trilha de auditoria.

## Como rodar

Requer Python ≥ 3.12.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt     # Windows (Linux/macOS: .venv/bin/python)

# Pipeline sobre o lote do case -> outputs/runs/<run_id>/
PYTHONPATH=src .venv/Scripts/python -m corporate_actions
#   --documents DIR   --golden CSV   --out DIR   (defaults apontam para case/)

# Avaliação de um run contra o gabarito manual -> <run>/evaluation/
PYTHONPATH=src .venv/Scripts/python -m evaluation --run-dir outputs/runs/<run_id>

# Testes
.venv/Scripts/python -m pytest
```

Cada run produz:
- `records/<documento>.json` — registro por documento: campos com valor, `raw`, `source_label`, evidência literal (offset e página), confiança e motivos, validações, roteamento e audit;
- `exceptions_report.md` — documentos para revisão e por quê;
- `run_manifest.json` — `run_id`, versões, hashes das entradas e do golden, configuração, resumo.

## Resultado do Baseline A (E-002)

Nos 7 documentos com camada de texto:
- 95% dos valores exatos e 7/7 tipos de evento;
- **0 valores inventados** e 0 falsos negativos de validação;
- roteamento DEFINED correto em 5/6.

Principal failure mode: semântica condicional do IR do doc 01, extraída como alíquota plana com confiança HIGH num registro aprovado. Detalhes em [docs/04-evaluation-log.md](docs/04-evaluation-log.md).

## Onde está cada coisa

| Caminho | Conteúdo |
|---|---|
| `case/` | Material original do case — somente leitura (bytes protegidos por `.gitattributes`) |
| `src/corporate_actions/` | Pipeline |
| `src/evaluation/` | Harness de avaliação (único código que lê o gabarito) |
| `tests/` | Testes; `tests/ground_truth/` = gabarito manual v2.0 |
| `outputs/experiments/` | Artefatos versionados de cada experimento registrado |
| `docs/00`–`04` | Entendimento, mapa de documentos, hipóteses, arquitetura, evaluation log |
| `DECISIONS.md` | Decisões tomadas (ADL) |
| `CLAUDE.md` | Princípios de trabalho do repositório |

## A preencher antes da entrega (exigências do enunciado)

- [x] Instruções de execução
- [ ] Decisões de arquitetura finais (hoje: `DECISIONS.md`, D-000 a D-014)
- [ ] O que decidimos **não** fazer e por quê (trade-offs)
- [ ] Premissas assumidas (critério de baixa confiança, regras de coerência)
- [ ] Saída final gerada sobre o lote em `outputs/`
