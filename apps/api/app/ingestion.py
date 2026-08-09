from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from .security import validate_public_url

ALLOWED_TEXT_TYPES = {
    "application/atom+xml",
    "application/json",
    "application/rss+xml",
    "application/xhtml+xml",
    "application/xml",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"reveal\s+(your\s+)?(secrets?|tokens?|credentials?)", re.I),
    re.compile(r"(?:call|use|invoke)\s+(?:the\s+)?tool", re.I),
)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.canonical_url: str | None = None
        self.author: str | None = None
        self.published_at: str | None = None
        self._in_title = False
        self._ignored_depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in {"script", "style", "nav", "footer", "noscript"}:
            self._ignored_depth += 1
        if tag.lower() == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical_url = values.get("href") or None
        if tag.lower() == "meta":
            name = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content") or ""
            if name in {"author", "article:author"} and content:
                self.author = content
            if name in {"article:published_time", "date", "datepublished"} and content:
                self.published_at = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() in {"script", "style", "nav", "footer", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if not clean:
            return
        if self._in_title:
            self.title = f"{self.title} {clean}".strip()
        if self._ignored_depth == 0:
            self._text.append(clean)

    @property
    def text(self) -> str:
        return "\n".join(self._text)


def prompt_injection_score(text: str) -> float:
    matches = sum(bool(pattern.search(text)) for pattern in PROMPT_INJECTION_PATTERNS)
    return round(min(1.0, matches / 2), 2)


async def fetch_public_text(
    url: str,
    *,
    max_bytes: int = 2_000_000,
    max_redirects: int = 5,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    current = validate_public_url(url)
    redirects: list[str] = []
    headers = {"User-Agent": "AgenticVideoStudio/0.1 (+https://agentic-video-studio.dev)"}
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_seconds, headers=headers) as client:
        for _ in range(max_redirects + 1):
            # DNS is resolved again before every request so redirects cannot cross into a private range.
            current = validate_public_url(current)
            async with client.stream("GET", current) as response:
                if response.status_code in REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response did not include a Location header")
                    target = validate_public_url(urljoin(current, location))
                    redirects.append(target)
                    current = target
                    continue
                response.raise_for_status()
                media_type = response.headers.get("content-type", "text/plain").split(";", 1)[0].lower()
                if media_type not in ALLOWED_TEXT_TYPES and not media_type.endswith("+xml"):
                    raise ValueError(f"Unsupported content type: {media_type or 'unknown'}")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Remote content exceeds the configured size limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if b"\x00" in body[:4096]:
                    raise ValueError("Binary content is not accepted by text ingestion")
                encoding = response.encoding or "utf-8"
                text = body.decode(encoding, errors="replace")
                return {
                    "url": current,
                    "content_type": media_type,
                    "text": text,
                    "content_hash": hashlib.sha256(body).hexdigest(),
                    "retrieved_at": response.headers.get("date"),
                    "redirect_chain": redirects,
                    "size_bytes": total,
                }
        raise ValueError("Remote URL exceeded the redirect limit")


def extract_article(fetch_result: dict[str, Any]) -> dict[str, Any]:
    text = str(fetch_result["text"])
    if fetch_result.get("content_type") in {"text/html", "application/xhtml+xml"}:
        parser = _ArticleParser()
        parser.feed(text)
        content = parser.text
        title = parser.title
        canonical = urljoin(str(fetch_result["url"]), parser.canonical_url) if parser.canonical_url else fetch_result["url"]
        author = parser.author
        published_at = parser.published_at
    else:
        content = text
        title = next((line.strip("# ") for line in text.splitlines() if line.strip()), "Imported source")[:300]
        canonical = fetch_result["url"]
        author = None
        published_at = None
    return {
        "title": title or "Imported source",
        "canonical_url": validate_public_url(str(canonical)),
        "content_markdown": content[:500_000],
        "author": author,
        "published_at": published_at,
        "metadata": {
            "content_type": fetch_result.get("content_type"),
            "retrieval_size_bytes": fetch_result.get("size_bytes"),
            "redirect_chain": fetch_result.get("redirect_chain", []),
            "source_content_hash": fetch_result.get("content_hash"),
            "prompt_injection_score": prompt_injection_score(content),
            "retrieved_content_is_data": True,
        },
    }
