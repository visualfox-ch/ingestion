from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


API_CONTEXT_ROOT = Path(
    os.environ.get(
        "API_CONTEXT_ROOT",
        str(Path(__file__).resolve().parents[3] / "docker" / "docs" / "knowledge" / "api_context"),
    )
)
SECTION_FILES = {
    "manifest": "manifest.json",
    "content": "content.md",
    "annotations": "annotations.local.md",
    "snapshot": "snapshot.md",
}


def _iter_pack_dirs() -> List[Path]:
    return sorted(path.parent for path in API_CONTEXT_ROOT.glob("*/*/*/manifest.json"))


def _load_manifest(pack_dir: Path) -> Dict[str, Any]:
    return json.loads((pack_dir / SECTION_FILES["manifest"]).read_text(encoding="utf-8"))


def _pack_summary(pack_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    relative_dir = pack_dir.relative_to(API_CONTEXT_ROOT)
    return {
        "provider": manifest["provider"],
        "doc_slug": manifest["doc_slug"],
        "language": manifest["language"],
        "title": manifest["title"],
        "version_label": manifest["version_label"],
        "verification_level": manifest.get("verification_level"),
        "source_url": manifest["source_url"],
        "pack_dir": str(relative_dir),
    }


def list_api_context_packs(
    provider: Optional[str] = None,
    language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    packs: List[Dict[str, Any]] = []
    for pack_dir in _iter_pack_dirs():
        manifest = _load_manifest(pack_dir)
        if provider and manifest["provider"] != provider:
            continue
        if language and manifest["language"] != language:
            continue
        packs.append(_pack_summary(pack_dir, manifest))
    return packs


def _get_pack_dir(provider: str, doc_slug: str, language: str) -> Path:
    return API_CONTEXT_ROOT / provider / doc_slug / language


def read_api_context_pack(
    provider: str,
    doc_slug: str,
    language: str = "py",
    section: str = "snapshot",
) -> Dict[str, Any]:
    if section not in {"manifest", "content", "annotations", "snapshot", "all"}:
        return {
            "success": False,
            "error": "Unknown section",
            "allowed_sections": ["manifest", "content", "annotations", "snapshot", "all"],
        }

    pack_dir = _get_pack_dir(provider, doc_slug, language)
    manifest_path = pack_dir / SECTION_FILES["manifest"]
    if not manifest_path.exists():
        return {
            "success": False,
            "error": "API context pack not found",
            "provider": provider,
            "doc_slug": doc_slug,
            "language": language,
        }

    manifest = _load_manifest(pack_dir)
    result: Dict[str, Any] = {
        "success": True,
        "provider": provider,
        "doc_slug": doc_slug,
        "language": language,
        "title": manifest["title"],
        "section": section,
        "pack_dir": str(pack_dir.relative_to(API_CONTEXT_ROOT)),
    }

    if section in {"manifest", "all"}:
        result["manifest"] = manifest
    if section in {"content", "all"}:
        result["content"] = (pack_dir / SECTION_FILES["content"]).read_text(encoding="utf-8")
    if section in {"annotations", "all"}:
        result["annotations"] = (pack_dir / SECTION_FILES["annotations"]).read_text(encoding="utf-8")
    if section in {"snapshot", "all"}:
        snapshot_path = pack_dir / SECTION_FILES["snapshot"]
        if snapshot_path.exists():
            result["snapshot"] = snapshot_path.read_text(encoding="utf-8")
        else:
            result["snapshot"] = None
            result["snapshot_warning"] = "snapshot.md not yet generated — run build_api_context_snapshot.py"

    return result


def _tokenize_query(query: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 2]


def _make_excerpt(text: str, query: str, width: int = 220) -> str:
    lower_text = text.lower()
    lower_query = query.lower()
    idx = lower_text.find(lower_query)
    if idx == -1:
        for token in _tokenize_query(query):
            idx = lower_text.find(token)
            if idx != -1:
                break
    if idx == -1:
        return text[:width].strip()

    start = max(0, idx - width // 3)
    end = min(len(text), idx + width)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."
    return excerpt


def search_api_context_packs(
    query: str,
    provider: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    query_lower = query.lower()
    tokens = _tokenize_query(query)
    results: List[Dict[str, Any]] = []

    for pack_dir in _iter_pack_dirs():
        manifest = _load_manifest(pack_dir)
        if provider and manifest["provider"] != provider:
            continue
        if language and manifest["language"] != language:
            continue

        content = (pack_dir / SECTION_FILES["content"]).read_text(encoding="utf-8")
        annotations = (pack_dir / SECTION_FILES["annotations"]).read_text(encoding="utf-8")
        snapshot_path = pack_dir / SECTION_FILES["snapshot"]
        snapshot = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else ""

        title_blob = " ".join(
            [
                manifest["title"],
                manifest["provider"],
                manifest["doc_slug"],
                manifest["language"],
                manifest.get("version_label", ""),
            ]
        ).lower()
        content_blob = content.lower()
        annotations_blob = annotations.lower()

        score = 0.0
        matched_sections: List[str] = []

        if query_lower in title_blob:
            score += 8.0
            matched_sections.append("title")
        if query_lower in content_blob:
            score += 6.0
            matched_sections.append("content")
        if query_lower in annotations_blob:
            score += 4.0
            matched_sections.append("annotations")

        for token in tokens:
            if token in title_blob:
                score += 2.0
                matched_sections.append("title")
            if token in content_blob:
                score += 1.5
                matched_sections.append("content")
            if token in annotations_blob:
                score += 1.0
                matched_sections.append("annotations")

        if score <= 0:
            continue

        preview_source = annotations if "annotations" in matched_sections else (snapshot or content)
        results.append(
            {
                "provider": manifest["provider"],
                "doc_slug": manifest["doc_slug"],
                "language": manifest["language"],
                "title": manifest["title"],
                "score": round(score, 2),
                "matched_sections": sorted(set(matched_sections)),
                "preview": _make_excerpt(preview_source, query),
                "pack_dir": str(pack_dir.relative_to(API_CONTEXT_ROOT)),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return {
        "success": True,
        "query": query,
        "provider": provider,
        "language": language,
        "count": len(results[:limit]),
        "results": results[:limit],
    }
