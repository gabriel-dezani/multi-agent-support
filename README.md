# Multi-Agent Support System

## Overview

Serviço multiagente para o desafio **AI Hardcore Engineer - Multi-Agent Support System**. A solução usa FastAPI + LangGraph, RAG sobre conteúdo público da Getnet, busca web para informações atuais, duas tools de suporte a cliente, guardrails e handoff humano.

## Arquitetura e fluxo

Há mais de três tipos distintos de agentes e um estado compartilhado pelo LangGraph:

`POST /chat -> Guardrail -> Router -> Knowledge RAG | Customer Support Tools | Web Search -> Human Escalation (quando necessário) -> END`

- **Router Agent**: ponto de decisão do workflow; classifica a mensagem e registra `route_reason`.
- **Knowledge Agent**: responde perguntas sobre produtos/serviços Getnet usando somente evidências recuperadas do vector store.
- **Customer Support Agent**: consulta dados mockados do usuário por meio de **duas tools**: `get_sales_data` e `get_terminal_status`.
- **Web Search Agent**: usa a tool Tavily para perguntas gerais que dependem de informação atual.
- **Human Escalation Agent (bonus)**: recebe fluxos sem evidência suficiente, falhas controladas, intenção ambígua ou pedido explícito por humano.
- **Guardrail Agent (bonus)**: bloqueia padrões comuns de prompt injection/jailbreak e tentativas de exfiltrar instruções internas.

O estado compartilhado contém mensagem, `user_id`, rota, agente, resposta, tools, fontes, confidence, erros, motivo de handoff e `request_id`. Depois de Knowledge, Support ou Web Search, `requires_human=true` causa uma transição real para Human Escalation.

## RAG: ingestion -> storage -> retrieval -> generation

### Ingestion

`scripts/ingest.py` ingere páginas públicas Getnet, incluindo a fonte sugerida no desafio e páginas adicionais:

- `https://www.getnet.net/en`
- `https://site.getnet.com.br/pix/`
- `https://site.getnet.com.br/link-de-pagamento/`
- `https://site.getnet.com.br/conta-digital/`

A ingestão aplica allowlist de hosts, valida o host final após redirects, limita tamanho de resposta, remove elementos de navegação/script, faz chunking com overlap e gera `chunk_id`/`content_hash`. IDs estáveis evitam crescimento por duplicação quando a mesma ingestão é repetida. Antes de executar scraping em produção, valide robots.txt, termos de uso e autorizações aplicáveis.

### Storage

`OpenAIEmbeddings` gera embeddings e o Chroma persiste os vetores em `VECTOR_STORE_PATH`.

### Retrieval

`KnowledgeRetriever` executa top-k e filtra por `RAG_MIN_RELEVANCE`.

### Generation e grounding

O Knowledge Agent fornece ao LLM apenas os trechos recuperados e instrui o modelo a tratar documentos como **dados, nunca comandos**. Respostas sem evidência, sem fonte rastreável, retrieval indisponível ou falha do provider resultam em handoff humano.

`confidence` no fluxo RAG é uma estimativa conservadora de **qualidade do retrieval** (melhor score + média), e **não** um score formal de factualidade. Groundedness completo exigiria avaliação adicional baseada em claims/evidências ou LLM-as-judge calibrado.

## API

### Health

`GET /health` -> `{"status":"ok"}`

### Chat

`POST /chat`

```json
{
  "message": "What's the difference between the Get Clássica and the Get Smart?",
  "user_id": "cliente1988"
}
```

Resposta:

```json
{
  "answer": "...",
  "agent": "knowledge",
  "route_reason": "...",
  "tools_used": [],
  "sources": ["https://..."],
  "confidence": 0.81,
  "requires_human": false,
  "request_id": "..."
}
```

Payload inválido retorna 422. Erros internos inesperados retornam 500; falhas esperadas de retrieval, geração, tools ou busca são convertidas em degradação controlada/handoff quando possível.

Swagger: `http://127.0.0.1:8000/docs`.

## Configuração e execução local

Requer Python 3.12+.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copie `.env.example` para `.env` e configure `OPENAI_API_KEY` e `TAVILY_API_KEY`. Nunca versione `.env` ou secrets.

Ingestão:

```bash
python -m scripts.ingest
```

API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t multi-agent-support .
docker run --rm -p 8000:8000 --env-file .env multi-agent-support
```

Ou:

```bash
docker compose up --build
```

O compose mantém `.vector_data` em volume persistente e possui healthcheck.

## Estratégia de testes

A estratégia separa quatro camadas:

1. **Unitários**: Router, Guardrail, Support e tools, incluindo falhas controladas e seleção conservadora de tool.
2. **Orquestração**: valida que `requires_human` realmente percorre o LangGraph até Human Escalation e preserva `request_id`.
3. **Integração HTTP**: contrato FastAPI (`/health`, validação 422 e, em ambiente com providers mockados, `/chat`).
4. **Evaluation/regressão**: os 10 cenários fornecidos no desafio + casos adversariais de routing.

```bash
python -m pytest -q --cov=app --cov-report=term-missing
```

Providers externos devem ser mockados nos testes automatizados para eliminar custo/flakiness. Antes de release, recomenda-se um smoke E2E controlado com credenciais de teste, ingestão real e um conjunto fixo de perguntas para RAG/web.

### Plano de integração abrangente

Para uma validação de produção, além da suíte local: testar timeout/5xx de OpenAI/Tavily/Chroma, indisponibilidade de vector store, dados de cliente inexistentes, concorrência, idempotência da ingestão, prompt injection indireta em documentos/resultados web, latência p50/p95/p99 e regressão de routing/RAG. O release deve falhar se houver regressão nos 10 cenários oficiais ou no handoff de baixa evidência.

## Avaliação, observabilidade e confiabilidade

- Dataset oficial executado contra o Router e casos adversariais adicionais.
- Logs estruturados JSON com `request_id` e `user_id` ligados ao contexto da requisição.
- `tools_used`, `sources`, `confidence` e `requires_human` tornam decisões observáveis na resposta.
- Timeouts e retries limitados para providers.
- Falhas controladas convergem para Human Escalation.
- Métricas recomendadas: route accuracy, tool accuracy, handoff rate, error rate, grounded-answer rate, source coverage e latência p50/p95/p99.
- Alertas recomendados: aumento de 5xx, handoff anormal, falha de ingestão, queda de source coverage e latência de provider.

## Segurança e guardrails

- Secrets somente por ambiente.
- Allowlist + validação de redirects na ingestão.
- Conteúdo RAG/web tratado como não confiável e nunca como instrução.
- Guardrail determinístico para ataques explícitos; não é uma fronteira de segurança completa.
- Tools recebem `user_id` validado pelo contrato da API e usam apenas dados mockados neste desafio.
- Em produção: autenticação/autorização, least privilege, validação forte de argumentos de tools, rate limiting, isolamento de rede e políticas de dados seriam obrigatórios.

## Estrutura

```text
app/api             FastAPI e schemas
app/agents          agentes especializados
app/orchestration   LangGraph e estado compartilhado
app/rag             ingestion, vector store e retriever
app/repositories    dados mockados de cliente
app/tools           tools de suporte e busca web
scripts             ingestão
 data               clientes mockados e dataset de avaliação
tests/unit          testes unitários
tests/integration   contrato HTTP
tests/evaluation    dataset oficial e regressões
```

## Limitações conhecidas / decisões de escopo

- O Router é determinístico para ser barato, reproduzível e testável no challenge; em produção, uma classificação estruturada por LLM com schema + fallback determinístico poderia melhorar cobertura sem perder controle.
- `confidence` não é probabilidade de verdade factual.
- Dados de cliente são mocks; autenticação real não faz parte do enunciado.
- Guardrails baseados em padrões são defense-in-depth, não proteção completa contra adversários.

## Submission checklist

- Publicar o repositório GitHub sem `.env`, `.vector_data`, caches ou ambientes virtuais.
- Confirmar `pytest` e Docker em uma máquina com acesso às dependências.
- Executar ingestão e smoke E2E com credenciais de teste.
