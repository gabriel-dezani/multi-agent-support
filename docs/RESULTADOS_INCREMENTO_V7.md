# Registro de validação do incremento pós-feedback V2

**Data:** 2026-10-13. **Fonte do projeto:** ZIP auditado da branch `main` de `gabriel-dezani/multi-agent-support` (V6, commit de referência `6ad8416`). Este é um **incremento local**, não um novo commit do GitHub.

## Evidências efetivamente produzidas

- `python -m compileall -q app scripts tests`: concluído, sem erros de sintaxe.
- Seleção de testes unitários antigos e novos executados neste ambiente: **67 passed**.
- A maior bateria incluiu novos testes em `test_rag_hybrid_v7.py`, `test_oidc_v7.py`, `test_observability_v7.py`, `test_replanning_v7.py`, `test_factual_verifier_v7.py`, `test_readiness_retention_v7.py`, `test_calibration_v7.py` e `test_weather_privacy_v7.py`, mais testes existentes de memória, contexto, métricas, segurança, guardrail, privacidade e telemetria.
- Uma seleção adicional de 63 testes antigos/novos aprovou 63 e acusou 1 **erro de dependência** (`langchain_core` ausente) no teste `test_grounding_eval.py`. O erro não representa avaliação funcional daquele componente.
- O ambiente de análise **não tem** `langgraph`, `langchain_core`, `langchain_chroma`, `chromadb`, `structlog`, Docker e acesso ao índice de pacotes; tentativa de `pip install structlog` falhou por DNS. Logo, NÃO foi possível reexecutar a suíte completa, os testes reais de grafo/RAG/HTTP e a construção Docker.
- **Não foram executados** modelos OpenAI reais, embeddings, Tavily, ingestão online, ensaio de performance/qualidade real ou calibração contra revisores humanos.

## Revalidação obrigatória antes de nova publicação

No Windows, partir da raiz do projeto com o Python 3.12 e venv criado:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q --cov=app --cov-report=term-missing
python -m scripts.evaluate_feedback_v6
python -m scripts.offline_api_smoke
python -m scripts.offline_graph_smoke
python -m scripts.offline_rag_smoke
python -m scripts.offline_api_stress
python -m scripts.evaluate --mode router --output router_v7.json
python -m scripts.evaluate_multiturn --mode router --output multiturn_v7.json
```

Para Docker: `docker compose -f docker-compose.yml -f docker-compose.hardened.yml up --build` e validar `/ready`, `/health`, autenticação e o fluxo humano completo.

Para qualidade semântica, obter chave OpenAI, popular Chroma, construir datasets rotulados e executar `scripts.evaluate_retrieval` + `scripts.calibrate_grounding` (consulte guia V7). **Não interpretar contagem de testes como garantia da nota 9,8.**
