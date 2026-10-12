> **Registro histórico de revisão anterior.** Para o estado atual da V6, consulte [RELATORIO_V6.md](RELATORIO_V6.md) e [RESULTADOS_EXECUTADOS_V6.json](RESULTADOS_EXECUTADOS_V6.json).

# Validação da implementação consolidada (2026-10-12)

## Fontes comparadas

1. `Desafio.zip/Desafio.md`: requisitos oficiais.
2. `Desafio.zip/multi-agent-support-definitivo-v3.zip`: branch **agentic**, escolhida como base por conter Router LLM com structured output, agente de síntese, memória, fila humana, eval multi-turn, CI e `pyproject.toml`.
3. `multi-agent-support-definitivo(1).zip`: primeira solução elogiada por RAG e Docker, mas sem memória nem colaboração.
4. `multi-agent-support-revisado-v1.zip`: primeiro esforço em autenticação e persistência, ainda limitado.
5. `multi-agent-support-revisado-alta-v2.zip`: supervisor/revisão e métricas, sem planejamento LLM nem Synthesis Agent.
6. `multi-agent-support-revisado-testes-v3.zip`: hardening do isolamento, testes de concorrência/ticket, avaliação adversarial e smoke HTTP; foi a segunda fonte para a consolidação.
7. `feedback_gabriel_dezani.md`: onze notas originais, principais lacunas e comparativo com candidato de referência.

## Decisão de arquitetura

Não se escolheu uma versão inteira por recência. **Partiu-se de `definitivo-v3`** pelo mecanismo agentic mais fiel ao desafio. Incorporou-se da versão revisada v3 a autenticação local/isolamento, tratamento de concorrência, estados de ticket, telemetria persistente e testes ofensivos. Foi criado supervisor sequencial com etapa de revisão após cada especialista, replanejamento restrito quando RAG público não sustenta a resposta, preservação de resultados parciais e isolamento HTTP por identidade.

### Comportamento de falhas

- Falha de agente não cancela os especialistas restantes no plano.
- Se uma parte não puder ser atendida, o ticket humano mantém os resultados comprovados de outras partes, sem apresentá-los como solução completa.
- Se só Knowledge falhar e Tavily estiver configurado, pode haver **uma única busca em fontes Getnet**, sempre com filtro de host HTTPS e sem consulta que contenha dígitos/`@`; nunca usar dados privados de Support na busca pública.
- Histórico de conversa fica isolado por token de cliente e `conversation_id`.
- Tickets usam índice único parcial e transação `BEGIN IMMEDIATE`; resposta de humano só é gravada uma vez.
- Falha de autenticação/configuração causa 401/403/503, não uso silencioso do `user_id` declarado.

## Execuções efetivamente realizadas

| Verificação | Resultado | Alcance |
|---|---|---|
| `python -m compileall -q app scripts tests` | Aprovada | Sintaxe Python |
| `python -m pytest -q -p no:ddtrace` | **52 testes aprovados, 6 módulos ignorados** | Unidades, dataset de rota, memória/segurança/tickets/telemetria; módulos que requerem LangGraph/LangChain não executados |
| `python -m scripts.evaluate --mode router` | **10/10 classificação correta** | Roteador fallback determinístico, não respostas de LLM |
| `python -m scripts.evaluate_multiturn --mode router` | **5/5 turnos classificados corretamente** | Roteamento com histórico simulado |
| `python -m scripts.offline_api_smoke` | **25 asserções aprovadas** | API real FastAPI e SQLite real; **grafo simulado** |
| `python -m scripts.offline_graph_smoke` | **19 asserções aprovadas** | Nós da orquestração reais e políticas; transições **emuladas**, não LangGraph instalado |
| Docker build e `docker compose` | Não executado | Docker indisponível neste ambiente |
| `pytest` com LangGraph/LangChain/Chroma real | Não executado | Dependências não presentes; instalação falhou por DNS/rede |
| Avaliação RAG OpenAI / Tavily | Não executada | Chaves/serviços externos e ingestão local não configurados |
| Juiz LLM de groundedness | Implementado como script opcional, **não executado** | Depende de RAG ingerido, LLM e calibração humana |

**Estes números não são notas estimadas da banca.** Não se pode concluir que os critérios receberam 8,5+ até uma avaliação externa. O objetivo da implementação é corrigir as lacunas técnicas do feedback com evidências reprodutíveis.

## Como reproduzir a validação integral (PowerShell com internet)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edite API_CREDENTIALS_JSON, OPENAI_API_KEY, TAVILY_API_KEY, OPERATOR_TOKEN
python -m pytest -q
python -m pytest --cov=app --cov-report=term-missing
python -m scripts.offline_api_smoke
python -m scripts.offline_graph_smoke
python -m scripts.ingest
uvicorn app.main:app --reload
```

Em outro PowerShell, com token associado a `cliente1988`:

```powershell
$env:EVAL_BEARER_TOKEN = 'SEU_TOKEN_DE_TESTE'
python -m scripts.evaluate --mode api --output api_eval.json
python -m scripts.evaluate_multiturn --mode api --output multiturn_eval.json
python -m scripts.evaluate_grounding --output groundedness.json
```

Execute também `docker compose up --build -d`, seguido por `docker compose exec api python -m scripts.ingest` para preencher o **volume da aplicação**. Faça testes cruzados com dois tokens diferentes, reinicie o container para verificar retenção da memória/tickets e grave a demonstração de fluxo multiagente e handoff.

## Melhoria ainda pendente para prova de produção

- Validar LangGraph/Chroma/Tavily/OpenAI e Docker com credenciais reais; a implementação não foi testada nesses serviços aqui.
- Calibrar LLM-as-judge com rótulos humanos e registrar taxa de alucinação, recall@k e limitações de citações.
- Calibrar custos dos serviços externos: Router, Knowledge, Web e Synthesis agora reportam usage se fornecido pelo provider; custos de embeddings e Tavily ainda exigem métricas próprias.
- Validar privacidade/consentimento/retenção de mensagens e gestão de segredos, aplicar TLS, rate limiting e IdP para produção.
- Esta entrega não inclui vídeo por decisão explícita de escopo do solicitante; o item consta no enunciado original.
