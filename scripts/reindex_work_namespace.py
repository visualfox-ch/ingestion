#!/usr/bin/env python3
"""
Reindex legacy work namespaces into umbrella "work" (Option A).

Sources:
- work_projektil
- work_visualfox

Targets:
- jarvis_work (emails/docs)
- jarvis_work_comms (chat windows)

Tags:
- origin_namespace (legacy source)
- org (projektil/visualfox)
"""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime

from app.embed import embed_texts
from app.qdrant_upsert import upsert_chunks
from app.chat_whatsapp import window_messages as wa_window_messages
from app.chat_google import window_messages as gchat_window_messages
from app import config as cfg
from app.namespace_constants import namespace_org


RAW_DIR = Path("/brain/raw") if Path("/brain/raw").exists() else Path("/volume1/BRAIN/raw")
PARSED_DIR = Path("/brain/parsed") if Path("/brain/parsed").exists() else Path("/volume1/BRAIN/parsed")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def chunk_text(text: str, max_chars: int = 2000, overlap: int = 200):
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


def extract_event_ts(text: str) -> str | None:
    match = re.search(r'^event_ts:\s*(.+)$', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def load_jsonl(path: Path):
    messages = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except Exception:
                continue
    return messages


def reindex_emails(source_ns: str, target_ns: str, limit_files: int = 0):
    email_dir = PARSED_DIR / source_ns / "email"
    if not email_dir.exists():
        print(f"⚠️  No email dir for {source_ns}: {email_dir}")
        return {"files": 0, "chunks": 0}

    total_files = 0
    total_chunks = 0
    ingest_ts = now_iso()
    org = namespace_org(source_ns)

    for label in ["inbox", "sent"]:
        label_dir = email_dir / label
        if not label_dir.exists():
            continue
        files = list(label_dir.glob("*.txt"))
        if limit_files > 0:
            files = files[:limit_files]

        for f in files:
            total_files += 1
            text = f.read_text(errors="ignore")
            chunks = chunk_text(
                text,
                max_chars=cfg.EMAIL_CHUNK_MAX_CHARS,
                overlap=cfg.EMAIL_CHUNK_OVERLAP
            )
            if not chunks:
                continue
            embeddings = embed_texts(chunks)

            rel_parts = f.relative_to(PARSED_DIR).parts
            source_path = str(Path(*rel_parts[:-1]) / f"{f.stem}.json")
            event_ts = extract_event_ts(text)

            meta = {
                "namespace": target_ns,
                "origin_namespace": source_ns,
                "org": org,
                "doc_type": "email",
                "channel": "gmail",
                "label": label,
                "source_path": source_path,
                "ingest_ts": ingest_ts,
                "event_ts": event_ts
            }
            upsert_chunks(
                collection=f"jarvis_{target_ns}",
                chunks=chunks,
                embeddings=embeddings,
                meta=meta
            )
            total_chunks += len(chunks)

    return {"files": total_files, "chunks": total_chunks}


def reindex_comms(source_ns: str, target_ns: str, subdir: str, channel: str, window_fn, window_size: int, step: int, limit_files: int = 0):
    comms_dir = PARSED_DIR / source_ns / subdir
    if not comms_dir.exists():
        print(f"⚠️  No comms dir for {source_ns}/{subdir}: {comms_dir}")
        return {"files": 0, "windows": 0}

    total_files = 0
    total_windows = 0
    ingest_ts = now_iso()
    org = namespace_org(source_ns)

    files = list(comms_dir.glob("*.jsonl"))
    if limit_files > 0:
        files = files[:limit_files]

    for f in files:
        total_files += 1
        messages = load_jsonl(f)
        if not messages:
            continue

        # Ensure channel exists
        for m in messages:
            m.setdefault("channel", channel)

        source_path = str(f.relative_to(PARSED_DIR))
        windows = window_fn(messages, window_size=window_size, step=step, source_path=source_path)
        if not windows:
            continue

        window_texts = [w["text"] for w in windows]
        embeddings = embed_texts(window_texts)

        meta = {
            "namespace": target_ns,
            "origin_namespace": source_ns,
            "org": org,
            "doc_type": "chat_window",
            "channel": channel,
            "source_path": source_path,
            "ingest_ts": ingest_ts,
            "window_size": window_size,
            "step": step,
        }

        upsert_chunks(
            collection=f"jarvis_{target_ns}_comms",
            chunks=window_texts,
            embeddings=embeddings,
            meta=meta,
            chunk_metadata=windows
        )
        total_windows += len(windows)

    return {"files": total_files, "windows": total_windows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="work")
    parser.add_argument("--sources", default="work_projektil,work_visualfox")
    parser.add_argument("--limit-files", type=int, default=0, help="Limit files per source (0 = no limit)")
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Also print the final totals as JSON to stdout.",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    target = args.target

    print("🚀 Reindex work namespaces (Option A)")
    print(f"Sources: {sources}")
    print(f"Target: {target}")
    print(f"Parsed dir: {PARSED_DIR}")
    print("")

    totals = {"email_files": 0, "email_chunks": 0, "wa_files": 0, "wa_windows": 0, "gchat_files": 0, "gchat_windows": 0}

    for ns in sources:
        print(f"==> {ns}")
        email_stats = reindex_emails(ns, target, limit_files=args.limit_files)
        wa_stats = reindex_comms(ns, target, "comms", "whatsapp", wa_window_messages, window_size=8, step=6, limit_files=args.limit_files)
        gchat_stats = reindex_comms(ns, target, "comms_gchat", "google_chat", gchat_window_messages, window_size=10, step=8, limit_files=args.limit_files)

        totals["email_files"] += email_stats["files"]
        totals["email_chunks"] += email_stats["chunks"]
        totals["wa_files"] += wa_stats["files"]
        totals["wa_windows"] += wa_stats["windows"]
        totals["gchat_files"] += gchat_stats["files"]
        totals["gchat_windows"] += gchat_stats["windows"]

    print("\n✅ Reindex complete")
    print(f"  email_files: {totals['email_files']}")
    print(f"  email_chunks: {totals['email_chunks']}")
    print(f"  wa_files: {totals['wa_files']}")
    print(f"  wa_windows: {totals['wa_windows']}")
    print(f"  gchat_files: {totals['gchat_files']}")
    print(f"  gchat_windows: {totals['gchat_windows']}")

    if args.print_json:
        print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
