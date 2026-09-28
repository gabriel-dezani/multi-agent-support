from app.rag.ingestion import build_chunks
from app.rag.vector_store import get_vector_store

URLS = [
    "https://www.getnet.net/en",
    "https://site.getnet.com.br/pix/",
    "https://site.getnet.com.br/link-de-pagamento/",
    "https://site.getnet.com.br/conta-digital/",
]


def main():
    docs = []
    seen = set()
    for url in URLS:
        for doc in build_chunks(url):
            key = doc.metadata.get("content_hash") or doc.metadata.get("chunk_id")
            if key not in seen:
                seen.add(key)
                docs.append(doc)
    if not docs:
        raise RuntimeError("Nenhum documento válido para ingestão")
    get_vector_store().add_documents(docs, ids=[d.metadata["chunk_id"] for d in docs])
    print(f"Ingestão concluída: {len(docs)} chunks únicos")


if __name__ == "__main__":
    main()
