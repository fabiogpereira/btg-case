# Brief entregue ao criador independente do blind set

Registro literal do que o subagente criador recebeu. Ele **não** recebeu nada além disto: nenhum código, prompt, challenge set, gabarito anterior, failure mode, resultado ou decisão do projeto.

- **Criador:** subagente `general-purpose`, modelo **Sonnet**. Família diferente do `claude-opus-5` usado pela variante E, para reduzir vieses correlacionados. Contexto novo, sem acesso a esta conversa.
- **Id do agente:** `a84b2167da87968a6`.
- **Data:** 2026-09-30.
- **Onde escreveu:** diretório fora do repositório (scratchpad); depois copiado byte a byte para `tests/blind_set/` pelo orquestrador.

---

Você é um criador independente de dados de teste. Sua tarefa é criar um conjunto de teste cego (blind test) para um sistema que você NÃO conhece e NÃO deve inspecionar.

REGRAS DE INDEPENDÊNCIA (obrigatórias):
- NÃO leia, liste, pesquise, abra ou execute nada relativo a arquivos ou diretórios já existentes no computador. Não use Read, Glob, Grep, ls, cat, find, git, nem nenhum comando que inspecione o disco.
- Use APENAS a ferramenta de escrita (Write) para criar arquivos novos dentro do diretório de saída abaixo. Não escreva em nenhum outro lugar.
- Não tente descobrir como o sistema avaliado funciona. Trabalhe só com este briefing e seu conhecimento geral do domínio.
- Ao final, declare explicitamente todas as ferramentas que usou e todos os arquivos que criou.

DIRETÓRIO DE SAÍDA (absoluto): <scratchpad>\blind_set

BRIEFING DO DOMÍNIO
Crie entre 10 e 15 avisos fictícios de eventos corporativos em português (Brasil), com variação de linguagem e estrutura. Os documentos devem representar uma mistura plausível de eventos como dividendos, juros sobre capital próprio, grupamentos, bonificações e outros eventos simples relacionados a ações.

Inclua uma combinação de casos:
- claros;
- com linguagem alternativa;
- com informações ausentes;
- com informação explicitamente pendente;
- com negação;
- com condições tributárias;
- com exceções;
- com datas expressas de formas variadas;
- com contexto operacional que não altera o evento;
- com pelo menos alguns casos ambíguos em que revisão humana seja a resposta correta.

Não crie pegadinhas artificiais apenas para enganar um sistema. Os documentos devem parecer avisos plausíveis de uma operação financeira real (estilo "Aviso aos Acionistas" / "Fato Relevante" de companhias abertas brasileiras, padrão B3/CVM). Todos os nomes de empresas, CNPJs, ISINs e tickers devem ser fictícios e inventados por você. Varie livremente o layout (tabela rótulo/valor, só texto corrido, listas, etc.).

Convenções de identificadores (para plausibilidade): ISIN brasileiro com 12 caracteres no padrão "BR" + 4 letras + "ACN" + "OR" (ações ordinárias) ou "PR" (preferenciais) + 1 dígito; ticker com 4 letras + 3 (ON) ou 4 (PN); CNPJ no formato NN.NNN.NNN/NNNN-NN. Valores monetários em reais no formato brasileiro (ex.: R$ 0,4500000000 ou R$ 1,25).

REGRAS DE NEGÓCIO para o roteamento esperado (use-as para decidir expected_routing):
- AUTO_APPROVE somente se o aviso estiver completo para o tipo de evento, internamente consistente, sem ambiguidade relevante, e o ativo estiver presente na base de referência (golden records).
- Completo significa: para proventos em dinheiro (dividendos, JCP), valor bruto por ação, data com (data-base), data ex e data de pagamento; para JCP, também a alíquota do imposto retido e o valor líquido por ação; para eventos em ações (grupamento, desdobramento, bonificação), a proporção, a data com e a data ex.
- REVIEW_REQUIRED se: faltar informação obrigatória; alguma informação obrigatória estiver declarada como pendente/"a definir"; houver ambiguidade real sobre o tipo do evento ou sobre um valor/condição que afete o registro financeiro; houver inconsistência interna (ex.: datas em ordem impossível, título que contradiz o conteúdo, valor líquido incompatível com bruto e alíquota); ou o ativo não estiver na base de referência.
- Contexto operacional (procedimentos, tratamento de frações, instruções administrativas) e contexto legal genérico não tornam o caso ambíguo por si só.

ARQUIVOS A CRIAR (todos UTF-8):
1. Um arquivo de texto por aviso: BT-01.txt, BT-02.txt, ... (conteúdo = o texto do aviso, como seria lido de um PDF; é a fonte textual do documento).
2. golden_records.csv — base de referência exclusiva deste teste, com EXATAMENTE este cabeçalho: `emissor,cnpj,isin,ticker,classe,segmento_listagem,status` (classe = ON ou PN; status = ativo). Inclua os ativos que aparecem nos avisos (exceto se você quiser, intencionalmente, um ou mais casos de ativo ausente da base) e mais 3 a 5 ativos adicionais que não aparecem em nenhum aviso.
3. ground_truth.json — gabarito separado (schema com case_id, document_file, case_categories, event_type, issuer, fields [approval_date, record_date, ex_date, payment_date, share_credit_date, gross_amount_per_share, net_amount_per_share, withholding_tax, ratio] com status present/absent/pending/not_applicable, value e evidence literal, material_qualifiers, non_material_context, expected_validation_findings, expected_routing, routing_reason). material_qualifiers: somente trechos que, se removidos, mudariam algum elemento do registro financeiro; contexto que não muda nada vai em non_material_context.
4. README.md — metodologia, lista de casos e declaração de independência.

Revise você mesmo, antes de terminar, que cada "evidence" aparece literalmente no aviso correspondente e que as datas/valores do gabarito conferem com o texto.

(O texto integral do schema JSON enviado está reproduzido no item 3 acima de forma resumida; o schema completo, com exemplos de valores, foi enviado no prompt original e corresponde exatamente às chaves presentes em `ground_truth.json`.)
