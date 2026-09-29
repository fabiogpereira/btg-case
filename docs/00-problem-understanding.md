# 00 — Entendimento do problema

Legenda: **[FATO]** vem do material do case · **[INTERPRETAÇÃO]** nossa leitura · **[HIPÓTESE]** ainda não testada.
Fonte: `case/Case AI Dev - Envio/enunciado/Enunciado - Case AI Dev.md` (citado como "enunciado").

---

## 1. Problema de negócio

**[FATO]** Asset Servicing recebe avisos de eventos corporativos (proventos, grupamentos, bonificações) em formatos heterogêneos: PDFs nativos, escaneados, com layouts e terminologia variados. Esses avisos precisam virar registros estruturados, confiáveis e auditáveis para alimentar processos downstream: cálculo de provento, custódia, conciliação e base regulatória.

**[FATO]** "Erros de extração são erros financeiros e regulatórios": classificar errado o tipo de provento muda o tratamento tributário; datas incoerentes quebram conciliações; valores inventados viram prejuízo.

**[INTERPRETAÇÃO]** O problema central não é "extrair texto de PDF". É **decidir, para cada aviso, se o registro gerado é confiável o suficiente para seguir automaticamente para downstream, e quando não for, dizer exatamente o quê, por quê e com qual evidência** para que um operador resolva sem reabrir o documento. A extração é meio; a decisão confiável e auditável é o produto.

**[INTERPRETAÇÃO]** O custo assimétrico domina o desenho: um registro errado que segue automaticamente é muito mais caro do que um registro correto enviado para revisão. Mas enviar tudo para revisão elimina o valor da automação. O sistema precisa ser **preciso no que aprova** e **específico no que escala**.

## 2. Inputs esperados

**[FATO]**
| Input | Conteúdo observado |
|---|---|
| `documents/` (enunciado chama de `documentos/`) | 8 PDFs de 1 página cada. 7 com camada de texto nativa (gerados por ReportLab), 1 escaneado (imagem JPEG, sem camada de texto): `07_telecom_norte_jcp_SCAN.pdf`. |
| `golden_records/golden records.csv` (enunciado chama de `golden_records.csv`) | 12 linhas, colunas `emissor, cnpj, isin, ticker, classe, segmento_listagem, status`. Todas com `status = ativo`. |

**[FATO]** O lote é sintético, "modelado em avisos reais de companhias abertas brasileiras (estrutura, terminologia e datas no padrão B3/CVM)". Nomes, CNPJs e ISINs são fictícios.

**[INTERPRETAÇÃO]** O lote é pequeno e de layout quase uniforme (7 dos 8 compartilham o mesmo template ReportLab). O enunciado, porém, descreve o problema real como heterogêneo. Uma solução que funcione só por causa da uniformidade deste lote (ex.: regex ajustado ao template) estará sobreajustada. A sessão ao vivo ("estender e depurar o próprio código") provavelmente testará generalização.

## 3. Outputs esperados

**[FATO]** Entregáveis:
- repositório com código e instruções de execução no README;
- README com decisões de arquitetura, **incluindo explicitamente o que decidimos não fazer e por quê** (trade-offs);
- saída gerada sobre o lote: **um JSON por documento + um relatório de exceções curto**.

**[FATO]** Conteúdo mínimo por registro:
- o que foi extraído **e de onde**;
- quão confiável é **cada campo**;
- o resultado da validação contra a base de referência;
- o que precisa de revisão humana **e por quê**.

**[FATO]** O schema é decisão nossa; "como você estrutura isso — e o que decide incluir além disso — será parte da avaliação".

**[FATO]** A saída deve permitir que o operador confie no registro e **audite cada valor sem reabrir o documento**, "inclusive quando o aviso está incompleto, ambíguo ou pouco legível".

**[INTERPRETAÇÃO]** "Sem reabrir o documento" implica que cada campo precisa carregar sua **evidência** (trecho literal de origem + localização), não só o valor normalizado.

## 4. Requisitos explícitos

| ID | Requisito [FATO] |
|---|---|
| R1 | Extrair: emissor, ISIN, ticker, tipo de evento, datas relevantes (aprovação, data com, ex, pagamento, "conforme o caso"), valor/proporção e moeda. |
| R2 | Classificar corretamente o tipo de evento (dividendo, JCP, bonificação, grupamento etc.) — "atenção ao que distingue um do outro e ao tratamento que cada tipo exige". |
| R3 | Validar cada registro contra `golden_records.csv` e contra regras de coerência (ex.: consistência entre datas, entre valor bruto e líquido), **usando tool / function calling**. |
| R4 | Atribuir níveis de confiança às extrações, **justificando-os**. |
| R5 | Rotear documentos ou campos de baixa confiança para atuação humana, com **decisão justificada**. |
| R6 | Saída: 1 JSON por documento + relatório de exceções curto (conteúdo mínimo na seção 3). |
| R7 | Construir "um agente **code-first**". Arquitetura, bibliotecas, desenho de tools e provider de LLM são livres. |
| R8 | Documentar premissas assumidas (ex.: o que é "baixa confiança", quais regras de coerência aplicar) — "parte do que avaliamos é seu critério". |
| R9 | README com decisões e trade-offs, incluindo o que **não** foi feito. |
| R10 | Estar preparado para estender e depurar o código ao vivo (45 min). |

## 5. Riscos implícitos [INTERPRETAÇÃO]

Identificados a partir do material (ver evidências em `01-document-map.md`):

1. **Classificação pelo título, não pelo conteúdo.** Doc 03 tem título "Distribuição de Dividendos", mas o conteúdo descreve JCP (remuneração do capital próprio, limite TJLP, IRRF 17,5%, valor líquido).
2. **Armadilha lexical.** Avisos de JCP contêm a palavra "dividendo" ("imputado aos dividendos obrigatórios" — docs 02 e 03). Classificação por palavra-chave ingênua erra.
3. **Valor inventado para campo ausente.** Doc 04 declara pagamento "A definir". Um LLM ou um schema com campo obrigatório tende a preencher algo.
4. **Correção silenciosa de incoerência.** Doc 05 tem pagamento (10/07) **antes** da data com (15/07) e da data ex (16/07). Não sabemos qual data está errada; "consertar" seria inventar.
5. **Emissor fora da base de referência.** Doc 08 (Construtora Horizonte, CNHZ3) não existe no golden records. Risco de fuzzy match com um emissor parecido ou de aprovar sem validação.
6. **Distratores na base de referência.** 5 dos 12 emissores do golden não aparecem em nenhum documento. Matching aproximado pode gerar falso positivo.
7. **Confusão de "valor" em eventos não-caixa.** Doc 08 contém "R$ 7,82" (custo atribuído para fins fiscais), que **não** é valor de provento. Doc 06 (grupamento) não tem valor monetário nem moeda.
8. **Direção da proporção.** Grupamento "10:1" (10 antigas → 1 nova) e bonificação "1 nova para cada 20" têm direções opostas de efeito. Representar como string ambígua ("10:1") é arriscado.
9. **Erro de leitura em documento escaneado.** Doc 07 é imagem ruidosa, levemente inclinada, com pontilhados de preenchimento (",,,,,,,,") colados aos valores. Dígito ou casa decimal lidos errado viram valor financeiro errado.
10. **Precisão numérica.** Valores com 10 casas decimais (ex.: R$ 0,1434196500). `float` introduz erro; separador decimal brasileiro (vírgula) pode ser mal interpretado.
11. **Formato de data.** dd/mm/aaaa vs mm/dd; datas também aparecem por extenso no corpo ("28 de maio de 2026").
12. **Confiança autodeclarada por LLM** tende a ser alta e mal calibrada; usá-la como sinal principal daria falsa segurança.
13. **Validador formalmente correto que gera falso alarme.** Os dígitos verificadores de ISIN falham em 10 dos 12 ISINs do golden (e no ISIN do doc 08); os de CNPJ falham em 10 dos 12. Coerente com "ISINs e CNPJs fictícios". Uma validação de check digit bloqueante rejeitaria quase tudo.
14. **Vazamento de pista pelo nome do arquivo.** `_sem_data`, `_datas`, `_SCAN`, `_proventos` antecipam o problema de cada doc. Não existe em produção; não pode ser usado como sinal.
15. **Subtipo jurídico ambíguo.** Doc 05: "dividendos intercalares à conta de reservas de lucros". Pela Lei 6.404/76 (art. 204), dividendos à conta de reservas de lucros costumam ser chamados de "intermediários"; "intercalares" referem-se a balanço de período menor. **[INTERPRETAÇÃO a confirmar]** Não muda o tipo (dividendo) nem o tratamento tributário, mas não devemos "corrigir" o subtipo declarado.

## 6. Consequências financeiras/regulatórias de erros [INTERPRETAÇÃO]

| Erro | Consequência provável |
|---|---|
| JCP classificado como dividendo (ou vice-versa) | Tratamento tributário errado: JCP tem IRRF de 17,5% retido na fonte (conforme docs 02, 03, 04, 07); dividendo, pelos avisos de 2026, tem IRRF de 10% só sobre o que excede R$ 50 mil/mês por beneficiário (doc 01). Retenção indevida/ausente, informe de rendimentos errado, exposição fiscal do custodiante. |
| Valor por ação errado (dígito/casa decimal) | Crédito errado em massa para todos os cotistas/clientes; prejuízo ou reprocessamento e estorno. |
| Valor inventado | Pagamento sem lastro; prejuízo direto. |
| Data com/ex errada | Elegibilidade errada (quem recebe), quebra de conciliação com a B3/depositária. |
| Data de pagamento errada ou inventada | Crédito na data errada; conciliação de caixa quebrada. |
| Emissor/ISIN errado | Evento aplicado ao ativo errado — o pior caso, afeta posições de terceiros. |
| Proporção invertida (grupamento/bonificação) | Posição em custódia errada por fator de 10× ou 20×; fração e leilão calculados errados. |
| Custo atribuído confundido com valor | Base fiscal das ações bonificadas errada; ou crédito em dinheiro inexistente. |
| Registro correto mas sem trilha de auditoria | Não defensável perante auditoria/regulador mesmo quando certo. |

## 7. Requisitos ambíguos

| ID | Ambiguidade | Por que importa |
|---|---|---|
| A1 | "usando **tool / function calling**" (R3): o LLM deve orquestrar e chamar os validadores, ou basta que as validações sejam implementadas como tools/funções chamadas pelo código? | Define se há um loop agêntico. Impacta determinismo, custo e auditabilidade. Ver Q-01. |
| A2 | "agente code-first" (R7): quanto de autonomia o avaliador espera de um "agente"? | Um pipeline determinístico com uma etapa LLM pode ou não ser lido como "agente". |
| A3 | "Datas relevantes ... conforme o caso": quais datas por tipo de evento? | Grupamento tem "data-base" e "início da negociação grupada" e "período de frações", não "pagamento". Bonificação tem "crédito das ações". |
| A4 | "valor/proporção e moeda" para eventos não-caixa. | Moeda em grupamento é `not_applicable`, não `not_found`. Bonificação tem proporção **e** custo atribuído em R$. |
| A5 | "baixa confiança" — critério livre (R8 pede documentar). | Precisamos de definição explícita e defensável. |
| A6 | "consistência entre valor bruto e líquido" — dividendos de 2026 não têm líquido por ação no aviso (IR depende do beneficiário). | A regra só se aplica quando ambos existem e há alíquota fixa declarada. |
| A7 | "níveis de confiança" — categórico (alto/médio/baixo) ou numérico? | Numérico sugere uma precisão/calibração que não temos com 8 docs. |
| A8 | Validação "contra a base de referência" — só ISIN/ticker ou também CNPJ, razão social e classe? | O golden tem `cnpj` e `classe`; ambos aparecem nos avisos e permitem checagem cruzada. |
| A9 | Emissor ausente do golden (doc 08): rejeitar, revisar ou aprovar com ressalva? | Decisão de negócio; nossa leitura é revisão humana. |
| A10 | Registro com data incoerente (doc 05): gerar JSON com os valores como no documento + exceção, ou não gerar? | Enunciado pede JSON "para cada documento" → nossa leitura: sempre gerar, com status. |
| A11 | "relatório de exceções curto": formato (MD, CSV, JSON)? para quem? | Nossa leitura: operador de Asset Servicing. |
| A12 | Pagamento "A definir" (doc 04): é exceção para revisão humana, ou registro válido "pendente de aviso complementar"? | Não é erro do documento nem da extração; é informação legitimamente ausente. |

## 8. Critérios de sucesso

**[FATO]** O avaliador observa: extração correta (R1), classificação correta (R2), validação com tools (R3), confiança justificada (R4), roteamento justificado (R5), saída auditável (R6), critério nas premissas (R8), trade-offs no README (R9), capacidade de estender/depurar ao vivo (R10).

**[INTERPRETAÇÃO]** Critérios mensuráveis que proporemos (a validar com o usuário):
1. 8/8 documentos geram JSON válido contra o schema, inclusive os problemáticos.
2. **Zero valores inventados**: todo valor preenchido tem evidência literal localizável na fonte.
3. Classificação 8/8, incluindo doc 03 como JCP.
4. Os casos com problema real (04, 05, 08 e possivelmente 07) são sinalizados com **motivo específico**; os casos limpos não são enviados para revisão sem motivo.
5. Nenhuma inconsistência corrigida silenciosamente.
6. Cada run é reprodutível e reconstruível pelo manifest (`run_id`, versões, hashes, métodos, validadores).
7. Execução com um comando, documentada no README; custo por documento medido.
8. Resultados comparados contra um gabarito manual dos 8 documentos (a construir) — sem isso não há como afirmar que uma mudança melhorou.

## 9. Perguntas em aberto

| ID | Pergunta | Status |
|---|---|---|
| Q-01 | Como interpretar "usando tool / function calling"? (A1) | **Resolvida → D-002** (híbrido: LLM usa ao menos uma tool de referência; orchestrator executa todas as validações obrigatórias) |
| Q-02 | O material em `case/` é a versão correta e completa? | **Resolvida → D-000** (confirmado pelo usuário) |
| Q-03 | Qual provider/modelo de LLM usar? API key? Restrição de custo? | **Adiada deliberadamente** |
| Q-04 | Qual o prazo real ("até segunda-feira")? | Aberta |
| Q-05 | Doc 04 (pagamento "A definir"): revisão ou pendência? (A12) | **Resolvida → D-005** (`declared_pending`; extração bem-sucedida; registro exige revisão) |
| Q-06 | Emissor fora do golden (doc 08): política? (A9) | **Resolvida → D-008** (`REFERENCE_NOT_FOUND` → `REVIEW_REQUIRED`, nunca `REJECT`) |
| Q-07 | Podemos instalar dependências locais (ex.: Tesseract)? | Aberta (ligada a Q-09) |
| Q-08 | Calendário B3 ou apenas dias da semana? | **Resolvida → D-006** (apenas seg–sex no baseline) |
| Q-09 | Escaneado: OCR local, visão de LLM ou ambos? | **Adiada deliberadamente** (H-02b) |
| Q-10 | Doc 03: conflito título × corpo com classificação corroborada vai para revisão ou é aprovado com alerta? (OD-08) | Aberta — `REVIEW_REQUIRED` **provisório**; tipo JCP é definitivo |
| Q-11 | Doc escaneado sem nenhuma falha de conteúdo: aprovar automaticamente ou sempre revisar? | Aberta — `POLICY_DEPENDENT`; ser scan não é motivo de revisão (D-011) |
