# Evolução V8 — engenharia e validação offline sem API paga

## Objetivo e origem

Implementação incremental sobre a V7 corrigida (aquela que passou em 260 testes na máquina do usuário). O feedback da avaliação original atribuiu **9,2 à V6**, não a esta V8. **Esta entrega não recebeu nova nota do avaliador.** 9,8 permanece uma meta, não uma pontuação atingida.

Nenhuma chamada OpenAI, Tavily ou outro endpoint pago foi utilizada para desenvolver ou testar estas alterações.

## Incrementos comprováveis nesta rodada

1. **Operação e HITL:** códigos de falha do fornecedor (`insufficient_quota`, `credit_balance_exhausted`, `invalid_api_key`, `rate_limit_exceeded`) não são confundidos com dúvida de cliente. A API produz `503`, request ID e registra telemetria sanitizada, sem registrar conversas nem criar tickets humanos para incidentes de infraestrutura. A ausência de credencial de modelo não impede testes unitários offline.
2. **Segurança / completude:** endpoints autenticados documentam `HTTP Bearer` de forma nativa na especificação OpenAPI, usando botão **Authorize** do Swagger. O mesmo validador local/OIDC da V7 continua em vigor; `user_id`, RBAC e allowlist continuam vinculados à credencial.
3. **RAG / qualidade numérica:** relevância Chroma levemente maior que 1 por precisão de ponto flutuante é normalizada. Scores não finitos ou fora do intervalo de tolerância são rejeitados; o limiar mínimo semântico não é reduzido.
4. **Evals reproduzíveis:** MRR/nDCG respeitam a posição de fonte inválida no top-k. Registros duplicados não aumentam recall. `scripts/offline_quality_scorecard.py` executa 24 cenários sintéticos de grounding e 30 regressões de roteamento, falhando explicitamente quando uma regressão é detectada. CI salva um artefato JSON com hash de dataset e classificação de escopo.
5. **Transparência:** o scorecard relata `human_verified_semantic_accuracy: null` e `scope: offline_synthetic_contracts_only`. As aprovações NÃO equivalem à precisão semântica/factual do LLM em produção.

## Execução gratuita no PyCharm

Com `.venv` ativo dentro da pasta do projeto:

```powershell
python -m scripts.offline_quality_scorecard --output offline_quality_scorecard.json
python -m pytest -q
```

Os comandos usam arquivos locais e testes simulados. O primeiro não invoca API. A suíte pytest existente foi desenhada para não depender de credenciais reais; mantenha o ambiente de teste isolado.

Se não quiser executar nenhuma chamada real ao usar a aplicação, deixe de iniciar `/chat` e evite `scripts.ingest` com `OpenAIEmbeddings`. Desabilitar `ROUTER_USE_LLM` sozinho **não torna o agente Knowledge offline**, porque embeddings/geração no caminho de produção continuam usando provedores.

### Avaliação factual SEM juiz LLM

Para produzir uma avaliação com **rótulos humanos de verdade**, crie um JSON com pelo menos 20 casos, contendo 8 afirmações claramente não sustentadas, cada uma revisada manualmente. Cada entrada deve incluir: `id`, `answer`, `evidence` (lista de textos oficiais), `sources` (URLs oficiais), `human_supported` (booleano decidido por revisor) e `reviewed_by` (identificador do revisor).

```powershell
python -m scripts.evaluate_grounding_local --dataset data/grounding_revisado.json --output scorecard_humano.json
```

Esse script mede a taxa de falsas aceitações do verificador heurístico sem rede, tokens nem créditos. **Nenhum rótulo humano foi inventado ou incluído nesta entrega.** Os 24 cenários sintéticos servem apenas para prevenção de regressões.

## Cobertura de critérios do feedback

| Critério | O que foi fortalecido nesta V8 | Pendente para alegar 9,8 |
|---|---|---|
| Observabilidade (8,8) | Resultado técnico `503` com telemetria e request id, CI evidências | Traços distribuídos e alertas em infraestrutura implantada |
| RAG (9,2) | Métricas que preservam ranking, scores válidos Chroma, regressões de grounding | Golden set revisado por humanos, reranker dedicado e prova de ganho de qualidade factual |
| Multi-agent (9,2) | Fallback não confunde indisponibilidade externa com decisão humana | Benchmark de replanejamento com casos adversariais complexos |
| Segurança (9,2) | HTTP Bearer explícito no OpenAPI e manutenção de RBAC | IdP e segredos corporativos de fato configurados |
| HITL (9,5) | Sem ticket falso por incidentes de créditos/serviço | Auditoria de jornadas reais de operadores |
| Infra (8,5) | Resposta de falha operacional clara sem estado inconsistente | DB e locks distribuídos, testes de deploy Docker/HA |
| Testes / quality (9,4) | Gate CI offline e cenários sintéticos com rótulos transparentes | Dados humanos de grounding e retrieval; medir false-accept sem LLM como prova semântica não basta |

## Resultado da validação nesta sessão

- Testes unitários focados podem ser executados sem acesso externo. Detalhes no retorno da execução desta rodada.
- A suíte integral de integração `LangGraph + Chroma` **não foi executada neste ambiente** por ausência dessas bibliotecas, embora a V7 anterior tenha passado 260 testes na máquina Windows do usuário.
- Validação real do provedor NÃO é pré-requisito para continuar desenvolvendo. É uma camada opcional separada, não uma etapa para a qual o usuário precise comprar créditos.
