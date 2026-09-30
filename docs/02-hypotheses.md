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
- **Observed result:** (E-003) C acertou 31/31 campos semânticos no original e 21/21 alvos no challenge set (contra 10/21 do B e 6/21 do A), com os valores, a aritmética e o lookup mantidos determinísticos. O ganho vem de papéis de data (8/8 contra 0/8), descrição do evento e negação/referências enganosas. O failure mode perigoso do E-002 também foi resolvido pelo B, sem LLM.
- **Decision:** O LLM agrega valor onde há interpretação semântica; não é necessário para qualificadores de padrão conhecido. Recomendação no E-003; sem decisão final até o E-004.
- **Status:** CONFIRMED (no lote e no challenge set ciente do autor; holdout cego pendente)

### H-06 — Grounding obrigatório: todo valor extraído tem evidência literal na fonte
- **Hypothesis:** Exigir que o extrator (regra ou LLM) devolva o trecho literal de origem e verificar deterministicamente que o trecho existe no texto do documento detecta valores alucinados.
- **Why it matters:** "Valores inventados viram prejuízo" e "auditar sem reabrir o documento". É o principal controle contra alucinação.
- **How to test:** Rodar sobre o lote; injetar valores alterados na resposta do extrator e verificar se o check os rejeita.
- **Expected signal:** 100% dos valores corretos passam; 100% dos injetados falham. Atenção à normalização (quebras de linha do pypdf nos rótulos, espaços).
- **Observed result:** (E-003) 150/150 trechos devolvidos pelo LLM foram localizados literalmente; nenhuma interpretação foi descartada nas execuções reais. O caminho de rejeição (citação inexistente, valor fora da citação) está coberto por testes offline.
- **Decision:** Manter grounding obrigatório.
- **Status:** CONFIRMED (grounding respeitado; rejeição exercitada só offline)

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
- **Observed result:** (E-002) (a) só o título erra o doc 03; (b) palavras-chave precisam de precedência e falham em negação. (E-003) (c) LLM: 7/7 no original e todos os alvos de tipo no challenge set, incluindo negação (CH-01, CH-02), referências enganosas (CH-04, CH-10), descrição sem palavra-chave (CH-03) e adiamento (CH-11 → não resolvido). (d) Corroboração com o determinístico: acordo → HIGH; o desacordo mandou para revisão CH-01 e CH-10, onde o LLM acertou e o determinístico errou (conservador por desenho).
- **Decision:** Classificar pelo conteúdo; o LLM é o intérprete mais robusto. A política de desacordo continua conservadora.
- **Status:** CONFIRMED

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
- **Observed result:** (E-003) Uma interpretação por documento (2 chamadas de API: rodada da tool + resposta estruturada) bastou: 0 falhas de parse/schema, 0 recusas, 0 novas tentativas. Multi-agente não foi necessário.
- **Decision:** Manter uma chamada estruturada por documento.
- **Status:** CONFIRMED

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
- **Observed result:** (E-003) Tool chamada em 18/18 documentos com texto, com argumentos corretos em todos; 1 chamada desnecessária (consulta extra por ticker); 0 divergências entre tool e validation engine. A presença e o número de chamadas variaram entre execuções (5/7 consistentes no original), o que confirma que a segurança não pode depender da chamada (D-002).
- **Decision:** D-002 mantida: o LLM usa a tool; o orchestrator valida sempre.
- **Status:** CONFIRMED

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
- **Observed result:** (E-002) confiança por âncora não detecta perda semântica. (E-003) Com a dimensão semântica separada (D-015), B e C eliminaram a aprovação insegura. Mas a regra de C (qualquer CONDITION → LOW) gerou alarmes falsos estáveis nos docs 01, 02 e 03, com a base do IR correta.
- **Decision:** Três dimensões mantidas; a política de fusão de qualificadores precisa de revisão (E-004).
- **Status:** MODIFIED (dimensão semântica confirmada; regra de qualificadores de C refutada como está)

### H-18 — Roteamento para revisão humana com códigos de motivo
- **Hypothesis:** Regras explícitas de roteamento (ex.: `EMISSOR_NAO_ENCONTRADO`, `INCOERENCIA_DATAS`, `CAMPO_CRITICO_BAIXA_CONFIANCA`, `CONFLITO_CLASSIFICACAO`, `CAMPO_PENDENTE_DECLARADO`) produzem o roteamento esperado no lote: 05 e 08 para revisão; 04 com pendência explícita (política em Q-05); 07 para revisão só se algum campo crítico não passar em grounding/checksum; 01, 02, 06 aprovados; 03 aprovado ou revisado conforme a política para conflito título × corpo.
- **Why it matters:** R5; e evitar tanto aprovação indevida quanto "tudo para revisão".
- **How to test:** Comparar o roteamento com o esperado no gabarito.
- **Expected signal:** Roteamento idêntico ao esperado, com motivo específico em cada exceção.
- **Observed result:** (E-003) Roteamento DEFINED no original: A 5/6, B 5/6, C 4/6 (C erra os docs 01 e 02 por alarme falso e acerta o 06). Challenge: A 3/7, B 4/7, C 5/7. Nenhuma variante produziu aprovação insegura.
- **Decision:** 
- **Status:** TESTING — depende da política de fusão v2

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
- **Observed result:** (E-003) As respostas das 4 execuções de C foram gravadas em cache (`llm_cache_run1`, `llm_cache_run2`). Entre execuções independentes: tipo, campos normalizados e roteamento 18/18 consistentes; interpretação bruta 16/18 (forma das datas) e tool calls 16/18. O replay está coberto por teste offline, não por uma re-execução oficial.
- **Decision:** Manter o cache como registro auditável; a reprodutibilidade de decisão foi observada mesmo sem replay.
- **Status:** CONFIRMED (decisões estáveis; forma bruta varia)

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
- **Observed result:** (E-003) ~US$ 0,055 e ~11 s por documento (claude-opus-5, effort medium, sem cache de prompt). ~7,5k tokens de entrada e ~0,75k de saída por documento. Total do experimento: US$ 2,01.
- **Decision:** Custo na ordem de centavos confirmado; latência é o custo dominante.
- **Status:** CONFIRMED

## F. Hipóteses novas a partir do E-002

### H-23 — Qualificadores próximos ao valor como sinal determinístico de semântica incompleta
- **Hypothesis:** Detectar, numa janela ao redor de um valor extraído, qualificadores que mudam seu significado ("sobre a parcela que exceder", "exceto", "ressalvados", "até", "limitado a") e rebaixar a confiança do campo para LOW captura erros semânticos silenciosos como o do doc 01, sem LLM.
- **Why it matters:** O E-002 mostrou um valor aprovado automaticamente com semântica errada e confiança HIGH. É o erro mais caro do experimento, e a confiança atual não o vê.
- **How to test:** Aplicar ao lote e às variações (H-24); medir quantos erros semânticos passam a ser sinalizados e quantos campos corretos são rebaixados sem necessidade.
- **Expected signal:** Doc 01 `withholding_tax` → LOW → revisão; poucos rebaixamentos indevidos. Se o léxico de qualificadores crescer caso a caso, isso é sinal de que o problema precisa de interpretação semântica (H-05).
- **Observed result:** (E-003) O patch B interpretou o IR condicional do doc 01 e do CH-05 (base EXCESS_OVER_THRESHOLD) e aceitou a exceção por titular do doc 02, sem alarme falso no original. Um alarme falso no challenge set (CH-06: qualificador atribuído à data da mesma frase). **Ressalva:** o léxico se sobrepõe ao CH-05 (mesmo autor).
- **Decision:** Qualificadores de padrão conhecido podem ser resolvidos deterministicamente e de graça.
- **Status:** CONFIRMED (com ressalva de contaminação por autoria)

### H-24 — O desempenho do Baseline A cai em avisos heterogêneos
- **Hypothesis:** Num pequeno conjunto de variações escritas à mão (rótulos sinônimos, ordem trocada, datas só por extenso, tabela ausente, negações, qualificadores), a acurácia de valor e de classificação do Baseline A cai de forma relevante em relação ao lote original, e as falhas se concentram em mapeamento semântico e não em localização de padrões.
- **Why it matters:** 7/8 documentos do lote compartilham o template. Sem variações, não dá para medir generalização, nem justificar ou refutar um componente de LLM.
- **How to test:** Criar de 10 a 20 variações com gabarito (mesmo formato v2.0) e rodar o Baseline A sem alterá-lo.
- **Expected signal:** Queda concentrada em classificação, papéis de data e qualificadores; identificadores e aritmética estáveis.
- **Observed result:** (E-003) A caiu de 28/31 campos semânticos no original para 6/21 alvos no challenge set, com falhas concentradas em papéis de data (0/8), descrição do evento (0/3) e negação (1/4). Identificadores e aritmética ficaram estáveis.
- **Decision:** 
- **Status:** CONFIRMED (challenge set ciente do autor)

## G. Hipóteses novas a partir do E-003

### H-25 — LLM sob demanda preserva a segurança com fração do custo
- **Hypothesis:** Chamar o intérprete semântico só quando o determinístico sinaliza necessidade (campo obrigatório ausente, classificação por precedência, ambígua ou indeterminada, qualificador detectado pelo B) mantém 0 aprovações inseguras e a acurácia semântica de C, com custo e latência bem menores que C sempre ligado.
- **Why it matters:** No lote, 7/8 documentos seguem um template em que A/B já acertam o que é localizável; C custa ~11 s e US$ 0,055 por documento.
- **How to test:** Variante D = B + C condicional, sobre o original, o challenge set e o holdout cego; comparar com B e C.
- **Expected signal:** Mesma segurança de C, taxa de chamadas ao LLM < 50%, sem regressão semântica.
- **Observed result:** (E-004) No original: LLM em 1/7 documentos elegíveis, custo −82% contra a C (US$ 0,073 × 0,411), latência p50 de 9,7 s para 13 ms, 0 aprovações inseguras, semântica 30/31, validação 104/104. No challenge set (quase todo semântico): LLM em 10/11, custo +8% contra a C (prompt v2 ~15% mais caro por chamada). Invocações falso-positivas 3 (CH-01 e CH-02 por desenho; CH-11 por atribuição do B); falso-negativa 1 (doc 03, por desenho). Decisão de invocar 19/19 estável entre execuções.
- **Decision:** Economia real e segura quando a maioria dos documentos não precisa de semântica; nula quando precisa. Arquitetura candidata D.
- **Status:** CONFIRMED (condicionada à distribuição de documentos)

### H-26 — Política de qualificadores v2 elimina os alarmes falsos de C sem reabrir o risco
- **Hypothesis:** Bloquear só quando o qualificador altera a base ou a taxa (ou definir CONDITION de forma estreita no prompt v2) elimina os alarmes falsos dos docs 01, 02 e 03, mantendo 0 aprovações inseguras.
- **Why it matters:** C-1 é a principal razão de C ter ficado abaixo de A/B no roteamento DEFINED.
- **How to test:** Prompt/política v2 congelados antes de rodar; avaliar no holdout cego além dos conjuntos atuais.
- **Expected signal:** Roteamento DEFINED 6/6 no original, sem aprovação insegura.
- **Observed result:** (E-004) A fusão v2 corrigiu os false reviews da C (CH-01, CH-10 → AUTO corretamente; docs 01 e 02 sem LLM e sem alarme) e levou o roteamento DEFINED do challenge set a 7/7. O modelo de qualificadores v2 introduziu novos false reviews: doc 06 (regras de frações rotuladas `other`/`event_eligibility`) e CH-07 na execução 1 (`affects` instável + salvaguarda de inconsistência), com 1/19 de instabilidade de roteamento. 0 aprovações inseguras. **Errata (E-005):** a D também mandou para revisão CH-03, CH-08 e CH-09 por qualificadores v2 (casos PROVISIONAL, fora do placar DEFINED); o problema era maior do que o reportado.
- **Decision:** Manter a fusão v2; refinar a taxonomia e a extração de qualificadores (v3) antes de adotar.
- **Status:** MODIFIED (fusão v2 confirmada; qualificadores v2 precisam de refinamento)

## H. Hipóteses do E-005

### H-27 — Qualificadores v3 reduzem revisões desnecessárias sem perder segurança
- **Hypothesis:** Separar qualificador material (teste de remoção, efeito e justificativa obrigatórios) de nota semântica (operacional, legal, informativa, que nunca bloqueia), aplicar uma guarda de escopo determinística contra rótulo com valor, e bloquear só efeito material não representado no registro reduz as revisões desnecessárias causadas por qualificadores, mantendo 0 aprovações inseguras.
- **Why it matters:** No E-004, a D mandou para revisão doc 06, CH-03, CH-07, CH-08 e CH-09 por qualificadores de contexto, com instabilidade no CH-07.
- **How to test:** Variante E contra a D, 2 execuções, critérios pré-registrados (FREEZE do E-005).
- **Expected signal:** doc 06 e CH-07 aprovados de forma estável; taxa de revisão menor ou igual; 0 inseguras.
- **Observed result:** (E-005) Challenge set: bloqueios falsos por qualificador 4 → 0, taxa de revisão 5/11 → 2/11, estabilidade semântica 8/10 → 10/10, CH-07 AUTO nas duas execuções, 0 inseguras, 21/21 semântica. Original: igual à D (5/6 DEFINED); doc 06 **continua em revisão** (E1: período de ajuste de frações marcado como `entitlement`; E2: frações corretamente como notas, mas `ex_date` rejeitada pelo grounding porque o LLM escreveu o valor em formato diferente da citação). A guarda de escopo determinística não precisou atuar em nenhuma execução real (0 rejeições). Custo +6–10% por documento com LLM.
- **Decision:** Critério 2 (doc 06) não atendido, portanto a E não passa formalmente pela regra pré-registrada. É Pareto-superior à D nas demais métricas. A adoção como candidata depende de decisão do usuário.
- **Status:** MODIFIED (confirmada para rótulos, frases que definem campos e contexto; não confirmada para procedimento de frações)

## I. Blind test

### H-28 — A arquitetura candidata (E) generaliza de forma segura e útil para avisos nunca vistos
- **Hypothesis:** Num conjunto criado por um processo independente, a E mantém 0 aprovações inseguras, manda ambiguidades reais para revisão e aprova automaticamente uma parte útil dos casos completos.
- **Why it matters:** O challenge set é ciente do autor; só um conjunto independente mede generalização.
- **How to test:** BT-001 (blind set independente, 14 casos, E congelada, avaliador pré-registrado).
- **Expected signal:** 0 inseguras; ambiguidades revisadas; roteamento correto na maioria.
- **Observed result:** (BT-001, execução completa + execução 1) 0 aprovações inseguras, 0 ambiguidades aprovadas, 0 aprovações falsas, 76/76 citações literais, identificadores 41/41, roteamento e decisão de invocar o LLM estáveis 14/14 entre execuções. Utilidade baixa: roteamento 8/14, revisão 11/14; revisões desnecessárias por cobertura determinística (proporção de desdobramento, data dd.mm.aaaa, segunda razão social), por qualificador (exclusão de tesouraria; exceção atribuída a valores pelo B) e por conflito de valores. Risco fora da métrica pré-registrada, estável: BT-01 aprovado sem a isenção de IR declarada (a fusão descarta tratamento não numérico).
- **Decision:** Segurança pré-registrada confirmada em dados independentes; utilidade insuficiente; a omissão de tratamento tributário não numérico precisa entrar na definição de aprovação insegura antes de qualquer adoção.
- **Status:** MODIFIED (seguro pela métrica pré-registrada; pouco útil; omissão silenciosa estável identificada)

## J. Hipóteses do E-006

### H-29 — Tratamento tributário explícito e gate de cobertura eliminam omissão material silenciosa
- **Hypothesis:** Representar o tratamento tributário como `tax_treatment` (alíquota, isenção, sem retenção, múltiplas alíquotas, exceções por beneficiário, condições) e exigir, antes do AUTO_APPROVE, que toda informação material detectada (declaração tributária, data de liquidação anunciada, papel de data mapeado pelo LLM, proporção, revogação, qualificador material) esteja representada, explicitamente não resolvida ou justificada leva a 0 aprovações inseguras pela definição enhanced, sem piorar materialmente o roteamento.
- **Why it matters:** O BT-001 mostrou que "não inventar" não basta: descartar uma informação material também produz registro errado.
- **How to test:** F × E (E reavaliada post-hoc) nos três conjuntos, com a definição enhanced (D-025).
- **Expected signal:** `unsafe_auto_approvals_enhanced` = 0 e 0 omissões aprovadas na F; false reviews da F ≤ E + 1 por conjunto.
- **Observed result:** (E-006, execução oficial única)
  - Aprovações inseguras enhanced: 0 nos três conjuntos (E post-hoc: 2 no blind-derived set, BT-01 e BT-03, ambas omissões).
  - BT-01 e BT-03 aprovados **com** a isenção e a data de crédito representadas.
  - False reviews: original +0, challenge +1 (CH-03, por variação do LLM nos qualificadores v3; lógica idêntica à da E), blind-derived −1.
  - O gate também bloqueou de forma segura uma data anafórica (BT-05) que o grounding literal não aceita.
  - Resultado **in-sample**: os três conjuntos foram vistos em dry run.
- **Decision:** Critérios 1–4 e 6 atendidos; recomenda-se adotar a F (decisão do usuário).
- **Status:** SUPPORTED (in-sample; sem medida independente)

### H-30 — Correções determinísticas pequenas e genéricas reduzem revisões desnecessárias sem regressão
- **Hypothesis:** Estas correções reduzem revisões por cobertura sem nenhuma regressão no original e no challenge set:
  - datas dd.mm.aaaa, dd-mm-aaaa e d/m/aaaa;
  - proporções em frases genéricas, com quantidade por extenso de 1 a 10 e direção preservada;
  - rótulo de crédito com qualificador ("crédito das novas ações");
  - emissor por papel estrutural, com agrupamento de alias "órgão da X S.A." → "X S.A." e revisão se houver duas entidades estruturais.
- **How to test:** Checagens por classe no blind-derived regression set; regressão no original e no challenge set.
- **Expected signal:** As classes observadas no BT-001 corrigidas; nenhuma aprovação nova incorreta.
- **Observed result:** (E-006)
  - Blind-derived set: datas com pontos (BT-11 → AUTO correto); proporções 4/4 (BT-05 1→3); crédito "das novas ações" (BT-03); alias de emissor (BT-12 sem LOW, mas em revisão por outro motivo).
  - Cobertura determinística 87 → 92/115; semântica 46 → 49/57; roteamento 8 → 9/14.
  - Original e challenge set sem regressão determinística (cobertura igual). As quedas no original (semântica 29/31, 1 FP de validação) vêm do LLM no doc 06 (valor fora da citação, failure mode já visto no E-005).
- **Status:** SUPPORTED (in-sample)

### H-31 — Contradição e revogação nunca viram evento vivo aprovado
- **Hypothesis:** Um detector determinístico de incompatibilidades documentadas e a revogação mínima garantem que contradições persistentes e revogações vão para revisão, e só adicionam chamada do LLM onde há contradição. As incompatibilidades são:
  - dividendo com retenção fixa sem condição de limite, que é o regime do JCP;
  - JCP isento no nível da distribuição;
  - direção da proporção incompatível com o tipo;
  - isenção junto com alíquota numérica.
- **How to test:** Checagens por classe e roteamento nos três conjuntos.
- **Expected signal:** 0 aprovações com contradição; revogação com `UNSUPPORTED_EVENT_REVOCATION`.
- **Observed result:** (E-006)
  - BT-13: `EVENT_TYPE_VS_TAX_TREATMENT` detectada, virou gatilho do LLM, persistiu → revisão.
  - BT-08: `UNSUPPORTED_EVENT_REVOCATION` → revisão, sem LLM.
  - 0 contradições aprovadas; nenhuma contradição falsa nos três conjuntos.
  - Custo: 1 documento a mais com LLM (BT-13) e 1 a menos (BT-08).
- **Status:** SUPPORTED (in-sample; 1 caso de cada classe)

## K. Validação cega da candidata F

### H-32 — A F continua segura e razoavelmente útil em casos novos e independentes
- **Hypothesis:** Em avisos criados por um processo independente, sem influência do desenvolvimento, a F:
  - não aprova nenhum registro de forma insegura pela definição enhanced;
  - não aprova registro com omissão material;
  - manda as ambiguidades perigosas para revisão;
  - tem limitações de utilidade fail-safe (revisão, não aprovação errada).
- **Why it matters:** Todos os resultados da F até aqui são in-sample (E-006). Só um conjunto novo mede generalização.
- **How to test:** BT-002 (10 avisos, criador independente, conjunto congelado, avaliador pré-registrado, uma execução).
- **Expected signal:** enhanced unsafe = 0; 0 omissões aprovadas; ambiguidades revisadas.
- **Observed result:** (BT-002, execução única)
  - Segurança: 0 aprovações inseguras pela definição enhanced, 0 omissões aprovadas, 2/2 ambiguidades perigosas revisadas, 0 aprovações falsas.
  - Utilidade nula neste conjunto: 0/4 aprovações corretas, revisão 10/10. Causa comum: nenhum aviso traz ISIN, e na F o ISIN é obrigatório e é a única chave da base de referência.
  - Semântica forte: tipo de evento 10/10, tratamento tributário 9/10, grounding 85/86.
  - A camada determinística generaliza pouco (50% de cobertura, contra 80%).
  - Risco latente registrado: rótulo depois do valor captura a data seguinte (data-base errada no BT2-02, segurada pela validação de ordem e pelo LLM).
- **Decision:** GO condicional para a etapa de OCR (critérios pré-registrados atendidos; limitações fail-safe). O caminho de aprovação não foi exercitado em dados independentes.
- **Status:** MODIFIED (segura e fail-safe em dados independentes; pouco útil; aprovação não validada de forma independente)
