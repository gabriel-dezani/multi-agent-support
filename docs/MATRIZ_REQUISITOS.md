# Matriz de aderência ao desafio e ao feedback

A avaliação recebida (nota geral 7,5/10) refere-se ao repositório original. As **situações abaixo são implementação/validação, não notas previstas**. A meta é superar 8,5 em cada critério anteriormente abaixo do limiar, mas isso só pode ser confirmado por nova avaliação externa.

| Dimensão | Nota original | Implementação consolidada | Evidência / pendência |
|---|---:|---|---|
| Arquitetura e código | 8,7 | Módulos separados, bounded graph, schemas, CI | Testes locais e revisão de source; runtime real ainda pendente |
| Multi-agent / orchestration | 7,0 | Planner LLM estruturado, até 3 especialistas, supervisor após cada passo, replanejamento público limitado a Getnet, síntese e fallback | Dataset roteamento e 19 verificações do grafo **emulado**; falta runtime LangGraph real |
| RAG / Knowledge | 8,8 | Chroma/OpenAI + retrieval threshold, grounded prompt, HTTPS/redirect/size | Preservado e endurecido; sem avaliação factual real nesta execução |
| Segurança / isolamento | 7,3 | Bearer token mapeado a `user_id` obrigatório no payload, roles, endpoint de operador, isolamento no banco | Unitários, negativas HTTP, concorrência, feedback apenas do dono |
| Testes / quality | 8,2 | pytest + avaliação golden, regressões multi-turn/concurrency, CI e smoke | 52 testes pytest aprovados, 6 módulos ignorados por libs ausentes; smoke 25 HTTP, 19 verificações de grafo emulado, 9 verificações RAG offline e 60+40 requisições HTTP concorrentes |
| Observabilidade / evals | 7,1 | Spans persistidos, métricas p50/p95, retrieval hits/scores, logs, tokens reportados, custo condicionado, feedback por cliente e juiz LLM opcional | Teste de persistência e leitura, falta avaliação LLM-as-judge e métricas reais de RAG/custo completo |
| Memória / multi-turn | 1,0 | SQLite com isolamento usuário × conversa; histórico isolado em SQLite, usado pelo Router e pelo Knowledge para interpretar referências; não se exporta histórico ao Web Search público | Testes de isolamento, dataset 5 turnos 100% em classificação offline; geração real ainda pendente |
| Human-in-the-loop | 3,0 | Ticket persistente, índice único por sessão, fila/operador, resolução atômica, retomada após humano | Concorrência, HTTP smoke, persistência; sem painel/UI e SLA |
| Infra / Docker | 9,0 | Python slim, non-root, volumes, Compose, healthcheck, CI Docker build | Arquivos presentes; build local não executado sem Docker |
| Produto / completude | 8,0 | API compatível, Swagger, documentação, replay de memória, métricas e manual operacional e relatórios internos de aceite | Teste end-to-end com rede pendente; vídeo não incluído por solicitação do usuário |
| Trade-offs | 9,2 | Limites explícitos, estratégias de falha segura e escopo demo documentados | Registrado no README; precisa defender decisões na entrevista |

## Requisitos exatos do enunciado

1. Router, Knowledge, Support e comunicação: **implementados** (plus Web, Synthesis, Guardrail, Human).
2. Knowledge com RAG e pesquisa web: **implementados**, mas a pesquisa geral é delegada ao Web Search Agent para separar responsabilidades.
3. Duas tools no Support: **implementadas** (mock data).
4. `POST` recebendo `message` e `user_id`: **mantidos**; Bearer autentica a identidade do cliente.
5. Docker: **fornecido**.
6. Estratégia de testes/integrados: **documentada**, com casos automatizados.
7. README e caminho GitHub: **fornecido**; publicar/linkar o repositório é ação posterior do proprietário.
8. Vídeo de walkthrough: **não gerado por decisão de escopo do solicitante**; o enunciado original menciona esse item, mas esta entrega é somente código em um ZIP.

## O que não é possível comprovar neste ambiente

- Nota prevista de avaliador (especialmente limiar 8,5): não há nova banca ou rubrica numérica oficial por critério.
- Qualidade factual/grounding do RAG ao vivo, custo/tokens completos, fluidez do planner LLM em produção.
- Testes de integração com pacotes LangGraph/LangChain/Chroma e build Docker: instalação indisponível por falha de rede.
- O item de vídeo do enunciado original não integra esta entrega por solicitação do proprietário.
