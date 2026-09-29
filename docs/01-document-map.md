# 01 — Mapa dos documentos

Análise individual de cada documento em `case/Case AI Dev - Envio/documents/`.
Método: leitura da camada de texto nativa via `pypdf` (docs 01–06, 08) e inspeção visual da imagem extraída (doc 07). Checagens exploratórias (dia da semana, dígito verificador, bruto × líquido) feitas com scripts descartáveis fora do repositório — registradas em `04-evaluation-log.md` como E-000.

> Regra: o tipo de evento é inferido do **conteúdo**, não do título nem do nome do arquivo.
> Os nomes dos arquivos contêm pistas (`_sem_data`, `_datas`, `_SCAN`) que **não** devem ser usadas pelo pipeline.

---

## 1. Proveniência do material

Origem: `C:\Users\Windows 11\Downloads\Case_AI_Dev_-_Envio.zip` (SHA-256 `82a506e7…73c3`), extraído sem modificação para `case/` em 2026-09-29. Timestamps internos do zip: 2026-06-18.

| Arquivo | SHA-256 |
|---|---|
| documents/01_energetica_vale_tiete_dividendo.pdf | `e49afdf81d2a1e4a74985e78fa0ea3639633cfa19f5dba633a2b545d115153cb` |
| documents/02_banco_meridional_jcp.pdf | `64e0787afd32c0d99e5407a5fbc6f5048245ba70826563d0b14205074b970668` |
| documents/03_siderurgica_paranaense_proventos.pdf | `a21a294ac3ededbb6fdef195be0edb0572069544e0b73f6fc1918fa77d6b0e85` |
| documents/04_rede_varejo_jcp_sem_data.pdf | `37f846a73cb5486b543bb1e580144c8d94eafee4aa7396424637c063a3bfbb83` |
| documents/05_aurora_saneamento_dividendo_datas.pdf | `925b6eb09fbcaecf81d3c1d125e041edd1460fed23d6a67bf10f8a6b170e9567` |
| documents/06_petroquimica_litoral_grupamento.pdf | `147d83f038f6ca94495a5d5248f36a6feedee7ae9a5cebc011d40e1f14d68068` |
| documents/07_telecom_norte_jcp_SCAN.pdf | `cf4af08dd23f507ae72b852d86827bbee6c3fe2d0e31f96e70bc74ea4238c45f` |
| documents/08_construtora_horizonte_bonificacao.pdf | `a509637f4b258454309e1d21e81beca56701a78624b8a6a6f9a6b0ec9389b0e5` |
| enunciado/Enunciado - Case AI Dev.md | `ab5c9aa087aa7ff3ccf9b7e4c337ee61bbdfe45216f6524329e8ada5c2d0dc6c` |
| golden_records/golden records.csv | `6ce677a6849febc4d3ccc02b4430e14ad50c415639017f159abb6219e6584f33` |

## 2. Características físicas

| Doc | Páginas | Produtor | Camada de texto | Imagens | Tamanho |
|---|---|---|---|---|---|
| 01–06, 08 | 1 | ReportLab | Sim (fontes F1/F2) | Nenhuma | ~3 KB |
| 07 | 1 | desconhecido | **Não** (0 caracteres) | 1 JPEG 1654×2339 RGB (DCTDecode) | 213 KB |

Famílias de layout:
- **Template A (docs 01–06, 08):** cabeçalho (razão social, CNPJ, NIRE) → título "AVISO AOS ACIONISTAS — …" → 2–3 parágrafos → tabela rótulo/valor → local e data → assinatura do DRI. Na extração de texto, rótulos longos quebram em duas linhas (ex.: "Valor bruto por ação ordinária\n(ON)").
- **Template B (doc 07):** escaneado; mesma estrutura lógica, mas a tabela é substituída por linhas "Rótulo ........ valor" com pontilhados de preenchimento; imagem com leve inclinação e ruído de fundo.

## 3. Tabela-resumo

| Doc | Tipo aparente (pelo conteúdo) | Nativo / Scan | Campos importantes presentes | Campos ausentes | Inconsistências | Validações determinísticas prováveis | OCR / visão? | Ambiguidade semântica | Relação com golden | Modo de falha provável |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 Energética Vale do Tietê | Dividendo | Nativo | emissor, CNPJ, ISIN, ticker, classe ON, aprovação 28/05, data com 12/06, ex 15/06, pgto 03/07, bruto R$ 0,4275000000 | valor líquido (não aplicável: IR depende do beneficiário) | Nenhuma | ordem das datas; ex = próximo dia útil após data com; lookup ISIN/ticker/CNPJ/classe | Não | Baixa. Texto tributário (10% acima de R$ 50 mil/mês) pode induzir a calcular um "líquido" inexistente | Match exato (TIET3) | Inventar valor líquido; tratar texto de IR como alíquota fixa |
| 02 Banco Meridional | JCP | Nativo | emissor, CNPJ, ISIN, ticker, classe PN, aprovação 02/06 (**só no corpo**), data com 16/06, ex 17/06, pgto 14/08, bruto 0,1738420000, IRRF 17,5%, líquido 0,1434196500 | — | Nenhuma (líquido = bruto × 0,825 exato) | bruto × (1 − IRRF) = líquido; ordem das datas; lookup | Não | Baixa, mas contém "imputado aos dividendos obrigatórios" | Match exato (BMRD4) | Classificador por palavra-chave "dividendo"; perder data de aprovação por estar só no corpo |
| 03 Siderúrgica Paranaense | **JCP** (título diz "Dividendos") | Nativo | emissor, CNPJ, ISIN, ticker, ON, aprovação 05/06 (corpo), data com 19/06, ex 22/06, pgto 11/09, bruto 0,0921500000, IRRF 17,5%, líquido 0,0760237500 | Nenhum; a sigla "JCP" nunca aparece | **Título × conteúdo**: título "Distribuição de Dividendos"; corpo descreve remuneração do capital próprio limitada à TJLP, IRRF 17,5%; tabela "Natureza do provento (conforme corpo do aviso): Remuneração do capital próprio" | bruto × 0,825 = líquido (exato); ordem das datas; lookup | Não | **Alta — é o caso de classificação do lote.** Exige interpretação semântica (sinônimo de JCP sem a sigla) e resolver conflito título × corpo | Match exato (CSPR3) | Classificar como dividendo pelo título → tratamento tributário errado |
| 04 Rede Varejo | JCP | Nativo | emissor, CNPJ, ISIN, ticker, ON, aprovação 09/06 (corpo), data com 23/06, ex 24/06, bruto 0,2050000000, IRRF 17,5%, líquido 0,1691250000 | **Data de pagamento: "A definir (vide aviso complementar)"** | Nenhuma nos valores presentes | bruto × 0,825 = líquido; ordem das datas presentes; pagamento ausente = `declared_pending` | Não | Baixa. Ambiguidade é de política (pendente vs revisão), não de leitura | Match exato (RVBR3) | Inventar data de pagamento; ou tratar "A definir" como falha de extração |
| 05 Aurora Saneamento | Dividendo (intercalar) | Nativo | emissor, CNPJ, ISIN, ticker, ON, aprovação 01/06, data com 15/07, ex 16/07, pgto 10/07, bruto 0,3100000000 | valor líquido (não aplicável) | **Pagamento (10/07) anterior à data com (15/07) e à ex (16/07)** — o corpo reforça que o crédito ocorre "na data de pagamento indicada abaixo" | ordem: pagamento ≥ ex → **falha** | Não | Média: não é possível saber qual data está errada. Subtipo "intercalares à conta de reservas de lucros" (tecnicamente soa como "intermediários") | Match exato (AURS3) | Corrigir silenciosamente uma das datas; ou aprovar sem checar ordem |
| 06 Petroquímica Litoral | Grupamento (inplit) | Nativo | emissor, CNPJ, ISIN, ticker, aprovação AGE 30/05 (corpo), data-base 26/06, negociação grupada 29/06, período de frações 29/06–28/07, proporção 10:1 | valor, moeda, data com/ex/pagamento no sentido de provento (não aplicáveis) | Nenhuma. Obs.: AGE num **sábado** (30/05/2026) — incomum, não inválido | proporção (10 antigas → 1 nova); data-base < início negociação; período de frações coerente | Não | Terminologia: "inplit" = grupamento; não confundir com desdobramento (split). Classe (ON) não citada na tabela | Match exato (PQLT3) | Inverter proporção; forçar valor/moeda; mapear "data-base do grupamento" como "data com" sem registrar a semântica |
| 07 Telecom Norte | JCP | **Scan** | (leitura visual) emissor, CNPJ, ISIN BRTLNRACNPR2, ticker TLNR4, PN, aprovação 06/06 (corpo), data com 22/06, ex 23/06, pgto 21/08, bruto 0,1124300000, IRRF 17,5%, líquido 0,0927547500 | Nenhum aparente | Nenhuma nos valores lidos (bruto × 0,825 = líquido exato). Obs.: RCA num **sábado** (06/06/2026) | Mesmas do JCP; a identidade bruto/líquido funciona como **checksum da leitura** | **Sim** — sem camada de texto | Baixa semanticamente; risco é de **leitura**: pontilhados ",,,,,,,," colados aos valores, inclinação, ruído | Match exato (TLNR4), se lido corretamente | Dígito/casa decimal lido errado; vírgula de pontilhado virar separador decimal |
| 08 Construtora Horizonte | Bonificação em ações | Nativo | emissor, CNPJ 09.888.999/0001-21, ISIN BRCNHZACNOR5, ticker CNHZ3, aprovação AGE 04/06 (corpo), data com 18/06, ex 19/06, crédito das ações 26/06, proporção 1 nova : 20 existentes (5%), custo atribuído R$ 7,820000/ação | Classe da ação não citada; valor de provento em dinheiro (não aplicável) | **Emissor/ISIN/ticker ausentes do golden records.** Obs.: AGE em 04/06/2026 (Corpus Christi, sem pregão na B3) | 1/20 = 5% (checagem interna da proporção); ordem das datas; lookup → **não encontrado** | Não | Média: "R$ 7,82" é custo fiscal, não valor do evento | **Não encontrado** | Aprovar sem validação de referência; fuzzy match com outro emissor; tratar R$ 7,82 como valor de provento |

## 4. Observações transversais

### 4.1 Golden records
- 12 emissores; 7 correspondem exatamente (ISIN, ticker, CNPJ e razão social) aos docs 01–07.
- Doc 08 não tem correspondência por nenhuma chave (ISIN, ticker, CNPJ).
- 5 emissores são distratores (AGCR3, LGAT3, SGPM4, MSAZ3, AGPL3).
- A coluna `classe` confere com o sufixo do ticker (3 = ON, 4 = PN) e com a classe citada nos avisos que a citam.
- A coluna `status` é sempre `ativo`, então não conseguimos testar o comportamento para emissor inativo com este lote.
- **Dígitos verificadores:** algoritmo ISIN (Luhn) validado com ISINs reais (US0378331005, BRPETRACNPR6, BRVALEACNOR0, BRITUBACNPR1). Mesmo assim, 10/12 ISINs do golden e o ISIN do doc 08 **falham**; 10/12 CNPJs do golden falham no DV. Isso é coerente com "ISINs e CNPJs fictícios". Consequência: validação de DV não pode ser bloqueante neste lote (ver H-12).

### 4.2 Datas
- Em todos os proventos, ex = próximo dia útil após a data com (sex→seg, ter→qua etc.).
- Datas de aprovação às vezes estão na tabela (01, 05) e às vezes **só no corpo por extenso** (02, 03, 04, 06, 07, 08).
- Datas de assembleia/reunião em sábado (06, 07) e feriado B3 (08) — informativo, não erro.

### 4.3 Valores
- JCP (02, 03, 04, 07): líquido = bruto × (1 − 0,175) **exato** em Decimal nos 4 casos.
- Dividendo (01, 05): só valor bruto; líquido não se aplica no nível do emissor.
- Valores com 10 casas decimais; separador decimal vírgula; prefixo "R$".
- Eventos não-caixa (06, 08): proporção em vez de valor. Doc 08 tem valor monetário **auxiliar** (custo atribuído).

### 4.4 Vocabulário heterogêneo para o mesmo conceito
- Data com: "data-base / 'data com'", "posição acionária final do dia", "inscritos nos registros … ao final do dia", "detentores de ações ao final do pregão", "data-base do grupamento".
- Data ex: "ex-dividendos", "ex-JCP", "ex", "ex-bonificação", "negociadas já grupadas".
- JCP: "Juros sobre o Capital Próprio (JCP)", "remuneração do capital próprio", "art. 9º da Lei nº 9.249/95".
- Órgão de aprovação: RCA (Conselho de Administração) vs AGE (Assembleia Geral Extraordinária).

### 4.5 Distinções que definem o tipo de evento [INTERPRETAÇÃO]
| Tipo | Sinais no conteúdo | Tratamento |
|---|---|---|
| Dividendo | "dividendos", resultado/lucro do exercício, reservas de lucros; sem alíquota fixa na fonte (2026: 10% acima de R$ 50 mil/mês por beneficiário) | Caixa; valor bruto por ação; IR dependente do beneficiário |
| JCP | "juros sobre o capital próprio", "remuneração do capital próprio", Lei 9.249/95, TJLP, IRRF 17,5% na fonte, bruto + líquido | Caixa; bruto e líquido por ação; IRRF retido na fonte (exceto imunes/isentos). "Imputado ao dividendo obrigatório" **não** o torna dividendo |
| Bonificação | capitalização de reservas, "ações novas", proporção, custo atribuído | Ações; proporção; custo fiscal; frações em leilão |
| Grupamento (inplit) | "grupamento", N ações → 1, sem mudança do capital | Ações; fator de conversão; frações; não-caixa |
