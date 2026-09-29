# Ground truth manual — v2.0

Gabarito dos 8 documentos do lote, construído **manualmente, a partir do conteúdo dos documentos** (camada de texto nativa ou leitura visual do escaneado). Serve para testes automatizados e para medir cada mudança do pipeline (`docs/04-evaluation-log.md`).

- **Não** foi derivado dos nomes dos arquivos (D-004). O nome aparece só como identificação; a chave do documento é o `sha256`.
- **Não** é lido pelo pipeline em runtime; é usado exclusivamente por `tests/` e pelo harness de avaliação (`src/evaluation/`).
- Autoria: Claude Code, revisado pelo usuário (v1.0) e ajustado conforme as decisões D-005, D-008, D-009, D-010 e D-011 (v2.0).
- Qualquer alteração exige incrementar `ground_truth_version` e registrar o motivo no histórico abaixo.
- A integridade é verificada automaticamente em `tests/test_ground_truth_integrity.py`.

## Três camadas de verdade (D-009)

| Camada | Pergunta que responde | Depende de política? |
|---|---|---|
| `document_truth` | O que o documento **diz**: tipo de evento correto, valores, datas, ausências, rótulo original e evidência literal. | Não |
| `validation_truth` | Quais regras **objetivas** passam, falham ou não podem ser avaliadas. | Não |
| `routing_expectation` | Qual decisão operacional esperamos (`AUTO_APPROVE`, `REVIEW_REQUIRED`, `REJECT`). | **Sim** — por isso tem `expectation_status` |

Um sistema pode acertar 100% do `document_truth` e do `validation_truth` e ainda divergir de uma `routing_expectation` provisória. Nesse caso o que diverge é a política, não o sistema.

## Estrutura

```
tests/ground_truth/
├── README.md
├── index.json                sha256 → arquivo de gabarito
├── doc01.json … doc08.json
└── transcriptions/
    └── doc07_visual_transcription.txt
```

## Formato de cada `docNN.json`

```jsonc
{
  "ground_truth_version": "2.0",
  "document": {
    "sha256": "...", "file_name": "...",          // file_name: somente identificação (D-004)
    "text_layer": "native" | "none",
    "evidence_source": "pypdf_text_layer" | "human_visual_transcription"
  },
  "document_truth": {
    "classification": {
      "event_type": "DIVIDEND" | "JCP" | "BONUS_SHARES" | "REVERSE_SPLIT",
      "subtype_as_declared": "..." | null,
      "source_label": "Tipo de evento" | "...",   // rótulo onde o documento declara o tipo
      "title_as_declared": "...",
      "title_consistent_with_content": true | false,
      "evidence": ["..."], "traps": ["..."],
      "classification_notes": "..."               // opcional
    },
    "fields": { "<campo comum>": FIELD },          // sempre os 14 campos comuns
    "event_specific_fields": { "<campo>": FIELD }
  },
  "validation_truth": {
    "reference": { "golden_match": true | false, "matched_ticker": "..." | null },
    "rules": [ { "rule_id": "...", "expected": "PASS" | "FAIL" | "NOT_EVALUATED", "note": "..." } ]
  },
  "routing_expectation": {
    "expectation_status": "DEFINED" | "PROVISIONAL" | "POLICY_DEPENDENT",
    "decision": "AUTO_APPROVE" | "REVIEW_REQUIRED" | "REJECT" | null,   // null quando POLICY_DEPENDENT
    "reason_codes": ["..."],
    "acceptable_alternatives": [ { "decision": "...", "condition": "..." } ],
    "rationale": "...",
    "policy_refs": ["D-xxx", "Q-xx"]
  },
  "open_points": ["..."]
}
```

### FIELD (normalização semântica preserva a origem — D-010)

```jsonc
{
  "status": "found" | "not_found" | "not_applicable" | "declared_pending",
  "value": <normalizado> | null,        // o campo normalizado é a chave do objeto (ex.: record_date)
  "raw": "<como aparece no documento>" | null,
  "source_label": "<rótulo original da fonte>" | null,   // ex.: "Data-base do grupamento"; null se o valor vem de frase do corpo sem rótulo
  "location": "header" | "body" | "table" | "closing",
  "evidence": ["<trecho literal>"],
  "notes": "..."
}
```

Exemplos de normalização com rótulo preservado:

| Rótulo original (`source_label`) | Campo normalizado |
|---|---|
| Data-base do grupamento | `record_date` |
| Início da negociação grupada | `ex_date` |
| Crédito das ações bonificadas | `share_credit_date` |
| Data “ex-JCP” / Data “ex” / Data “ex-bonificação” | `ex_date` |
| Imposto de Renda Retido na Fonte / IRRF na fonte | `withholding_tax` |

### Campos comuns (`fields`)

| Campo | Normalização de `value` |
|---|---|
| `issuer_name` | razão social como no corpo (grafia mista) |
| `cnpj` | `NN.NNN.NNN/NNNN-NN` |
| `isin` | 12 caracteres, maiúsculas |
| `ticker` | maiúsculas |
| `share_class` | `ON` / `PN` |
| `approval_date` | ISO `YYYY-MM-DD`; órgão (`RCA`/`AGE`) em `notes` |
| `record_date` | ISO — data com / data-base |
| `ex_date` | ISO — primeiro dia sem direito / com o evento aplicado |
| `payment_date` | ISO — pagamento em dinheiro |
| `gross_amount_per_share` | string decimal com **todas as casas do documento** (D-007) |
| `net_amount_per_share` | idem |
| `withholding_tax` | `{ "rate": "0.175", "base": "GROSS_AMOUNT" }` — `rate` preserva as casas declaradas ("10%" → `"0.10"`) |
| `currency` | ISO 4217 |
| `ratio` | grupamento `{ "shares_before", "shares_after" }`; bonificação `{ "shares_held", "bonus_shares", "percentage" }` |

### Campos específicos (`event_specific_fields`)

| Campo | Tipos | Significado |
|---|---|---|
| `share_credit_date` | BONUS_SHARES | crédito das ações bonificadas |
| `tax_cost_per_share` | BONUS_SHARES | `{ "amount", "currency" }` — custo fiscal, **não** é valor do provento |
| `fraction_adjustment_period` | REVERSE_SPLIT | `{ "start", "end" }` |

## Convenções

1. **Status de ausência:** `not_found` (o documento não informa); `not_applicable` (não se aplica ao tipo); `declared_pending` (o documento declara pendente — é extração bem-sucedida, D-005). Dado do golden records nunca preenche campo extraído.
2. **Evidência literal:** substring exata do texto após `re.sub(r"\s+", " ", texto).strip()`. Aspas tipográficas e travessão são preservados. No doc 07, a referência é a transcrição.
3. **Números:** strings decimais preservando a precisão declarada; nunca float (D-007).
4. **Dia útil:** seg–sex, sem feriados (D-006).
5. **Checksum ISIN/CNPJ:** fora do gabarito (D-003).

## Regras objetivas (`validation_truth.rules`)

| rule_id | Verifica |
|---|---|
| `REF_ISIN_FOUND` | ISIN do documento existe no golden (match exato) |
| `REF_TICKER_CONSISTENT` | ticker = ticker do golden para esse ISIN |
| `REF_CNPJ_CONSISTENT` | CNPJ = golden |
| `REF_ISSUER_NAME_CONSISTENT` | razão social = golden (sem diferença de caixa/espaços) |
| `REF_SHARE_CLASS_CONSISTENT` | classe = `classe` do golden (`NOT_EVALUATED` se o documento não informa) |
| `REF_ISSUER_ACTIVE` | `status` do golden = `ativo` |
| `REQUIRED_FIELDS_PRESENT` | nenhum campo obrigatório do tipo com status `not_found` |
| `REQUIRED_FIELDS_NOT_PENDING` | nenhum campo obrigatório do tipo com status `declared_pending` |
| `CLASSIFICATION_TITLE_CONSISTENT` | título compatível com o tipo sustentado pelo conteúdo |
| `DATE_APPROVAL_NOT_AFTER_RECORD` | aprovação ≤ data com |
| `DATE_RECORD_BEFORE_EX` | data com < data ex |
| `DATE_EX_NEXT_WEEKDAY_AFTER_RECORD` | data ex = próximo dia seg–sex após a data com |
| `DATE_SETTLEMENT_NOT_BEFORE_EX` | pagamento (ou crédito de ações) ≥ data ex |
| `AMOUNT_GROSS_POSITIVE` | valor bruto > 0 |
| `AMOUNT_NET_MATCHES_GROSS_AND_TAX` | líquido declarado = bruto × (1 − alíquota), comparação Decimal exata (D-007) |
| `RATIO_POSITIVE` | termos da proporção > 0 |
| `RATIO_PERCENTAGE_CONSISTENT` | bonificação: bonus_shares = percentage × shares_held |

Obrigatórios por tipo: todos → `issuer_name`, `isin`, `ticker`, `record_date`, `ex_date`; DIVIDEND/JCP → `gross_amount_per_share`, `currency`, `payment_date`; JCP → `net_amount_per_share`, `withholding_tax`; BONUS_SHARES/REVERSE_SPLIT → `ratio`.

Uma regra é `NOT_EVALUATED` quando falta um dado de que ela depende (ausente, pendente ou sem linha de referência). Isso **nunca** é `FAIL`.

## Códigos de motivo

| reason_code | Quando |
|---|---|
| `REFERENCE_NOT_FOUND` | ISIN sem correspondência no golden records (D-008) |
| `DATE_INCONSISTENCY` | alguma regra `DATE_*` de severidade bloqueante falhou |
| `PAYMENT_DATE_PENDING` | `payment_date` = `declared_pending` (D-005) |
| `CLASSIFICATION_TITLE_CONFLICT` | título contradiz o tipo sustentado pelo conteúdo |
| `NO_USABLE_TEXT_LAYER` | sem camada de texto e sem fallback de extração |
| `LOW_EXTRACTION_CONFIDENCE` | campo crítico sem evidência/confiança suficiente |

## Resumo esperado

| Doc | Tipo | Referência | Regras que falham | Roteamento | Status da expectativa |
|---|---|---|---|---|---|
| 01 | DIVIDEND | TIET3 | — | AUTO_APPROVE | DEFINED |
| 02 | JCP | BMRD4 | — | AUTO_APPROVE | DEFINED |
| 03 | **JCP** | CSPR3 | `CLASSIFICATION_TITLE_CONSISTENT` | REVIEW_REQUIRED | **PROVISIONAL** (Q-10) |
| 04 | JCP | RVBR3 | `REQUIRED_FIELDS_NOT_PENDING` | REVIEW_REQUIRED | DEFINED (D-005) |
| 05 | DIVIDEND | AURS3 | `DATE_SETTLEMENT_NOT_BEFORE_EX` | REVIEW_REQUIRED | DEFINED |
| 06 | REVERSE_SPLIT | PQLT3 | — | AUTO_APPROVE | DEFINED |
| 07 | JCP | TLNR4 | — | — | **POLICY_DEPENDENT** (Q-11) |
| 08 | BONUS_SHARES | não encontrado | `REF_ISIN_FOUND` | REVIEW_REQUIRED | DEFINED (D-008) |

## Pontos não inequívocos

1. **Doc 03 — roteamento provisório (Q-10).** O tipo JCP é definitivo, e DIVIDEND é erro. A classificação pode ter confiança alta; o registro vai para revisão por inconsistência da própria fonte.
2. **Doc 07 — roteamento dependente de política (Q-11).** O conteúdo é válido. Ser escaneado não é motivo de revisão (D-011). A decisão final depende da evidência/confiança que o fallback OCR/visão produzir.
3. **Doc 07 — transcrição humana**, sem verificação possível contra camada de texto.
4. **Doc 06 — mapeamentos funcionais** "Data-base do grupamento" → `record_date` e "Início da negociação grupada" → `ex_date` (rótulos preservados em `source_label`).
5. **Doc 08 — crédito das ações** em `share_credit_date`; `payment_date` = `not_applicable`.
6. **Doc 01 — IR de dividendo condicional** (10% sobre o excedente de R$ 50 mil/mês por beneficiário); líquido `not_applicable`.
7. **Doc 03 — base do IRRF** ("valor bruto") inferida da aritmética da tabela; não é literal no corpo.
8. **Doc 05** — não é determinável qual data está errada; subtipo mantido como declarado.

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 1.0 | 2026-09-29 | Versão inicial |
| 2.0 | 2026-09-29 | Separação em `document_truth` / `validation_truth` / `routing_expectation` (D-009); `source_label` em todos os campos encontrados (D-010); nova regra `REQUIRED_FIELDS_NOT_PENDING`; status das regras em maiúsculas; doc 03 com nota de classificação e roteamento PROVISIONAL; doc 07 POLICY_DEPENDENT (D-011); doc 08 com `REFERENCE_NOT_FOUND` → REVIEW_REQUIRED como DEFINED (D-008) |
