# 02 — Hipóteses

Status possíveis: `UNTESTED` · `TESTING` · `CONFIRMED` · `REJECTED` · `MODIFIED`.
Uma hipótese só vira decisão em `DECISIONS.md` depois de testada e registrada em `04-evaluation-log.md`.

Pré-requisito para quase todas: **gabarito manual** (expected output) dos 8 documentos, construído por leitura humana e revisado pelo usuário. Sem ele, "melhorou" não é mensurável.

Algumas hipóteses têm **evidência exploratória** (E-000, sem experimento formal). Ela está anotada em "Notas" e não muda o status.

---

## A. Ingestão e extração de texto

### H-01 — Extração de texto nativo antes de OCR
- **Hypothesis:** Para PDFs com camada de texto, a extração nativa (pypdf) produz texto completo e fiel, sem OCR.
- **Why it matters:** OCR adiciona custo, latência, dependência e erro de leitura onde não é necessário.
- **How to test:** Extrair texto dos 8 docs; comparar com o gabarito (todos os valores do gabarito aparecem literalmente no texto?).
- **Expected signal:** 7/7 nativos com 100% dos valores presentes literalmente; doc 07 com ~0 caracteres.
- **Observed result:** (E-002) 7/7 documentos nativos com texto completo; todos os trechos de evidência do gabarito são literais no texto do pypdf (E-001); 76/80 valores extraídos exatamente sem OCR. Doc 07: 0 caracteres.
- **Decision:** Manter extração nativa como caminho primário.
- **Status:** CONFIRMED (no lote)
- **Notas:** E-000: 7 docs retornaram texto legível; doc 07 retornou string vazia.

### H-02 — OCR/visão apenas como fallback
- **Hypothesis:** OCR ou visão só são necessários quando não há camada de texto utilizável; aplicá-los a todos os docs não melhora a qualidade.
- **Why it matters:** Custo e superfície de erro; justifica a pergunta "por que (não) OCR?".
- **How to test:** Rodar o fallback sobre um doc nativo e comparar com a extração nativa.
- **Expected signal:** Fallback em nativo não acrescenta informação e introduz divergências.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

### H-02b — OCR local vs visão de LLM para o documento escaneado
- **Hypothesis:** Para o doc 07, visão de LLM atinge precisão igual ou maior que OCR local (Tesseract) nos campos críticos, com menos pós-processamento; OCR local tem custo zero e é determinístico.
- **Why it matters:** Decide a dependência do fallback (setup do avaliador, custo, determinismo).
- **How to test:** Extrair os campos do doc 07 pelos dois caminhos; comparar campo a campo com o gabarito; medir erros em dígitos, casas decimais e datas.
- **Expected signal:** Ambos acertam o texto corrido; OCR local erra mais em números colados a pontilhados.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED
- **Notas:** Tesseract não está instalado localmente (Q-07). Inspeção visual humana do doc 07 foi legível sem ambiguidade.

### H-03 — Detecção de camada de texto utilizável por heurística simples
- **Hypothesis:** Um limiar simples (nº de caracteres alfanuméricos por página, presença de fontes) distingue PDF nativo de escaneado.
- **Why it matters:** É o roteador da ingestão; se falhar, o doc vai para o caminho errado.
- **How to test:** Aplicar aos 8 docs; testar também um PDF com camada de texto "lixo" (se conseguirmos um exemplo).
- **Expected signal:** Separação perfeita no lote (7 vs 1). Registrar a limitação: camada de texto corrompida não seria detectada só por contagem.
- **Observed result:** (E-002) Limiar de 100 caracteres alfanuméricos/página separou 7 nativos × 1 escaneado sem erro (teste automatizado). **Não testado:** PDF com camada de texto corrompida ou parcial.
- **Decision:** Manter o limiar simples; registrar a limitação.
- **Status:** CONFIRMED (no lote; camada corrompida não testada)

## B. Interpretação e extração de campos

### H-04 — Baseline 100% determinístico como medida de referência
- **Hypothesis:** Um extrator só com regras (regex + rótulos + dicionário de termos) acerta a maioria dos campos nos docs nativos deste lote, mas falha na classificação do doc 03 e não generaliza para layouts/terminologias novas.
- **Why it matters:** Estabelece o piso. Sem ele não conseguimos provar que o LLM agrega valor, nem onde.
- **How to test:** Implementar o baseline; medir acerto por campo e por tipo contra o gabarito; depois aplicar a **variações perturbadas** (rótulos reescritos, ordem trocada, sinônimos) para medir generalização.
- **Expected signal:** Alta acurácia no lote original; queda relevante nas variações; doc 03 errado se as regras não forem ajustadas especificamente a ele.
- **Observed result:** (E-002) Mais alto que o esperado no lote: 95% dos valores exatos, 98% dos status e 7/7 tipos nos nativos. **A expectativa de errar o doc 03 foi refutada:** a classificação sem o título mais a precedência JCP > DIVIDEND acertou. Falhas observadas: IR condicional achatado (doc 01, silencioso), `ex_date` com rótulo não literal (doc 06), base do IR não literal (doc 03). Generalização: 4 variações escritas à mão falham como previsto (xfail), mas **não houve medição sistemática** — 7/8 documentos compartilham o template.
- **Decision:** Parte "falha no doc 03" rejeitada; parte "não generaliza" inconclusiva. Reformulada em H-24 (conjunto de variações).
- **Status:** MODIFIED

### H-05 — LLM só para ambiguidade semântica e heterogeneidade
- **Hypothesis:** O LLM agrega valor em (a) classificação do tipo de evento pelo conteúdo, (b) mapear expressões heterogêneas para papéis de data (data com / ex / pagamento / data-base) e (c) identificar o valor principal vs valores auxiliares. Não agrega em ISIN, ticker, CNPJ, formatos de data e número.
- **Why it matters:** Responde "por que IA aqui e não ali".
- **How to test:** Comparar H-04 vs extração com LLM vs híbrido, por campo, no lote original e nas variações.
- **Expected signal:** Híbrido ≥ LLM puro ≥ regras em classificação/papéis de data; regras = LLM em identificadores com formato fixo.
- **Observed result:** Não testado (sem LLM). (E-002) localizou onde o determinístico falha: semântica condicional (doc 01), mapeamento de rótulo para papel (doc 06) e classificação dependente de precedência (docs 02/03). São exatamente as categorias previstas para o LLM.
- **Decision:** 
- **Status:** UNTESTED — candidata ao próximo experimento

### H-06 — Grounding obrigatório: todo valor extraído tem evidência literal na fonte
- **Hypothesis:** Exigir que o extrator (regra ou LLM) devolva o trecho literal de origem e verificar deterministicamente que o trecho existe no texto do documento detecta valores alucinados.
- **Why it matters:** "Valores inventados viram prejuízo" e "auditar sem reabrir o documento". É o principal controle contra alucinação.
- **How to test:** Rodar sobre o lote; injetar valores alterados na resposta do extrator e verificar se o check os rejeita.
- **Expected signal:** 100% dos valores corretos passam; 100% dos injetados falham. Atenção à normalização (quebras de linha do pypdf nos rótulos, espaços).
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

### H-07 — Números como Decimal/string, nunca float
- **Hypothesis:** Converter "R$ 0,1434196500" para `Decimal` a partir da string preserva exatamente o valor; `float` introduz erro na checagem bruto × líquido.
- **Why it matters:** Precisão financeira; falsos negativos/positivos na regra de consistência.
- **How to test:** Teste unitário com os 4 pares bruto/líquido do lote em Decimal e em float.
- **Expected signal:** Decimal exato; float com diferenças na ordem de 1e-17 que exigem tolerância arbitrária.
- **Observed result:** (E-002) + `tests/test_numeric.py`: em float, 0.1738420000 × (1 − 0.175) ≠ 0.1434196500; em Decimal, os 4 pares do lote fecham exatamente. Contexto estrito levanta `Inexact` em vez de arredondar. A serialização recusa float.
- **Decision:** Política decidida em D-007; comportamento verificado.
- **Status:** CONFIRMED

### H-08 — Classificar pelo conteúdo, não pelo título
- **Hypothesis:** Classificar o tipo de evento a partir do corpo e da tabela (e não do título/nome do arquivo) acerta o doc 03 (JCP com título "Dividendos"). Sinais determinísticos (Lei 9.249/95, TJLP, IRRF 17,5%, presença de valor líquido) podem **corroborar** a classificação do LLM e, em caso de conflito, reduzir a confiança.
- **Why it matters:** Erro de tipo muda tratamento tributário (enunciado).
- **How to test:** Classificar com (a) só título, (b) regras de palavras-chave, (c) LLM, (d) LLM + corroboração. Verificar doc 03 e armadilha lexical dos docs 02/03 ("imputado aos dividendos obrigatórios").
- **Expected signal:** (a) erra doc 03; (b) é frágil; (c) e (d) acertam; (d) sinaliza o conflito título × corpo como evidência auditável.
- **Observed result:** (E-002) (a) Só o título: o doc 03 seria DIVIDEND (o título tem sinal só de dividendo) — refutada como estratégia. (b) Palavras-chave no conteúdo sem o título: 7/7, mas docs 02 e 03 precisaram da regra de precedência (MEDIUM) e o caso de negação falha (xfail). A regra `CLASSIFICATION_TITLE_CONSISTENT` sinalizou o conflito do doc 03. (c) e (d), com LLM, não testados.
- **Decision:** 
- **Status:** TESTING — (a) e (b) medidos; (c) e (d) pendentes

### H-09 — Schema condicional ao tipo de evento com três estados de ausência
- **Hypothesis:** Um schema com campos requeridos/aplicáveis por tipo e ausência tipada (`not_found`, `not_applicable`, `declared_pending`) representa fielmente os docs 04, 06 e 08 sem inventar valores.
- **Why it matters:** "Ausente continua ausente"; evita que moeda de grupamento vire "BRL" inventado ou que "A definir" vire data.
- **How to test:** Validar a saída dos 8 docs contra o schema; verificar os estados atribuídos em 04 (pagamento), 06 (valor/moeda), 01/05 (líquido).
- **Expected signal:** Nenhum campo preenchido sem evidência; estados corretos em 100% dos casos do gabarito.
- **Observed result:** (E-002) Nos nativos: `declared_pending` 1/1, `not_applicable` 17/17, `not_found` 3/3, **0 valores inventados**. Campo não suportado pelo extrator é declarado em `unsupported_fields`, não reportado como `not_found` (D-013).
- **Decision:** Manter o schema condicional com ausência tipada.
- **Status:** CONFIRMED (nos documentos com texto)

### H-10 — Uma chamada de LLM por documento com saída estruturada é suficiente
- **Hypothesis:** Uma única chamada por documento, com JSON schema, temperatura 0 e exigência de evidência por campo, basta. Multi-agent/loop não melhora a qualidade.
- **Why it matters:** Simplicidade, custo, determinismo e depurabilidade na sessão ao vivo.
- **How to test:** Medir acerto com 1 chamada; só testar alternativas se aparecer modo de falha que 1 chamada não resolve.
- **Expected signal:** Acerto no nível do gabarito com 1 chamada.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

## C. Validação

### H-11 — Golden records como lookup determinístico por chave exata
- **Hypothesis:** Validar por chave exata (ISIN e ticker) e checar cruzado CNPJ, razão social normalizada e classe identifica os 7 emissores presentes e rejeita o doc 08, sem falso positivo com os 5 distratores. Fuzzy matching não é necessário e é perigoso para identidade.
- **Why it matters:** Emissor/ISIN errado aplica o evento ao ativo errado.
- **How to test:** Rodar o lookup com os identificadores do gabarito e com identificadores perturbados (1 caractere trocado).
- **Expected signal:** 7 match, 1 not-found; perturbações → not-found ou conflito, nunca match silencioso.
- **Observed result:** (E-002) + `tests/test_reference.py`: 7 matches exatos, doc 08 não encontrado, nenhum distrator casado, qualquer ISIN com 1 caractere trocado → não encontrado.
- **Decision:** Lookup exato por ISIN; sem fuzzy (D-008).
- **Status:** CONFIRMED

### H-12 — Validação de dígito verificador (ISIN/CNPJ) não pode ser bloqueante neste lote
- **Hypothesis:** Como os identificadores são fictícios, DV falha em quase todos; tratá-lo como erro geraria falso alarme generalizado. Em produção seria um validador útil.
- **Why it matters:** Mostra critério: validador tecnicamente correto pode ser inadequado aos dados.
- **How to test:** Rodar DV sobre golden e docs.
- **Expected signal:** Maioria falha → manter como informativo (ou desligado por configuração) e documentar.
- **Observed result:** E-000: 10/12 ISINs e 10/12 CNPJs do golden falham no DV, assim como o ISIN do doc 08; algoritmo validado com 4 ISINs reais.
- **Decision:** Checksum não bloqueante e sem efeito em confiança/roteamento → **D-003**.
- **Status:** CONFIRMED
- **Notas:** E-000: 10/12 ISINs e 10/12 CNPJs do golden falham no DV; algoritmo ISIN validado com 4 ISINs reais.

### H-13 — Regras temporais determinísticas por tipo de evento
- **Hypothesis:** Regras explícitas — aprovação ≤ data com < ex ≤ pagamento; ex = próximo dia útil após data com; data-base < início de negociação (grupamento); datas de mercado em dias úteis — detectam o doc 05 sem falsos positivos nos demais.
- **Why it matters:** "Datas incoerentes quebram conciliações".
- **How to test:** Aplicar aos valores do gabarito.
- **Expected signal:** Só doc 05 falha (pagamento < data com). Doc 04: regra de pagamento é "não avaliada", não "falha".
- **Observed result:** (E-002) Regras `DATE_*` com FAIL só no doc 05 (pagamento < ex); doc 04 `NOT_EVALUATED` (pendente); doc 06 `NOT_EVALUATED` (sem `ex_date`), nunca FAIL indevido. Nenhum falso positivo de data nos nativos.
- **Decision:** Manter as regras; a regra de dia útil é WARNING por falta de calendário (D-006, D-012).
- **Status:** CONFIRMED (no lote)
- **Notas:** Dia útil = seg–sex, sem feriados B3 (**D-006**). Sábados/feriado aparecem só em datas de reunião (06, 07, 08) — nenhuma regra é aplicada ao dia da semana da aprovação. Resultados esperados por documento em `tests/ground_truth/`.

### H-14 — Regras de valor determinísticas
- **Hypothesis:** líquido = bruto × (1 − IRRF) com Decimal e igualdade exata (ou tolerância declarada de arredondamento), aplicada só quando bruto, líquido e alíquota existem; proporção interna consistente (1/20 = 5% no doc 08); valor > 0.
- **Why it matters:** Pedido explícito do enunciado; também funciona como **checksum de leitura** no doc escaneado.
- **How to test:** Aplicar aos valores do gabarito; injetar erro de 1 dígito no bruto do doc 07 e verificar detecção.
- **Expected signal:** 4/4 JCP consistentes; erro injetado detectado.
- **Observed result:** (E-002) bruto×líquido PASS exato nos 3 JCP nativos (02, 03, 04). Os testes unitários detectam erro de 1 dígito no líquido e erro de percentual na bonificação. O papel de checksum de leitura no doc 07 **não foi testado** (sem extração do escaneado).
- **Decision:** Manter.
- **Status:** CONFIRMED (nativos; checksum de scan pendente)
- **Notas:** E-000: 4/4 pares exatos em Decimal. IRRF esperado de 17,5% para JCP é conhecimento de domínio **declarado nos próprios avisos**; não codificar alíquota fixa sem registrar como premissa.

### H-15 — Function calling híbrido: o LLM usa a tool de referência de forma confiável e útil
- **Contexto:** O desenho foi decidido por princípio em **D-002**: o LLM usa ao menos uma tool de referência, e o orchestrator executa todas as validações obrigatórias. A hipótese passa a medir o **comportamento** do LLM dentro desse desenho, não se o desenho é seguro (isso é garantido por construção).
- **Hypothesis:** Com tool de lookup no golden records disponível, o LLM (a) chama a tool em 100% dos documentos, (b) com argumentos corretos (ISIN/ticker lidos do documento) e (c) seu resultado nunca diverge do resultado do orchestrator.
- **Why it matters:** Atende a letra do R3 com evidência mensurável; se o LLM omitir chamadas, isso não afeta a segurança, mas mostra que a chamada pelo LLM não pode ser a única linha de defesa.
- **How to test:** Registrar no audit trail as tool calls feitas pelo LLM; comparar com as execuções do orchestrator nos 8 docs, em ≥ 2 runs.
- **Expected signal:** Chamadas presentes e coerentes; qualquer divergência é registrada e o resultado do orchestrator prevalece.
- **Observed result:**
- **Decision:** Desenho já decidido (D-002); o resultado desta hipótese só informa métricas e o texto do README.
- **Status:** MODIFIED (reformulada após D-002; teste pendente)

## D. Confiança, roteamento e revisão humana

### H-16 — Confiança de campo separada de status do registro
- **Hypothesis:** Confiança por campo (a leitura está correta?) e status do registro (pode seguir downstream?) são dimensões diferentes. Ex.: doc 05 tem todos os campos com alta confiança e registro inválido.
- **Why it matters:** Pedido explícito do usuário; evita que "extração perfeita" seja lida como "registro aprovado".
- **How to test:** Verificar no lote que existe pelo menos um caso de campos com alta confiança e registro bloqueado (05), e um de registro válido com pendência (04).
- **Expected signal:** As duas dimensões divergem exatamente nesses casos.
- **Observed result:** (E-002) Doc 05: campos em HIGH (exceto `issuer_name` MEDIUM) e registro REVIEW_REQUIRED por `DATE_INCONSISTENCY`. Doc 04: pendência extraída com HIGH e registro REVIEW_REQUIRED. As duas dimensões divergem exatamente como previsto.
- **Decision:** Manter confiança de campo e decisão de registro separadas.
- **Status:** CONFIRMED

### H-17 — Confiança derivada de sinais observáveis, não de autoavaliação do LLM
- **Hypothesis:** Uma confiança categórica (HIGH/MEDIUM/LOW) calculada por regras explícitas a partir de sinais — método de extração (nativo/OCR/visão), grounding verificado, formato válido, concordância regra × LLM, validações do campo, local da evidência (tabela vs corpo) — é mais explicável e útil que um score numérico autodeclarado pelo LLM.
- **Why it matters:** R4 exige justificativa; com 8 docs não há como calibrar um score numérico.
- **How to test:** Pedir também o score do LLM e comparar com o nosso nos casos difíceis (03, 05, 07).
- **Expected signal:** Score do LLM alto em quase tudo, inclusive no doc 05; nossa confiança diferencia os casos e traz o motivo.
- **Observed result:** (E-002) **Resultado negativo parcial:** a confiança por sinais é explicável (cada nível tem motivo), mas deu HIGH aos 2 valores com semântica incompleta (IR do doc 01 e do doc 03). Âncora mede "achei no lugar certo", não "entendi o que diz". A comparação com a autoavaliação de um LLM não foi feita.
- **Decision:** 
- **Status:** TESTING — lacuna identificada (ver H-23)

### H-18 — Roteamento para revisão humana com códigos de motivo
- **Hypothesis:** Regras explícitas de roteamento (ex.: `EMISSOR_NAO_ENCONTRADO`, `INCOERENCIA_DATAS`, `CAMPO_CRITICO_BAIXA_CONFIANCA`, `CONFLITO_CLASSIFICACAO`, `CAMPO_PENDENTE_DECLARADO`) produzem o roteamento esperado no lote: 05 e 08 para revisão; 04 com pendência explícita (política em Q-05); 07 para revisão só se algum campo crítico não passar em grounding/checksum; 01, 02, 06 aprovados; 03 aprovado ou revisado conforme a política para conflito título × corpo.
- **Why it matters:** R5; e evitar tanto aprovação indevida quanto "tudo para revisão".
- **How to test:** Comparar o roteamento com o esperado no gabarito.
- **Expected signal:** Roteamento idêntico ao esperado, com motivo específico em cada exceção.
- **Observed result:** (E-002) Expectativas DEFINED 5/6. A lógica de roteamento se comportou como especificado dado o que recebeu; o único erro (doc 06 → revisão) vem da extração. Doc 07 → `NO_USABLE_TEXT_LAYER` (POLICY_DEPENDENT, não conta). Doc 01 aprovado com IR semanticamente errado: o roteamento não tinha sinal para detectar.
- **Decision:** 
- **Status:** TESTING — depende de H-04/H-05 e H-23

## E. Auditoria, reprodutibilidade e custo

### H-19 — Audit trail desde o dia 1
- **Hypothesis:** Um manifest por run (`run_id`, versão do pipeline, timestamp, hashes dos inputs, modelo, versão de prompt, config) + proveniência por campo no JSON (valor bruto como no documento, valor normalizado, trecho de evidência, localização, método, validações) permite reconstruir qualquer decisão sem reabrir o PDF.
- **Why it matters:** Requisito de arquitetura e do enunciado (R6).
- **How to test:** Para 3 campos escolhidos ao acaso, responder "de onde veio, como foi extraído, por que foi aceito/rejeitado" só com os outputs.
- **Expected signal:** Resposta completa em todos os casos, sem abrir o PDF e sem logar o documento inteiro.
- **Observed result:** (E-002) Implementado: manifest do run (`run_id`, versões, hashes de entrada e do golden, config), audit por documento (estágios com duração, validadores executados, decisão, motivos, erros, retries) e proveniência por campo (raw, `source_label`, evidência com offset e página, regras de extração). O teste formal de "reconstruir 3 campos sem o PDF" ainda não foi executado.
- **Decision:** 
- **Status:** TESTING

### H-20 — Reprodutibilidade via cache de respostas do LLM
- **Hypothesis:** Cachear respostas do LLM por (hash do documento, modelo, versão de prompt), com temperatura 0, torna os runs reprodutíveis, baratos e depuráveis offline (inclusive na sessão ao vivo).
- **Why it matters:** Auditoria ("qual resposta o modelo deu naquele run?"), custo e demo ao vivo sem depender da rede.
- **How to test:** Rodar 2×; diffar outputs; rodar sem rede com cache.
- **Expected signal:** Outputs idênticos; segundo run com custo zero.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

### H-21 — Nome do arquivo não influencia o resultado
- **Hypothesis:** Renomear os PDFs para hashes não altera nenhum output (exceto o campo de nome de origem).
- **Why it matters:** Os nomes do lote vazam o problema de cada doc; em produção não existiriam.
- **How to test:** Rodar com arquivos renomeados; diffar.
- **Expected signal:** Diff vazio nos campos extraídos e no roteamento.
- **Observed result:** (E-002) `tests/test_pipeline.py`: os 8 documentos copiados com nome = hash do conteúdo produzem registros idênticos (exceto `file_name` e `audit`).
- **Decision:** Princípio D-004 verificado automaticamente.
- **Status:** CONFIRMED

### H-22 — Custo por documento é baixo e mensurável
- **Hypothesis:** Com 1 chamada por documento (visão só no escaneado), o custo por documento fica na ordem de centavos de dólar e é dominado pelo documento escaneado.
- **Why it matters:** "Quanto custa?" e "como escalaríamos?".
- **How to test:** Registrar tokens de entrada/saída por chamada no manifest; calcular custo com a tabela de preços do provider.
- **Expected signal:** Custo total do lote baixo; escaneado com mais tokens.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

## F. Hipóteses novas a partir do E-002

### H-23 — Qualificadores próximos ao valor como sinal determinístico de semântica incompleta
- **Hypothesis:** Detectar, numa janela ao redor de um valor extraído, qualificadores que mudam seu significado ("sobre a parcela que exceder", "exceto", "ressalvados", "até", "limitado a") e rebaixar a confiança do campo para LOW captura erros semânticos silenciosos como o do doc 01, sem LLM.
- **Why it matters:** O E-002 mostrou um valor aprovado automaticamente com semântica errada e confiança HIGH. É o erro mais caro do experimento, e a confiança atual não o vê.
- **How to test:** Aplicar ao lote e às variações (H-24); medir quantos erros semânticos passam a ser sinalizados e quantos campos corretos são rebaixados sem necessidade.
- **Expected signal:** Doc 01 `withholding_tax` → LOW → revisão; poucos rebaixamentos indevidos. Se o léxico de qualificadores crescer caso a caso, isso é sinal de que o problema precisa de interpretação semântica (H-05).
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED

### H-24 — O desempenho do Baseline A cai em avisos heterogêneos
- **Hypothesis:** Num pequeno conjunto de variações escritas à mão (rótulos sinônimos, ordem trocada, datas só por extenso, tabela ausente, negações, qualificadores), a acurácia de valor e de classificação do Baseline A cai de forma relevante em relação ao lote original, e as falhas se concentram em mapeamento semântico e não em localização de padrões.
- **Why it matters:** 7/8 documentos do lote compartilham o template. Sem variações, não dá para medir generalização, nem justificar ou refutar um componente de LLM.
- **How to test:** Criar de 10 a 20 variações com gabarito (mesmo formato v2.0) e rodar o Baseline A sem alterá-lo.
- **Expected signal:** Queda concentrada em classificação, papéis de data e qualificadores; identificadores e aritmética estáveis.
- **Observed result:**
- **Decision:**
- **Status:** UNTESTED
