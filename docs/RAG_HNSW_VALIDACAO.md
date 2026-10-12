# RAG V6: investigação e regressões Chroma/HNSW

Validação local com Python 3.12.10 da `.venv`, sem chamadas OpenAI e sem modificar
Docker, autenticação, memória ou LangGraph. Não representa nova avaliação da nota
8,8 original nem mede qualidade semântica de embeddings/LLMs externos.

## Causas reproduzidas

- Chroma 0.6.3 + chroma-hnswlib 0.7.6: após atualizações e remoções, o índice
  persistente combina HNSW com um buffer. A consulta nativa pede mais vizinhos
  para compensar atualizações/exclusões; vetores coincidentes e exclusões podem
  impedir a entrega desses vizinhos. Ocorreu com 160 registros ativos e top-k
  1, 2, 4 e 8, não apenas quando top-k excede o total disponível.
- A combinação também apresentou retorno incompleto sem exceção: 79 resultados
  com 80 registros relevantes disponíveis. Vetores distintos reduziram as
  falhas para top-k pequeno, mas não eliminaram problemas para k próximo do total.
- Coleções com configuração padrão de 1, 2, 4 e 10 fontes, com três chunks iniciais por fonte, retornaram
  normalmente o limite real de documentos disponíveis quando k era maior.
  A matriz também incluiu 40 e 80 fontes, ciclos 3 -> 2 -> 1 -> 2 chunks,
  top-k 1/2/4/8 e valores superiores ao total ativo.
- Um thread e batches menores não eliminaram todos os problemas. Aumentar
  search_ef/M também não resolveu o cenário da auditoria anterior.
- `pip check` não detectava a incompatibilidade funcional de telemetria:
  Chroma 0.6.3 chama `posthog.capture(distinct_id, event, properties)`; PostHog
  7.68.0 rejeita essa assinatura. PostHog 5.4.0 foi testado primeiro em um
  diretório isolado, sem dependências adicionais, e depois instalado na `.venv`.
- O indexador direto verificava apenas propriedade da URL, permitindo URLs
  não oficiais e chunks vazios. A ingestão HTTP e o Knowledge Agent já tinham
  barreiras, mas isso não protegia a entrada direta do indexador.

## Correção restrita

O caminho normal de recuperação permanece Chroma. Apenas a exceção nativa
específica ou um retorno menor que `min(top-k, active_count)` antes do threshold
aciona reconstrução de um HNSW temporário com os vetores ativos armazenados.
Não há busca linear substituindo HNSW, redução arbitrária de k, alteração da
coleção persistente ou reembedding dos documentos. A conversão de distância em
relevância permanece a do LangChain-Chroma, inclusive para l2/cosine/ip.
Falhas na reconstrução continuam propagando para abstention/handoff.

O indexador agora valida URL oficial e todos os conteúdos antes de modificar
metadados ou escrever a substituição. Uma entrada inválida não remove a versão
anterior. IDs estáveis, isolamento por URL e remoção de chunks antigos permanecem.

Versões testadas e fixadas: Chroma 0.6.3, chroma-hnswlib 0.7.6,
LangChain-Chroma 0.2.3 e PostHog 5.4.0. Apenas PostHog mudou no ambiente;
as outras versões já estavam instaladas. Não houve migração ampla de dependências.

## Reprodução automatizada

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs tests\unit\test_indexing_idempotency.py tests\integration\test_rag_chroma_real.py
.\.venv\Scripts\python.exe -m pytest -q -rs
```

`test_update_delete_stress_and_persistence` usa Chroma persistente verdadeiro,
embeddings determinísticos, 80 ingestões, 240 atualizações e 300 consultas em
cada cenário (vetores idênticos/distintos), além das sondagens de top-k. Asserções
exigem quantidade correta de resultados, ausência de chunks antigos e nenhum
embedding adicional de documentos durante as consultas. O banco original é
parado e reaberto em outro processo Python para validar persistência.

Uma rodada local de medição produziu:

| Vetores | Ingestão: 80 operações | Atualização: 240 operações | Consulta: 300 operações | p95 de consulta | Falhas entregues ao chamador |
|---|---:|---:|---:|---:|---:|
| Idênticos | 1.131,40 ms | 8.586,31 ms | 1.617,05 ms | 9,416 ms | 0 |
| Distintos | 1.168,91 ms | 9.489,09 ms | 536,84 ms | 2,526 ms | 0 |

As sondagens nativas sem recuperação registraram 11 e 1 exceções, respectivamente.
Os tempos são de execução local sequencial, não um benchmark de produção; variam
com CPU/disco e não incluem latência de APIs externas. Logs `rag_hnsw_recovery`
identificam o caminho de recuperação.

Suíte completa após as correções e o teste de parada/reabertura do banco:
**151 passed, 0 failed, 0 skipped, 5103 warnings em 49,58 segundos**.
Os 117 testes anteriores permanecem, com 34 regressões/caracterizações novas.
`pip check`: **No broken requirements found**. Os avisos são detalhados abaixo;
o erro de assinatura de telemetria não voltou a ocorrer nos testes.

## Segurança e limites preservados

IDs citados inexistentes, zero/negativos, falta de citações e `supported=false`
continuam levando a abstention. Conteúdo recuperado permanece como dado não
confiável no prompt humano; não pode substituir a mensagem de sistema. Isso
reduz risco de prompt injection, mas não prova resistência universal do modelo.

O teste de caracterização `test_valid_citation_is_not_semantic_truth_verification`
mostra que um provedor adversarial pode citar um ID real e produzir uma afirmação
falsa. IDs válidos não provam veracidade. Uma extensão futura com trechos literais
verificados poderia rejeitar citações de texto inexistente, mas também não
substituiria verificação semântica ou revisão humana. Não foi introduzida uma
mudança de contrato LLM nesta correção.

A reconstrução temporária custa memória/CPU proporcionais ao corpus e pode
repetir o embedding da consulta. Não modifica os vetores armazenados. Usa APIs
internas do adaptador Chroma para métrica/relevância, justificando as versões
fixadas e os testes de regressão antes de futuras atualizações. O defeito da
dependência permanece reproduzível nas consultas diretas sem recuperação.

Persistem avisos de depreciação de Pydantic no Chroma e LangGraph, além de pequenas
diferenças float32/float64 nas métricas cosine/ip. Nenhuma atualização ampla foi
feita para silenciar avisos. Recall, factualidade, threshold com embeddings reais
e resistência do LLM a prompt injection ainda exigem validação externa controlada.
