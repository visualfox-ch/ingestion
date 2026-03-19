from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..observability import get_logger

logger = get_logger("jarvis.web_docs_snapshot")


@dataclass
class SnapshotConfig:
    domain: str
    subdomain: str
    start_urls: list[str]
    allowed_domains: list[str]
    output_path: str
    version: str = "1.0"
    owner: str = "michael_bohl"
    channel: str | None = None
    language: str = "en"
    quality: str = "high"
    auto_reingest: bool = True
    max_depth: int = 0
    max_pages: int = 1
    timeout_seconds: float = 10.0
    rate_limit_ms: int = 0
    allowed_content_types: list[str] | None = None
    follow_links: bool = False


@dataclass
class SnapshotFile:
    url: str
    title: str
    file_path: str
    content_type: str


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "snapshot"


def _normalize_content_type(raw_content_type: str | None) -> str:
    if not raw_content_type:
        return ""
    return raw_content_type.split(";", 1)[0].strip().lower()


def _is_allowed_url(url: str, allowed_domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allowed = {domain.lower() for domain in allowed_domains}
    return bool(host) and any(host == domain or host.endswith(f".{domain}") for domain in allowed)


def _extract_links(base_url: str, soup: BeautifulSoup, allowed_domains: list[str]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        candidate = urljoin(base_url, href)
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            continue
        normalized = parsed._replace(fragment="").geturl()
        if normalized in seen:
            continue
        if not _is_allowed_url(normalized, allowed_domains):
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def _fetch_via_requests(url: str, timeout_seconds: float) -> tuple[str, str]:
    response = requests.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": "Jarvis-WebDocsSnapshot/1.0"},
    )
    response.raise_for_status()
    return response.text, _normalize_content_type(response.headers.get("Content-Type"))


def _fetch_via_scrapling(url: str, timeout_seconds: float) -> tuple[str, str]:
    from scrapling import Fetcher

    fetcher = Fetcher(auto_match=False)
    page = fetcher.get(url, timeout=timeout_seconds)
    if getattr(page, "status", 200) >= 400:
        raise requests.HTTPError(f"scrapling returned status {page.status}")
    html = getattr(page, "html_content", None) or getattr(page, "html", None) or ""
    content_type = _normalize_content_type(getattr(page, "content_type", "text/html"))
    return html, content_type or "text/html"


def get_fetch_backend() -> str:
    return "scrapling" if importlib.util.find_spec("scrapling") else "requests"


def _fetch(url: str, timeout_seconds: float) -> tuple[str, str, str]:
    backend = get_fetch_backend()
    if backend == "scrapling":
        html, content_type = _fetch_via_scrapling(url, timeout_seconds)
        return html, content_type, backend
    html, content_type = _fetch_via_requests(url, timeout_seconds)
    return html, content_type, backend


def run_web_docs_snapshot(
    config: SnapshotConfig,
    fetcher: Callable[[str, float], tuple[str, str, str]] | None = None,
) -> dict:
    if not config.start_urls:
        raise ValueError("start_urls must not be empty")
    if not config.allowed_domains:
        raise ValueError("allowed_domains must not be empty")
    if config.max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if config.max_depth < 0:
        raise ValueError("max_depth must be >= 0")

    for start_url in config.start_urls:
        if not _is_allowed_url(start_url, config.allowed_domains):
            raise ValueError(f"start_url not allowlisted: {start_url}")

    snapshot_root = Path(config.output_path)
    snapshot_root.mkdir(parents=True, exist_ok=True)

    files: list[SnapshotFile] = []
    queue: list[tuple[str, int]] = [(url, 0) for url in config.start_urls]
    visited: set[str] = set()
    fetch = fetcher or _fetch
    backend_used: str | None = None

    while queue and len(files) < config.max_pages:
        current_url, depth = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        html, content_type, backend = fetch(current_url, config.timeout_seconds)
        backend_used = backend
        normalized_content_type = _normalize_content_type(content_type)
        allowed_content_types = config.allowed_content_types or ["text/html"]
        if normalized_content_type not in {value.lower() for value in allowed_content_types}:
            logger.info("Skipping web docs page due to content type", extra={"url": current_url, "content_type": normalized_content_type})
            continue

        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string.strip() if soup.title and soup.title.string else current_url)
        markdown_lines = [f"# {title}", "", f"Source: {current_url}", "", f"Fetched-At: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", ""]
        body = soup.find("main") or soup.find("article") or soup.body or soup
        for node in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code"]):
            text = node.get_text(" ", strip=True)
            if not text:
                continue
            if node.name.startswith("h"):
                level = min(int(node.name[1]), 4)
                markdown_lines.extend([f"{'#' * level} {text}", ""])
            elif node.name == "li":
                markdown_lines.append(f"- {text}")
            elif node.name in {"pre", "code"}:
                markdown_lines.extend(["```", text, "```", ""])
            else:
                markdown_lines.extend([text, ""])

        parsed = urlparse(current_url)
        path_slug = _slugify(parsed.path or parsed.netloc)
        file_path = snapshot_root / f"{path_slug}.md"
        file_path.write_text("\n".join(markdown_lines).strip() + "\n", encoding="utf-8")

        files.append(
            SnapshotFile(
                url=current_url,
                title=title,
                file_path=str(file_path),
                content_type=normalized_content_type or "text/html",
            )
        )

        if config.follow_links and depth < config.max_depth and len(files) < config.max_pages:
            for next_url in _extract_links(current_url, soup, config.allowed_domains):
                if next_url not in visited:
                    queue.append((next_url, depth + 1))

        if config.rate_limit_ms > 0 and len(files) < config.max_pages:
            time.sleep(config.rate_limit_ms / 1000.0)

    return {
        "status": "completed",
        "backend": backend_used or get_fetch_backend(),
        "files": [file.__dict__ for file in files],
        "count": len(files),
        "output_path": config.output_path,
        "domain": config.domain,
        "subdomain": config.subdomain,
    }
