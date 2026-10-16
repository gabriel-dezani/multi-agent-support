# Golden set de retrieval — preparo para revisão humana

Nenhum caso nesta pasta é apresentado como **revisado por uma pessoa** até receber
`reviewed_by` e `reviewed_at` reais, após conferência da URL oficial e da pergunta.
Não inserir nomes fictícios de revisores. Não fabricar uma nota de factualidade.

Esquema do arquivo JSON a produzir (`retrieval_gold_reviewed.json`):

```json
[
  {
    "id": "identificador-unico-001",
    "question": "Pergunta realmente revisada, sem dados de clientes",
    "category": "pix",
    "gold_source_urls": ["https://site.getnet.com.br/pix/"],
    "reviewed_by": "identificacao-real-do-revisor",
    "reviewed_at": "2026-10-13"
  }
]
```

**Atenção:** este é um exemplo de formato, NÃO um caso rotulado que já tenha sido
revisado. Escolha perguntas diversificadas (Pix, link de pagamento, terminal,
taxas, suporte), identifique consultas sem resposta e separe o conjunto de
desenvolvimento do de avaliação final. Confira URLs atuais antes de rotular.

Teste A/B na mesma base de Chroma, após preenchimento humano:

```
python -m scripts.compare_retrieval --dataset data/reviewed/retrieval_gold_reviewed.json --output retrieval_ablation.json
```

Se o provedor de embeddings usa OpenAI, esse comando pode consumir créditos.
**Não está no CI offline.** Métricas de retrieval não comprovam, sozinhas,
a qualidade factual do texto produzido pelo modelo.
