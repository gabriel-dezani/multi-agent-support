# Auditoria criteriosa do feedback 9,2/10 — meta >= 9,6

**Escopo:** evolução incremental **V8.2** do projeto `multi-agent-support`, baseada na V8 validada no Windows e nas correções V8.1. A nota de 9,2 é a **nota externa anterior**, não uma medição desta versão. **Ninguém recalculou a nota atual da V8.2**. Nada aqui garante 9,6 ou 9,8.

**Baseline fornecido pelo desenvolvedor:** Windows/Python 3.12, **283 testes aprovados, 91% de statements cobertos, 5.737 warnings** na V8 antes das mudanças V8.1/V8.2. Não transferir esses números para V8.2 sem nova execução.

## Matriz de critérios — o que existe vs. o que permanece aberto

| Critério (nota anterior) | Implementado até V8.2 | Lacuna relevante ainda aberta | Prioridade |
|---|---|---|---|
| Arquitetura/código **9,5** | Módulos separados, LangGraph, especialistas, contratos Pydantic, falhas externas classificadas | Validação de recuperação operacional e qualidade sob incidentes correlacionados | Média |
| Multiagentes/orchestration **9,2** | Planejamento structured LLM (opcional), supervisor a cada agente, replanejamento limitado, síntese, allowlist; **agora reage também a baixa confiança, resposta vazia e ausência de fontes** | Benchmark com modelos reais e colaboração adaptativa por mais de uma revisão, evitando loops/custos | Alta |
| RAG/Knowledge **9,2** | Chroma, BM25, fusão RRF, filtro de relevância densa, fontes, abstention e verificador numérico/URL/garantias; Recall@k/MRR/nDCG implementados | Recuperação lexical independente + **reranker semântico dedicado** não implementados; **gold set real revisado por humanos e medição factual não disponíveis** | **Crítica** |
| Segurança/isolamento **9,2** | RBAC, autorização Bearer, identidade derivada de credencial, OIDC/JWT opcional, políticas SSRF/PII | Deployment real com IdP/JWKS, gestão segura de segredos, revisão de logs e pentest externo | Alta |
| Testes/qualidade **9,4** | 283 testes executados pelo desenvolvedor na V8; CI com piso de 90% e smoke Docker; testes V8.1 e V8.2 | **Suíte Windows completa desta nova revisão ainda não executada**, CI Linux/Docker não confirmado nesta sessão, warnings de terceiros | Alta |
| Observabilidade/evals **8,8** | Traces locais, OTLP opcional, histórico de spans, feedback, métricas, SLO; **agora janela UTC com alertas por taxa de erro, degradação, falhas do planner, latência e qualidade de contabilização**; overlay Jaeger local opcional | Alertmanager/paging externo, collector e dashboard distribuído rodando em produção, avaliação semântica contínua com humanos | **Crítica** |
| Memória/multi-turn **9,0** | SQLite persistente, isolation por usuário/conversa, TTL e recuperação de contexto | Medir acurácia de referências em sessões longas, política de exclusão abrangente, locking entre réplicas | Alta |
| HITL **9,5** | Ticket durável, fila, autenticação do operador, resolução atômica e continuidade | DR/auditoria operador real e monitoramento de tempo de resolução operacional | Média |
| Infra/Docker **8,5** | Docker, compose, overlay hardened, CI de imagem, volumes, health e readiness; overlay de tracing local | **Ainda single-instance, SQLite e lock por processo. NÃO é seguro usar múltiplas réplicas sem persistência/locks centralizados.** PostgreSQL, Redis, migrations e ensaio de HA ainda não implementados | **Crítica** |
| Produto/completude **9,3** | API, fluxo HITL, RAG, ferramentas, docs, feedback, observabilidade | Demonstração ponta a ponta em ambiente controlado/reprodutível, gestão de incidentes | Alta |
| Trade-offs/engenharia **9,6** | Max agentes/tempo, allowlist, fail-closed, não envio de dados privados; avaliação offline honesta | Registrar limites de custo/qualidade e critérios de rollback de release a partir de observações reais | Média |

## Correções comprováveis nesta V8.2 (sem API paga)

1. **Supervisor:** `unresolved` e `bounded_replan` compartilham a mesma avaliação de fragilidade. O supervisor pode recuperar um resultado com baixa confiança, sem fontes ou vazio, mesmo quando o especialista declarou `requires_human=False`. Limites de plano e privacidade permanecem ativos.
2. **Web provider:** chave ausente, HTTP 401/429/5xx e resposta malformada passam a ser incidentes de infraestrutura, não pedidos de atendimento humano. Exceções não exibem segredos.
3. **Observabilidade operacional:** `TelemetryRepository.recent_stats()` usa o mesmo período UTC para todas as contagens. `/ops/slo` passa a avaliar janela recente e `/ops/alerts` entrega riscos, dados insuficientes e indicadores sem expor mensagens. Ambos exigem token de operador. Há índice em `created_at`.
4. **Gates operacionais:** taxa de erro, degradação, erros de fallback, p95 e cobertura de usage; `insufficient_data` não pode ser confundido com sucesso. Taxa de handoff, por si só, não reprova: atendimento humano pode ser correto.
5. **Calibração factual:** além do limite de falsas aceitações, exige casos positivos e recall mínimo, evitando um “juiz” que apenas rejeita todas as respostas.
6. **Bench supervisor:** 22 casos **sintéticos criados para regressão** testam recuperação, privacidade, limites de agentes, erros e sucessos. Não são revisão humana nem validação de LLM ao vivo.
7. **Tracing local opcional:** Compose com Jaeger, sem mensalidade por API. Precisa baixar imagem Docker; a integração **não foi executada neste ambiente**.
8. **CI:** inclui benchmark de decisões do supervisor e validação de configuração dos overlays Docker.

## Resultados desta sessão de desenvolvimento

- Testes focados da V8.2 + regressões relacionadas: **58 passed** (Python 3.13 isolado, sem dependências integrais LangGraph/Chroma).
- `scripts.offline_supervisor_scorecard`: **22/22 casos sintéticos aprovados**, **0 chamadas pagas**.
- `compileall app scripts tests`: aprovado.
- YAML da configuração e CI: carregado com PyYAML.
- Um smoke de `offline_operational_report` com 35 requisições SQLite sintéticas terminou com SLO `pass` e gates `healthy`. Não equivale a operação real.
- Teste HTTP de RBAC para `/ops/alerts` foi adicionado, mas **não executado neste ambiente** por falta de `langgraph`/`structlog`.
- **Não** executei a suíte integral de integração da V8.2; os 283 testes da V8 não substituem essa execução.
- **Não** realizei chamadas à OpenAI/Tavily nem publiquei alterações no GitHub.

## Próximos passos para sustentar uma possível nota >= 9,6

### P0: regressão/segurança/infra local (sem créditos)

1. Rodar no Windows/PyCharm (Python 3.12): `python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90`.
2. Rodar `python -m scripts.offline_quality_scorecard` e `python -m scripts.offline_supervisor_scorecard`.
3. Se tiver Docker, testar build, compose config e Jaeger local. O overlay Jaeger é **opcional** e não deve ser confundido com HA.
4. Exercitar `/ops/alerts` e `/ops/slo` com dados locais simulados e token **de operador**, sem exposição pública.

### P1: evidências de qualidade real, sem pagar por modelo

1. Organizar um conjunto de, por exemplo, **30 perguntas oficiais, respostas esperadas e fontes Getnet manualmente revisadas**. Rótulos humanos devem ser reais e documentados, não fabricados por IA.
2. Criar exemplos **positivos e negativos** (no mínimo 8 de cada) para `scripts.evaluate_grounding_local` e medir falsas aceitações **e** recall de respostas válidas.
3. Avaliar retrieval real com `scripts.evaluate_retrieval` em base populada; embeddings de consulta OpenAI podem gerar custo. Para permanecer 100% offline, será necessário um **modelo local de embeddings e uma base reindexada para esse modelo**, e registrar explicitamente a diferença de qualidade entre ambientes. Esta migração ainda **não** foi implementada.
4. Construir avaliação comparativa de reranking semântico local, incluindo Recall@k, MRR, nDCG, latência e grounding; não alegar melhoria sem resultados.

### P2: alto impacto na infraestrutura (ainda não implementado)

- PostgreSQL para memória, tickets e telemetria, migrations e transações que preservem o handoff atômico.
- Locks distribuídos/coordenação (Redis ou transações/advisory locks) para múltiplos workers.
- Teste Docker Compose com **2 instâncias** e concorrência interinstância, falhas de reinício, retenção e recuperação de tickets.
- Pipeline de alertas externo/SLIs de falhas com retenção e custos conhecidos.

**Por que não fingir que já corrigimos infra:** SQLite e locks locais são decisões aceitáveis para o challenge single-service, mas a limitação explícita do feedback continua. Adicionar só uma variável de configuração ou um serviço Postgres no Compose não produziria persistência distribuída de verdade.

## Como usar os recursos gratuitos adicionados

```powershell
# Na pasta do projeto com .venv ativo (nenhum usa API paga):
python -m scripts.offline_quality_scorecard
python -m scripts.offline_supervisor_scorecard
python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90

# Opcional, apenas depois de existir telemetria local e com a aplicação parada:
python -m scripts.offline_operational_report --db .state/support.db --minutes 60

# Opcional com Docker instalado (não é necessário para testes Python):
docker compose -f docker-compose.yml -f docker-compose.observability.yml up --build
# Interface Jaeger: http://127.0.0.1:16686
```

**Atenção:** `offline_operational_report` retorna código diferente de zero quando não há amostra suficiente; isso é intencional, pois ausência de evidência não é sucesso operacional. Evite copiar `.env` de teste para um repositório público.
