# Evolução pós-feedback V2 — objetivo 9,8/10 (candidato V7)

**Base:** projeto V6 publicado em `gabriel-dezani/multi-agent-support`, commit `6ad8416`. **Meta:** corrigir lacunas do feedback que atribuiu 9,2/10. **Esta entrega não recebeu nota do avaliador**; 9,8 é objetivo, não resultado aferido.

Referências de trabalho: `feedback_gabriel_dezani_02.md` (feedback fornecido pelo usuário) e benchmark público `https://github.com/farrulla-darze/skywalker`. Da referência Skywalker foram aproveitadas **ideias de avaliação com métricas determinísticas e experimentos**, não componentes de código nem credenciais, e a arquitetura Getnet original foi mantida.

## Matriz de melhorias implementadas

| Feedback V2 | Lacuna descrita | Incremento implementado nesta versão | Limite que permanece |
|---|---|---|---|
| Multi-agent 9,2 | Flexibilidade do supervisor | Replanejamento reverso com `bounded_replan`: RAG → web oficial ou web → RAG, preservando privacidade, no máximo 3 especialistas e sem repetição | Não há deliberação livre ou colaboração assíncrona em paralelo (intencional para controle de custo) |
| RAG 9,2 | Hybrid retrieval, reranker e métricas profundas | Candidatos semânticos ampliados + BM25 + RRF com diversidade por fonte e limiar semântico obrigatório; Recall@K, Precision@K, Hit@K, MRR e nDCG com gate real | *Reranking híbrido seguro*, não é um reranker neural dedicado. Um resultado só lexical não ultrapassa o filtro de similaridade; recall pode exigir futura expansão controlada |
| Qualidade factual | Citação ≠ verdade | Verificador de números, garantias e URLs não sustentados; verificação semântica estruturada opcional e **obrigatória em APP_ENV=production**; falha do verificador causa handoff | Verificação por LLM é probabilística; só calibração humana/live mede qualidade real |
| Segurança 9,2 | Credenciais demonstrativas | `AUTH_MODE=oidc` com assinatura RS256, JWKS HTTPS, emissor, audiência, expiração, roles e identidade assinada; token local de operador desativado em modo OIDC | IdP corporativo, TLS reverso e armazenamento seguro de segredos precisam ser configurados pelo operador |
| Observabilidade 8,8 | Sem tracing distribuído/alertas externos | Emissão opcional OTLP para collector externo com campos permitidos (sem texto/PII), `/ops/slo` autenticado com `pass/fail/insufficient_data`, retrieval timings e counters | Collector, dashboards e alertas externos só funcionam quando provisionados |
| Memória 9,0 | Gestão operacional do estado | TTL opcional `MEMORY_RETENTION_DAYS`, índice e deleção atômica de mensagens expiradas, mantendo isolamento por usuário/sessão | Retenção de tickets e auditoria demanda política corporativa adicional; não há armazenamento distribuído |
| Infra 8,5 | Robustez de implantação e replicação | Compose hardened opcional: root filesystem read-only, remoção de capabilities, limites de CPU/RAM/processos, tmpfs, logging rotation e restart; `/ready` checa persistência; validação estrita do modo produção | **Ainda single-service SQLite e locks por processo.** Não implementar múltiplas réplicas sem migrar estado/locks para backend compartilhado |
| Testes 9,4 | Mais gates e experimentos | Novos testes de segurança, roteamento, retrieval e factualidade; `scripts/evaluate_retrieval.py` e `scripts/calibrate_grounding.py` falham em gates não atingidos | Rodar teste integrado LangGraph/Chroma/Docker/LLM ao vivo em ambiente conectado, sem skips |
| Produto 9,3; HITL 9,5; trade-offs 9,6 | Componentes existentes maduros | Mantidos API, tickets atômicos, fila do operador, ownership, modelos limitados e rastreabilidade | UI operador e SLA externo ainda dependem de produto/implantação |

## Como rodar a versão incrementada

```powershell
python -m pip install -r requirements.txt
python -m pytest -q --cov=app --cov-report=term-missing
python -m scripts.evaluate_feedback_v6
python -m scripts.offline_api_smoke
python -m scripts.offline_api_stress
```

**RAG:** ingira a base em Chroma antes da execução com embeddings reais (`python -m scripts.ingest`). Configuração nova em `.env.example`: `RAG_HYBRID_ENABLED`, `RAG_CANDIDATE_MULTIPLIER`, `RAG_LEXICAL_MAX_CHUNKS`, `RAG_MAX_CHUNKS_PER_SOURCE`, `RAG_VERIFIER_MODE`. O modo `heuristic` protege contra afirmações de alto risco; `llm` adiciona uma crítica conservadora por outro prompt, com custo de tokens e maior latência. Sem evidência, **abster-se**.

**Retrieval live:** crie um dataset JSON revisado por especialistas, por exemplo:

```json
[
  {
    "id": "gold-01",
    "question": "Pergunta concreta sobre Pix Getnet",
    "gold_source_urls": ["https://site.getnet.com.br/pix/"],
    "reviewed_by": "revisor-humano",
    "reviewed_at": "2026-10-13"
  }
]
```

O registro é apenas um **formato de exemplo**, não um rótulo factual validado. Exija pelo menos 5 casos revisados, de preferência 30+ e cobrindo respostas negativas:

```powershell
python -m scripts.evaluate_retrieval --dataset data/retrieval_gold_reviewed.json --output retrieval_report.json --min-cases 5 --min-recall 0.80 --min-mrr 0.75 --min-hit 0.90
```

**Calibração semântica:** monte `data/grounding_calibration_reviewed.json` com itens `{id, question, answer, evidence: [trechos], human_supported: true|false, reviewed_by}`. Inclua muitos casos com alucinação humana identificada. Use:

```powershell
$env:OPENAI_API_KEY = "<sua_chave_local>"
python -m scripts.calibrate_grounding --dataset data/grounding_calibration_reviewed.json --output calibration_report.json --min-cases 20 --min-negatives 8 --max-false-accept 0.05
```

O gate reprova quando o juiz aprova respostas que o revisor humano marcou como não sustentadas. Os JSONs revisados **não estão incluídos porque não foram fornecidos**; não fabricamos nota, dataset, resultado de juiz ou qualidade live.

**Observabilidade OTLP:** `python -m pip install -r requirements-production.txt` ou build Docker hardened. Configure `OTLP_ENDPOINT=https://.../v1/traces` e `OTLP_SERVICE_NAME`. Traces nunca incluem corpo das mensagens, histórico, evidência bruta, tokens ou identidade do cliente; apenas request UUID e eventos estruturais. Em desenvolvimento é permitido `http://localhost:4318/v1/traces` para collector local.

**Docker endurecido (uma réplica):**

```powershell
docker compose -f docker-compose.yml -f docker-compose.hardened.yml up --build -d
docker compose ps
```

Por segurança, o Compose publica `127.0.0.1:8000` por padrão. Para exposição externa, use reverse proxy HTTPS com política de autenticação. `/health` é liveness; `/ready` checa armazenamento local; `/ops/slo` é exclusivo do operador.

**Produção:** exige `APP_ENV=production`, `AUTH_MODE=oidc`, issuer HTTPS, JWKS HTTPS no mesmo host, `OIDC_AUDIENCE`, `RAG_VERIFIER_MODE=llm` e OTLP HTTPS. Para ambiente de demonstração preserve `APP_ENV=development` e credenciais de teste. **Nunca compartilhe `.env`.**

## Evidências e pendências para reavaliação

- Os testes unitários adicionados podem ser executados offline. Consulte a validação desta rodada ao final da entrega; não misture contagens com relatórios V6 históricos.
- A suíte completa, o cenário LangGraph/Chroma, embeddings reais, E2E OpenAI/Tavily e Docker não foram reproduzidos neste ambiente por falta de dependências externas e rede.
- Antes da reavaliação, rode os scripts completos na máquina com Python 3.12 e dependências. Gere evidências brutas novas e acrescente relatórios de dados humanos rotulados. **A meta 9,8 depende do avaliador e de validação semântica real, não de quantidades de funcionalidades.**
- Para alta disponibilidade é necessária uma migração futura para banco compartilhado (por exemplo PostgreSQL), locking distribuído, migrações automatizadas por versão e implantação/alertas reais. O Compose hardened presente não equivale a isso.
