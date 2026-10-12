import logging
from app.rag.ingestion import build_chunks
from app.rag.vector_store import get_vector_store

URLS = [
    "https://www.getnet.net/en",
    "https://site.getnet.com.br/pix/",
    "https://site.getnet.com.br/link-de-pagamento/",
    "https://site.getnet.com.br/conta-digital/",
    "https://site.getnet.com.br/crediario/",
    "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/como-antecipar-sua-vendas-pelo-app/",
    "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/",
]


def main():
    from app.rag.indexing import upsert_source

    store = get_vector_store()
    updated = 0
    stale_removed = 0
    failed = []
    for url in URLS:
        try:
            docs = build_chunks(url)
            if not docs:
                raise ValueError("Página não possui chunks utilizáveis")
            count, stale = upsert_source(store, url, docs)
            updated += count
            stale_removed += stale
            logging.info("Página atualizada: %s (%s chunks)", url, count)
        except Exception as exc:
            failed.append(url)
            logging.warning("Página ignorada (%s): %s", url, type(exc).__name__)
    if not updated:
        raise RuntimeError("Nenhum documento válido para ingestão")
    logging.info("Ingestão concluída: %s chunks; %s obsoletos removidos; %s URLs falharam",
                 updated, stale_removed, len(failed))
    if failed:
        logging.warning("Rever URLs não ingeridas: %s", ", ".join(failed))


if __name__ == "__main__":
    main()
