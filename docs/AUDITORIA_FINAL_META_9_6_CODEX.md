# Rodada final de engenharia — três pilares

Data: 15/10/2026. Python 3.12.10 / Windows. Trabalho exclusivo sobre o workspace local, após leitura de `AUDITORIA_FINAL_TRES_PILARES_CODEX.md`. Sem uso da main remota, publicação, instalação de serviços, alteração de `.env` ou chamada paga a modelos, embeddings ou busca. SQLite e Chroma persistentes utilizados nos testes são temporários; documentos, embeddings e respostas de provedores são sintéticos.

Antes das alterações, os diretórios/arquivos afetados foram copiados para:

`C:\Users\Nitro\AppData\Local\Temp\multi-agent-pre-final-08f90a61a3bc4abca13b356d31faf521`

`final_meta_96_changes.json` registra os arquivos de código/configuração alterados, hashes anteriores/atuais e a localização do backup. Os relatórios da auditoria anterior foram preservados. Nenhum teste anterior foi removido ou teve exigência reduzida.

## 1. Causas e correções implementadas

### RAG: candidatos independentes, união e segurança

**Problema anterior:** o snapshot BM25 só era consultado se houvesse candidatos densos aprovados; a fusão rejeitava qualquer documento fora desse conjunto. A recuperação lexical não ampliava recall.

**Implementação:** `app/rag/lexical.py` faz BM25 sobre um snapshot independente de documentos do Chroma. Só documentos com URL HTTPS na allowlist Getnet participam. O retriever executa esse caminho mesmo com resultado vetorial vazio e oferece modos `dense`, `lexical` e `hybrid`, preservando `hybrid_enabled` para compatibilidade. A consulta lexical não usa os resultados ANN como corpus.

Os candidatos lexicais fora do conjunto ANN passam por **admissão semântica exata**: reutilizam seus embeddings armazenados, calculam a distância com a métrica da coleção (`l2`, `cosine` ou `ip`) e usam a mesma conversão de relevância do Chroma. Vetor ausente, dimensões incompatíveis, valores não finitos, fonte inválida ou relevância abaixo do threshold impedem admissão. Um documento já rejeitado pela busca densa não recebe nova confiança a partir do BM25. Documentos não são reembutidos nessa verificação; no caminho normal da aplicação pode haver uma consulta adicional ao provedor de embeddings da pergunta quando existem candidatos novos. Nos testes, o provedor é inteiramente local.

RRF une os rankings e deduplica por identidade do chunk. Um candidato lexical novo recebe contribuição somente do ranking lexical; a validação exata não fabrica posição na busca ANN. Em empate RRF, a posição lexical antecede o score semântico no desempate. A relevância continua sendo um filtro de entrada, não probabilidade de factualidade. Diversidade e backfill de fontes permanecem. Contadores de admissão lexical entram na telemetria sem conteúdo documental ou texto privado.

O modo `lexical` significa **recuperação BM25 com o mesmo gate semântico de segurança**, não BM25 bruto autorizado a gerar respostas. Snapshot ou validação indisponíveis não promovem documentos sem verificação; o modo híbrido conserva os candidatos densos válidos. URL/citações, gate factual local, verificador independente configurável, abstention e tratamento de documentos como dados não confiáveis continuam no Knowledge. Os testes adversariais anteriores são reexecutados na suíte completa.

**Limite deliberado:** um documento com embedding realmente abaixo do piso semântico continua sendo recusado, mesmo com ótimo BM25. O ganho implementado alcança documentos relevantes omitidos do conjunto ANN/candidate budget; não elimina falhas do modelo de embeddings. O snapshot ainda é limitado por `rag_lexical_max_chunks`; não é um índice lexical distribuído de corpus ilimitado.

### PostgreSQL: limites de espera, readiness e evidência de CI

**Problemas:** aquisição do advisory lock não limitava todo o tempo de conexão; sessões SQL não tinham limites explícitos para statements/locks; readiness verificava apenas parte do schema. Além disso, o comando de cobertura PostgreSQL da CI herdava a exclusão local de seus próprios módulos.

**Correções:**

* `postgres_conversation_lock` aplica deadline à conexão e aquisição, fecha a conexão em erro/cancelamento e limita o desbloqueio explícito. O corpo protegido tem seu orçamento próprio de request, preservado.
* Conexões SQL usam `connect_timeout=5`, `statement_timeout=15000`, `lock_timeout=5000` e `idle_in_transaction_session_timeout=15000`; conexão do advisory lock usa statement/lock timeout de 5 segundos. São limites operacionais fixos atuais. Não há retry automático de mutações cujo commit possa ser ambíguo.
* Readiness PostgreSQL exige as cinco tabelas de estado/telemetria, coluna da migração de tópicos e sessão fora de modo read-only. Não substitui teste de todas as permissões nem a saúde completa do índice vetorial.
* Overlay PostgreSQL passa a ter restart policy no banco/API e `init` na API, permitindo ao orquestrador reiniciar uma API cujo startup falhou por indisponibilidade do banco. Nenhum serviço foi instalado ou iniciado nesta máquina.
* `.coveragerc.postgres` mede os dois módulos PostgreSQL com arquivo de dados separado, sem `omit`, e habilita cobertura de multiprocessing. A CI combina os dados e publica JSON separado; verifica que ambos os módulos aparecem com linhas executadas. A cobertura local original e seu gate de 90% permanecem.
* O smoke real exige DSN de serviço local/CI. Além dos contratos anteriores, testa rollback de resolução humana quando a gravação na memória falha, processos distintos disputando o mesmo advisory lock, liberação após encerramento de processo, falha de conexão seguida de nova operação e recuperação de tópico aos 250/500/1.000 follow-ups PostgreSQL. Todas as operações usam identificadores exclusivos de teste; não há exclusão de bancos existentes.

Dockerfile, Compose base/overlays, requisitos e job PostgreSQL existentes foram revisados. Não houve substituição do backend SQLite nem flexibilização do bloqueio de múltiplas réplicas.

### Memória e Supervisor: índice durável e recuperação limitada

**Problema de memória:** recuperar uma âncora exigia ler até 200 mensagens de usuário anteriores à janela. A primeira referência era perdida após cadeias mais longas de elipses.

**Implementação:** coluna `topic_anchor` na própria mensagem e índice parcial `(conversation_id,user_id,id) WHERE topic_anchor IS NOT NULL`. Somente tópicos explícitos de usuário são indexados; não há resumo gerado ou chamada a LLM. A migração é aditiva, transacional e idempotente; mensagens legadas são examinadas uma vez em lotes de até 500. SQLite serializa a migração com `BEGIN IMMEDIATE`; PostgreSQL usa advisory lock de migração em namespace distinto dos locks HTTP/memória.

O lookup da âncora anterior usa o índice, sem limite de 200 mensagens. “Retome o assunto vendas” pesquisa apenas âncoras da mesma conversa/usuário, em páginas, exigindo todos os termos significativos. O tópico retomado é persistido junto à mensagem, preservando a continuidade de perguntas elípticas subsequentes após restart. Mensagem explícita sobre outro assunto continua tendo prioridade. A janela de prompt permanece em 12 mensagens nos benchmarks e âncoras são limitadas a 500 caracteres.

Âncoras ficam na mesma linha da mensagem: TTL/clear não deixam uma cópia privada órfã em outra tabela. Testes exercitam migração de histórico legado, retenção, duas sessões simultâneas com 250 follow-ups cada, rollback de turno incompleto e retry após reabrir o store.

**Problema do Supervisor:** indisponibilidade/timeouts do primeiro especialista web causavam 503 antes que uma pergunta pública Getnet pudesse tentar o RAG local.

**Correção:** o grafo registra essa falha e permite uma tentativa local ainda não executada quando a política de privacidade, allowlist e orçamento autorizam. Resultado local válido encerra a tarefa com sua evidência; não recebe uma ressalva incorreta de que essa mesma pergunta ficou sem resposta. Falhas públicas gerais continuam retornando indisponibilidade quando não há alternativa segura. Erros de política como `privacy_blocked`, `unauthorized_tool` e `prompt_injection` impedem replanejamento; confiança, fontes e disponibilidade continuam sendo consideradas. A política também aceita disponibilidade explícita do Knowledge para callers que possuam essa informação; não foi criado um registro distribuído de saúde de especialistas.

## 2. Benchmark comparativo de retrieval

Comando: `python -m scripts.offline_final_pillars`.

Artefato completo: `final_pillars_benchmark.json`. São **12 perguntas sintéticas**, 64 documentos sintéticos no Chroma real e embeddings fixos locais. Há quatro casos de omissão no conjunto ANN, quatro paráfrases sem overlap lexical e quatro de concordância. No primeiro grupo, treze distratores semanticamente mais próximos ocupam o orçamento vetorial; o documento correto permanece acima do piso semântico e é encontrado pelo BM25. URLs dos documentos são fixtures sob hosts autorizados; não foram buscadas nem apresentadas como páginas reais revisadas.

As consultas e gold sources são idênticos entre modos. `previous_rerank` é uma ablação que reproduz a restrição anterior a candidatos densos; não executa toda a aplicação antiga. O hash do conjunto rotulado está no JSON. Não há rótulos nem revisão humana inventados.

| Modo, K=1 | Recall@1 | Precision@1 | MRR | nDCG@1 | Hit rate |
|---|---:|---:|---:|---:|---:|
| Restrição anterior / rerank | 0,6667 | 0,6667 | 0,6667 | 0,6667 | 0,6667 |
| Vetorial | 0,6667 | 0,6667 | 0,6667 | 0,6667 | 0,6667 |
| Lexical com gate | 0,6667 | 0,6667 | 0,6667 | 0,6667 | 0,6667 |
| Híbrido independente | 1,0000 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |

Também foi medido K=4 com o orçamento padrão de 12 candidatos densos:

| Modo, K=4 | Recall@4 | Precision@4 | MRR | nDCG@4 | Hit rate |
|---|---:|---:|---:|---:|---:|
| Vetorial | 0,6667 | 0,1667 | 0,6667 | 0,6667 | 0,6667 |
| Lexical com gate | 0,6667 | 0,1667 | 0,6667 | 0,6667 | 0,6667 |
| Híbrido independente | 1,0000 | 0,2500 | 1,0000 | 1,0000 | 1,0000 |

Há uma fonte relevante por pergunta, portanto a Precision@4 máxima é 0,25. O ganho é **8/12 → 12/12 perguntas com fonte recuperada neste corpus controlado**, sem inferência de melhora percentual no corpus real Getnet. Embeddings foram construídos para testar complementaridade; os resultados não medem groundedness humana ou generalização semântica.

### Procedimento para o conjunto de referência humano

1. Usar o esquema já existente em `data/reviewed/README.md`; nenhum arquivo de gold revisado foi encontrado ali. Selecionar perguntas públicas reais, sem dados de clientes, em categorias de produtos, condições, suporte público e consultas sem evidência. Separar desenvolvimento e avaliação antes de ajustar parâmetros.
2. Uma pessoa verifica pergunta, texto/documento, URL oficial, validade temporal e fontes contraditórias. Registrar identidade real, data real, categorias e URLs; não usar o gerador da resposta para fabricar rótulos. Recomenda-se revisão independente para desacordos, com decisão e justificativa rastreáveis.
3. Construir um snapshot versionado do corpus e registrar hashes, modelo de embeddings, parâmetros, data de coleta e relevância por documento. Casos sem resposta precisam de gate de abstention próprio; não preencher gold fictício para forçar Recall/MRR.
4. Usar `compare_retrievers` com os mesmos casos e funções `retrieve(...,mode='dense'/'lexical'/'hybrid')`; o parâmetro `human_reviewed=True` exige metadados, mas não autentica revisão. O avaliador pareado anterior continua disponível para bootstrap e regressão por categoria. Analisar também citações e sustentação de cada afirmação separadamente do retrieval.
5. Com o provedor OpenAI normal, embeddings de consulta podem consumir créditos. Essa execução **não foi feita** nesta rodada. Pode ser preparada com embeddings locais e corpus rotulado legítimo; uso pago futuro requer autorização própria.

## 3. Resultados de memória longa

Os tamanhos abaixo contam follow-ups, além de um turno inicial com o assunto. A consulta anterior `LIMIT 200` foi reproduzida sobre os mesmos registros para comparação funcional. As latências são medições locais de dez leituras, com outras validações em execução; não são SLO de produção nem comparação de velocidade com a versão anterior.

| Follow-ups | Turnos com semente | Âncora antes | Âncora depois | Mediana de leitura | Índice usado |
|---:|---:|---|---|---:|---|
| 250 | 251 | perdida | recuperada | 3,332 ms | sim |
| 500 | 501 | perdida | recuperada | 4,240 ms | sim |
| 1.000 | 1.001 | perdida | recuperada | 6,049 ms | sim |

Nos três tamanhos passaram: restart por nova instância do store, janela de 12 mensagens, isolamento por usuário/conversa, troca de assunto, retomada nominal do assunto antigo e continuidade depois de persistir a retomada. `EXPLAIN QUERY PLAN` confirmou `idx_memory_topics`. Tempos de escrita dos follow-ups: 6.014,71 / 11.777,00 / 23.587,36 ms, respectivamente; incluem abertura/commit de conexão por turno no Windows.

## 4. Testes desta rodada

**Suíte final: 415 testes aprovados, 0 falhas, 0 erros, 0 skips, em 213,76 segundos. Cobertura local: 93,06% (2.307 de 2.479 statements cobertos; 172 ausentes), com gate de 90% aprovado.** Artefatos: `final_meta_96_tests.xml` e `final_meta_96_coverage.json`. A primeira execução completa desta rodada passou com 413 testes/93,02%; a suíte foi repetida depois de acrescentar duas regressões das opções de conexão e uma asserção de continuidade imediata da retomada. Nenhuma execução de testes desta rodada registrou falha. Os resultados históricos de 385 testes/92,52% não são atribuídos a esta versão nem usados como baseline novo de cobertura; o denominador também mudou com os novos módulos. Há 6.000 warnings, predominantemente das dependências, preservados no resultado.

| Validação executada | Resultado real |
|---|---|
| Suíte completa final com cobertura | 415 aprovados; 0 falhas/erros/skips; cobertura local 93,06%; gate 90% aprovado |
| Testes focados, antes da ampliação final do corpus | 63 aprovados, 0 falhas |
| Benchmark offline final | Exit code 0; tabelas e resultados acima |
| Supervisor existente | 22/22 cenários offline, pass |
| Memória longa existente | 134 verificações offline, pass |
| Qualidade offline | 24 contratos factuais sintéticos e 30 de roteamento, pass |
| Multi-turn Router | 29/29 turnos, pass |
| Feedback V6 | 20/20 cenários, pass |
| Smoke HTTP | 25 asserções, pass |
| Smoke grafo | 24 asserções, pass; transições emuladas |
| Smoke Knowledge | 9 asserções, pass |
| Smoke privacidade web | 7 asserções, pass |
| Stress HTTP | 60 solicitações → um ticket; 40 resoluções → uma resposta humana; 10 solicitações de outro usuário, pass |
| `compileall` e `pip check` | Exit code 0; dependências sem incompatibilidades declaradas |
| Parse de CI e configuração de cobertura PostgreSQL | YAML com três jobs; serviço PostgreSQL 16 e fonte de cobertura dos dois módulos, `omit=[]`, dados separados e multiprocessing confirmados |

As regressões novas cobrem admissão lexical fora do conjunto denso, URLs inválidas, falta/corrupção de vetores, threshold, falha de snapshot, métricas de distância, migração/TTL/clear, isolamento concorrente, rollback/retry e deadline de lock. O **LangGraph real** foi testado com dois tipos de falha web simulada (indisponibilidade e timeout), recuperação pelo Knowledge e plano de exatamente dois especialistas. Nenhuma dessas execuções usa LLM/Tavily reais. A suíte anterior mantém os cenários de documentos contraditórios, injection, citações incorretas e alegações não fundamentadas.

## 5. Status PostgreSQL e cobertura

`Get-Command docker,psql,postgres -ErrorAction SilentlyContinue` não encontrou ferramentas no PATH. O driver opcional `psycopg` também não está instalado neste virtualenv. Não foi fornecido um banco de teste local. Não foram instalados serviços nem utilizados bancos externos. **PostgreSQL real, Docker build/Compose e job GitHub Actions não foram executados nesta sessão.** `final_meta_96_environment.json` registra as verificações de ambiente e configuração da cobertura separada.

Foi validado localmente o parse do workflow, a presença do serviço PostgreSQL 16, dependências declaradas, compilação dos módulos/smoke e carregamento da configuração separada de cobertura. Os testes locais de aquisição/fechamento usam driver simulado; não comprovam locks reais entre processos. Esses cenários estão implementados no smoke do job `postgres-contract`, com timeout de dez minutos e publicação de cobertura própria.

A configuração local `.coveragerc` continua excluindo `app/core/postgres_state.py` e `app/core/distributed_lock.py`; o percentual local não representa cobertura do backend PostgreSQL. `.coveragerc.postgres` corrige essa exclusão para o job separado, usa `.coverage.postgres` e não altera `.coverage` local. Não se exige um percentual PostgreSQL inventado; a CI verifica presença/execução dos módulos e publica o valor real quando for executada.

## 6. Quais operações podem ser retomadas

| Operação | Garantia implementada | Limite |
|---|---|---|
| Gravar turno | Par usuário/assistente atômico; replay interno do mesmo request_id/payload é no-op; falha permite retry após reabrir store | Request HTTP novo recebe outro ID; não é idempotência HTTP geral |
| Atualizar tópico | Mesma transação/linha da mensagem; migração transacional e repetível | Backfill grande custa tempo/lock no startup; planejar janela operacional |
| Criar ticket pendente | Unicidade por usuário/conversa e transação | Não retoma a execução de qualquer nó do grafo |
| Resolver ticket + resposta humana | Transição e memória juntas, somente a primeira resolução altera estado | PostgreSQL precisa da execução real de CI para esta entrega |
| Consultar dados de suporte | Ferramentas atuais são consultas; repetir leitura após falha é possível | Resultado pode mudar no tempo; não há snapshot de negócio distribuído |
| RAG/web | Uma tentativa alternativa permitida por política e orçamento | Não há checkpoint completo para continuar no meio de uma chamada |
| Telemetria | Persistência separada; falha não apaga turno já persistido | Pode haver lacunas de telemetria; não é entrega exatamente uma vez |

Não foi implementada execução exatamente uma vez nem recuperação distribuída completa após crash. Cancelar um request não garante interromper trabalho síncrono já iniciado em thread. Nenhuma ferramenta nova de mutação foi autorizada pelo replanejamento.

## 7. Arquivos desta rodada

Código e configuração alterados/adicionados:

* RAG/avaliação: `app/rag/lexical.py`, `app/rag/retriever.py`, `app/rag/ranking.py`, `app/evaluation/retrieval.py`.
* Memória/contexto: `app/memory/topics.py`, `app/memory/store.py`, `app/orchestration/context.py`.
* Supervisor/grafo: `app/orchestration/review_policy.py`, `app/orchestration/graph.py`.
* Infraestrutura: `app/core/postgres_state.py`, `app/core/distributed_lock.py`, `app/core/readiness.py`, `app/core/telemetry.py`, `docker-compose.postgres.yml`, `.github/workflows/ci.yml`, `.coveragerc.postgres`.
* Testes/ferramentas: `tests/unit/test_final_pillars.py`, `scripts/offline_final_pillars.py`, `scripts/postgres_state_smoke.py`.

Evidências: este relatório, `final_meta_96_changes.json`, `final_meta_96_environment.json`, `final_pillars_benchmark.json`, `final_meta_96_quality.json`, `final_meta_96_supervisor.json`, `final_meta_96_long_turn.json`, `final_meta_96_multiturn.json`, XML de testes e JSON de cobertura.

## 8. Pendências que ainda podem reduzir a avaliação

1. Exigir execução bem-sucedida do job PostgreSQL real antes de aprovar esse backend: os novos casos entre processos, falha/retorno de conexão e rollback ainda não foram executados contra servidor nesta rodada. Restart/queda real do servidor, permissões restritas e build/Compose continuam sem validação local.
2. O backend PostgreSQL continua opcional e Chroma local impede declarar prontidão de múltiplas réplicas. Locks SQL não tornam ingestão vetorial concorrente ou snapshots do Chroma transacionais.
3. BM25 usa snapshot limitado, reconstituído por consulta; em corpus maior é necessário medir e avaliar índice lexical incremental/serviço externo. Admissão de candidatos novos pode exigir um embedding adicional da pergunta. A política exata preserva segurança, mas continua dependente da qualidade dos embeddings.
4. Heurística factual não prova entailment. Contradições e validade temporal precisam de rótulos humanos e verificador semântico avaliado; a configuração de produção mantém o juiz independente obrigatório. Não foi inventada capacidade de resolver automaticamente documentos conflitantes ou desatualizados.
5. Tópicos são âncoras determinísticas curtas, não compreensão semântica de toda a conversa. Retomada nominal usa palavras explícitas; paráfrases sem termos comuns podem não encontrar tópico. O lookup elíptico é indexado, mas busca nominal pode percorrer muitas âncoras. Não há checkpoint distribuído completo do LangGraph.
6. Migração do novo campo é aditiva e idempotente, mas não constitui um framework completo de migrations versionadas com downgrade. Rollback operacional usa a cópia externa e preserva dados; a coluna adicional pode permanecer sem prejudicar código anterior. Testar volumes e janela de migração antes de produção.
7. Timeouts PostgreSQL são valores fixos e podem precisar de parametrização segundo carga/SLO. Opções customizadas da URI, como `search_path`, são preservadas; os caps de timeout são acrescentados por último para não serem desativados pela URI. Restart policy é recuperação pelo orquestrador, não prova de failover.
8. Avisos das dependências Chroma/Pydantic/LangGraph continuam presentes. Atualizar dependências exige rodada própria de compatibilidade; warnings não foram ocultados para melhorar o relatório.

## 9. Reproduzir sem APIs pagas

Na raiz, com o virtualenv existente:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs --cov=app --cov-report=json:docs/final_meta_96_coverage.json --cov-report=term --cov-fail-under=90 --junitxml=docs/final_meta_96_tests.xml
.\.venv\Scripts\python.exe -m scripts.offline_final_pillars
.\.venv\Scripts\python.exe -m scripts.offline_quality_scorecard --output docs/final_meta_96_quality.json
.\.venv\Scripts\python.exe -m scripts.offline_supervisor_scorecard --output docs/final_meta_96_supervisor.json
.\.venv\Scripts\python.exe -m scripts.offline_long_turn_scorecard --output docs/final_meta_96_long_turn.json
.\.venv\Scripts\python.exe -m scripts.evaluate_multiturn --mode router --output docs/final_meta_96_multiturn.json
.\.venv\Scripts\python.exe -m scripts.evaluate_feedback_v6
.\.venv\Scripts\python.exe -m scripts.offline_api_smoke
.\.venv\Scripts\python.exe -m scripts.offline_graph_smoke
.\.venv\Scripts\python.exe -m scripts.offline_rag_smoke
.\.venv\Scripts\python.exe -m scripts.offline_web_privacy_smoke
.\.venv\Scripts\python.exe -m scripts.offline_api_stress
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
.\.venv\Scripts\python.exe -m pip check
```

PostgreSQL, **somente quando houver serviço local descartável e `TEST_POSTGRES_DSN` configurado para ele**, sem utilizar credenciais de produção:

```powershell
.\.venv\Scripts\python.exe -m coverage run --rcfile=.coveragerc.postgres -m scripts.postgres_state_smoke
.\.venv\Scripts\python.exe -m coverage combine --rcfile=.coveragerc.postgres
.\.venv\Scripts\python.exe -m coverage report --rcfile=.coveragerc.postgres -m
.\.venv\Scripts\python.exe -m coverage json --rcfile=.coveragerc.postgres -o docs/final_postgres_coverage.json
```

O mesmo procedimento está no job `postgres-contract`, com serviço temporário próprio. Não requer API de modelo nem publicação do projeto.

## 10. Prontidão para nova avaliação

Está implementado e medido offline: recuperação lexical que amplia candidatos, fusão RRF com gate preservado, comparação de três modos nos mesmos casos, memória indexada aos 250/500/1.000 follow-ups, retomada durável e isolamento, recuperação segura de falha web pelo RAG e preparação de validação PostgreSQL com cobertura independente. As pendências de operação e qualidade semântica estão delimitadas acima.

A entrega permite uma nova avaliação técnica com evidências verificáveis. Não certifica produção distribuída e não garante nota 9,6 ou 9,8; isso depende de avaliação independente e dos resultados PostgreSQL/semânticos ainda pendentes.
