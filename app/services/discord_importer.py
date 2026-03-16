"""
Discord Chat Importer Service

Imports Discord channel exports from DiscordChatExporter (JSON format)
and indexes them in Qdrant for semantic search.

Usage:
    from app.services.discord_importer import DiscordImporter

    importer = DiscordImporter()

    # Import a single export file
    result = await importer.import_file("/path/to/export.json")

    # Import all exports in a directory
    results = await importer.import_directory("/path/to/exports/")

    # Search Discord messages
    results = await importer.search("what did they say about the release?")
"""

import json
import logging
import os
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import asyncio

logger = logging.getLogger(__name__)

# Qdrant collection for Discord messages
DISCORD_COLLECTION = "discord_messages"


@dataclass
class DiscordMessage:
    """A parsed Discord message."""
    id: str
    content: str
    author_id: str
    author_name: str
    author_nickname: Optional[str] = None
    channel_id: str = ""
    channel_name: str = ""
    server_id: str = ""
    server_name: str = ""
    timestamp: Optional[datetime] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    embeds: List[Dict[str, Any]] = field(default_factory=list)
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    reply_to_id: Optional[str] = None
    is_pinned: bool = False
    message_type: str = "Default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_nickname": self.author_nickname,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "server_id": self.server_id,
            "server_name": self.server_name,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "attachments": self.attachments,
            "embeds": self.embeds,
            "reactions": self.reactions,
            "reply_to_id": self.reply_to_id,
            "is_pinned": self.is_pinned,
            "message_type": self.message_type,
        }

    def to_searchable_text(self) -> str:
        """Create searchable text representation."""
        parts = []

        # Add author context
        author = self.author_nickname or self.author_name
        parts.append(f"[{author}]")

        # Add main content
        if self.content:
            parts.append(self.content)

        # Add embed content
        for embed in self.embeds:
            if embed.get("title"):
                parts.append(f"[Embed: {embed['title']}]")
            if embed.get("description"):
                parts.append(embed["description"])

        # Add attachment descriptions
        for att in self.attachments:
            if att.get("fileName"):
                parts.append(f"[Attachment: {att['fileName']}]")

        return " ".join(parts)


@dataclass
class ImportResult:
    """Result of an import operation."""
    file_path: str
    success: bool
    messages_imported: int = 0
    messages_skipped: int = 0
    server_name: str = ""
    channel_name: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "success": self.success,
            "messages_imported": self.messages_imported,
            "messages_skipped": self.messages_skipped,
            "server_name": self.server_name,
            "channel_name": self.channel_name,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


class DiscordImporter:
    """
    Imports Discord channel exports and indexes them for search.

    Supports DiscordChatExporter JSON format.
    """

    def __init__(
        self,
        import_dir: Optional[str] = None,
        batch_size: int = 100,
    ):
        """
        Initialize Discord importer.

        Args:
            import_dir: Default directory for imports
            batch_size: Number of messages to index at once
        """
        self._import_dir = Path(
            import_dir or os.environ.get(
                "DISCORD_IMPORT_DIR",
                "/brain/system/data/discord/imports"
            )
        )
        self._import_dir.mkdir(parents=True, exist_ok=True)
        self._batch_size = batch_size
        self._qdrant_initialized = False

    async def _ensure_collection(self) -> None:
        """Ensure Qdrant collection exists."""
        if self._qdrant_initialized:
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))

            client = QdrantClient(host=qdrant_host, port=qdrant_port)

            # Check if collection exists
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]

            if DISCORD_COLLECTION not in collection_names:
                # Create collection with same dimensions as other Jarvis collections
                client.create_collection(
                    collection_name=DISCORD_COLLECTION,
                    vectors_config=VectorParams(
                        size=384,  # sentence-transformers default
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {DISCORD_COLLECTION}")

            self._qdrant_initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection: {e}")
            raise

    def _parse_export_file(self, file_path: Path) -> tuple[Dict[str, Any], List[DiscordMessage]]:
        """
        Parse a DiscordChatExporter JSON file.

        Returns:
            (metadata, messages)
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract metadata
        guild = data.get("guild", {})
        channel = data.get("channel", {})

        metadata = {
            "server_id": str(guild.get("id", "")),
            "server_name": guild.get("name", "Unknown Server"),
            "channel_id": str(channel.get("id", "")),
            "channel_name": channel.get("name", "unknown-channel"),
            "channel_type": channel.get("type", "Unknown"),
            "export_date": data.get("exportedAt"),
            "message_count": data.get("messageCount", 0),
        }

        # Parse messages
        messages = []
        for msg_data in data.get("messages", []):
            try:
                msg = self._parse_message(msg_data, metadata)
                if msg and msg.content.strip():  # Skip empty messages
                    messages.append(msg)
            except Exception as e:
                logger.warning(f"Failed to parse message: {e}")
                continue

        return metadata, messages

    def _parse_message(
        self,
        msg_data: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Optional[DiscordMessage]:
        """Parse a single message from export data."""
        author = msg_data.get("author", {})

        # Parse timestamp
        timestamp = None
        ts_str = msg_data.get("timestamp")
        if ts_str:
            try:
                # Handle various timestamp formats
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                pass

        # Extract content
        content = msg_data.get("content", "")

        # Handle system messages
        msg_type = msg_data.get("type", "Default")
        if msg_type != "Default" and not content:
            # Skip system messages without content
            return None

        return DiscordMessage(
            id=str(msg_data.get("id", "")),
            content=content,
            author_id=str(author.get("id", "")),
            author_name=author.get("name", "Unknown"),
            author_nickname=author.get("nickname"),
            channel_id=metadata["channel_id"],
            channel_name=metadata["channel_name"],
            server_id=metadata["server_id"],
            server_name=metadata["server_name"],
            timestamp=timestamp,
            attachments=msg_data.get("attachments", []),
            embeds=msg_data.get("embeds", []),
            reactions=msg_data.get("reactions", []),
            reply_to_id=str(msg_data.get("reference", {}).get("messageId", "")) or None,
            is_pinned=msg_data.get("isPinned", False),
            message_type=msg_type,
        )

    async def _index_messages(self, messages: List[DiscordMessage]) -> int:
        """Index messages in Qdrant."""
        if not messages:
            return 0

        await self._ensure_collection()

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct
            from ..embed import embed_texts

            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
            client = QdrantClient(host=qdrant_host, port=qdrant_port)

            indexed = 0

            # Process in batches
            for i in range(0, len(messages), self._batch_size):
                batch = messages[i:i + self._batch_size]

                # Create searchable texts
                texts = [msg.to_searchable_text() for msg in batch]

                # Generate embeddings
                embeddings = embed_texts(texts)

                # Create points
                points = []
                for msg, embedding in zip(batch, embeddings):
                    # Create unique ID from message ID
                    point_id = int(hashlib.md5(
                        f"{msg.server_id}:{msg.channel_id}:{msg.id}".encode()
                    ).hexdigest()[:16], 16)

                    points.append(PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "message_id": msg.id,
                            "content": msg.content,
                            "author_name": msg.author_name,
                            "author_nickname": msg.author_nickname,
                            "channel_id": msg.channel_id,
                            "channel_name": msg.channel_name,
                            "server_id": msg.server_id,
                            "server_name": msg.server_name,
                            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                            "has_attachments": len(msg.attachments) > 0,
                            "has_embeds": len(msg.embeds) > 0,
                            "source": "discord",
                        },
                    ))

                # Upsert to Qdrant
                client.upsert(
                    collection_name=DISCORD_COLLECTION,
                    points=points,
                )

                indexed += len(points)

            return indexed

        except Exception as e:
            logger.error(f"Failed to index messages: {e}")
            raise

    async def import_file(self, file_path: Union[str, Path]) -> ImportResult:
        """
        Import a single Discord export file.

        Args:
            file_path: Path to the JSON export file

        Returns:
            ImportResult with import statistics
        """
        import time
        start_time = time.time()

        file_path = Path(file_path)

        if not file_path.exists():
            return ImportResult(
                file_path=str(file_path),
                success=False,
                error=f"File not found: {file_path}",
            )

        if not file_path.suffix.lower() == ".json":
            return ImportResult(
                file_path=str(file_path),
                success=False,
                error="File must be a JSON export",
            )

        try:
            # Parse the export
            metadata, messages = self._parse_export_file(file_path)

            logger.info(
                f"Parsed {len(messages)} messages from "
                f"{metadata['server_name']}/#{metadata['channel_name']}"
            )

            # Index messages
            indexed = await self._index_messages(messages)

            duration_ms = (time.time() - start_time) * 1000

            return ImportResult(
                file_path=str(file_path),
                success=True,
                messages_imported=indexed,
                messages_skipped=len(messages) - indexed,
                server_name=metadata["server_name"],
                channel_name=metadata["channel_name"],
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(f"Import failed for {file_path}: {e}")
            return ImportResult(
                file_path=str(file_path),
                success=False,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def import_directory(
        self,
        directory: Optional[Union[str, Path]] = None,
    ) -> List[ImportResult]:
        """
        Import all JSON files from a directory.

        Args:
            directory: Directory path (uses default if not provided)

        Returns:
            List of ImportResults
        """
        directory = Path(directory) if directory else self._import_dir

        if not directory.exists():
            logger.warning(f"Import directory does not exist: {directory}")
            return []

        results = []
        json_files = list(directory.glob("*.json"))

        logger.info(f"Found {len(json_files)} JSON files in {directory}")

        for json_file in json_files:
            result = await self.import_file(json_file)
            results.append(result)

        # Summary
        total_imported = sum(r.messages_imported for r in results)
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Import complete: {successful}/{len(results)} files, "
            f"{total_imported} messages indexed"
        )

        return results

    async def search(
        self,
        query: str,
        limit: int = 20,
        server_name: Optional[str] = None,
        channel_name: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search Discord messages.

        Args:
            query: Search query
            limit: Maximum results
            server_name: Filter by server
            channel_name: Filter by channel
            author_name: Filter by author

        Returns:
            List of matching messages with scores
        """
        await self._ensure_collection()

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            from ..embed import embed_texts

            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
            client = QdrantClient(host=qdrant_host, port=qdrant_port)

            # Generate query embedding
            query_embedding = embed_texts([query])[0]

            # Build filter
            filter_conditions = []
            if server_name:
                filter_conditions.append(
                    FieldCondition(key="server_name", match=MatchValue(value=server_name))
                )
            if channel_name:
                filter_conditions.append(
                    FieldCondition(key="channel_name", match=MatchValue(value=channel_name))
                )
            if author_name:
                filter_conditions.append(
                    FieldCondition(key="author_name", match=MatchValue(value=author_name))
                )

            search_filter = Filter(must=filter_conditions) if filter_conditions else None

            # Search
            results = client.search(
                collection_name=DISCORD_COLLECTION,
                query_vector=query_embedding,
                query_filter=search_filter,
                limit=limit,
            )

            return [
                {
                    "score": hit.score,
                    "message_id": hit.payload.get("message_id"),
                    "content": hit.payload.get("content"),
                    "author": hit.payload.get("author_nickname") or hit.payload.get("author_name"),
                    "channel": hit.payload.get("channel_name"),
                    "server": hit.payload.get("server_name"),
                    "timestamp": hit.payload.get("timestamp"),
                }
                for hit in results
            ]

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about indexed Discord messages."""
        await self._ensure_collection()

        try:
            from qdrant_client import QdrantClient

            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
            client = QdrantClient(host=qdrant_host, port=qdrant_port)

            collection_info = client.get_collection(DISCORD_COLLECTION)

            return {
                "collection": DISCORD_COLLECTION,
                "total_messages": collection_info.points_count,
                "vectors_count": collection_info.vectors_count,
                "status": collection_info.status.value,
            }

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}

    def list_import_files(self) -> List[Dict[str, Any]]:
        """List available import files."""
        files = []
        for json_file in self._import_dir.glob("*.json"):
            stat = json_file.stat()
            files.append({
                "name": json_file.name,
                "path": str(json_file),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return sorted(files, key=lambda x: x["modified"], reverse=True)


# =============================================================================
# Singleton & Convenience Functions
# =============================================================================

_importer: Optional[DiscordImporter] = None


def get_discord_importer() -> DiscordImporter:
    """Get the singleton Discord importer instance."""
    global _importer
    if _importer is None:
        _importer = DiscordImporter()
    return _importer


async def import_discord_export(file_path: str) -> ImportResult:
    """Convenience function to import a Discord export."""
    importer = get_discord_importer()
    return await importer.import_file(file_path)


async def search_discord(
    query: str,
    limit: int = 20,
    server: Optional[str] = None,
    channel: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convenience function to search Discord messages."""
    importer = get_discord_importer()
    return await importer.search(
        query,
        limit=limit,
        server_name=server,
        channel_name=channel,
    )
