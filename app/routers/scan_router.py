"""
Folder Scanning Router for Jarvis Document Ingestion

Provides endpoints for scanning folders and batch-ingesting documents.
Phase 3: Automated Document Pipeline
"""
import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ..observability import get_logger, log_with_context
from ..auth import auth_dependency
from ..models import ScopeRef
from .. import config, metrics

router = APIRouter(prefix="/scan", tags=["scan"])
logger = get_logger("jarvis.scan")

# Supported file extensions for document ingestion
SUPPORTED_EXTENSIONS = {
    ".txt": "text",
    ".md": "markdown",
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".rtf": "rtf",
    ".json": "json",
    ".csv": "csv",
    ".eml": "email",
}

# Default inbox/processed folders
DEFAULT_INBOX = Path("/brain/documents/inbox")
DEFAULT_PROCESSED = Path("/brain/documents/processed")


class FolderScanRequest(BaseModel):
    """Request to scan a folder for documents."""
    folder: str = Field(default="/brain/documents/inbox", description="Folder to scan")
    namespace: Optional[str] = Field(default=None, description="Namespace for ingested documents (deprecated, use scope)")
    scope: Optional[ScopeRef] = Field(default=None, description="Scope for ingested documents")
    source_type: str = Field(default="document", description="Source type for documents")
    recursive: bool = Field(default=False, description="Scan subfolders")
    patterns: List[str] = Field(
        default=["*.pdf", "*.txt", "*.md", "*.doc", "*.docx"],
        description="File patterns to match"
    )
    move_processed: bool = Field(default=True, description="Move processed files to archive")
    archive_folder: str = Field(
        default="/brain/documents/processed",
        description="Folder to move processed files"
    )
    max_files: int = Field(default=50, description="Max files to process per scan")

    def get_scope(self) -> ScopeRef:
        """Return scope, falling back to legacy namespace or defaults."""
        if self.scope is not None:
            return self.scope

        if self.namespace is not None and str(self.namespace).strip():
            return ScopeRef.from_legacy_namespace(self.namespace)

        # Default scope for scan operations
        return ScopeRef(
            org="personal",
            visibility="private",
            owner="scan_service"
        )

    def get_namespace(self) -> str:
        """Return the effective legacy namespace for backward-compatible code paths."""
        return self.get_scope().to_legacy_namespace()


class FolderScanResult(BaseModel):
    """Result of a folder scan."""
    success: bool
    folder: str
    files_found: int
    files_processed: int
    files_failed: int
    files_skipped: int
    processed_files: List[dict]
    errors: List[dict]
    scan_duration_ms: float


def _file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of file for deduplication."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_file_extension(filename: str) -> str:
    """Get normalized file extension."""
    return Path(filename).suffix.lower()


def _matches_patterns(filename: str, patterns: List[str]) -> bool:
    """Check if filename matches any of the patterns."""
    from fnmatch import fnmatch
    return any(fnmatch(filename.lower(), p.lower()) for p in patterns)


def _read_file_content(filepath: Path) -> Optional[str]:
    """Read text content from file. Returns None if binary/unsupported."""
    ext = _get_file_extension(filepath.name)

    # Text-based files
    if ext in [".txt", ".md", ".json", ".csv", ".rtf"]:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            log_with_context(logger, "warning", "Failed to read text file",
                           file=str(filepath), error=str(e))
            return None

    # Email files
    if ext == ".eml":
        try:
            from email import policy
            from email.parser import BytesParser

            with open(filepath, "rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)

            # Extract text content
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_content() or ""
            else:
                body = msg.get_content() or ""

            # Include headers
            headers = f"From: {msg['from']}\nTo: {msg['to']}\nSubject: {msg['subject']}\nDate: {msg['date']}\n\n"
            return headers + body

        except Exception as e:
            log_with_context(logger, "warning", "Failed to parse email file",
                           file=str(filepath), error=str(e))
            return None

    # PDF files (basic extraction)
    if ext == ".pdf":
        try:
            # Try pypdf (modern PyPDF2 successor)
            from pypdf import PdfReader
            with open(filepath, "rb") as f:
                reader = PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text if text.strip() else None
        except ImportError:
            log_with_context(logger, "debug", "pypdf not installed, skipping PDF",
                           file=str(filepath))
            return None
        except Exception as e:
            log_with_context(logger, "warning", "Failed to extract PDF text",
                           file=str(filepath), error=str(e))
            return None

    # Word documents (basic extraction)
    if ext in [".doc", ".docx"]:
        try:
            import docx
            doc = docx.Document(filepath)
            text = "\n".join([para.text for para in doc.paragraphs])
            return text if text.strip() else None
        except ImportError:
            log_with_context(logger, "debug", "python-docx not installed, skipping Word doc",
                           file=str(filepath))
            return None
        except Exception as e:
            log_with_context(logger, "warning", "Failed to extract Word text",
                           file=str(filepath), error=str(e))
            return None

    return None


@router.post("/folder", response_model=FolderScanResult)
async def scan_folder(
    request: FolderScanRequest,
    _: str = Depends(auth_dependency)
):
    """
    Scan a folder for documents and ingest them into Jarvis.

    - Supports: txt, md, pdf, doc, docx, eml, json, csv
    - Deduplicates by file hash
    - Optionally moves processed files to archive
    - Returns detailed processing results
    - Accepts both legacy `namespace` and new `scope` parameters
    """
    import time
    start_time = time.time()

    # Resolve scope and namespace (dual-mode support)
    request_scope = request.get_scope()
    effective_namespace = request.get_namespace()
    raw_namespace = (request.namespace or "").strip()
    if request.scope is not None:
        input_mode = "scope"
    elif raw_namespace:
        input_mode = "namespace"
    else:
        input_mode = "default"
    metrics.SCAN_SCOPE_REQUEST_INPUT_TOTAL.labels(
        input_mode=input_mode,
        namespace=raw_namespace or "<none>",
        scope_org=request_scope.org,
        scope_visibility=request_scope.visibility,
        source_type=request.source_type or "document",
    ).inc()

    folder_path = Path(request.folder)
    archive_path = Path(request.archive_folder) if request.move_processed else None

    # Validate folder exists
    if not folder_path.exists():
        # Try to create inbox folder if it doesn't exist
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            log_with_context(logger, "info", "Created inbox folder", folder=str(folder_path))
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Folder not found: {request.folder}")

    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {request.folder}")

    # Create archive folder if needed
    if archive_path and not archive_path.exists():
        try:
            archive_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_with_context(logger, "warning", "Could not create archive folder",
                           folder=str(archive_path), error=str(e))

    # Find matching files
    files_to_process = []

    if request.recursive:
        for pattern in request.patterns:
            files_to_process.extend(folder_path.rglob(pattern))
    else:
        for pattern in request.patterns:
            files_to_process.extend(folder_path.glob(pattern))

    # Remove duplicates and limit
    files_to_process = list(set(files_to_process))[:request.max_files]

    log_with_context(logger, "info", "Folder scan started",
                    folder=str(folder_path),
                    files_found=len(files_to_process),
                    patterns=request.patterns)

    # Process files
    processed_files = []
    errors = []
    skipped = 0

    # Import knowledge_db for ingestion
    try:
        from .. import knowledge_db
    except ImportError:
        raise HTTPException(status_code=500, detail="Knowledge DB not available")

    for filepath in files_to_process:
        file_info = {
            "name": filepath.name,
            "path": str(filepath),
            "size_bytes": filepath.stat().st_size,
        }

        try:
            # Calculate hash for deduplication
            file_hash = _file_hash(filepath)

            # Check if already processed (by hash)
            existing = knowledge_db.check_duplicate_upload(file_hash)
            if existing:
                log_with_context(logger, "debug", "File already processed (duplicate)",
                               file=filepath.name, hash=file_hash[:16])
                skipped += 1
                continue

            # Read content
            content = _read_file_content(filepath)
            if not content:
                log_with_context(logger, "warning", "Could not extract text from file",
                               file=filepath.name)
                errors.append({
                    "file": filepath.name,
                    "error": "Could not extract text content"
                })
                continue

            # Determine doc type
            ext = _get_file_extension(filepath.name)
            doc_type = SUPPORTED_EXTENSIONS.get(ext, "other")

            # Create upload entry
            upload_entry = knowledge_db.create_upload_entry(
                filename=filepath.name,
                file_path=str(filepath),
                source_type=request.source_type,
                namespace=effective_namespace,
                file_hash=file_hash,
                file_size_bytes=filepath.stat().st_size,
                metadata={
                    "original_path": str(filepath),
                    "doc_type": doc_type,
                    "scan_timestamp": datetime.utcnow().isoformat(),
                }
            )
            upload_id = upload_entry.get("id") if isinstance(upload_entry, dict) else str(upload_entry)

            # Chunk and embed content
            from ..main import chunk_text
            from ..embed import embed_texts
            from .. import qdrant_upsert

            chunks = chunk_text(content, max_chars=config.CHUNK_MAX_CHARS, overlap=config.CHUNK_OVERLAP)

            # Generate embeddings for all chunks at once
            embeddings = embed_texts(chunks)

            # Build metadata dict for batch upsert
            meta = {
                "source_path": str(filepath),
                "namespace": effective_namespace,
                "source_type": request.source_type,
                "doc_type": doc_type,
                "filename": filepath.name,
                "upload_id": upload_id,
                "ingested_at": datetime.utcnow().isoformat(),
            }

            # Upsert all chunks at once
            upsert_result = qdrant_upsert.upsert_chunks(
                collection=f"jarvis_{effective_namespace}",
                chunks=chunks,
                embeddings=embeddings,
                meta=meta,
                dedupe=True
            )

            # Update upload status
            knowledge_db.update_upload_status(
                upload_id=upload_id,
                status="processed"
            )

            # Move to archive if configured
            if archive_path and request.move_processed:
                try:
                    # Create dated subfolder
                    date_folder = archive_path / datetime.now().strftime("%Y-%m-%d")
                    date_folder.mkdir(parents=True, exist_ok=True)

                    dest_path = date_folder / filepath.name
                    # Handle name collision
                    if dest_path.exists():
                        base = filepath.stem
                        suffix = filepath.suffix
                        counter = 1
                        while dest_path.exists():
                            dest_path = date_folder / f"{base}_{counter}{suffix}"
                            counter += 1

                    shutil.move(str(filepath), str(dest_path))
                    file_info["archived_to"] = str(dest_path)

                except Exception as e:
                    log_with_context(logger, "warning", "Could not move file to archive",
                                   file=filepath.name, error=str(e))

            file_info["status"] = "processed"
            file_info["chunks"] = len(chunks)
            file_info["upload_id"] = upload_id
            processed_files.append(file_info)

            log_with_context(logger, "info", "Document ingested",
                           file=filepath.name, chunks=len(chunks),
                           namespace=effective_namespace)

        except Exception as e:
            log_with_context(logger, "error", "Failed to process file",
                           file=filepath.name, error=str(e))
            errors.append({
                "file": filepath.name,
                "error": str(e)[:200]
            })

    duration_ms = (time.time() - start_time) * 1000

    result = FolderScanResult(
        success=len(errors) == 0,
        folder=str(folder_path),
        files_found=len(files_to_process),
        files_processed=len(processed_files),
        files_failed=len(errors),
        files_skipped=skipped,
        processed_files=processed_files,
        errors=errors,
        scan_duration_ms=round(duration_ms, 2),
    )

    log_with_context(logger, "info", "Folder scan complete",
                    folder=str(folder_path),
                    processed=len(processed_files),
                    failed=len(errors),
                    skipped=skipped,
                    duration_ms=round(duration_ms, 2))

    return result


@router.get("/status")
async def get_scan_status(_: str = Depends(auth_dependency)):
    """Get current scan configuration and folder status."""
    inbox = DEFAULT_INBOX
    processed = DEFAULT_PROCESSED

    inbox_files = 0
    processed_files = 0

    if inbox.exists():
        inbox_files = sum(1 for f in inbox.iterdir() if f.is_file())

    if processed.exists():
        processed_files = sum(1 for f in processed.rglob("*") if f.is_file())

    return {
        "inbox_folder": str(inbox),
        "inbox_exists": inbox.exists(),
        "inbox_files_count": inbox_files,
        "processed_folder": str(processed),
        "processed_exists": processed.exists(),
        "processed_files_count": processed_files,
        "supported_extensions": list(SUPPORTED_EXTENSIONS.keys()),
    }
