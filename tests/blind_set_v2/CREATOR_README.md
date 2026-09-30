# Conjunto sintético BT2 — Avisos de Eventos Corporativos (fictício)

## Como este conjunto foi criado

Todos os documentos, emissores, CNPJs, ISINs, tickers, datas e valores são
**fictícios**, criados especificamente para este exercício de teste. Nenhuma
companhia real, CNPJ real ou evento real foi utilizado. As coincidências de
nomes com empresas reais, se existirem, são involuntárias.

Os 10 avisos (`BT2-01.txt` a `BT2-10.txt`) foram escritos manualmente para
simular a variedade natural de comunicados de RI/CVM/B3 de diferentes
companhias brasileiras: alguns em formato de "Aviso aos Acionistas" formal,
outros como "Fato Relevante" ou "Comunicado ao Mercado", com diferenças de
estrutura, ordem das informações, terminologia (ex.: "data-base" vs.
"acionistas com posição em"), formatos de data (`22/04/2024`, `02.05.2024`,
"10 de abril de 2024") e formas de expressar proporções ("1 para 3", "10%",
"razão de 5 para 1").

A base de referência (`golden_records.csv`) foi construída à parte, contendo
todos os emissores/tickers citados nos avisos (exceto um, propositalmente
ausente — ver BT2-10) mais um ativo adicional (Trilha Agro S.A. / TRAG3) que
não aparece em nenhum aviso, para simular uma base de mercado mais ampla que
o lote de eventos do dia.

O `ground_truth.json` foi elaborado depois dos avisos, lendo cada documento
isoladamente e extraindo apenas o que está literalmente escrito. Onde o
aviso não traz uma informação, o campo foi marcado `absent`; onde o aviso
declara explicitamente que a informação virá depois, foi marcado `pending`;
onde o campo não faz sentido para o tipo de evento, foi marcado
`not_applicable`. Todas as evidências são trechos copiados literalmente dos
respectivos `.txt`.

## Lista de casos e intenção de cada um

| Caso | Emissor | Evento | Intenção |
|---|---|---|---|
| BT2-01 | Cerrado Mineração S.A. (CRDO3) | DIVIDEND | Caso simples e completo, isenção fiscal explícita, formato de aviso de RI clássico → `AUTO_APPROVE`. |
| BT2-02 | Aurora Têxtil Nordeste S.A. (AURT3) | JCP | Caso completo com alíquota padrão de 15%, valor líquido consistente com o bruto, formato de lista → `AUTO_APPROVE`. |
| BT2-03 | Rio Bravo Energia S.A. (RBRA4) | SPLIT | Desdobramento completo, com cláusula operacional sobre frações/leilão na B3 (contexto material mas não bloqueante) → `AUTO_APPROVE`. |
| BT2-04 | Planalto Siderurgia S.A. (PLSD4) | REVERSE_SPLIT | Grupamento com data ex e data de crédito **expressamente pendentes** de homologação na B3 → `REVIEW_REQUIRED` (campo obrigatório pendente). |
| BT2-05 | Vale do Sol Alimentos S.A. (VSOL3) | BONUS_SHARES | Bonificação com proporção expressa de duas formas (percentual e razão), ISIN ausente do texto (mas ativo localizável via ticker/CNPJ) → `AUTO_APPROVE`. |
| BT2-06 | Costa Verde Logística S.A. (CVLG3) | DIVIDEND | Dividendo com valor adicional **condicionado** a ratificação futura em AGO sem data definida, e data de pagamento pendente → `REVIEW_REQUIRED`. |
| BT2-07 | Nortline Transportes S.A. (NTLN3) | JCP | JCP com alíquota de IRRF **expressamente pendente** de divulgação, impossibilitando cálculo do valor líquido → `REVIEW_REQUIRED`. |
| BT2-08 | Serra Alta Papel e Celulose S.A. (SRAL4) | OTHER | Cisão parcial — evento societário fora dos tipos padronizados, com proporção e efeitos tributários pendentes de laudo de avaliação → `REVIEW_REQUIRED`, classificado como `OTHER`. |
| BT2-09 | Horizonte Digital S.A. (HZDG3) | UNRESOLVED | Caso **legitimamente ambíguo**: o próprio aviso declara que o provento pode ser dividendo, JCP, ou combinação de ambos, a depender de deliberação futura → `UNRESOLVED` / `REVIEW_REQUIRED`. |
| BT2-10 | Aviamento Capital S.A. (AVCP3) | REVERSE_SPLIT | Grupamento **completo e consistente**, porém o emissor/ticker não consta na base de referência fornecida → `REVIEW_REQUIRED` apesar da completude textual, para testar a regra de matching contra a base. |

## Observações de fidelidade

- Nenhuma "pegadinha" artificial (ex.: erros ortográficos propositais,
  armadilhas de formatação) foi introduzida; toda ambiguidade ou lacuna
  decorre de situações plausíveis do mundo real (deliberações condicionadas,
  homologações operacionais pendentes, cisões sem laudo pronto, dupla
  natureza de provento a depender de apuração fiscal futura).
- Cada `evidence` no `ground_truth.json` foi conferida manualmente contra o
  texto correspondente em `BT2-XX.txt` para garantir correspondência literal.
- Os cálculos de valor líquido/bruto e as proporções expressas de mais de
  uma forma foram verificados aritmeticamente (ex.: BT2-02: 0,30 × (1 − 0,15)
  = 0,255; BT2-05: 10% equivale a 1 nova ação para cada 10 possuídas).
