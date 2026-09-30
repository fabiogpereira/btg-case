# BT-002 — revisão de qualidade do dataset (antes do pipeline)

A revisão pôde corrigir **erros do dataset**. Não pôde mudar casos por parecerem fáceis ou difíceis para a F. Nenhum documento foi processado pela F antes do congelamento.

## Verificações

| Verificação | Método | Resultado |
|---|---|---|
| Arquivos abrem (UTF-8) | `creator/qa.py` + leitura manual dos 10 avisos | OK |
| Gabarito corresponde ao conteúdo | leitura manual, campo a campo | OK |
| Evidências literais | `evidence` de campos, qualificadores e contexto ⊂ texto do aviso | OK (todas literais, sem normalização) |
| Identificadores do gabarito no aviso | CNPJ e ticker presentes no texto | OK. Nenhum aviso traz ISIN; `isin: null` no gabarito é fiel ao documento |
| Aritmética | bruto × (1 − alíquota) = líquido | OK (BT2-02: 0,30 × 0,85 = 0,255) |
| Datas | ISO válidas; ordem aprovação ≤ data-base < ex ≤ liquidação; dia da semana | OK |
| Base de referência | cabeçalho; ISIN/ticker/classe coerentes; sem duplicidade de ISIN/ticker | OK. CNPJ repetido só entre ON e PN da mesma companhia (legítimo) |
| Ativo fora da base | `in_reference_base` × base | Coerente: só BT2-10 (AVCP3) fora, escolha do criador |
| Roteamento esperado justificado | `routing_reason` presente e coerente com o critério de negócio | OK |

## Correção feita (1)

**CNPJs colidiam com conjuntos anteriores.**
- **Problema:** os 11 CNPJs do conjunto eram placeholders sequenciais ("12.345.678/0001-90", "23.456.789/0001-01", …) idênticos a CNPJs do dataset original e/ou do blind set v1, lá associados a outras empresas. Isso viola o requisito de "identificadores fictícios diferentes dos datasets anteriores".
- **Correção:** substituição mecânica 1:1 por CNPJs novos (gerador pseudoaleatório com semente fixa `BT-002-cnpj-remap`; verificados como ausentes de `case/`, `tests/` e `docs/`), aplicada igualmente aos avisos, à base e ao gabarito.
- **Registro:** mapeamento e contagens em `creator/cnpj_mapping.json`. A resposta original do criador está intacta em `creator/response_raw.txt`.
- **Efeito sobre a dificuldade:** nenhum. Mesmo formato, mesma posição, mesma associação ON/PN.
- Razões sociais, ISINs e tickers não colidiam; não foram tocados.

## Observado e NÃO corrigido (julgamento do criador ou traço genuíno do documento)

1. **BT2-03 — procedimento de frações rotulado como qualificador material (`affects: other`) num caso com AUTO_APPROVE esperado.**
   - Há uma tensão interna: o próprio anexo define material como "mudaria algum elemento do registro financeiro", e a razão do roteamento não menciona frações.
   - Não corrigido: reclassificar a materialidade usaria o entendimento prévio do projeto (debate do doc 06 / BT-10), e materialidade é justamente o julgamento que o teste mede.
   - **Pré-registro:** o resultado é computado como rotulado. Se esse item sozinho decidir o GO/STOP, a decisão é sinalizada para o usuário, não tomada pelo orquestrador.
2. **BT2-05 — data ex 02/05/2024** (a data-base é terça, 30/04; 01/05 é feriado nacional). A F não tem calendário B3 (D-006). Traço genuíno do documento.
3. **Nenhum aviso traz ISIN.** Identificação só por ticker e CNPJ. Traço genuíno do conjunto.
4. **BT2-09 — `approval_date` marcado como pending** ("deliberação final … na mesma data de pagamento"). É uma leitura do criador e é fiel ao texto.
