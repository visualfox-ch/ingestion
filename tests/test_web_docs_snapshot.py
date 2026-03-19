from pathlib import Path

import pytest

from app.services.web_docs_snapshot import SnapshotConfig, run_web_docs_snapshot


def test_run_web_docs_snapshot_rejects_non_allowlisted_start_url(tmp_path):
    config = SnapshotConfig(
        domain="web_docs",
        subdomain="scrapling_docs",
        start_urls=["https://example.com/docs"],
        allowed_domains=["scrapling.readthedocs.io"],
        output_path=str(tmp_path),
    )

    with pytest.raises(ValueError, match="start_url not allowlisted"):
        run_web_docs_snapshot(config)


def test_run_web_docs_snapshot_writes_markdown_with_requests_fallback(tmp_path):
    config = SnapshotConfig(
        domain="web_docs",
        subdomain="scrapling_docs",
        start_urls=["https://scrapling.readthedocs.io/en/latest/Introduction/index.html"],
        allowed_domains=["scrapling.readthedocs.io"],
        output_path=str(tmp_path),
        max_pages=1,
    )

    def fake_fetch(url: str, timeout_seconds: float):
        assert timeout_seconds == 10.0
        html = """
        <html>
          <head><title>Scrapling Introduction</title></head>
          <body>
            <main>
              <h1>Introduction</h1>
              <p>Scrapling makes scraping easier.</p>
            </main>
          </body>
        </html>
        """
        return html, "text/html", "requests"

    result = run_web_docs_snapshot(config, fetcher=fake_fetch)

    assert result["status"] == "completed"
    assert result["backend"] == "requests"
    assert result["count"] == 1
    written = Path(result["files"][0]["file_path"])
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert "# Scrapling Introduction" in content
    assert "Scrapling makes scraping easier." in content


def test_run_web_docs_snapshot_follows_links_within_limit(tmp_path):
    config = SnapshotConfig(
        domain="web_docs",
        subdomain="scrapling_docs",
        start_urls=["https://scrapling.readthedocs.io/index.html"],
        allowed_domains=["scrapling.readthedocs.io"],
        output_path=str(tmp_path),
        follow_links=True,
        max_depth=1,
        max_pages=2,
    )

    html_by_url = {
        "https://scrapling.readthedocs.io/index.html": (
            "<html><head><title>Home</title></head><body><main><p>Home</p><a href='/intro.html'>Intro</a></main></body></html>",
            "text/html",
            "requests",
        ),
        "https://scrapling.readthedocs.io/intro.html": (
            "<html><head><title>Intro</title></head><body><main><p>Intro page</p></main></body></html>",
            "text/html",
            "requests",
        ),
    }

    def fake_fetch(url: str, timeout_seconds: float):
        return html_by_url[url]

    result = run_web_docs_snapshot(config, fetcher=fake_fetch)

    assert result["count"] == 2
    assert {Path(item["file_path"]).name for item in result["files"]} == {
        "index-html.md",
        "intro-html.md",
    }
