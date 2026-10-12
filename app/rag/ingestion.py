from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
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


def _valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and _is_allowed_host(parsed.hostname)
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (ValueError, TypeError):
        return False


def fetch_page(url):
    """HTTPS allowlist is checked BEFORE EVERY network request (including redirects).

    Streaming bounds memory usage even when remote Content-Length is missing.
    """
    if not _valid_url(url):
        raise ValueError("URL HTTPS Getnet não autorizada")
    s = get_settings()
    current = url
    with httpx.Client(timeout=s.request_timeout_seconds, follow_redirects=False,
                      headers={"User-Agent": "multi-agent-support/2.0"}, trust_env=False) as client:
        for _ in range(6):
            if not _valid_url(current):
                raise ValueError("Destino de redirecionamento não autorizado")
            with client.stream("GET", current) as response:
                if response.status_code in (301,302,303,307,308):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirecionamento sem destino")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                if "text/html" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Página não contém HTML")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_PAGE_BYTES:
                        raise ValueError("Página excede limite de download")
                text = bytes(content).decode(response.encoding or "utf-8", errors="replace")
                break
        else:
            raise ValueError("Redirecionamentos em excesso")
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "form"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else current
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
                    "chunk_id": hashlib.sha256(f"{url}::{i}".encode()).hexdigest(),
                    "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
                },
            )
        )
    return out
