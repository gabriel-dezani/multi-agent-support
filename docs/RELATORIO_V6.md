# V6 — Auditoria orientada ao feedback e evidências de teste

**Base:** feedback original (nota 7,5/10), desafio oficial e release V5.  
**Objetivo:** tratar principalmente as notas abaixo de 8,5.  
**Escopo de entrega:** um projeto Python único, sem publicar no GitHub ou gravar vídeo.

## Aderência aos comentários do avaliador

| Rubrica | Nota original | Evidência implementada na V6 | Aceite externo pendente |
|---|---:|---|---|
| Arquitetura | 8,7 | FastAPI, LangGraph, módulos independentes, estado tipado, contratos estruturados | Validar runtime com bibliotecas instaladas |
| Multi-agent/orchestration | 7,0 | Planner LLM estruturado; verificação de intenções explícitas; múltiplos especialistas; supervisor após cada execução, rejeição de subrespostas sem evidência; síntese; fallback Getnet estrito | Fluxo LangGraph real + casos qualitativos com provedores |
| RAG/Knowledge | 8,8 | Ingestão oficial allowlisted, Chroma, threshold e contratos grounded com fontes | Ingestão com embeddings reais, recall@k e grounding humano |
| Segurança/isolamento | 7,3 | Bearer vinculado a `user_id`, operador autenticado, segregação SQLite, três barreiras de privacidade da busca externa | Pen-test, TLS e gerenciamento corporativo de segredos em produção |
| Testes/quality | 8,2 | Suite pytest, cenários oficiais e de feedback, testes HTTP e concorrência, gate de CI que reprova skips | Suite integrada sem dependências faltantes, Docker real |
| Observabilidade/evals | 7,1 | Traces de router, supervisor, especialistas e tools, falhas LLM visíveis, estatísticas SQLite, tokens quando reportados, feedback, evals automatizadas | LLM-as-judge calibrado, custos completos Tavily/embeddings, qualidade em dados reais |
| Memória/multi-turn | 1,0 | Histórico persistente por `(user_id, conversation_id)`; ancoragem conservadora no último turno; novo tópico não herda intenções antigas | Diálogos end-to-end com LLM real e variação longa de contexto |
| Human-in-the-loop | 3,0 | Ticket persistente único, fila do operador, resposta auditada e atômica, retomada e concorrência | Reinício real do contêiner e fluxo integrado com grafo real |
| Infra/Docker | 9,0 | Imagem non-root, volumes persistentes com mountpoints pré-criados e permissão adequada; teste de volumes em CI | Build e execução Docker não disponíveis no ambiente local |
| Produto/completude | 8,0 | README, API, dataset oficial, scripts, relatório, matriz de requisitos, caso humano real no SQLite | Avaliar uso real com modelos e dados externos |
| Trade-offs | 9,2 | Limites de agentes, fallback explícito, preferência por privacidade e abstention | Novas decisões após observação real |

**As notas desta tabela são exclusivamente as notas originais da banca.** A V6 não recebeu notas da banca; não é possível prometer nota mínima de 8,5 por critério.

## Problemas específicos da auditoria V5 resolvidos

1. `Pix e as minhas vendas` passou a produzir `knowledge` + `customer_support`, inclusive no fallback sem chave OpenAI. O planner LLM tem verificação de cobertura de intenções múltiplas explícitas.
2. `E quanto ao crediário?` e `E o câmbio do dólar?` não importam indevidamente assuntos mais antigos. Follow-ups genuinamente elípticos usam **no máximo o último turno do usuário**, não todas as mensagens anteriores.
3. **Toda** busca web, inclusive se roteada incorretamente como apenas `web_search`, passa pela extração de consulta pública e pela barreira dentro do próprio WebSearchAgent. CPF/e-mail/conta não vão no query ou prompt do provedor. Temas privados arbitrários sem extração segura são escalados.
4. Supervisor agora emite span próprio entre especialistas; falha do planner LLM é registrada por tipo, com fallback e indicador de degradação.
5. SQLite fecha todas as conexões; filas e memória mantêm commit/rollback, isolamento e resolução atômica.
6. Docker prepara diretórios de volumes como propriedade do usuário non-root; CI foi reforçada para verificar escrita e rejeitar testes ignorados.

## Validação efetivamente executada neste ambiente

| Comando | Resultado observado | Dependências simuladas? |
|---|---|---|
| `python -m pytest -q` | **69 passed, 7 skipped** | 7 módulos exigem bibliotecas ausentes |
| `python -m scripts.evaluate --mode router` | **10/10** casos oficiais de classificação | Roteamento determinístico, não respostas reais |
| `python -m scripts.evaluate_multiturn --mode router` | **5/5** turnos | Classificação offline |
| `python -m scripts.evaluate_feedback_v6` | **16/16** regressões da auditoria | Classificação + política de privacidade |
| `python -m scripts.offline_api_smoke` | **25** verificações HTTP | FastAPI/SQLite reais; grafo simulado |
| `python -m scripts.offline_graph_smoke` | **24** verificações | Nós reais e transições emuladas, não LangGraph |
| `python -m scripts.offline_rag_smoke` | **9** verificações | Knowledge real; retriever/LLM falsos |
| `python -m scripts.offline_web_privacy_smoke` | **7** verificações | WebSearchAgent real; HTTP/LLM falsos |
| `python -m scripts.offline_api_stress` | **60** requisições e **40** resoluções concorrentes em **3 rodadas independentes** | FastAPI/SQLite reais; grafo simulado |
| `python -m compileall -q app scripts tests` | Aprovada | Não |

As execuções acima foram feitas sem Codex: **não há ambiente Codex disponível nesta conversa**. A instalação de LangGraph/LangChain/OpenAI/Chroma falhou por ausência de acesso funcional ao índice de pacotes; Docker não está instalado. Não foi realizada uma execução real ponta a ponta com OpenAI, Tavily, Chroma, LangGraph e Docker. Os testes de integração de LangGraph estão incluídos no repositório e deverão ser executados por CI ou em outro ambiente Python 3.12 com dependências instaladas.

## Gates antes de publicar como aplicação validada ponta a ponta

- [ ] Instalar `requirements.txt` no Python 3.12, rodar `pytest` e **exigir zero skipped**.
- [ ] Executar `tests/integration/test_graph_v6_real.py` com LangGraph verdadeiro (modelos/tools falsos) e depois validar os outros módulos integrados.
- [ ] Criar `.env` real local com credenciais fortes, ingerir páginas Getnet e consultar produtos com evidências RAG válidas.
- [ ] Testar consulta mista com duas tools e Web Search com chave Tavily real, monitorando ausência de dados privados no tráfego externo.
- [ ] Rodar `scripts.evaluate_grounding` e inspecionar manualmente as afirmações; calibrar avaliador/limiar.
- [ ] Build/run Docker com volumes em branco, reinício, persistência, permissões non-root e tickets respondidos após restart.
- [ ] Validar custo e telemetria real das chamadas de LLM, embeddings e Tavily.

**Conclusão:** V6 atende os defeitos reproduzidos do feedback na lógica e nos testes locais; **não há comprovação completa** de qualidade acima de 8,5 em todos os critérios ou de funcionamento integral com todos os serviços externos. A CI foi configurada para reprovar esses skips quando as dependências forem instaladas.
