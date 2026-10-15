# Revisão V8.1 — observabilidade, readiness e gates offline

**Origem:** relatório de cobertura enviado pelo autor em 13/10/2026 para a V8 no Windows/Python 3.12: **283 testes aprovados**, **91% de cobertura global**, **5.737 warnings**. Os módulos `app/core/observability.py` e `app/core/readiness.py` apresentavam, respectivamente, **52% e 61%** de cobertura no relatório enviado. Estes percentuais são o baseline **antes** desta revisão, e não descrevem a V8.1.

## Correções implementadas

1. **Traces sem PII:** somente categorias estruturadas com valores conhecidos e métricas numéricas finitas/não negativas podem ser exportadas. O request ID só é exportado se for UUID válido. Assim, um campo falsamente rotulado como `route`, `status` ou `request_id` não permite exportar texto privado. O limite de 40 spans e o tratamento resiliente de indisponibilidade do exporter foram preservados.
2. **SLO mais exato:** quando estão disponíveis `errors` e `requests`, a taxa de erro é calculada por contagem real, sem reutilizar o valor arredondado do dashboard; medidas ausentes, negativas, infinitas, NaN ou inconsistentes não passam no gate.
3. **Readiness sem mutação:** `/ready` abre o SQLite existente com `mode=rw`, obtém/solta uma transação breve e fecha a conexão sem criar tabelas, alterar dados ou criar um banco inexistente.
4. **Configuração fail-closed:** os modos `APP_ENV`, `AUTH_MODE` e `RAG_VERIFIER_MODE` aceitam somente os valores declarados; grafias como `prod` ou `Production` não podem escapar silenciosamente das regras de produção.
5. **CI:** o teste de cobertura passa a exigir pelo menos **90% de cobertura de statements** com `--cov-fail-under=90`, além dos contratos offline existentes.
6. **Testes novos:** casos para privacidade de traces, exporter OTLP simulado, SLO na fronteira exata, SQLite sem mudanças de schema e rejeição de configurações incorretas.

## Verificação nesta rodada

- `python -m pytest -q tests/unit/test_v8_coverage_hardening.py tests/unit/test_observability_v7.py tests/unit/test_readiness_retention_v7.py`: **30 passed** (ambiente isolado de desenvolvimento; não representa toda a suíte).
- `python -m compileall -q app scripts tests`: aprovado.
- Arquivo de GitHub Actions validado como YAML.
- **Zero chamadas pagas** a OpenAI/Tavily ou a qualquer serviço externo.

## Próximos gates obrigatórios no Windows

```powershell
python -m scripts.offline_quality_scorecard
python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90
```

O projeto segue **single-process / SQLite**. A cobertura mede execução de linhas, **não** semântica factual de LLM, recall real de embeddings ou prontidão multi-réplica. Para buscar uma nova avaliação acima de 9,2, também são necessárias evidências rotuladas por humanos para qualidade factual, métricas reais sobre retrieval, supervision/replanning multi-turn e robustez operacional sob Docker; essas etapas podem ser estruturadas offline sem consumo de API, mas não devem ser declaradas verificadas antes de executadas.

**Não foi feita publicação no GitHub nesta revisão.**
