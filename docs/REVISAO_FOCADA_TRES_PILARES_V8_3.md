# V8.3 — revisão concentrada nos 3 maiores gaps da avaliação 9,2

**Referência:** `feedback_gabriel_dezani_02.md`, versão avaliada com nota 9,2.
**Objetivo:** entregar evidências e controles que possam sustentar uma reavaliação ≥9,6.
**Nota:** nenhuma pontuação foi inventada ou reatribuída; a decisão cabe ao avaliador.
**Restrições:** desenvolvimento e CI offline, sem OpenAI/Tavily/LLM judge pago.

## 1. RAG e factualidade — nota anterior 9,2

### Já vinha da V8.2.1

- Ingestão controlada, sanitização, threshold e citação/abstenção.
- Retrieval dense + BM25 + RRF, máximo de chunks por fonte.
- Verificador factual heurístico e contrato de avaliação offline.
- Métricas de retrieval (Recall@K, MRR, nDCG, Hit@K).

### V8.3: mudança nova

- `app/evaluation/paired_retrieval.py`: **comparação A/B nas MESMAS perguntas**.
  A/B mede dense vs hybrid, inclui delta pareado, bootstrap determinístico de 95%,
  identificação de falhas e segmentação por categoria.
- Exige `id`, pergunta distinta, categorias, URLs HTTPS e registro de revisão
  (`reviewed_by`, `reviewed_at`), e recusa duplicatas/casos não rotulados.
- Gates identificam regressões de métricas e falhas de recuperação.
- `KnowledgeRetriever.retrieve(..., hybrid_enabled=...)` permite alternar o
  método sem modificar configuração global, mantendo o mesmo Chroma/index.
- Script `scripts/compare_retrieval.py` grava relatório com SHA-256 do conjunto.
  **Não faz parte do CI gratuito**, pois embeddings OpenAI podem gerar custo.
- `data/reviewed/README.md` fornece instrução de CURADORIA HUMANA. Nenhum
  exemplo artificial foi marcado como verdade factual de produção.

### Lacunas explícitas

- O conjunto humano de perguntas e URLs oficiais ainda precisa ser revisado.
- Não foi validada a qualidade de texto gerado com um LLM real; sem essa evidência
  não é possível comprovar factualidade semântica de ponta a ponta.
- BM25 + RRF reordena candidatos densos, mas ainda não implementa um
  cross-encoder dedicado nem um índice lexical centralizado; não declarar
  equivalência com arquitetura mais completa do Skywalker.

## 2. Infra e múltiplas instâncias — nota anterior 8,5

### Já vinha da V8.2.1

Docker, Compose, usuário sem privilégios, check de saúde, CI, SQLite transacional,
tracing e alertas. Limite real: SQLite + `session_lock` em processo único.

### V8.3: mudança nova

- `STATE_BACKEND=postgres` e `STATE_DATABASE_URL`: configuração opcional e
  driver `psycopg` carregado apenas quando ativado.
- `app/core/postgres_state.py`: memória, tickets e telemetria numa base
  PostgreSQL central; tickets pendentes deduplicados por **índice único parcial**;
  resolução e inclusão da mensagem humana dentro da MESMA transação.
- `app/core/distributed_lock.py`: advisory locks entre instâncias, identificados
  por hash estável do usuário autenticado + conversa, com timeout e liberação
  após cancelamento/erro.
- `scripts/postgres_state_smoke.py`: contrato com Postgres real para testar
  20 criações concorrentes do mesmo ticket, rollback/resolução atômica,
  isolamento, métricas, exclusão mútua, timeout e independência de chaves.
- CI ganha job com PostgreSQL 16 descartável, sem API paga.
- Cobertura de testes SQLite e de PostgreSQL é separada em relatórios: `.coveragerc`
  exclui os módulos opcionais de PostgreSQL do denominador de 90% local,
  enquanto o job PostgreSQL mede-os à parte. Não somar os números como se
  fossem uma cobertura unificada do projeto inteiro.
- `docker-compose.postgres.yml` e `requirements-postgres.txt`: modo de teste
  local opt-in. SQLite permanece o default e não requer PostgreSQL.
- `app/main.py`: inicializa tabelas antes de abrir tráfego, corrigindo a
  corrida do primeiro `/ready` num volume vazio.
- `readiness` verifica tabelas essenciais de memória, handoff e telemetria.
- `REPLICAS>1` **é recusado explicitamente**, inclusive no modo PostgreSQL,
  porque o Chroma EMBUTIDO ainda não permite múltiplos escritores seguros.

### Lacunas explícitas

- PostgreSQL real ainda precisa rodar no CI ou ambiente com Docker antes
  de declararmos esse backend certificado. Testes com mocks NÃO bastam.
- Indexação vetorial compartilhada, migração de dados, backup/restore, pool de
  conexões, TLS/secret manager e carga com múltiplas réplicas ainda pendem.
- Essa versão NÃO afirma que o modo `replicas>1` esteja pronto. O passo
  honesto para esse requisito é trocar Chroma embutido por um serviço vetorial
  compartilhado, depois remover o bloqueio sob evidência de stress real.

## 3. Supervisor e memória multi-turn — notas anteriores 9,2 / 9,0

### Já vinha da V8.2.1

- Supervisor revisando confiança, fontes, handoffs, replanejamento limitado,
  isolamento por cliente/conversa, janela de memória e resolução de elipses.
- Política de não exportar consultas privadas para mecanismos públicos.

### V8.3: mudança nova

- `get_history(..., current_message=...)`: só pesquisa âncora antiga quando a
  solicitação atual REALMENTE depende do contexto; assunto explícito não traz
  contexto anterior desnecessariamente. Consulta anterior limitada a 200 turnos
  do MESMO cliente/conversa. A janela do prompt continua limitada.
- API fornece `current_message` para a recuperação antes de rotear.
- `scripts/offline_long_turn_scorecard.py` testa **140 follow-ups por conversa**,
  reabertura da persistência, isolamento multiusuário, troca explícita de assunto
  e casos do supervisor em privado/público; 134 verificações automatizadas.
- Novos testes unitários sobre memória, supervisor e A/B de recuperação.

### Lacunas explícitas

- Esse scorecard é uma REGRESSÃO DETERMINÍSTICA de contexto/roteamento,
  não uma prova de qualidade de conversa gerada por modelos externos.
- Sem modelos reais não há comparação humana entre trajetórias alternativas
  nem garantia de que um LLM seguirá exatamente as expectativas de conteúdo.
- Deliberação ilimitada foi intencionalmente evitada para manter segurança,
  privacidade, latência e custos sob controle (trade-off defensável).

## Como executar localmente SEM custo de API

Abra a V8.3 no PyCharm com Python 3.12 / `.venv`, instale os pacotes normais:

```powershell
python -m pip install -r requirements.txt
python -m scripts.offline_quality_scorecard
python -m scripts.offline_supervisor_scorecard
python -m scripts.offline_long_turn_scorecard
python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90
```

Não é necessário `.env` nem `OPENAI_API_KEY` para essa verificação offline.
Se seu computador estiver configurado com `STATE_BACKEND=postgres`, mantenha
`STATE_BACKEND=sqlite` no modo de testes local até habilitar o Docker.

### Teste opcional de persistência centralizada SEM APIs pagas

Com Docker e PostgreSQL disponível (ainda não executado neste ambiente):

```powershell
python -m pip install -r requirements-postgres.txt
$env:TEST_POSTGRES_DSN="postgresql://ci:ci_test_only@127.0.0.1:5432/multi_agent_ci"
python -m scripts.postgres_state_smoke
```

**O banco acima deve ser de TESTE descartável**, nunca de cliente ou produção.
O job `postgres-contract` do GitHub Actions cria um banco isolado automaticamente.

## Gates para submissão ao avaliador

1. Suite completa e 90% de cobertura no Windows e no CI, sem testes pulados.
2. Scorecards offline registrados como evidência *estrutural*.
3. PostgreSQL real: transações e advisory locks aprovados no job opcional.
4. Dataset de retrieval revisado de fato por pessoa e métrica A/B calculada;
   sinalizar *não mensurado* se não houver esse dataset.
5. Testes de múltiplas réplicas e vector-service externo: **não disponíveis**
   nesta revisão; não apresentar como prontos em entrevista.

## Por que esta rodada não representa automaticamente 9,6

Cobertura alta, gates determinísticos e suporte arquitetural opcional
reduzem riscos, mas não comprovam geração factual com LLM nem operação de
múltiplas réplicas. Só a nova avaliação poderá atribuir nota. Isso não
impede desenvolvimento local contínuo, gratuito e reproduzível.
