# Auditoria técnica dos três pilares — V8.3 local

Data: 15/10/2026. Ambiente: Windows, Python 3.12.10, virtualenv existente. Base: exclusivamente os arquivos deste workspace; `git status --short` informou que não existe repositório Git reconhecível. Nenhuma versão remota foi usada. Nenhum `.env`, segredo ou dado persistente foi alterado. Nenhuma chamada paga ou publicação foi executada.

## Implementações existentes e escopo da auditoria

Foram inspecionados ingestão, indexação, vector store, retriever, ranking, verificação, avaliadores de retrieval/A-B, grafo, política de revisão, contexto, privacidade, agentes, rotas, memória, tickets, telemetria, locks, readiness, Dockerfile, overlays Compose e CI.

* **RAG:** ingestão HTTPS com allowlist Getnet por redirecionamento, limite de download, chunks de 900 caracteres com overlap 150 e hashes. Chroma persistente com embeddings OpenAI no caminho normal. Upsert por URL com IDs estáveis e remoção posterior de chunks antigos. O retriever real já usa candidatos densos, BM25 de snapshot limitado, RRF, diversidade e piso semântico obrigatório. Recovery HNSW reconstrói índice dos vetores ativos sem reembutir documentos. Knowledge valida URLs, IDs de citações e alegações numéricas/absolutas; verificador LLM opcional é obrigatório na configuração de produção.
* **Infraestrutura:** SQLite com WAL, fechamento explícito de conexões e transações; PostgreSQL opcional com conexões por operação e commit/rollback via psycopg. Ticket pendente único por usuário/conversa; resolução e memória humana na mesma transação. Telemetria persistente com detalhes restritos e identidade do operador derivada da autenticação. PostgreSQL possui advisory locks; SQLite usa lock local por conversa no fluxo HTTP. A configuração recusa múltiplas réplicas enquanto o Chroma for local. CI já tem serviço PostgreSQL e smoke real separado.
* **Orquestração:** Router com saída estruturada e fallback, allowlist e plano limitado; especialistas seguem para review; replanejamento determinístico entre RAG e web oficial com orçamento e restrições de privacidade. Busca pública recebe consulta sanitizada e histórico vazio. Síntese com suporte privado é determinística. Memória isola por usuário e conversa e recupera uma âncora anterior para perguntas elípticas. O scorecard existente persiste 140 follow-ups por sessão, em três combinações de usuário/conversa, e reabre o store.

Esses mecanismos foram preservados, sem reconstruir funcionalidades existentes.

## Problemas, causas e correções

| Problema real | Causa raiz | Correção e evidência |
|---|---|---|
| Resolução HITL com PostgreSQL falhava antes da transação | A rota acessava `.path`, exclusivo do backend SQLite, e adquiria apenas lock local | Seleção do advisory lock PostgreSQL por usuário/conversa e validação de DSN dos dois repositórios; teste da rota com objetos sem `.path`, persistência atômica solicitada e rejeição de backends inconsistentes |
| Falha na aquisição do lock PostgreSQL escapava da classificação de indisponibilidade | A conexão é aberta antes do tratamento de erros de `_chat` | Fronteira externa converte falhas em 503 com mensagem sanitizada; resolução HITL também trata falha de aquisição |
| Retry de persistência duplicava um turno completo | `append_turn` inseria sempre duas linhas, sem consultar o request_id | Check e insert na mesma transação, serializados por `BEGIN IMMEDIATE` no SQLite e advisory transaction lock PostgreSQL. Replay idêntico é no-op; payload conflitante é rejeitado. Sem apagar linhas existentes nem exigir migração destrutiva |
| Possível autointerbloqueio ao adicionar serialização da memória | Lock HTTP e gravação usam conexões distintas | Namespace específico `memory-turn` para o lock transacional; teste de distinção de chaves e smoke PostgreSQL ampliado para gravar enquanto o lock HTTP está ativo |
| Fallback fraco/indisponível podia marcar a tarefa anterior como recuperada | Recuperação verificava apenas presença de fontes e `requires_human`; ignorava resposta, confiança e indisponibilidade | Recuperação exige resultado utilizável; confiança acima de 1 também é rejeitada. Comparação reproduzível em seis casos sintéticos: política anterior 2/6, corrigida 6/6 |
| Síntese podia acrescentar taxa, garantia ou URL após o especialista ter validado sua resposta | Nova geração não passava pelo gate factual local | Validar síntese contra respostas dos especialistas e fontes permitidas; em rejeição, compor deterministicamente as respostas existentes. Teste rejeita taxa inventada de 99% |
| Gate factual isolado aceitava ausência completa de evidência | Heurística só procurava números, garantias e URLs não sustentadas | Rejeição explícita quando falta resposta, evidência textual ou fontes |
| Duplicata lexical podia piorar a posição de um chunk no RRF | Dicionário sobrescrevia o primeiro rank com a última ocorrência | Ranking esparso usa primeira posição em sequência deduplicada. Regressão compara resultado com e sem repetição |
| Métricas podiam contar páginas distintas como acertos | Normalização convertia path para minúsculas e descartava toda query string; não validava porta | Preservar caixa do path e parâmetros de conteúdo; ignorar apenas `ref`, `utm_*` e fragmento; rejeitar portas inválidas/não padrão e espaços |
| A/B omitia Precision@K | Conjunto de métricas exportadas não incluía precision já calculada | Precision incluída em relatório global, por categoria, bootstrap e comparação de regressão |
| Consulta vazia podia invocar embeddings e preservar metadados da consulta anterior | Ausência de validação inicial no retriever | Retornar vazio antes do store e limpar metadados por contexto |
| Smoke do grafo falhava em replanejamento | Settings simulado não tinha `router_max_agents` | Fixture alinhada ao contrato atual, mantendo asserções |
| Stress passava as asserções, mas terminava com WinError 32 | Context manager SQLite não fecha conexão de inspeção | `contextlib.closing`; reexecução termina com exit code 0 |

Idempotência é interna à persistência pelo mesmo request_id, usuário e conversa. O endpoint continua gerando novo request_id por chamada: isso **não** implementa chave de idempotência HTTP nem execução exatamente uma vez de ferramentas. `append_message` mantém seu contrato anterior; duplicatas históricas não são removidas.

## Arquivos modificados/adicionados

Código: `app/api/routes.py`, `app/core/distributed_lock.py`, `app/core/postgres_state.py`, `app/memory/store.py`, `app/orchestration/review_policy.py`, `app/agents/synthesis.py`, `app/rag/ranking.py`, `app/rag/retriever.py`, `app/rag/verification.py`, `app/evaluation/retrieval.py`, `app/evaluation/paired_retrieval.py`.

Regressões e ferramentas: `tests/unit/test_audit_three_pillars.py`, `tests/unit/test_replanning_v7.py`, `scripts/audit_three_pillars_evidence.py`, `scripts/postgres_state_smoke.py`, `scripts/offline_api_stress.py`, `scripts/offline_graph_smoke.py`.

O teste anterior de fallback válido foi mantido com suas asserções; sua fixture recebeu `answer`, campo presente no resultado real do grafo. Nenhum teste foi eliminado.

## Resultados executados nesta auditoria

**Execução final: 385 testes aprovados, 0 falhas, 0 erros, 0 skips, em 178,15 segundos. Cobertura de linhas: 92,52% (2.166 de 2.341 statements cobertos; 175 ausentes).** O terminal arredonda para 93%; o percentual aqui vem do JSON. Artefatos: `audit_three_pillars_tests.xml` e `audit_three_pillars_coverage.json`. A exclusão preexistente dos dois módulos PostgreSQL é detalhada abaixo. Os números históricos de 361 testes/91,84% não foram reutilizados como resultado novo; não há baseline de cobertura pré-alteração reexecutado nesta sessão para atribuir um ganho percentual comparável.

| Execução | Resultado real |
|---|---|
| Suíte completa com cobertura, estado final | 385 aprovados; 0 falhas/erros/skips; 92,52% de cobertura no escopo local |
| Novas regressões focadas | 24 aprovadas, sem falhas |
| Supervisor offline existente | 22/22 cenários, pass |
| Memória longa offline existente | 134 verificações, pass; 140 follow-ups por sessão |
| Qualidade offline existente | 24 casos factuais sintéticos e 30 casos de roteamento, pass |
| Avaliação multi-turn do Router | 29/29 turnos, acurácia de contrato 1,0 |
| Feedback V6 | 20/20 cenários, pass |
| Smoke API | 25 asserções, pass; FastAPI e SQLite reais, grafo simulado |
| Smoke RAG | 9 asserções, pass; evidência/modelo simulados, Knowledge real |
| Smoke privacidade web | 7 asserções, pass; provedores simulados |
| Smoke do grafo | 24 asserções, pass após correção; transições emuladas, não substitui integração LangGraph |
| Stress HTTP | 60 solicitações concorrentes → um ticket; 40 resoluções → uma resposta humana; 10 solicitações de outro usuário; isolamento e métricas, pass após correção do fechamento da conexão |
| `pip check` | No broken requirements found |
| `compileall -q app scripts tests` | Exit code 0 |

Uma execução intermediária da suíte, iniciada antes de finalizar as fixtures e os novos testes, teve 360 aprovados e uma falha na fixture sem `answer`. Outra execução passou com 381 testes; a execução final foi repetida para incluir as quatro regressões adicionadas após sua coleta. Os dois smokes descritos acima também falharam inicialmente e foram corrigidos e reexecutados com sucesso. A suíte final registrou 5.746 warnings, predominantemente de depreciação nas dependências; não foram suprimidos para produzir um resultado artificialmente limpo.

Artefatos separados desta entrega: `audit_offline_quality_scorecard.json`, `audit_supervisor_scorecard.json`, `audit_long_turn_scorecard.json`, `audit_multiturn.json`, `audit_three_pillars_decisions.json`.

### Evidência de qualidade e limites de interpretação

`python -m scripts.audit_three_pillars_evidence` executa a política atual e a condição de recuperação anterior congelada sobre o mesmo conjunto sintético de seis casos: 2/6 → 6/6 decisões corretas. Quatro casos demonstram que fallback marcado indisponível não deve autorizar síntese; dois preservam recuperação válida. Não é uma comparação com um LLM antigo nem uma estimativa de acurácia de produção.

A fixture de métricas com um documento relevante, uma URL inválida antes dele e uma duplicata depois produz Recall@3=1, Precision@3=0,3333, MRR=0,5, nDCG@3=0,6309 e hit rate=1. Ela valida fórmulas/posições/deduplicação, **não** mede qualidade do índice real. O A/B existente continua exigindo metadados de revisão humana, categorias, casos distintos, limites de regressão e bootstrap. A pasta `data/reviewed` contém apenas o README com esquema e orientações, não o arquivo de rótulos revisados. Essa estrutura existente foi preservada. Não foram produzidos rótulos humanos fictícios nem executado `compare_retrieval` contra embeddings OpenAI.

Testes novos com documentos contraditórios, condição datada de 2020 e instrução maliciosa verificam que um parecer independente negativo prevalece sobre `supported=true` do gerador. O parecer é simulado: esses testes validam a integração fail-closed, não a capacidade semântica real do juiz de detectar contradição, desatualização ou injection. A integração Chroma existente testa persistência/reingestão, conversão de relevância, recuperação HNSW, citações e documentos maliciosos com embeddings/modelo locais simulados.

## Reproduzir

Executar na raiz com o virtualenv existente; os comandos abaixo não usam APIs pagas:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs --cov=app --cov-report=json:docs/audit_three_pillars_coverage.json --cov-report=term --junitxml=docs/audit_three_pillars_tests.xml
.\.venv\Scripts\python.exe -m scripts.audit_three_pillars_evidence
.\.venv\Scripts\python.exe -m scripts.offline_quality_scorecard --output docs/audit_offline_quality_scorecard.json
.\.venv\Scripts\python.exe -m scripts.offline_supervisor_scorecard --output docs/audit_supervisor_scorecard.json
.\.venv\Scripts\python.exe -m scripts.offline_long_turn_scorecard --output docs/audit_long_turn_scorecard.json
.\.venv\Scripts\python.exe -m scripts.evaluate_multiturn --mode router --output docs/audit_multiturn.json
.\.venv\Scripts\python.exe -m scripts.evaluate_feedback_v6
.\.venv\Scripts\python.exe -m scripts.offline_api_smoke
.\.venv\Scripts\python.exe -m scripts.offline_graph_smoke
.\.venv\Scripts\python.exe -m scripts.offline_rag_smoke
.\.venv\Scripts\python.exe -m scripts.offline_web_privacy_smoke
.\.venv\Scripts\python.exe -m scripts.offline_api_stress
.\.venv\Scripts\python.exe -m pip check
```

## Execuções pendentes e riscos restantes

1. **PostgreSQL e Docker reais:** `Get-Command docker,psql,postgres -ErrorAction SilentlyContinue` não encontrou executáveis no PATH. Nenhum banco de teste foi fornecido/utilizado. Smoke real ampliado para concorrência/idempotência/rollback e gravação sob lock HTTP, mas **não executado localmente**. CI já instala psycopg e sobe PostgreSQL 16; é preciso executar esse job antes de aprovar o backend para produção. Não foi alegado que essa CI passou nesta sessão. Não foram validados build, Compose, restart, queda/retorno do banco nem locks entre processos reais.
2. **Cobertura:** `.coveragerc` preexistente exclui `app/core/postgres_state.py` e `app/core/distributed_lock.py` do denominador local. A cobertura informada da suíte offline não representa cobertura do PostgreSQL. A configuração não foi alterada para melhorar percentuais.
3. **Retrieval semântico real:** não há corpus de avaliação revisado por humanos cuja procedência tenha sido confirmada nesta auditoria. BM25 reordena candidatos densos aprovados; não recupera documentos fora desse conjunto, e o snapshot lexical tem limite. Não se demonstrou ganho de Recall/MRR do índice real nem benefício de adicionar cross-encoder. O reranking RRF foi corrigido sem adicionar serviço externo ou relaxar segurança.
4. **Factualidade:** heurística detecta classes limitadas de alegações, não entailment geral. Mesmo juiz LLM é falível e não foi chamado. `retrieved_at` registra coleta, não validade do conteúdo; não há política automática suficiente para decidir qual documento contraditório é autoritativo ou qual informação está obsoleta. Síntese agora tem gate local, mas inferências sem números/URLs/absolutos ainda exigem avaliação semântica independente.
5. **Chroma e ingestão:** substituição por URL não é uma transação global entre upsert/delete, nem oferece isolamento de snapshots sob ingestões simultâneas. Persistência SQL central não torna Chroma local distribuído. Múltiplas réplicas continuam bloqueadas; SQLite permanece adequado ao desenvolvimento local, não à coordenação HTTP entre processos.
6. **Memória:** recuperação de âncora anterior é limitada aos 200 turnos de usuário anteriores à janela. A validação de 140 follow-ups não garante retenção de qualquer assunto em conversas arbitrariamente longas. Não há resumo semântico durável, checkpoint distribuído completo do LangGraph nem garantia de retomada no meio de qualquer ferramenta após crash. Timeout de coroutine não interrompe necessariamente função síncrona já em execução em thread.
7. **Operação:** schema é inicializado pelos repositórios, não por uma cadeia completa de migrations versionadas. Readiness verifica existência de componentes/tabelas, não toda a saúde do índice nem todas as permissões SQL. Inicialização com PostgreSQL indisponível ainda pode exigir restart/orquestrador. Telemetria falha sem bloquear resposta já persistida; isso preserva atendimento, mas admite lacunas de auditoria operacional. Credenciais locais de demonstração não equivalem a identidade corporativa; produção mantém as exigências OIDC, verificador e OTLP já existentes.
8. **Dependências:** há avisos de depreciação LangGraph/Pydantic/Chroma; não foram feitas atualizações amplas sem validação de compatibilidade. O warning de relevância fora de faixa por arredondamento é provocado por teste de integração e o retriever já normaliza spillover dentro de epsilon.

## Comparação com feedback e prontidão

| Pilar | Avanço verificável nesta entrega | O que ainda impede uma afirmação ampla |
|---|---|---|
| RAG/factualidade | RRF protegido contra duplicatas, métricas de URL mais fiéis, Precision no A/B, abstention sem evidência e gate adicional na síntese | Benchmark humano, qualidade semântica real, conflitos/freshness e avaliação de recall fora do conjunto denso |
| Infra/PostgreSQL | Rota HITL compatível com backend configurado, locks consistentes, transações de turnos idempotentes e smoke real ampliado | Execução PostgreSQL/Docker, falhas/restart reais, migrations e vector store externo |
| Supervisor/memória | Recuperação condicionada a resultado utilizável, ganho 2/6 → 6/6 no conjunto de regressão, preservação dos scorecards e limites de plano/privacidade | Autonomia semântica medida externamente e retomada distribuída de execução |

Parecer: há melhorias concretas e evidências offline reproduzíveis para submeter a versão a uma nova avaliação técnica. Não há base para certificar produção distribuída ou afirmar nota 9,6/9,8. A nova avaliação deve examinar as pendências explicitadas, especialmente PostgreSQL real e dataset humano de retrieval/groundedness.
