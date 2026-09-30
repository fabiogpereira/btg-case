# BT-002 — criador independente do blind set v2

## Quem criou

| Item | Valor |
|---|---|
| Modelo | `claude-sonnet-5` (servido: `claude-sonnet-5`). Família diferente do `claude-opus-5` usado pela variante F, para reduzir vieses correlacionados |
| Forma | **uma única chamada direta à API da Anthropic** (`messages.stream`), feita por `creator/harness.py` |
| Contexto | limpo: sem system prompt, sem histórico, sem ferramentas (`tools: null`), sem arquivos anexados |
| Entrada | exatamente o texto de `creator/PROMPT.txt` (SHA-256 `ee488bc7…6bb716`, registrado em `creator/request.json`) |
| Parâmetros | `max_tokens` 64000, `thinking: adaptive` |
| Id da mensagem | `msg_011CfYq1Ppmuj9UqKMfN4skD` |
| Uso | 2.671 tokens de entrada, 42.223 de saída; `stop_reason` end_turn; 332,7 s |
| Data | 2026-09-30 |
| Saída bruta | `creator/response_raw.txt` (sem edição; SHA-256 em `creator/response_meta.json`) |
| Extração | os blocos `<<<FILE: …>>>` foram gravados sem alteração de conteúdo; depois veio a única correção registrada em `QA.md` (CNPJs) |

## Ferramentas e arquivos acessíveis ao criador

- **Ferramentas:** nenhuma. A API foi chamada sem `tools`; o modelo só pode responder texto.
- **Arquivos:** nenhum. O modelo não tem acesso a disco, ao repositório, ao `CLAUDE.md`, a prompts, código, datasets, resultados ou a esta conversa. A única informação recebida é o prompt.
- Quem gravou os arquivos foi o harness (código determinístico), não o modelo.

## Prompt

`creator/PROMPT.txt`, em duas partes:

1. **Brief neutro:** o texto fornecido pelo usuário, verbatim.
2. **Anexo técnico:** formato de entrega (blocos de arquivo); cabeçalho do `golden_records.csv`; convenções de identificadores; schema do `ground_truth.json`, com as mesmas chaves do BT-001, para que o avaliador pré-registrado se aplique sem mudança; e o mesmo critério de negócio de roteamento dado ao criador do BT-001 (completude por tipo de evento; ativo na base; contexto operacional ou jurídico não torna o caso ambíguo por si só).

**Desvio declarado.** O usuário pediu "APENAS um brief equivalente". O anexo técnico foi acrescentado porque sem ele o gabarito não seria avaliável pelo avaliador pré-registrado. Ele define formato e critério de negócio de roteamento, e não menciona failure modes, casos anteriores, componentes da F, tratamento tributário da F, gate de cobertura ou detector de contradições.

Ainda assim:
- a lista de valores de `affects` e os códigos de base de IR (`GROSS_AMOUNT | EXCESS_OVER_THRESHOLD | EXEMPT | NOT_STATED`) refletem o vocabulário do projeto;
- o critério de roteamento é o contrato de campos obrigatórios do sistema.

## Evidências e limitações de independência

**Garantido tecnicamente.**
- O criador não viu código, prompts, datasets, resultados nem o projeto (contexto de API sem ferramentas).
- A F não processou nenhum documento antes do congelamento: o primeiro contato é o run oficial.

**Não garantido.**
1. O orquestrador (Claude Opus 5.5, nesta sessão), que conhece o projeto, escreveu o anexo técnico, o harness e a revisão de QA. A revisão leu os documentos e o gabarito antes do run, sem alterar a F.
2. Mesmo fornecedor e família de modelos (Claude) do interpretador da F: vieses de linguagem podem ser correlacionados, mesmo com modelos diferentes (Sonnet 5 × Opus 5).
3. O modelo pode ter visto, no pré-treino, padrões genéricos de avisos parecidos com os dos conjuntos anteriores. Um indício são os CNPJs sequenciais de placeholder, idênticos aos dos conjuntos anteriores, corrigidos no QA.
4. O vocabulário do schema (item acima) pode orientar levemente o que o criador considera material.
