#!/usr/bin/env python3
"""
Reindex comms into unified "comms" namespace.

Sources:
- private
- work_projektil
- work_visualfox

Target:
- jarvis_comms (namespace = comms)
"""
import argparse
import json
from pathlib import Path
from datetime import datetime

from app.embed import embed_texts
from app.qdrant_upsert import upsert_chunks
from app.chat_whatsapp import window_messages as wa_window_messages, parse_whatsapp_text
from app.chat_google import window_messages as gchat_window_messages, parse_google_chat_json
from app.namespace_constants import namespace_org, COMMS_NAMESPACE, COMMS_COLLECTION


RAW_DIR = Path("/brain/raw") if Path("/brain/raw").exists() else Path("/volume1/BRAIN/raw")
PARSED_DIR = Path("/brain/parsed") if Path("/brain/parsed").exists() else Path("/volume1/BRAIN/parsed")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


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


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def normalized_source_path(path: Path) -> str:
    # Preserve legacy source_path without _processed segment
    rel = str(path.relative_to(PARSED_DIR))
    return rel.replace("/_processed/", "/")


def reindex_comms(source_ns: str, target_ns: str, subdir: str, channel: str, window_fn, window_size: int, step: int, limit_files: int, collection: str):
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

        for m in messages:
            m.setdefault("channel", channel)

        source_path = normalized_source_path(f)
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
            collection=collection,
            chunks=window_texts,
            embeddings=embeddings,
            meta=meta,
            chunk_metadata=windows
        )
        total_windows += len(windows)

    return {"files": total_files, "windows": total_windows}


def reindex_inbox_whatsapp(source_ns: str, target_ns: str, limit_files: int, collection: str):
    inbox_dir = PARSED_DIR / source_ns / "inbox" / "chats" / "_processed"
    if not inbox_dir.exists():
        print(f"⚠️  No inbox chats dir for {source_ns}: {inbox_dir}")
        return {"files": 0, "windows": 0}

    total_files = 0
    total_windows = 0
    ingest_ts = now_iso()
    org = namespace_org(source_ns)

    files = list(inbox_dir.glob("*.txt"))
    if limit_files > 0:
        files = files[:limit_files]

    for f in files:
        total_files += 1
        raw = load_text(f)
        parsed = parse_whatsapp_text(raw, normalized_source_path(f), ingest_ts)
        messages = parsed.get("messages", [])
        if not messages:
            continue

        windows = wa_window_messages(messages, window_size=12, step=6, source_path=normalized_source_path(f))
        if not windows:
            continue

        window_texts = [w["text"] for w in windows]
        embeddings = embed_texts(window_texts)

        meta = {
            "namespace": target_ns,
            "origin_namespace": source_ns,
            "org": org,
            "doc_type": "chat_window",
            "channel": "whatsapp",
            "source_path": normalized_source_path(f),
            "ingest_ts": ingest_ts,
            "window_size": 12,
            "step": 6,
        }

        upsert_chunks(
            collection=collection,
            chunks=window_texts,
            embeddings=embeddings,
            meta=meta,
            chunk_metadata=windows
        )
        total_windows += len(windows)

    return {"files": total_files, "windows": total_windows}


def reindex_inbox_gchat(source_ns: str, target_ns: str, limit_files: int, collection: str):
    inbox_dir = PARSED_DIR / source_ns / "inbox" / "gchat" / "_processed"
    if not inbox_dir.exists():
        print(f"⚠️  No inbox gchat dir for {source_ns}: {inbox_dir}")
        return {"files": 0, "windows": 0}

    total_files = 0
    total_windows = 0
    ingest_ts = now_iso()
    org = namespace_org(source_ns)

    files = list(inbox_dir.glob("*.json"))
    if limit_files > 0:
        files = files[:limit_files]

    for f in files:
        total_files += 1
        raw = load_text(f)
        parsed = parse_google_chat_json(raw, normalized_source_path(f), ingest_ts)
        messages = parsed.get("messages", [])
        if not messages:
            continue

        # Normalize channel label to gchat for unified comms
        for m in messages:
            m["channel"] = "gchat"

        windows = gchat_window_messages(messages, window_size=12, step=6, source_path=normalized_source_path(f))
        if not windows:
            continue

        window_texts = [w["text"] for w in windows]
        embeddings = embed_texts(window_texts)

        meta = {
            "namespace": target_ns,
            "origin_namespace": source_ns,
            "org": org,
            "doc_type": "chat_window",
            "channel": "gchat",
            "source_path": normalized_source_path(f),
            "ingest_ts": ingest_ts,
            "window_size": 12,
            "step": 6,
        }

        upsert_chunks(
            collection=collection,
            chunks=window_texts,
            embeddings=embeddings,
            meta=meta,
            chunk_metadata=windows
        )
        total_windows += len(windows)

    return {"files": total_files, "windows": total_windows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=COMMS_NAMESPACE)
    parser.add_argument("--collection", default=COMMS_COLLECTION)
    parser.add_argument("--sources", default="private,work_projektil,work_visualfox")
    parser.add_argument("--limit-files", type=int, default=0, help="Limit files per source (0 = no limit)")
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Also print the final totals as JSON to stdout.",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    target = args.target

    print("🚀 Reindex comms into unified namespace")
    print(f"Sources: {sources}")
    print(f"Target namespace: {target}")
    print(f"Collection: {args.collection}")
    print(f"Parsed dir: {PARSED_DIR}")
    print("")

    totals = {
        "wa_files": 0,
        "wa_windows": 0,
        "gchat_files": 0,
        "gchat_windows": 0,
        "wa_inbox_files": 0,
        "wa_inbox_windows": 0,
        "gchat_inbox_files": 0,
        "gchat_inbox_windows": 0,
    }

    for ns in sources:
        print(f"==> {ns}")
        wa_stats = reindex_comms(
            source_ns=ns,
            target_ns=target,
            subdir="comms",
            channel="whatsapp",
            window_fn=wa_window_messages,
            window_size=12,
            step=6,
            limit_files=args.limit_files,
            collection=args.collection
        )
        totals["wa_files"] += wa_stats["files"]
        totals["wa_windows"] += wa_stats["windows"]

        gchat_stats = reindex_comms(
            source_ns=ns,
            target_ns=target,
            subdir="comms_gchat",
            channel="gchat",
            window_fn=gchat_window_messages,
            window_size=12,
            step=6,
            limit_files=args.limit_files,
            collection=args.collection
        )
        totals["gchat_files"] += gchat_stats["files"]
        totals["gchat_windows"] += gchat_stats["windows"]

        wa_inbox_stats = reindex_inbox_whatsapp(
            source_ns=ns,
            target_ns=target,
            limit_files=args.limit_files,
            collection=args.collection
        )
        totals["wa_inbox_files"] += wa_inbox_stats["files"]
        totals["wa_inbox_windows"] += wa_inbox_stats["windows"]

        gchat_inbox_stats = reindex_inbox_gchat(
            source_ns=ns,
            target_ns=target,
            limit_files=args.limit_files,
            collection=args.collection
        )
        totals["gchat_inbox_files"] += gchat_inbox_stats["files"]
        totals["gchat_inbox_windows"] += gchat_inbox_stats["windows"]

    print("\n✅ Comms reindex complete")
    print(f"  wa_files: {totals['wa_files']}")
    print(f"  wa_windows: {totals['wa_windows']}")
    print(f"  gchat_files: {totals['gchat_files']}")
    print(f"  gchat_windows: {totals['gchat_windows']}")
    print(f"  wa_inbox_files: {totals['wa_inbox_files']}")
    print(f"  wa_inbox_windows: {totals['wa_inbox_windows']}")
    print(f"  gchat_inbox_files: {totals['gchat_inbox_files']}")
    print(f"  gchat_inbox_windows: {totals['gchat_inbox_windows']}")

    if args.print_json:
        print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
