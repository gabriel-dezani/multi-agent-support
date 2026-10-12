> **Registro histórico de revisão anterior.** Para o estado atual da V6, consulte [RELATORIO_V6.md](RELATORIO_V6.md) e [RESULTADOS_EXECUTADOS_V6.json](RESULTADOS_EXECUTADOS_V6.json).

# Relatório de aceite — versão final de trabalho (12/10/2026)

## Escopo e decisão de base

Partimos da **versão consolidada v4**, que combina o `definitivo-v3` (planner estruturado, síntese e memória) com a versão revisada v3 (segurança e handoff). Comparamos os requisitos do `Desafio.md` oficial e a avaliação de 7,5/10. O desenvolvimento usa critérios de engenharia de implantação: contratos explícitos, fail-closed, testes de regressão, isolamento multi-tenant, rastreabilidade e um conjunto reproduzível de testes de aceite.

**A meta é superar 8,5 em cada rubrica anteriormente inferior a 8,5, mas isso não é uma nota prevista nem uma garantia.** Somente a banca pode avaliá-la. A execução real em um ambiente com LangGraph, Chroma, OpenAI, Tavily e Docker ainda precisa passar.

## Lacunas da avaliação tratadas

| Critério abaixo de 8,5 | Correções verificáveis | Limites atuais |
|---|---|---|
| Multi-agent 7,0 | Router por LLM estruturado ou fallback, até 3 especialistas, revisão a cada resultado, síntese e busca oficial após falha controlada de RAG; campos de estado LangGraph declarados; busca externa sanitizada | Integração LangGraph real ainda não executada aqui |
| Segurança 7,3 | Bearer vincula caller a `user_id`, autorização por papel, auditoria de operador derivada da credencial, proteção de tool arguments, isolamento por tenant, RAG/Getnet HTTPS | IdP/TLS/rate limit corporativos não implementados; token local é demonstração |
| Testes 8,2 | Golden dataset, avaliação multi-turn, adversariais, testes concorrentes 80+80, APIs FastAPI/SQLite e regressões de RAG | Sem testes reais de modelos/serviços externos neste ambiente |
| Observabilidade 7,1 | Spans de Router/especialistas/tools, tracing HTTP por request, tokens reportados de modelos, retrieval relevance, p50/p95, avaliação e feedback persistente | Custo de embeddings/Tavily não medido; qualidade semântica ao vivo pendente |
| Memória 1,0 | SQLite durável por `(user_id, conversation_id)`, histórico de conversas, consulta autenticada, continuação após resposta humana | Memória semântica vetorial e sumarização longa não implementadas |
| Human-in-the-loop 3,0 | Fila persistente, ticket com índice único, resolução idempotente e atômica, identidade auditada do operador, persistência em histórico e retomada | Sem UI dedicada, SLA/alertas/canal humano externo |
| Produto 8,0 | Contrato `POST /chat`, documentação, dados fictícios claramente rotulados, Docker + volumes, guias de demonstração e regressão | Vídeo omitido conforme pedido; sistemas bancários simulados |

RAG, Docker, arquitetura e trade-offs eram pontos relativamente fortes, preservados e reforçados. A ingestão agora faz upsert com IDs por URL/posição e remove chunks obsoletos somente após sucesso. O Knowledge Agent exige citações estruturadas de trechos Getnet para respostas fundamentadas.

## Validação realmente executada no ambiente disponível

| Comando/checagem | Resultado | O que **não** demonstra |
|---|---|---|
| `python -m compileall -q app scripts tests` | Aprovado | Execução com pacotes de produção |
| `python -m pytest -q` | **52 passed, 6 skipped** | Módulos de integração sem LangGraph/LangChain |
| `python -m scripts.evaluate --mode router` | **10/10** rotas | Qualidade de texto gerado por LLM |
| `python -m scripts.evaluate_multiturn --mode router` | **5/5** turnos | Recuperação de contexto com LLM real |
| `python -m scripts.offline_api_smoke` | **25 asserções** | Grafo simulado |
| `python -m scripts.offline_graph_smoke` | **19 asserções** | Transições emuladas, não runtime LangGraph |
| `python -m scripts.offline_rag_smoke` | **9 asserções** | Retriever e LLM simulados, Knowledge real |
| `python -m scripts.offline_api_stress` | **60 chats concorrentes** com um ticket; **40 resoluções concorrentes** com um único humano; mais 10 consultas de outro tenant | Grafo simulado |
| Testes SQLite (`test_stress_isolation.py`) | 80 escalonamentos -> 1 caso; 80 resoluções -> 1 resposta humana; 30 usuários isolados | Banco distribuído e alta disponibilidade |

As páginas oficiais Getnet para Pix, Link de Pagamento, Conta Digital, Crediário e Antecipação foram verificadas por consulta externa. **Não foi realizada ingestão de embeddings no Chroma neste ambiente** por ausência de rede/credenciais/dependências instaladas.

### Gates mínimos antes de publicar

1. Em Python 3.12 com internet, instalar `requirements.txt` e obter `pytest` **sem módulos ignorados por dependências ausentes**.
2. Executar `python -m scripts.ingest` e verificar que várias fontes Getnet foram ingeridas, incluindo a atualização idempotente.
3. Configurar tokens locais de demonstração e chaves válidas em `.env`; nunca incluir segredos no ZIP ou Git.
4. Iniciar API; testar `POST /chat` para os dez cenários do desafio, inclusive perguntas combinadas e multi-turn com `conversation_id` persistente.
5. Verificar traces, `handoff_id`, fila, resposta de operador autenticado e retomada após reiniciar o processo/contêiner.
6. Executar `python -m scripts.evaluate_grounding`; revisar manualmente amostra de respostas e erros factuais.
7. Executar `docker compose up --build -d`, depois ingestão **dentro do volume Docker** e repetir chamadas à API.
8. Tratar qualquer regressão e repetir a suíte; nenhum resultado offline autoriza declarar o item validado em produção.

## Limitações de ambiente

Não foi encontrado executor Codex conectado. A tentativa de instalar `structlog` e LangGraph falhou por resolução de DNS; Docker não está instalado, e não foram fornecidas chaves OpenAI/Tavily. Por isso **não é defensável afirmar que todos os testes de integração reais passaram**. A base está estruturada para rodá-los localmente/Codex/CI quando o ambiente permitir.
