from datetime import datetime, timezone
from urllib.parse import urlparse
import hashlib
import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import get_settings

ALLOWED_HOSTS = {"getnet.net", "www.getnet.net", "site.getnet.com.br"}
MAX_PAGE_BYTES = 5_000_000


def _is_allowed_host(hostname: str | None) -> bool:
    return bool(hostname) and (hostname in ALLOWED_HOSTS)


def fetch_page(url):
    original_host = urlparse(url).hostname
    if not _is_allowed_host(original_host):
        raise ValueError("Domínio não autorizado")
    s = get_settings()
    with httpx.Client(
        timeout=s.request_timeout_seconds,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": "multi-agent-support/1.0"},
    ) as client:
        response = client.get(url)
        final_host = urlparse(str(response.url)).hostname
        if not _is_allowed_host(final_host):
            raise ValueError("Redirecionamento para domínio não autorizado")
        response.raise_for_status()
        if len(response.content) > MAX_PAGE_BYTES:
            raise ValueError("Página excede limite")
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "form"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else str(response.url)
    return title, " ".join(soup.get_text(" ", strip=True).split())


def build_chunks(url):
    title, text = fetch_page(url)
    split = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for i, chunk in enumerate(split.split_text(text)):
        out.append(
            Document(
                page_content=chunk,
                metadata={
                    "source_url": url,
                    "page_title": title,
                    "retrieved_at": now,
                    "chunk_id": hashlib.sha256(f"{url}:{i}:{chunk}".encode()).hexdigest(),
                    "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
                },
            )
        )
    return out
