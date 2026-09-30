# Blind Test Set — Avisos de Eventos Corporativos (B3/CVM, fictício)

## Como este conjunto foi criado

Este conjunto foi produzido de forma independente, sem qualquer inspeção do
sistema que será avaliado. Toda a empresa, CNPJ, ISIN, ticker e valor
apresentados nos avisos são fictícios, criados apenas para este teste, sem
correspondência intencional com companhias, códigos ou eventos reais.

Foram criados 14 avisos (`BT-01.txt` a `BT-14.txt`), representando uma
combinação plausível de dividendos, juros sobre capital próprio (JCP),
grupamento, desdobramento e bonificação em ações, com variação de layout
(tabela rótulo/valor, texto corrido, listas com marcadores), de registro
(formal, arcaico, direto) e de formato de datas (numérico com barra, com
ponto, por extenso).

A base de referência (`golden_records.csv`) contém os ativos que aparecem
nos avisos — exceto um caso deliberadamente ausente (ACLA4, caso BT-13) —
mais 4 ativos adicionais que não aparecem em nenhum aviso (SCNO3, VEST4,
TSAZ3, LRNO4), para simular uma base de referência real que não se limita
aos casos de teste.

O gabarito (`ground_truth.json`) foi construído aplicando estritamente as
regras de negócio fornecidas no briefing:
- **AUTO_APPROVE**: aviso completo para o tipo de evento, internamente
  consistente, sem ambiguidade relevante, e ativo presente na base de
  referência.
- **REVIEW_REQUIRED**: falta informação obrigatória, informação obrigatória
  declarada como pendente, ambiguidade real sobre o tipo de evento ou sobre
  um valor/condição que afete o registro financeiro, inconsistência interna,
  ou ativo ausente da base de referência.

Todos os campos `evidence` no gabarito são trechos copiados literalmente do
texto do aviso correspondente (conferidos manualmente, um a um, contra o
arquivo `.txt` de origem). Valores de `gross_amount_per_share`,
`withholding_tax.rate` e `net_amount_per_share` foram checados
aritmeticamente (bruto × (1 − alíquota) = líquido) em todos os casos de JCP
para garantir consistência interna, exceto no caso BT-13, onde a
inconsistência não está na aritmética, e sim na natureza do evento
(dividendo declarado, mas tributado como JCP).

## Lista de casos e intenção de cada um

| Caso | Emissor / Ticker | Tipo de evento | Categorias | Routing esperado | Intenção |
|---|---|---|---|---|---|
| BT-01 | Grão Dourado Alimentos S.A. / GRAO3 | DIVIDEND | clear | AUTO_APPROVE | Caso base limpo, em formato de lista rótulo/valor, todos os campos obrigatórios presentes. |
| BT-02 | Cerâmica Vale Azul S.A. / CVAZ4 | JCP | clear, tax_condition | AUTO_APPROVE | JCP completo com ressalva de isenção para acionistas imunes; a ressalva não compromete o caso geral. |
| BT-03 | Transportes Serra Verde S.A. / TSVE3 | BONUS_SHARES | clear, operational_context | AUTO_APPROVE | Bonificação completa; o procedimento de leilão de frações (com data futura "a informar") é contexto operacional que não é um campo obrigatório do evento. |
| BT-04 | Metalúrgica Rio Bonito S.A. / MRBO4 | REVERSE_SPLIT | clear | AUTO_APPROVE | Grupamento simples e completo, com tratamento de frações como contexto operacional. |
| BT-05 | Companhia Têxtil Nortelândia S.A. / CTNL3 | SPLIT | clear, alternative_language | AUTO_APPROVE | Desdobramento completo, mas redigido em linguagem formal/arcaica e com datas por extenso, testando robustez de extração textual. |
| BT-06 | Papel e Celulose Araucária S.A. / PCEL3 | DIVIDEND | missing_info | REVIEW_REQUIRED | Falta a data de pagamento — nunca mencionada no texto (diferente de "pendente"). |
| BT-07 | Energia Solar Cerrado S.A. / ESOL3 | JCP | pending_info | REVIEW_REQUIRED | Data de pagamento explicitamente declarada como "a ser definida". |
| BT-08 | Banco Nortecred S.A. / BNCR4 | OTHER (negação) | negation | REVIEW_REQUIRED | Aviso de retificação que revoga uma distribuição de dividendos anteriormente anunciada; exige reconciliação humana com o aviso original. |
| BT-09 | Mineração Serra Alta S.A. / MSAL3 | JCP | clear, tax_condition | AUTO_APPROVE | JCP completo com alíquota diferenciada (25%) para acionistas em países de tributação favorecida, totalmente quantificada — condição tributária que não gera ambiguidade. |
| BT-10 | Construtora Horizonte Azul S.A. / CHAZ3 | BONUS_SHARES | clear, exception, operational_context | AUTO_APPROVE | Bonificação completa com exceção padrão (ações em tesouraria não recebem) — exceção de boilerplate que não altera o evento para os demais acionistas. |
| BT-11 | Laticínios Vale do Sol S.A. / LVSO3 | DIVIDEND | clear, varied_dates | AUTO_APPROVE | Dividendo completo com datas em três formatos diferentes (extenso, barra, ponto) no mesmo aviso. |
| BT-12 | Farmacêutica Novavida S.A. / FNVD4 | JCP | clear, operational_context | AUTO_APPROVE | JCP completo com extenso contexto operacional (telefone, site, instruções de cadastro) que não altera o evento. |
| BT-13 | Agropecuária Campo Largo S.A. / ACLA4 | UNRESOLVED | ambiguous, missing_info | REVIEW_REQUIRED | Caso ambíguo por natureza: o aviso chama o evento de "dividendos", mas aplica retenção de IR de 15% e calcula valor líquido — característica de JCP, não de dividendo (isento). Além disso, ISIN não informado e ativo ausente da base de referência. Caso desenhado para exigir revisão humana genuína, não uma "pegadinha". |
| BT-14 | Distribuidora Águas Claras S.A. / DAGC3 | DIVIDEND | internal_inconsistency | REVIEW_REQUIRED | Todos os campos obrigatórios presentes, mas a data de pagamento (29/09/2026) é anterior à data ex (03/10/2026) — sequência cronológica internamente inconsistente. |

**Distribuição por tipo de evento:** DIVIDEND (4), JCP (4), BONUS_SHARES (2),
REVERSE_SPLIT (1), SPLIT (1), OTHER (1), UNRESOLVED (1).

**Distribuição por routing esperado:** AUTO_APPROVE (9), REVIEW_REQUIRED (5).

## Declaração de independência

- Nenhum arquivo ou diretório pré-existente no computador foi lido, listado,
  pesquisado, aberto ou executado. Não foram usadas ferramentas de
  inspeção de disco (Read, Glob, Grep, ls, cat, find, git, etc.) sobre
  nada além dos arquivos que eu mesmo criei neste diretório de saída.
- Nenhuma tentativa foi feita de descobrir como o sistema avaliado
  funciona internamente. Todo o conteúdo foi produzido a partir do
  briefing fornecido e de conhecimento geral de domínio (avisos de
  companhias abertas brasileiras, padrão B3/CVM).
- **Ferramenta utilizada:** exclusivamente a ferramenta de escrita de
  arquivos (Write), para criar os arquivos listados abaixo dentro do
  diretório de saída designado. Nenhuma outra ferramenta (leitura,
  busca, execução de comandos, navegação web, etc.) foi utilizada nesta
  tarefa.

## Arquivos criados

- `BT-01.txt` a `BT-14.txt` (14 avisos)
- `golden_records.csv`
- `ground_truth.json`
- `README.md` (este arquivo)
