# Challenge set semântico — v1.0 (E-003)

Pequeno conjunto **sintético** para medir generalização semântica. É **totalmente separado** do dataset original do case: arquivos, gabarito e métricas próprios, sem mistura (D-017).

- **Origem:** escrito à mão por Claude Code em 2026-09-29 para o E-003. Modelado nos failure modes do E-002 e no vocabulário de avisos B3/CVM. Emissores e identificadores vêm do golden records, para que a validação de referência não contamine a medição semântica. **Não** foi derivado da saída de nenhuma variante.
- **Formato:** texto puro (`cases/CH-xx.txt`), porque o objetivo é medir interpretação, não parsing de PDF. A ingestão trata `.txt` como uma página de texto nativo.
- **Nomes de arquivo neutros** (`CH-01.txt`...), sem pista do problema (D-004).
- **Gabarito:** `ground_truth.json`. Cada caso tem categorias, propósito, **alvos** (o que se mede), evidência literal de cada alvo, expectativa de roteamento com status (`DEFINED` / `PROVISIONAL`) e SHA-256.
- **Coerência controlada:** em todos os casos, ex = próximo dia útil após a data com, e bruto × (1 − alíquota) = líquido, para que avisos de data ou de valor não interfiram na medição semântica.

## Casos

| Caso | Categorias | O que testa | Alvos |
|---|---|---|---|
| CH-01 | negation, event_description | Dividendo com "Não haverá crédito de juros sobre o capital próprio" | tipo = DIVIDEND |
| CH-02 | negation, misleading_keywords | Bonificação que "não altera ... dividendos" | tipo = BONUS_SHARES |
| CH-03 | event_description | JCP descrito pela definição (juros sobre o patrimônio líquido limitados à TJLP), sem as expressões canônicas | tipo = JCP |
| CH-04 | misleading_keywords | Grupamento que cita um desdobramento passado | tipo = REVERSE_SPLIT |
| CH-05 | conditional_tax | IR de 10% "incidente apenas sobre os valores que ultrapassarem R$ 50.000,00" | tipo; IR = {0.10, EXCESS_OVER_THRESHOLD} |
| CH-06 | conditional_tax, misleading_keywords | **Controle:** IR plano de 17,5% sobre o bruto, com exceção por titular, e uma data de prazo que não é papel do evento | tipo; IR = {0.175, GROSS_AMOUNT}; data com; pagamento |
| CH-07 | alternative_date_labels | "Último dia com direito", "ex-direito a partir de", "Crédito em conta" | data com, ex, pagamento |
| CH-08 | alternative_date_labels | "posição acionária do dia", "negociadas grupadas a partir de" | data com, ex |
| CH-09 | alternative_date_labels | Datas só por extenso no corpo | data com, ex, pagamento |
| CH-10 | negation, misleading_keywords | Dividendo que cita um JCP passado, já pago e "não objeto deste aviso"; título genérico | tipo = DIVIDEND; pagamento |
| CH-11 | event_description, unresolvable | O aviso **adia** a natureza (dividendo ou JCP) | tipo = **não resolvido** (null); roteamento = REVIEW_REQUIRED |

## Métricas (separadas das do dataset original)

- **Acurácia semântica:** alvos corretos / total de alvos.
- **Por categoria:** negação, expressão condicional, mapeamento de papel de data, palavras enganosas, descrição do evento.
- **Interpretações falsamente confiantes:** alvo errado **e** registro aprovado automaticamente (ninguém sinalizou o erro).
- **Aprovações automáticas inseguras:** registro aprovado automaticamente com algum alvo errado ou com expectativa `REVIEW_REQUIRED`.

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 1.0 | 2026-09-29 | 11 casos |
