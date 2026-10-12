# Relatório de validação final — Multi-Agent Support V6

Data: 12/10/2026. Ambiente Windows, Python 3.12.10 da `.venv`. Auditoria executada exclusivamente no projeto; sem chamadas pagas, instalação de dependências, commits, push ou alterações no GitHub. Bancos de carga e destruição são temporários e usam dados sintéticos. Nenhum banco operacional foi apagado.

## 1. Resumo executivo

O baseline conhecido foi confirmado: **151 aprovados, zero falhas, zero ignorados**, em 48,42 s, com 5.103 avisos. `pip check` não encontrou incompatibilidades declaradas. A validação ampliada encontrou defeitos reais mesmo com esse baseline verde: perda de resultados parciais, concorrência no histórico, perda de contexto em cadeias longas, deadlines incompletos, payloads vazios e respostas malformadas. As correções têm regressões automatizadas e preservam os nós e arestas do LangGraph, o contrato de autenticação, a persistência e os mecanismos RAG.

As contagens finais, cobertura e métricas estão na seção 5 e nos artefatos associados. Não atribuímos notas novas. A evidência demonstra funcionamento integrado local; não comprova qualidade semântica dos modelos pagos nem operação distribuída em produção.

## 2. Comparação com os critérios e requisitos

As notas abaixo são somente as originais informadas pelo usuário. O arquivo independente do feedback original não foi encontrado; foram examinados os relatórios existentes, `docs/Desafio.md` e `data/evaluation_feedback_v6.json`. O dataset é uma matriz de regressões, não a íntegra da avaliação original.

| Critério / nota original | Evidência e evolução verificável | Limite da conclusão |
|---|---|---|
| Memória / multi-turn — 1,0 | Conversas HTTP de 10 e 11 turnos; persistência/reabertura; cadeias elípticas; mudança Pix/crediário; 20 sessões de dois usuários; concorrência serializada | Coordenação da mesma sessão vale em um processo; não há protocolo de ordem fornecido pelo cliente |
| Human-in-the-loop — 3,0 | Ticket SQLite persistente, fila protegida, consulta isolada, resolução autenticada, rollback transacional e retomada real | Operadores locais e dados demonstrativos; não há sistema externo de atendimento integrado |
| Multi-agent — 7,0 | LangGraph instalado e compilado, plano estruturado simulado, três especialistas, revisão após cada resultado, replanejamento limitado, falhas parciais e síntese | Planner e geração simulados não medem competência semântica de um LLM real |
| Observabilidade / evals — 7,1 | Correlação request/session/user pseudonimizados; spans guardrail/router/tools/retrieval/supervisor/synthesis/human; erros seguros, durações, tokens quando fornecidos, custo somente com dados completos; datasets determinísticos | Embeddings, Tavily e trabalho sem token reportado não têm custo total inferido |
| Segurança / isolamento — 7,3 | Bearer ausente/inválido/não ASCII/expirado; spoofing; separação cliente/operador; acesso cruzado; privacidade Web; validação URL; injection e redaction | Guardrails por regras não oferecem resistência universal; IdP/TLS/rate limiting externos não validados |
| Produto / completude — 8,0 | FastAPI/OpenAPI em Uvicorn HTTP real, validação de mensagens/resoluções, deadlines, erros JSON sanitizados, migração aditiva | Vídeo e publicação exigidos pelo desafio permanecem entrega do responsável |
| Testes / quality — 8,2 | Baseline preservado, testes integrados e adversariais novos, cobertura de branches e artefatos reproduzíveis | Percentual de cobertura não prova qualidade semântica nem todas as interleavings possíveis |
| Arquitetura / código — 8,7 | Correções localizadas; LangGraph mantém construção, compilação, nós e transições existentes | Sem reescrita estrutural ou nova infraestrutura distribuída |
| RAG / Knowledge — 8,8 | Chroma/HNSW reais, recuperação após atualizações/remoções, persistência, threshold/top-k, URLs/chunks/citações; ingestão pública real 7/7 | Embeddings determinísticos; citação existente não comprova verdade de uma afirmação |
| Docker / Infra — 9,0 | Dockerfile e Compose preservados; regressão estática de non-root/volumes/healthcheck | Docker CLI indisponível; build e execução de container não foram validados nesta missão |
| Trade-offs — 9,2 | Fallbacks limitados, síntese privada determinística, isolamento por identidade, persistência local e falhas controladas | Custos e limites operacionais explícitos; não substituem validação de provedores externos |

O desafio exige suporte, Knowledge, busca pública, duas ferramentas, API JSON e Docker. Esses contratos estão implementados e as ferramentas de vendas/terminal continuam usando dados demonstrativos, como documentado. Documentação antiga com contagens menores ou skips foi preservada como histórico e o README aponta para este relatório.

## 3. Defeitos reproduzidos e causas

| Defeito | Causa comprovada | Correção mínima e regressão |
|---|---|---|
| Terminal válido perdido quando vendas falham | Resultado do especialista marcava intervenção humana sem separar sua parte válida | `partial_answer` preservado pelo suporte e ramo human; testes verificam terminal e ticket na mesma resposta |
| Exceção/resposta inválida de síntese descartava especialistas | Exceção propagava ou conteúdo era convertido indiscriminadamente para string | Fallback determinístico com resultados válidos; conteúdo/tipo/confiança inválidos são tratados |
| Web Search assíncrono sem limite efetivo | Ausência de `wait_for` no passo assíncrono | Deadline do especialista e escalonamento controlado |
| Deadline não incluía fila da sessão | Medição começava depois de adquirir o lock | Orçamento começa na admissão; espera limitada e tempo restante compartilhado com o grafo |
| Requisições concorrentes liam o mesmo histórico | Leitura, execução e append não eram serializados | Lock por banco/usuário/sessão cobrindo a operação inteira; teste observa históricos 0/2/4/6 |
| Cadeias “E hoje?” → “E quanto foi?” perdiam assunto | Somente o último turno elíptico era considerado | Busca da âncora explícita mais recente; assunto novo interrompe herança |
| Janela longa só com elipses perdia a âncora | Assunto saiu do limite de histórico retornado | Metadado de âncora obtido em busca limitada a 100 turnos anteriores do mesmo usuário/sessão |
| Token não ASCII causava exceção | `compare_digest` em strings incompatíveis | Rejeição antes de comparar, sem bypass de autenticação |
| Expiração configurada era ignorada | Campo de expiração não validado | `expires_at` opcional, UTC com fuso obrigatório, 401 expirado/503 configuração inválida |
| Falha SQL ao resolver ticket expunha erro genérico | Rollback existia, mas exceção não era traduzida | Resposta JSON 503 segura; ticket e histórico permanecem consistentes |
| Mensagem/resolução só com espaços eram aceitas | `min_length` não rejeita whitespace | Validação adicional sem alterar conteúdo de mensagens válidas |
| Override explícito em português não era bloqueado | Padrões incompletos para esse idioma | Padrão localizado e regressão; sem promessa de detector universal |
| Busca oficial aceitava portas inválidas | Validação Web divergia da ingestão | Reutilização da validação HTTPS/host/porta existente |
| Respostas Web `None`/lista/blank podiam virar texto aparente | Conversão por `str` não valida saída do modelo | Abstention e erro seguro em conteúdo inválido |
| Traces insuficientes para investigar decisões | Não armazenavam correlação de sessão, revisões e erros seguros | Migração aditiva de telemetria; allowlist de dados estruturais e métricas |
| Avaliação grounding podia enviar dados privados e aceitar judge contraditório | Falta de gate antes de retrieval/judge e contrato permissivo | Gate privado, abstention explícito, contrato consistente, erros sanitizados e metodologia publicada |

Os oito primeiros testes adicionados reproduziram oito falhas antes das correções. Outros defeitos foram reproduzidos durante a ampliação. Um caso de parametrização com HTML de 5 MB provocou erro de setup no Windows pelo tamanho do nome do teste; corrigido com IDs curtos, sem alterar produção.

O defeito HNSW já corrigido antes desta missão continua reproduzível no acesso nativo: remoções/atualizações e duplicação de vetores podem causar exceção ou resultados incompletos, inclusive com `k` menor que a população ativa. Não se trata apenas de solicitar mais resultados que existem. O retriever existente recupera com HNSW temporário sobre embeddings ativos, preservando base persistente, top-k e threshold. Nenhuma troca ou atualização de dependências foi feita nesta missão.

## 4. Arquivos modificados e justificativas

Mudanças de produção nesta missão:

- `app/api/routes.py`, `app/api/schemas.py`: serialização, deadlines, contratos não vazios, falhas sanitizadas e correlação.
- `app/core/session_lock.py` (novo), `auth.py`, `security.py`, `config.py`, `telemetry.py`: coordenação local cancelável, validação de tokens/expiração, orçamento total e migração observável sem dados privados completos.
- `app/orchestration/context.py`, `graph.py`, `state.py`: continuidade, preservação parcial, recuperação de síntese e spans, mantendo arquitetura do grafo.
- `app/memory/store.py`: âncora limitada e isolada além da janela, sem mudança de schema.
- `app/agents/support.py`, `synthesis.py`, `web_search_agent.py`, `guardrail.py`: resultados parciais, validação de geração, URLs oficiais e padrão de segurança localizado.
- `app/agents/knowledge.py`, `app/rag/retriever.py`: instrumentação de retrieval, consumo conhecido e recuperação HNSW; algoritmo de recuperação/threshold/ingestão não refatorado.

Testes/datasets/scripts: `tests/integration/test_final_system.py`, `test_final_boundaries.py`; `tests/unit/test_grounding_eval.py`, `test_telemetry_final.py`, `test_context.py`; `scripts/evaluate_grounding.py`, `evaluate_multiturn.py`, `offline_graph_smoke.py`; `data/evaluation_multiturn.json`, `evaluation_feedback_v6.json`.

Documentação/configuração de exemplo/evidências: README, `.env.example` (deadline total), este relatório, cobertura baseline/final, XML pytest, `validation_environment.json`, `validation_runtime_evidence.json`, `validation_stress_metrics.json`, `validation_public_ingestion.json` e avaliações finais. Não havia repositório `.git` reconhecido em `git status`; assim não há diff Git confiável. A lista é o registro das edições desta missão, não atribui a ela mudanças anteriores de RAG e dependências.

## 5. Testes executados e resultados

Comando exato final `python -m pytest -q -rs`, pelo executável da `.venv`: **233 aprovados, zero falhas, zero ignorados**, em **102,58 s**, com **5.710 avisos**. Os **151 anteriores mais 82 novos** passam. Execução completa com cobertura: 233 aprovados em 132,97 s. Coleta independente dos cenários integrados/estresse: **92 aprovados**, zero falhas/ignorados, em 118,72 s. `pip check` final: **No broken requirements found**.

Cobertura combinada de statements/branches: **79,95% → 91,83%** (80% → 92% arredondados pelo pytest-cov). Evidências JSON: [baseline](coverage_baseline.json), [final](coverage_final.json); resultados estruturados: [pytest XML](pytest_final.xml). Grafo 92%, memória 96%, handoffs 99%, contexto/lock 100%, telemetria 94%, Knowledge 92%, Web 93%, ingestão 97%. Caminhos ainda menos cobertos: agente human 74%, terminal tool 69%, synthesis 81%, rotas 83%, inicialização sem fixtures/configuração inválida e algumas falhas secundárias. A cobertura não substitui integração dos provedores.

Avisos: depreciação do serializador LangGraph, acesso a `model_fields` em Chroma/Pydantic e pequeno erro de ponto flutuante no score cosine de um teste de conversão (1,0000000238). Não foram escondidos nem resolvidos por atualização indiscriminada. Versões verificadas em [validation_environment.json](validation_environment.json): LangGraph 0.6.11, Chroma 0.6.3, chroma-hnswlib 0.7.6, LangChain-Chroma 0.2.3 e PostHog 5.4.0. O pacote agregador `langchain` não está instalado nem é necessário: o projeto utiliza seus pacotes modulares declarados.

Comandos principais, sempre pelo Python da `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q -rs --cov=app --cov-branch --cov-report=term-missing --cov-report=json:docs/coverage_final.json --junitxml=docs/pytest_final.xml
```

Os smokes históricos passaram: grafo 24 assertions, API 25, RAG 9 e Web/privacy 7. O smoke de grafo usa emulação e não é a evidência do runtime verdadeiro; essa evidência está nos testes integrados novos e `test_graph_v6_real.py`.

Avaliações determinísticas: dataset original **10/10** rotas principais; feedback ampliado **20/20** planos/privacidade; multi-turn **29/29** turnos em oito cenários. Não medem respostas semânticas de LLM real. Artefatos: [router](evaluation_router_final.json), [feedback](evaluation_feedback_final.json), [multi-turn](evaluation_multiturn_final.json).

O judge foi validado por sete casos de contrato/privacidade usando respostas simuladas. Não foi executado contra OpenAI. O relatório do judge informa dataset hash, modelo/temperatura/versão do prompt e denominadores; não declara determinismo nem calibração semântica.

## 6. Estresse e desempenho

As métricas são de execução local com provedores simulados, não SLA nem benchmark de rede/LLMs. Na coleta final houve outra execução de cobertura em paralelo no mesmo computador; interpretar as latências como observações sob essa contenção. Valores completos e tempos totais disponíveis em [validation_stress_metrics.json](validation_stress_metrics.json).

| Cenário | Operações | Erros finais | p50 ms | p95 ms | Tempo total ms |
|---|---:|---:|---:|---:|---:|
| API, dois usuários / 20 sessões | 100 | 0 | 33,06 | 1.503,33 | 2.613,25 |
| Criação concorrente de handoff, um ticket | 40 | 0 | 185,86 | 1.489,02 | 1.681,03 |
| Resolução concorrente, uma resposta humana | 40 | 0 | 14,88 | 429,96 | 502,09 |
| Falhas intermitentes, cinco encaminhamentos esperados | 40 | 0 | 63,02 | 1.274,99 | Não coletado |
| RAG idênticos: ingestão | 80 | 0 | 15,683 | 26,497 | 1.433,06 |
| RAG idênticos: atualização/remoção | 240 | 0 | 59,135 | 80,876 | 12.319,18 |
| RAG idênticos: consultas recuperadas | 300 | 0 | 5,475 | 10,282 | 1.713,48 |
| RAG distintos: ingestão | 80 | 0 | 15,528 | 21,139 | 1.320,39 |
| RAG distintos: atualização/remoção | 240 | 0 | 49,836 | 66,631 | 10.211,95 |
| RAG distintos: consultas recuperadas | 300 | 0 | 1,686 | 2,168 | 525,82 |

São **600 consultas RAG após 480 atualizações e 160 ingestões**; 160 chunks ativos persistem em cada cenário. Probes diretos ao Chroma nativo reproduziram **11 exceções com vetores idênticos e 2 com distintos**; o retriever recuperado teve **0/600 falhas**. A mediana RAG usa `statistics.median`; outros p50/p95 usam posição no vetor ordenado, conforme código do teste. Não são percentis populacionais estimados.

A criação concorrente verifica um único ticket, uma execução do grafo e ausência de tools repetidas. A resolução concorrente verifica uma única resposta humana persistida e idempotência. Falhas intermitentes são deliberadas e provocam tickets; não são contabilizadas como erros do sistema quando o resultado parcial e o encaminhamento são corretos. As exceções nativas HNSW deliberadamente reproduzidas são distinguíveis de falhas do retriever recuperado.

## 7. Evidências de integrações reais

- **LangGraph:** `build_graph()` em `app/orchestration/graph.py` constrói e compila `StateGraph`; testes usam o objeto compilado e `astream` com updates/values para capturar nós efetivos. Não substituem o runtime nem suas transições.
- **Coordenação:** execução combinada observa `guardrail → router → knowledge → review → customer_support → review → synthesis`. `review` é o nome efetivo do nó Supervisor; os spans usam `supervisor`. Replanejamento observa `knowledge → review → web_search → review`; falha parcial conserva resultado válido e termina em `human`. O plano de três agentes também é executado e limitado; outputs de cada especialista alimentam o estado revisado antes do próximo passo.
- **HTTP:** servidor Uvicorn real em loopback, quatro requisições (health, OpenAPI e duas conversas), shutdown verificado. Demais testes FastAPI usam TestClient/ASGI real, sem socket externo.
- **SQLite:** memória, handoffs e telemetria reais em arquivos temporários, reabertura, transações/rollback, concorrência e migração de schema legado.
- **Chroma/HNSW:** persistência e consultas reais, centenas de atualizações/consultas, vetores idênticos/distintos, fechamento/reabertura; validações de top-k/threshold e atualização sem chunks obsoletos.
- **Getnet pública:** GET HTTPS real nas sete URLs de `scripts/ingest.py`, via pipeline de produção com allowlist e sanitização; **7/7 indexadas**, **36 chunks**, **4 resultados** recuperados. Evidência em [validation_public_ingestion.json](validation_public_ingestion.json). Embeddings de teste tornam a recuperação estrutural, não uma avaliação de relevância semântica.

[validation_runtime_evidence.json](validation_runtime_evidence.json) contém sequências efetivas, decisões de supervisão, métricas de retrieval e consumo sintético, sem conteúdo privado completo.

## 8. Simulações e mocks

Os modelos de planner, Knowledge, Web e synthesis são simulados, inclusive saída estruturada, tokens, timeout, exception e conteúdo inválido. Embeddings são determinísticos e sintéticos. CustomerRepository usa contas sintéticas; tools reais validam identidade e argumentos. Busca Tavily não é chamada: retornos controlados e `httpx.MockTransport` validam contratos HTTP, sanitização e falhas, não o serviço externo. Os testes de ingestão adversarial também usam transporte controlado; distinguem-se da ingestão Getnet real acima.

Os testes unitários antigos de RAG/roteamento usam doubles conforme cada fixture. `test_api.py` e `test_api_agentic.py` não devem ser apresentados como integração de LLM. O novo `test_final_system.py`, `test_graph_v6_real.py` e `test_rag_chroma_real.py` sustentam as afirmações de runtime/persistência reais, mantendo somente provedores e dados externos simulados.

## 9. Riscos e limitações restantes

- Citações/IDs existentes e correspondência literal comprovam vínculo a um trecho, **não veracidade nem entailment semântico**. Há teste de caracterização dessa limitação. RAG abstém sem evidência/citação válida, mas uma geração com referência válida ainda pode afirmar algo falso. Auditoria humana e judge calibrado externo continuam necessários para maior garantia.
- Prompt injection é mitigado por validação, regras e separação entre instruções/evidências; não é impossível. Parafraseamento adversarial desconhecido pode contornar regras.
- Locks são locais ao processo, sem FIFO estrito, sem coordenação entre workers. Requisições fora de ordem são processadas conforme aquisição; não há sequenciamento do cliente. Testes provam isolamento e ausência de leitura concorrente desatualizada, não ordenação distribuída.
- Âncora contextual busca no máximo 100 turnos anteriores; sessões ainda maiores só com elipses podem perder contexto. Não é memória semântica ilimitada.
- Timeout cancela espera assíncrona, mas não mata imediatamente chamadas síncronas já em threads; SDK, SQLite e transporte mantêm seus próprios limites. Ferramentas atuais são leituras; escritas externas precisariam de idempotency keys.
- Recuperação HNSW reindexa embeddings ativos temporariamente e custa CPU/memória proporcional à base; o defeito nativo permanece no acesso direto. Adaptador usa APIs internas pinadas. Não houve benchmark de milhões de vetores nem upgrade indiscriminado.
- Tokens opacos locais com expiração opcional não equivalem a OAuth/JWT/IdP. Credenciais legadas sem expiração continuam válidas; TLS, secret manager e rate limiting de borda exigem implantação própria.
- Telemetria é minimizada e pseudonimizada, não anonimizada; auth rejeitada antes de `/chat` não está incluída em todos os denominadores de chat. Falha do armazenamento de telemetria pode impedir registro durável. Preços configurados/tokens reportados não representam custo integral de embeddings/busca.
- Dependências emitem deprecations; `pip check` confirma metadados, não ausência de bugs nativos. Não foram feitas alterações amplas para eliminar avisos.

## 10. Regressões

Não há regressão conhecida nos testes executados. Os 151 testes anteriores permanecem na suíte. RAG preserva allowlist, redirects seguros, chunks válidos, persistência, top-k, threshold, citações, abstention, deduplicação e recuperação HNSW. Docker/Compose não foram modificados. Alterações intencionais: respostas whitespace passam a 422, token expirado a 401, conteúdo malformado de geração a fallback/abstention, falha transacional a JSON 503, traces ganham campos aditivos e a sessão concorrente aguarda seu turno.

## 11. Verificações dependentes de provedores externos

Não verificados: planner/geração com OpenAI real, embeddings OpenAI reais e relevância em produção, Tavily real, calibração LLM-as-judge, banco/CRM externo, Docker runtime, infraestrutura distribuída e latência/custo sob rede real. A ingestão HTTPS pública Getnet foi verificada e não exigiu serviço pago. Nenhuma autorização para cobrança foi inferida.

## 12. Parecer técnico

A execução integrada local e os caminhos críticos corrigidos são demonstráveis por artefatos e regressões. O projeto está apto a uma demonstração técnica local com escopo explícito: runtime LangGraph, API HTTP, persistência, isolamento, HITL e RAG estrutural reais; provedores pagos simulados. Não se declara prontidão irrestrita de produção nem qualidade semântica comprovada dos modelos externos. Para submissão, anexar este relatório e os artefatos, demonstrar os cenários, e concluir vídeo/repositório pelo responsável sem atribuir notas fictícias.
