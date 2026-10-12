# Multi-Agent Support System — Getnet Challenge

Validação atual: consulte [`docs/RELATORIO_VALIDACAO_FINAL.md`](docs/RELATORIO_VALIDACAO_FINAL.md) e os artefatos associados. Os relatórios V6/release anteriores documentam etapas históricas; suas contagens de testes e integrações pendentes não representam necessariamente o estado atual. A validação distingue LangGraph, HTTP, SQLite e Chroma reais de LLMs, embeddings e dados de clientes simulados.

O deadline total de uma conversa é configurável por `TOTAL_REQUEST_TIMEOUT_SECONDS` (90 segundos por padrão, incluindo espera pela sessão). `REQUEST_TIMEOUT_SECONDS` limita chamadas aos provedores. Solicitações da mesma sessão são serializadas dentro de um processo; múltiplos workers exigem coordenação distribuída. Credenciais de `API_CREDENTIALS_JSON` podem incluir `expires_at` ISO 8601 com fuso horário; tokens expirados são rejeitados.

Implementação do desafio **AI Hardcore Engineer – Multi-Agent Support System**. O contrato oficial da tarefa está preservado em [`docs/Desafio.md`](docs/Desafio.md). A **V6** consolida o projeto `definitivo-v3` (planner LLM, síntese, memória e CI) com as correções de segurança, testes e handoff, e fecha os três defeitos reproduzidos na auditoria da V5. Leia primeiro [`docs/RELATORIO_V6.md`](docs/RELATORIO_V6.md): nele distinguimos implementação, validação offline e testes integrados ainda pendentes.

## Requisitos entregues

| Obrigação do desafio | Implementação |
|---|---|
| Três agentes e comunicação entre agentes | Router/Planner, Knowledge (RAG), Customer Support (duas tools) e Web Search ligados pelo LangGraph; síntese e supervisor |
| POST JSON com `message`, `user_id` | `POST /chat` mantém ambos; `conversation_id` é opcional. `Authorization: Bearer` confirma a identidade declarada |
| RAG Getnet | Ingestão HTTPS Getnet → sanitização → chunking → OpenAI Embeddings → Chroma → retrieval filtrado → resposta grounded |
| Duas ferramentas | `get_sales_data` e `get_terminal_status` operam em dados mockados com identidade autenticada |
| Docker | Dockerfile non-root, Compose com volumes persistentes, healthcheck |
| Testes e avaliação | pytest, datasets de roteamento e multi-turn, scripts de smoke offline, CI e relatórios de cobertura |
| Extras | Segurança, handoff com fila, memória persistente, métricas, spans, feedback e planner LLM híbrido |

## Arquitetura

```text
POST /chat + Bearer token
   ├── verificar token × user_id; consultar sessão e ticket pendente
   └── Guardrail
        └── Router/Planner (LLM structured output ou fallback controlado)
             └── Knowledge (RAG) ──────┐
                 Customer Support ──────┤ sequência de até 3 especialistas
                 Web Search ────────────┘
                     ↓ revisão do supervisor após CADA especialista
                     ├── executar próximo especialista
                     ├── synthesis (combina evidências e ressalvas)
                     └── human escalation (caso pendente com ID)
                            ↓ operador responde pelo endpoint protegido
                        SQLite: memória, tickets e telemetria
```

**Por que LangGraph?** Não apenas para alternar entre rotas. Cada solicitação tem um plano limitado, cada resultado é revisado antes da próxima ação, e múltiplos especialistas podem colaborar antes da síntese. Um resultado fraco não cancela automaticamente os demais especialistas; o supervisor pode concluir o plano e escalar apenas as partes não resolvidas. Quando o RAG público falha, o supervisor pode adicionar uma única busca web restrita a URLs oficiais da Getnet, se houver Tavily e nenhum dado pessoal na consulta. O Router usa `with_structured_output` quando a chave OpenAI está configurada e fallback determinístico testável quando não está. O plano LLM **não pode** selecionar agentes arbitrários: somente nós da allowlist são executados, no máximo três.

O planejamento é limitado por design; não há agente autônomo de loops ilimitados nem execução paralela. Esse limite evita custos e ciclos inesperados. O contrato de estado do LangGraph declara explicitamente `usage`, `retrieval` e `web_getnet_only` para que as informações não se percam ao avançar entre nós. Em **todas** as consultas de Web Search — mesmo se o Router escolher somente esse especialista — a busca pública recebe apenas uma pergunta validada/sanitizada e o agente sintetizador não envia resultados de conta para outro LLM externo.

## Rodar localmente (Windows PowerShell)

Requisitos: **Python 3.12**, internet para instalar dependências, uma chave OpenAI para o RAG e opcionalmente uma chave Tavily para pesquisas gerais. As ferramentas de suporte usam **dados de demonstração** e não requerem integração bancária.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `.env` com suas chaves e **substitua todos os tokens demonstrativos**. Configure, por exemplo:

```dotenv
OPENAI_API_KEY=COLOQUE_SUA_CHAVE
TAVILY_API_KEY=COLOQUE_SUA_CHAVE
OPERATOR_TOKEN=TOKEN_LOCAL_FORTE_DO_OPERADOR
API_CREDENTIALS_JSON={"token-cliente-forte":{"user_id":"cliente1988","role":"customer"}}
```

**Não publique `.env` nem tokens reais no Git.** Os nomes/tokens na `.env.example` são exclusivamente ilustrativos. A API devolve `503` quando a identidade não foi configurada; não há modo anônimo silencioso.

Prepare a base de conhecimento da Getnet (demanda rede e embeddings):

```powershell
python -m scripts.ingest
```

Inicie:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Documentação: `http://127.0.0.1:8000/docs`; saúde: `GET /health`.

### Exemplo de chamada que respeita o desafio

```powershell
$headers = @{ Authorization = 'Bearer token-cliente-forte' }
$body = @{ message = "Explain Pix and check yesterday's payout"; user_id = 'cliente1988' } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/chat' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
```

A primeira resposta contém `conversation_id`; envie o mesmo campo nas chamadas posteriores para continuar o diálogo. Observe `plan`, `agents_used`, `sources`, `tools_used`, `requires_human`, `handoff_id` e `request_id`. Um resultado de suporte se refere **somente** ao `user_id` verificado pelo token. Para testar outra identidade, crie outra entrada em `API_CREDENTIALS_JSON`.

### Atendimento humano completo

Se a ferramenta/RAG falhar, faltar evidência ou o usuário solicitar um atendente:

1. O `HumanEscalationAgent` cria um único ticket `pending` por usuário e conversa, gravado em SQLite com índice único e transação segura para concorrência.
2. Enquanto estiver pendente, novas mensagens da sessão são armazenadas e não acionam mais ferramentas (o guardrail continua válido). O operador pode consultar o histórico da conversa pelo endpoint autorizado.
3. O operador consulta `GET /handoffs` e `GET /handoffs/{handoff_id}` com header `X-Operator-Token: TOKEN_LOCAL_FORTE_DO_OPERADOR`.
4. O operador responde `POST /handoffs/{handoff_id}/resolve`, JSON `{"resolution":"Orientação prestada"}`; o status e a resposta humana são persistidos atomicamente no mesmo SQLite. A auditoria `resolved_by` é gerada **pela credencial autenticada**, nunca por um campo do cliente (o campo antigo é aceito por compatibilidade, mas ignorado). É possível utilizar `X-Operator-Token` (identidade `local-operator`) ou um Bearer mapeado para `role=operator` no `API_CREDENTIALS_JSON`.
5. O cliente pode consultar **apenas seus próprios** casos em `GET /my-handoffs/{conversation_id}` (Bearer). Após `resolved`, os próximos turnos usam o histórico, incluindo o retorno humano.

Resolução é idempotente: a segunda tentativa não grava resposta duplicada. Uma implantação com mais de uma réplica exigiria persistência centralizada e gestão de segredos/identidades corporativa.

### Operação e observabilidade

Os seguintes endpoints exigem o token de operador:

- `GET /metrics`: contadores de requisições/handoffs/degradações, duração média e p50/p95, agentes, tokens reportados e avaliações recebidas.
- `GET /traces/{request_id}`: duração/status de cada agente e das ferramentas do suporte.
- `GET /conversations/{conversation_id}?user_id=...`: histórico para investigação autorizada.

`POST /feedback` usa Bearer do **mesmo cliente** que efetuou a requisição: `{"request_id":"UUID da resposta", "rating":5}`. Telemetria não salva corpos de mensagens. Usage de tokens é somado **apenas quando o provider retorna usage**; números ausentes permanecem desconhecidos, não zero. O custo em USD só é estimado quando a empresa configurar preços por milhão em `INPUT_PRICE_PER_MILLION_USD` e `OUTPUT_PRICE_PER_MILLION_USD`. A versão atual contabiliza os tokens reportados de Router estruturado, Knowledge, Web Search e Synthesis. Custos do serviço de embeddings, Tavily e outros fornecedores podem precisar de telemetria própria e não são presumidos como zero.

### RAG: ingestão, armazenamento, recuperação e geração

- `scripts/ingest.py` visita URLs públicas da Getnet, incluindo `https://www.getnet.net/en`, Pix, Link de Pagamento, Get Conta, Crediário e páginas de antecipação. Restringe HTTPS e hosts Getnet **antes de cada requisição e redirect**, limita download por streaming, remove scripts/navegação e divide conteúdo com overlap. Verifique robots.txt, políticas e permissões antes de executar scraping.
- `OpenAIEmbeddings` produz vetores guardados no Chroma persistente. IDs estáveis por URL/posição garantem upsert idempotente; trechos antigos daquela URL são removidos **após** a escrita bem-sucedida da nova versão, impedindo que texto desatualizado contamine a base.
- `KnowledgeRetriever` executa top-k com limiar `RAG_MIN_RELEVANCE`, e o Knowledge Agent responde apenas com trechos que tenham fonte rastreável.
- Falta de evidência ou indisponibilidade levam a abstention + handoff. O Knowledge Agent usa saída estruturada `supported` + `citation_ids`; fontes inválidas, referências inexistentes e respostas sem trecho citado são recusadas. `confidence` representa **relevância estimada do retrieval**, não prova de veracidade. O dataset de groundedness precisa de validação com modelo/embeddings reais.

## Docker

```powershell
Copy-Item .env.example .env
# Edite as credenciais e chaves no .env
# Rode ingestão antes de avaliar perguntas RAG; veja os comandos locais acima.
docker compose up --build -d
```

Compose usa volumes `vector_data` e `state_data`; o container não roda como root. **Primeiro ingira a base no mesmo volume do container**; ingeri-la apenas no diretório local do host não preenche automaticamente o volume Docker. Exemplo:

```powershell
docker compose exec api python -m scripts.ingest
```

## Testes e avaliação

```powershell
python -m pytest -q
python -m pytest -q --cov=app --cov-report=term-missing
python -m scripts.evaluate --mode router --output router_eval.json
python -m scripts.evaluate_multiturn --mode router --output multiturn_eval.json
python -m scripts.evaluate_feedback_v6
python -m scripts.offline_api_smoke
python -m scripts.offline_web_privacy_smoke
python -m scripts.offline_graph_smoke
python -m scripts.offline_rag_smoke
python -m scripts.offline_api_stress
```

- `tests/unit`: identidade/autorização, Router, ferramentas, fila concorrente, resolução atômica, memória multiusuário, política do supervisor, telemetria.
- `tests/integration`: grafo e API reais com dependências instaladas, ferramentas mockadas, limites de dados e handoff.
- `tests/evaluation`: dataset de **dez perguntas** e cenários adversariais/multi-turn.
- `scripts/evaluate_feedback_v6.py`: gate determinístico de **16 cenários adicionais** de regressão da auditoria (intenção mista, novo tópico, seguimento e privacidade).
- `scripts/offline_web_privacy_smoke.py`: executa o WebSearchAgent real com ferramentas e geração simuladas; não compartilha conteúdo privado com o provedor.
- `scripts/offline_api_smoke.py`: executa **FastAPI e SQLite reais**, simulando somente o grafo.
- `scripts/offline_graph_smoke.py`: executa os nós reais do fluxo com transições LangGraph **emuladas**, aplicando o filtro de chaves do estado.
- `scripts/offline_rag_smoke.py`: executa a lógica real de citação/abstenção do Knowledge Agent, com recuperador e LLM simulados.
- `scripts/offline_api_stress.py`: 60 chamadas HTTP de handoff e 40 resoluções de operador concorrentes; FastAPI + SQLite reais, grafo simulado. **Nenhum desses três substitui a integração real.**
- `scripts/evaluate.py --mode api` e `scripts/evaluate_multiturn.py --mode api` exigem API em execução e variável de ambiente `EVAL_BEARER_TOKEN` com credencial vinculada a `cliente1988`; veja `docs/VALIDACAO_E_LIMITACOES.md`.

CI em `.github/workflows/ci.yml` instala dependências, compila, roda pytest/coverage e constrói Docker. A matriz de critérios, os gates de aceite e os limites da V6 estão em [`docs/RELATORIO_V6.md`](docs/RELATORIO_V6.md). Não incluí vídeo nesta entrega, conforme escopo combinado.

## Limitações e segurança de produção

- Tokens locais são adequados **apenas à demonstração**; em produção trocar por IdP/JWT validado por assinatura, TLS, rate limits, políticas de consentimento/retenção e secret manager. Não expor porta Docker publicamente com tokens de exemplo.
- SQLite é adequado a execução single-service, não cluster multinó com alta disponibilidade. Há persistência durável e isolamento, mas não uma UI de operador ou alertas SLA.
- O grafo faz supervisão sequencial limitada, não planejamento/replanejamento ilimitado nem deliberação livre de agentes. Os testes offline não verificam qualidade semântica da geração real.
- RAG e busca dependem de chaves, rede, disponibilidade e conteúdo atual das páginas Getnet. Sem ingestão, o agente corretamente se abstém.
- Dados de vendas e terminal são **mockados** e identificados como demonstrativos nas respostas; não representam contas reais, datas atuais de repasse nem integração bancária. Os escores no feedback foram atribuídos à versão antiga e não constituem notas desta versão.

Veja [`docs/MATRIZ_REQUISITOS.md`](docs/MATRIZ_REQUISITOS.md) e [`docs/VALIDACAO_E_LIMITACOES.md`](docs/VALIDACAO_E_LIMITACOES.md) antes da submissão.

### Avaliação opcional de groundedness com juiz LLM

Depois de ingerir a base, definir `OPENAI_API_KEY`, configurar `EVAL_BEARER_TOKEN` e subir a API:

```powershell
python -m scripts.evaluate_grounding --output grounding_report.json
```

O script consulta a API e recupera trechos do Chroma para um **juiz LLM estruturado** marcar afirmações não sustentadas. Casos que escalam por falta de evidência são reportados como `abstained`, não como acertos. O juízo de um segundo LLM **não equivale à validação humana**; é necessário calibrá-lo com respostas rotuladas por especialistas. O script não foi executado nesta revisão sem serviços externos disponíveis.

## Situação comprovada da V6

No ambiente de revisão: **69 testes pytest passaram, 7 módulos foram ignorados** porque LangGraph/LangChain não estão instalados; avaliação original **10/10**, continuidade **5/5**, matriz adicional do feedback **16/16**, além de testes HTTP, concorrência e grafo emulado aprovados. Esses resultados são **offline**, não uma certificação E2E. A CI tem gate para reprovar skips e inclui testes com o LangGraph real quando as dependências estão disponíveis. A imagem Docker pré-cria diretórios persistentes graváveis pelo usuário non-root; a execução do Docker também deve ser validada fora deste ambiente.

O projeto não foi publicado nem teve vídeo gravado, conforme solicitado. O enunciado oficial preservado em `docs/Desafio.md` contém uma exigência de vídeo; a decisão de não incluir vídeo faz parte do escopo desta entrega, não altera essa exigência original.
