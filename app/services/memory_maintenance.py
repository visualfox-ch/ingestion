"""
Memory Maintenance Service

Self-Healing, Decay Strategies, and Proactive Archiving for Jarvis Memory.

Features:
1. Self-Healing: Detect and repair corrupted/inconsistent data
2. Decay Strategies: Time-based confidence decay with policies
3. Proactive Archiving: Auto-archive old/unused memories
4. Maintenance Jobs: Scheduled cleanup and optimization

Decay Policies:
- AGGRESSIVE: 2% daily decay, archive after 30 days
- MODERATE: 0.5% daily decay, archive after 90 days
- CONSERVATIVE: 0.1% daily decay, archive after 365 days
- CUSTOM: User-defined parameters
"""

import logging
import math
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock
import json

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

class DecayPolicy(str, Enum):
    """Pre-defined decay policies."""
    AGGRESSIVE = "aggressive"     # Fast decay, quick archive
    MODERATE = "moderate"         # Balanced (default)
    CONSERVATIVE = "conservative" # Slow decay, long retention
    NONE = "none"                # No automatic decay
    CUSTOM = "custom"            # User-defined


class ArchiveReason(str, Enum):
    """Reasons for archiving a memory."""
    LOW_CONFIDENCE = "low_confidence"
    STALE = "stale"
    UNUSED = "unused"
    SUPERSEDED = "superseded"
    USER_REQUEST = "user_request"
    CONTRADICTION = "contradiction"
    DUPLICATE = "duplicate"


class HealthStatus(str, Enum):
    """Memory health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CORRUPTED = "corrupted"
    ORPHANED = "orphaned"


# Decay policy configurations
DECAY_CONFIGS = {
    DecayPolicy.AGGRESSIVE: {
        "daily_decay_rate": 0.02,    # 2% per day
        "archive_threshold": 0.2,     # Archive below 20% confidence
        "stale_days": 30,            # Days until considered stale
        "unused_days": 14,           # Days without access = unused
    },
    DecayPolicy.MODERATE: {
        "daily_decay_rate": 0.005,   # 0.5% per day
        "archive_threshold": 0.15,
        "stale_days": 90,
        "unused_days": 60,
    },
    DecayPolicy.CONSERVATIVE: {
        "daily_decay_rate": 0.001,   # 0.1% per day
        "archive_threshold": 0.1,
        "stale_days": 365,
        "unused_days": 180,
    },
    DecayPolicy.NONE: {
        "daily_decay_rate": 0.0,
        "archive_threshold": 0.0,
        "stale_days": 9999,
        "unused_days": 9999,
    },
}


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class MemoryItem:
    """Represents a memory item for maintenance."""
    id: str
    content: str
    memory_type: str
    confidence: float
    created_at: datetime
    last_accessed: Optional[datetime]
    access_count: int
    source: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """Result of a health check on a memory item."""
    item_id: str
    status: HealthStatus
    issues: List[str]
    repairs_needed: List[str]
    can_auto_repair: bool


@dataclass
class DecayResult:
    """Result of decay application."""
    item_id: str
    original_confidence: float
    new_confidence: float
    decay_applied: float
    should_archive: bool
    reason: Optional[ArchiveReason]


@dataclass
class ArchiveResult:
    """Result of archive operation."""
    item_id: str
    archived: bool
    reason: ArchiveReason
    archived_at: datetime
    original_confidence: float
    can_restore: bool


@dataclass
class MaintenanceReport:
    """Report from maintenance run."""
    run_id: str
    started_at: datetime
    completed_at: datetime
    items_scanned: int
    items_decayed: int
    items_archived: int
    items_healed: int
    items_failed: int
    total_confidence_decay: float
    issues_found: List[Dict[str, Any]]
    actions_taken: List[Dict[str, Any]]


# =============================================================================
# Self-Healing Engine
# =============================================================================

class SelfHealingEngine:
    """Detects and repairs memory inconsistencies."""

    def check_health(self, item: MemoryItem) -> HealthCheckResult:
        """Check health of a single memory item."""
        issues = []
        repairs = []
        status = HealthStatus.HEALTHY

        # Check for missing required fields
        if not item.content or len(item.content.strip()) == 0:
            issues.append("Empty content")
            repairs.append("Mark for deletion or request content")
            status = HealthStatus.CORRUPTED

        # Check for invalid confidence
        if item.confidence < 0 or item.confidence > 1:
            issues.append(f"Invalid confidence: {item.confidence}")
            repairs.append("Clamp confidence to [0, 1]")
            status = HealthStatus.DEGRADED

        # Check for future dates
        now = datetime.utcnow()
        if item.created_at > now + timedelta(hours=1):
            issues.append("Created date is in the future")
            repairs.append("Set created_at to now")
            status = HealthStatus.DEGRADED

        # Check for orphaned references
        if item.metadata.get("parent_id") and not item.metadata.get("parent_exists"):
            issues.append("Orphaned - parent not found")
            repairs.append("Clear parent reference")
            status = HealthStatus.ORPHANED

        # Check for stale without access
        if item.last_accessed is None and item.access_count > 0:
            issues.append("Access count > 0 but no last_accessed date")
            repairs.append("Set last_accessed to created_at")
            status = HealthStatus.DEGRADED

        # Check for invalid tags
        if any(not t or len(t) > 100 for t in item.tags):
            issues.append("Invalid tags detected")
            repairs.append("Filter invalid tags")
            status = HealthStatus.DEGRADED

        can_auto_repair = all(
            "deletion" not in r.lower() and "request" not in r.lower()
            for r in repairs
        )

        return HealthCheckResult(
            item_id=item.id,
            status=status,
            issues=issues,
            repairs_needed=repairs,
            can_auto_repair=can_auto_repair,
        )

    def repair(self, item: MemoryItem, check: HealthCheckResult) -> Tuple[MemoryItem, List[str]]:
        """Attempt to repair a memory item."""
        actions = []

        if not check.can_auto_repair:
            return item, ["Cannot auto-repair - manual intervention needed"]

        # Clamp confidence
        if item.confidence < 0:
            item.confidence = 0.0
            actions.append("Clamped confidence to 0")
        elif item.confidence > 1:
            item.confidence = 1.0
            actions.append("Clamped confidence to 1")

        # Fix future dates
        now = datetime.utcnow()
        if item.created_at > now:
            item.created_at = now
            actions.append("Fixed future created_at")

        # Fix missing last_accessed
        if item.last_accessed is None and item.access_count > 0:
            item.last_accessed = item.created_at
            actions.append("Set last_accessed to created_at")

        # Filter invalid tags
        original_tags = len(item.tags)
        item.tags = [t for t in item.tags if t and len(t) <= 100]
        if len(item.tags) < original_tags:
            actions.append(f"Removed {original_tags - len(item.tags)} invalid tags")

        # Clear orphaned parent
        if item.metadata.get("parent_id") and not item.metadata.get("parent_exists"):
            item.metadata.pop("parent_id", None)
            actions.append("Cleared orphaned parent reference")

        return item, actions


# =============================================================================
# Decay Engine
# =============================================================================

class DecayEngine:
    """Applies time-based confidence decay."""

    def __init__(self, policy: DecayPolicy = DecayPolicy.MODERATE):
        self.policy = policy
        self.config = DECAY_CONFIGS.get(policy, DECAY_CONFIGS[DecayPolicy.MODERATE])

    def set_policy(self, policy: DecayPolicy, custom_config: Optional[Dict] = None):
        """Update decay policy."""
        self.policy = policy
        if policy == DecayPolicy.CUSTOM and custom_config:
            self.config = custom_config
        else:
            self.config = DECAY_CONFIGS.get(policy, DECAY_CONFIGS[DecayPolicy.MODERATE])

    def calculate_decay(self, item: MemoryItem) -> DecayResult:
        """Calculate decay for a single item."""
        now = datetime.utcnow()

        # Calculate days since last access (or creation)
        reference_date = item.last_accessed or item.created_at
        days_since_access = (now - reference_date).total_seconds() / 86400

        # Calculate days since creation
        days_since_creation = (now - item.created_at).total_seconds() / 86400

        # Apply exponential decay based on days since access
        daily_rate = self.config["daily_decay_rate"]
        decay_factor = math.exp(-daily_rate * days_since_access)

        # Calculate new confidence
        new_confidence = item.confidence * decay_factor

        # Check if should archive
        should_archive = False
        reason = None

        if new_confidence < self.config["archive_threshold"]:
            should_archive = True
            reason = ArchiveReason.LOW_CONFIDENCE

        elif days_since_creation > self.config["stale_days"]:
            should_archive = True
            reason = ArchiveReason.STALE

        elif days_since_access > self.config["unused_days"]:
            should_archive = True
            reason = ArchiveReason.UNUSED

        return DecayResult(
            item_id=item.id,
            original_confidence=item.confidence,
            new_confidence=round(new_confidence, 6),
            decay_applied=round(item.confidence - new_confidence, 6),
            should_archive=should_archive,
            reason=reason,
        )

    def apply_decay(self, item: MemoryItem) -> MemoryItem:
        """Apply decay to item and return updated item."""
        result = self.calculate_decay(item)
        item.confidence = result.new_confidence
        return item

    def simulate_decay(
        self,
        item: MemoryItem,
        days_forward: int = 30
    ) -> List[Dict[str, Any]]:
        """Simulate decay over time for visualization."""
        projections = []
        current_confidence = item.confidence
        daily_rate = self.config["daily_decay_rate"]

        for day in range(days_forward + 1):
            decay_factor = math.exp(-daily_rate * day)
            projected = current_confidence * decay_factor
            projections.append({
                "day": day,
                "confidence": round(projected, 4),
                "below_threshold": projected < self.config["archive_threshold"],
            })

        return projections


# =============================================================================
# Archive Manager
# =============================================================================

class ArchiveManager:
    """Manages memory archiving and restoration."""

    def __init__(self, archive_path: Optional[str] = None):
        self.archive_path = archive_path or os.environ.get(
            "JARVIS_ARCHIVE_DB",
            "/brain/system/data/memory_archive.db"
        )
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        """Initialize archive database."""
        try:
            os.makedirs(os.path.dirname(self.archive_path), exist_ok=True)
            with sqlite3.connect(self.archive_path) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS archived_memories (
                        id TEXT PRIMARY KEY,
                        original_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        original_confidence REAL NOT NULL,
                        final_confidence REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        archived_at TEXT NOT NULL,
                        archive_reason TEXT NOT NULL,
                        source TEXT,
                        tags TEXT,
                        metadata TEXT,
                        can_restore INTEGER DEFAULT 1
                    );

                    CREATE INDEX IF NOT EXISTS idx_archive_reason
                    ON archived_memories(archive_reason);

                    CREATE INDEX IF NOT EXISTS idx_archived_at
                    ON archived_memories(archived_at);

                    CREATE TABLE IF NOT EXISTS archive_stats (
                        date TEXT PRIMARY KEY,
                        items_archived INTEGER DEFAULT 0,
                        items_restored INTEGER DEFAULT 0,
                        total_confidence_lost REAL DEFAULT 0
                    );
                """)
        except Exception as e:
            logger.error(f"Failed to initialize archive DB: {e}")

    def archive(
        self,
        item: MemoryItem,
        reason: ArchiveReason,
        final_confidence: Optional[float] = None
    ) -> ArchiveResult:
        """Archive a memory item."""
        archive_id = f"arch_{item.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        archived_at = datetime.utcnow()

        try:
            with self._lock:
                with sqlite3.connect(self.archive_path) as conn:
                    conn.execute("""
                        INSERT INTO archived_memories
                        (id, original_id, content, memory_type, original_confidence,
                         final_confidence, created_at, archived_at, archive_reason,
                         source, tags, metadata, can_restore)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        archive_id,
                        item.id,
                        item.content,
                        item.memory_type,
                        item.confidence,
                        final_confidence or item.confidence,
                        item.created_at.isoformat(),
                        archived_at.isoformat(),
                        reason.value,
                        item.source,
                        json.dumps(item.tags),
                        json.dumps(item.metadata),
                        1 if reason not in [ArchiveReason.CONTRADICTION, ArchiveReason.DUPLICATE] else 0,
                    ))

                    # Update stats
                    today = datetime.utcnow().strftime("%Y-%m-%d")
                    conn.execute("""
                        INSERT INTO archive_stats (date, items_archived, total_confidence_lost)
                        VALUES (?, 1, ?)
                        ON CONFLICT(date) DO UPDATE SET
                            items_archived = items_archived + 1,
                            total_confidence_lost = total_confidence_lost + ?
                    """, (today, item.confidence, item.confidence))

            return ArchiveResult(
                item_id=item.id,
                archived=True,
                reason=reason,
                archived_at=archived_at,
                original_confidence=item.confidence,
                can_restore=reason not in [ArchiveReason.CONTRADICTION, ArchiveReason.DUPLICATE],
            )

        except Exception as e:
            logger.error(f"Archive failed: {e}")
            return ArchiveResult(
                item_id=item.id,
                archived=False,
                reason=reason,
                archived_at=archived_at,
                original_confidence=item.confidence,
                can_restore=False,
            )

    def restore(self, archive_id: str) -> Optional[MemoryItem]:
        """Restore an archived memory."""
        try:
            with sqlite3.connect(self.archive_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT * FROM archived_memories
                    WHERE id = ? AND can_restore = 1
                """, (archive_id,)).fetchone()

                if not row:
                    return None

                # Restore with boosted confidence
                restored_confidence = min(0.5, row["original_confidence"])

                item = MemoryItem(
                    id=row["original_id"],
                    content=row["content"],
                    memory_type=row["memory_type"],
                    confidence=restored_confidence,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_accessed=datetime.utcnow(),
                    access_count=0,
                    source=row["source"] or "restored",
                    tags=json.loads(row["tags"]) if row["tags"] else [],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )

                # Mark as restored
                conn.execute("""
                    UPDATE archived_memories SET can_restore = 0
                    WHERE id = ?
                """, (archive_id,))

                # Update stats
                today = datetime.utcnow().strftime("%Y-%m-%d")
                conn.execute("""
                    INSERT INTO archive_stats (date, items_restored)
                    VALUES (?, 1)
                    ON CONFLICT(date) DO UPDATE SET
                        items_restored = items_restored + 1
                """, (today,))

                return item

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return None

    def get_archived(
        self,
        reason: Optional[ArchiveReason] = None,
        days_back: int = 30,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get archived items with filters."""
        try:
            with sqlite3.connect(self.archive_path) as conn:
                conn.row_factory = sqlite3.Row

                cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()

                if reason:
                    rows = conn.execute("""
                        SELECT * FROM archived_memories
                        WHERE archive_reason = ? AND archived_at >= ?
                        ORDER BY archived_at DESC
                        LIMIT ?
                    """, (reason.value, cutoff, limit)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT * FROM archived_memories
                        WHERE archived_at >= ?
                        ORDER BY archived_at DESC
                        LIMIT ?
                    """, (cutoff, limit)).fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Get archived failed: {e}")
            return []

    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get archive statistics."""
        try:
            with sqlite3.connect(self.archive_path) as conn:
                cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

                # Daily stats
                daily = conn.execute("""
                    SELECT date, items_archived, items_restored, total_confidence_lost
                    FROM archive_stats
                    WHERE date >= ?
                    ORDER BY date
                """, (cutoff,)).fetchall()

                # Totals
                totals = conn.execute("""
                    SELECT
                        COUNT(*) as total_archived,
                        SUM(CASE WHEN can_restore = 1 THEN 1 ELSE 0 END) as restorable,
                        AVG(original_confidence) as avg_original_confidence
                    FROM archived_memories
                """).fetchone()

                # By reason
                by_reason = conn.execute("""
                    SELECT archive_reason, COUNT(*) as count
                    FROM archived_memories
                    GROUP BY archive_reason
                """).fetchall()

                return {
                    "daily": [dict(zip(["date", "archived", "restored", "confidence_lost"], row)) for row in daily],
                    "totals": {
                        "total_archived": totals[0] or 0,
                        "restorable": totals[1] or 0,
                        "avg_confidence": round(totals[2] or 0, 4),
                    },
                    "by_reason": {row[0]: row[1] for row in by_reason},
                }

        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            return {"daily": [], "totals": {}, "by_reason": {}}


# =============================================================================
# Main Maintenance Service
# =============================================================================

class MemoryMaintenance:
    """
    Main memory maintenance service.

    Coordinates self-healing, decay, and archiving operations.
    """

    def __init__(
        self,
        decay_policy: DecayPolicy = DecayPolicy.MODERATE,
        archive_path: Optional[str] = None
    ):
        self.healing_engine = SelfHealingEngine()
        self.decay_engine = DecayEngine(decay_policy)
        self.archive_manager = ArchiveManager(archive_path)
        self._last_run: Optional[datetime] = None

    def run_maintenance(
        self,
        items: List[MemoryItem],
        apply_decay: bool = True,
        apply_healing: bool = True,
        apply_archive: bool = True,
        dry_run: bool = False
    ) -> MaintenanceReport:
        """
        Run full maintenance cycle on memory items.

        Args:
            items: List of memory items to maintain
            apply_decay: Whether to apply confidence decay
            apply_healing: Whether to attempt self-healing
            apply_archive: Whether to archive qualifying items
            dry_run: If True, don't make changes, just report

        Returns:
            MaintenanceReport with actions taken
        """
        import uuid
        run_id = str(uuid.uuid4())[:8]
        started_at = datetime.utcnow()

        issues_found = []
        actions_taken = []
        items_decayed = 0
        items_archived = 0
        items_healed = 0
        items_failed = 0
        total_decay = 0.0

        for item in items:
            try:
                # 1. Health check
                if apply_healing:
                    health = self.healing_engine.check_health(item)
                    if health.status != HealthStatus.HEALTHY:
                        issues_found.append({
                            "item_id": item.id,
                            "status": health.status.value,
                            "issues": health.issues,
                        })

                        if health.can_auto_repair and not dry_run:
                            item, repairs = self.healing_engine.repair(item, health)
                            if repairs:
                                items_healed += 1
                                actions_taken.append({
                                    "type": "heal",
                                    "item_id": item.id,
                                    "repairs": repairs,
                                })

                # 2. Apply decay
                if apply_decay:
                    decay_result = self.decay_engine.calculate_decay(item)
                    if decay_result.decay_applied > 0:
                        items_decayed += 1
                        total_decay += decay_result.decay_applied

                        if not dry_run:
                            item.confidence = decay_result.new_confidence
                            actions_taken.append({
                                "type": "decay",
                                "item_id": item.id,
                                "from": decay_result.original_confidence,
                                "to": decay_result.new_confidence,
                            })

                    # 3. Archive if needed
                    if apply_archive and decay_result.should_archive:
                        if not dry_run:
                            archive_result = self.archive_manager.archive(
                                item,
                                decay_result.reason,
                                decay_result.new_confidence
                            )
                            if archive_result.archived:
                                items_archived += 1
                                actions_taken.append({
                                    "type": "archive",
                                    "item_id": item.id,
                                    "reason": decay_result.reason.value,
                                })
                        else:
                            # Dry run: count but don't archive
                            items_archived += 1

            except Exception as e:
                items_failed += 1
                logger.error(f"Maintenance failed for {item.id}: {e}")

        completed_at = datetime.utcnow()
        self._last_run = completed_at

        return MaintenanceReport(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            items_scanned=len(items),
            items_decayed=items_decayed,
            items_archived=items_archived,
            items_healed=items_healed,
            items_failed=items_failed,
            total_confidence_decay=round(total_decay, 6),
            issues_found=issues_found,
            actions_taken=actions_taken if not dry_run else [],
        )

    def get_decay_policy(self) -> Dict[str, Any]:
        """Get current decay policy configuration."""
        return {
            "policy": self.decay_engine.policy.value,
            "config": self.decay_engine.config,
        }

    def set_decay_policy(
        self,
        policy: DecayPolicy,
        custom_config: Optional[Dict] = None
    ):
        """Update decay policy."""
        self.decay_engine.set_policy(policy, custom_config)

    def simulate_maintenance(
        self,
        items: List[MemoryItem],
        days_forward: int = 30
    ) -> Dict[str, Any]:
        """Simulate maintenance over time for planning."""
        projections = []

        for day in range(days_forward + 1):
            archived_count = 0
            surviving_confidence = 0.0

            for item in items:
                # Simulate decay
                decay_factor = math.exp(
                    -self.decay_engine.config["daily_decay_rate"] * day
                )
                projected_conf = item.confidence * decay_factor

                if projected_conf < self.decay_engine.config["archive_threshold"]:
                    archived_count += 1
                else:
                    surviving_confidence += projected_conf

            projections.append({
                "day": day,
                "items_remaining": len(items) - archived_count,
                "items_archived": archived_count,
                "avg_confidence": round(
                    surviving_confidence / max(1, len(items) - archived_count), 4
                ),
            })

        return {
            "policy": self.decay_engine.policy.value,
            "initial_items": len(items),
            "projections": projections,
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_memory_maintenance: Optional[MemoryMaintenance] = None

def get_memory_maintenance() -> MemoryMaintenance:
    """Get singleton instance of MemoryMaintenance."""
    global _memory_maintenance
    if _memory_maintenance is None:
        _memory_maintenance = MemoryMaintenance()
    return _memory_maintenance
