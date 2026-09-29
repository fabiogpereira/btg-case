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
