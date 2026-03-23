"""
Deploy Notification System - Unified Telegram updates with threading and enhanced error reporting.

Features:
- Single message per deploy cycle (no spam)
- Thread-based message updates (Telegram groups)
- Detailed error diagnostics (docker logs, health checks)
- Deploy history tracking
- Auto-rollback context
"""

import json
import os
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import subprocess
import requests
from pathlib import Path

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.deploy_notifier")

# ============ Config ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_ALLOWED_USERS", ""))
NAS_HOST = os.getenv("NAS_HOST", "jarvis-nas")
DOCKER_BIN = os.getenv("DOCKER_BIN", "/usr/local/bin/docker")
DOCKER_COMPOSE_BIN = os.getenv("DOCKER_COMPOSE_BIN", "/usr/local/bin/docker-compose")

# Database path
DEPLOY_DB_PATH = Path("/volume1/BRAIN/system/docker/.deploy_history.db") if os.path.exists("/volume1/BRAIN") else Path("/tmp/.deploy_history.db")
DEPLOY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============ Data Models ============
class DeployPhase(Enum):
    """Deploy lifecycle phases"""
    STARTED = "started"           # Deploy initiated
    BUILDING = "building"          # Docker build in progress
    HEALTH_CHECK = "health_check" # Health check running
    SUCCESS = "success"            # Deploy successful
    FAILED = "failed"              # Deploy failed
    ROLLBACK = "rollback"          # Rollback initiated
    ROLLBACK_SUCCESS = "rollback_success"  # Rollback successful
    ROLLBACK_FAILED = "rollback_failed"    # Rollback failed


class DeployStatus(Enum):
    """Overall deploy status"""
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLBACK_FAILED = "rollback_failed"


@dataclass
class HealthCheckFailure:
    """Health check failure details"""
    endpoint: str
    expected_status: int
    actual_status: Optional[int]
    error_message: str
    timestamp: str = None
    container_logs_excerpt: str = ""

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()


@dataclass
class DeployRecord:
    """Complete deploy record for history tracking"""
    deploy_id: str                    # Unique deploy ID (timestamp-based)
    commit_sha: Optional[str] = None
    commit_message: Optional[str] = None
    started_at: str = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = DeployStatus.IN_PROGRESS.value
    phase: str = DeployPhase.STARTED.value
    telegram_thread_id: Optional[str] = None
    telegram_message_id: Optional[str] = None

    # Error tracking
    health_check_failures: List[Dict] = None  # HealthCheckFailure as dict
    rollback_tag: Optional[str] = None
    rollback_reason: Optional[str] = None

    # Context
    hostname: str = NAS_HOST
    deployed_by: str = "auto"

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.utcnow().isoformat()
        if self.health_check_failures is None:
            self.health_check_failures = []


# ============ Database Layer ============
class DeployHistoryDB:
    """SQLite database for deploy history and state"""

    def __init__(self, db_path: Path = DEPLOY_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deploys (
                deploy_id TEXT PRIMARY KEY,
                commit_sha TEXT,
                commit_message TEXT,
                started_at TEXT,
                ended_at TEXT,
                duration_seconds REAL,
                status TEXT,
                phase TEXT,
                telegram_thread_id TEXT,
                telegram_message_id TEXT,
                health_check_failures TEXT,
                rollback_tag TEXT,
                rollback_reason TEXT,
                hostname TEXT,
                deployed_by TEXT
            )
        """)
        conn.commit()
        conn.close()

    def save_deploy(self, record: DeployRecord):
        """Save or update deploy record"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO deploys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.deploy_id,
            record.commit_sha,
            record.commit_message,
            record.started_at,
            record.ended_at,
            record.duration_seconds,
            record.status,
            record.phase,
            record.telegram_thread_id,
            record.telegram_message_id,
            json.dumps(record.health_check_failures),
            record.rollback_tag,
            record.rollback_reason,
            record.hostname,
            record.deployed_by,
        ))
        conn.commit()
        conn.close()

    def get_deploy(self, deploy_id: str) -> Optional[DeployRecord]:
        """Get deploy record by ID"""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT * FROM deploys WHERE deploy_id = ?", (deploy_id,)).fetchone()
        conn.close()

        if not row:
            return None

        return DeployRecord(
            deploy_id=row[0],
            commit_sha=row[1],
            commit_message=row[2],
            started_at=row[3],
            ended_at=row[4],
            duration_seconds=row[5],
            status=row[6],
            phase=row[7],
            telegram_thread_id=row[8],
            telegram_message_id=row[9],
            health_check_failures=json.loads(row[10]) if row[10] else [],
            rollback_tag=row[11],
            rollback_reason=row[12],
            hostname=row[13],
            deployed_by=row[14],
        )

    def get_recent_deploys(self, limit: int = 10) -> List[DeployRecord]:
        """Get recent deploy history"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT * FROM deploys ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()

        records = []
        for row in rows:
            records.append(DeployRecord(
                deploy_id=row[0],
                commit_sha=row[1],
                commit_message=row[2],
                started_at=row[3],
                ended_at=row[4],
                duration_seconds=row[5],
                status=row[6],
                phase=row[7],
                telegram_thread_id=row[8],
                telegram_message_id=row[9],
                health_check_failures=json.loads(row[10]) if row[10] else [],
                rollback_tag=row[11],
                rollback_reason=row[12],
                hostname=row[13],
                deployed_by=row[14],
            ))

        return records


# ============ Telegram Integration ============
class TelegramNotifier:
    """Telegram notification with thread support"""

    def __init__(self, token: str = TELEGRAM_BOT_TOKEN, chat_id: str = TELEGRAM_ADMIN_ID):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(
        self,
        text: str,
        thread_id: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        buttons: Optional[List[List[Dict]]] = None,
        parse_mode: str = "HTML"
    ) -> Dict[str, Any]:
        """
        Send Telegram message with optional thread support.

        Returns: {'ok': bool, 'message_id': str, 'result': dict}
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured (TOKEN or ADMIN_ID missing)")
            return {"ok": False, "error": "Telegram not configured"}

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if thread_id:
            payload["message_thread_id"] = thread_id

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}

        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=10
            )
            result = response.json()

            if result.get("ok"):
                return {
                    "ok": True,
                    "message_id": result.get("result", {}).get("message_id"),
                    "result": result.get("result", {})
                }
            else:
                logger.warning(f"Telegram API error: {result.get('description', 'Unknown')}")
                return {
                    "ok": False,
                    "error": result.get("description", "Unknown Telegram error")
                }

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return {"ok": False, "error": str(e)}

    def edit_message(
        self,
        message_id: str,
        text: str,
        buttons: Optional[List[List[Dict]]] = None,
        parse_mode: str = "HTML"
    ) -> Dict[str, Any]:
        """Edit an existing Telegram message"""
        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured")
            return {"ok": False}

        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}

        try:
            response = requests.post(
                f"{self.base_url}/editMessageText",
                json=payload,
                timeout=10
            )
            return {"ok": response.json().get("ok", False)}
        except Exception as e:
            logger.error(f"Failed to edit Telegram message: {e}")
            return {"ok": False}


# ============ Deploy Notifier (Main API) ============
class DeployNotifier:
    """Central deploy notification coordinator"""

    def __init__(self):
        self.db = DeployHistoryDB()
        self.telegram = TelegramNotifier()
        self._current_deploy: Optional[DeployRecord] = None

    def start_deploy(
        self,
        commit_sha: Optional[str] = None,
        commit_message: Optional[str] = None,
        deployed_by: str = "auto"
    ) -> DeployRecord:
        """Initialize a new deploy notification session"""
        deploy_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        record = DeployRecord(
            deploy_id=deploy_id,
            commit_sha=commit_sha,
            commit_message=commit_message,
            deployed_by=deployed_by,
        )

        self._current_deploy = record
        self.db.save_deploy(record)

        # Send initial Telegram message (with thread support)
        msg = self._format_started_message(record)
        result = self.telegram.send_message(msg)

        if result.get("ok"):
            record.telegram_message_id = str(result.get("message_id"))
            self.db.save_deploy(record)

        logger.info(f"Deploy started: {deploy_id}", extra={"deploy_id": deploy_id})
        return record

    def update_phase(self, phase: DeployPhase, details: Optional[str] = None):
        """Update deploy progress"""
        if not self._current_deploy:
            logger.warning("No active deploy to update")
            return

        self._current_deploy.phase = phase.value
        self.db.save_deploy(self._current_deploy)

        # Send phase update to Telegram (edit existing message)
        if self._current_deploy.telegram_message_id:
            msg = self._format_phase_update(self._current_deploy, details)
            self.telegram.edit_message(
                self._current_deploy.telegram_message_id,
                msg
            )

        logger.info(f"Deploy phase: {phase.value}", extra={"deploy_id": self._current_deploy.deploy_id})

    def report_health_check_failure(
        self,
        endpoint: str,
        expected_status: int,
        actual_status: Optional[int],
        error_message: str
    ):
        """Record health check failure with diagnostics"""
        if not self._current_deploy:
            logger.warning("No active deploy to report failure")
            return

        failure = HealthCheckFailure(
            endpoint=endpoint,
            expected_status=expected_status,
            actual_status=actual_status,
            error_message=error_message,
            container_logs_excerpt=self._get_container_logs_excerpt(lines=50)
        )

        self._current_deploy.health_check_failures.append(asdict(failure))
        self._current_deploy.status = DeployStatus.FAILED.value
        self._current_deploy.phase = DeployPhase.FAILED.value
        self.db.save_deploy(self._current_deploy)

        logger.warning(f"Health check failed: {endpoint} -> {actual_status}", extra={
            "deploy_id": self._current_deploy.deploy_id,
            "error": error_message
        })

    def mark_rollback(self, tag: str, reason: str):
        """Mark deployment as rolling back"""
        if not self._current_deploy:
            return

        self._current_deploy.status = DeployStatus.ROLLING_BACK.value
        self._current_deploy.phase = DeployPhase.ROLLBACK.value
        self._current_deploy.rollback_tag = tag
        self._current_deploy.rollback_reason = reason
        self.db.save_deploy(self._current_deploy)

        # Update Telegram with rollback info
        if self._current_deploy.telegram_message_id:
            msg = self._format_rollback_message(self._current_deploy)
            self.telegram.edit_message(
                self._current_deploy.telegram_message_id,
                msg
            )

        logger.info(f"Rollback initiated: {tag}", extra={"deploy_id": self._current_deploy.deploy_id})

    def mark_success(self, duration_seconds: Optional[float] = None):
        """Mark deployment as successful"""
        if not self._current_deploy:
            logger.warning("No active deploy to mark success")
            return

        self._current_deploy.ended_at = datetime.utcnow().isoformat()
        self._current_deploy.duration_seconds = duration_seconds or (
            (datetime.fromisoformat(self._current_deploy.ended_at) -
             datetime.fromisoformat(self._current_deploy.started_at)).total_seconds()
        )
        self._current_deploy.status = DeployStatus.SUCCESS.value
        self._current_deploy.phase = DeployPhase.SUCCESS.value
        self.db.save_deploy(self._current_deploy)

        # Send final success message
        msg = self._format_success_message(self._current_deploy)
        if self._current_deploy.telegram_message_id:
            self.telegram.edit_message(
                self._current_deploy.telegram_message_id,
                msg
            )

        logger.info(f"Deploy successful: {self._current_deploy.deploy_id}", extra={
            "deploy_id": self._current_deploy.deploy_id,
            "duration_seconds": self._current_deploy.duration_seconds
        })

    def mark_failed(self, reason: str, duration_seconds: Optional[float] = None):
        """Mark deployment as failed (without rollback)"""
        if not self._current_deploy:
            return

        self._current_deploy.ended_at = datetime.utcnow().isoformat()
        self._current_deploy.duration_seconds = duration_seconds or (
            (datetime.fromisoformat(self._current_deploy.ended_at) -
             datetime.fromisoformat(self._current_deploy.started_at)).total_seconds()
        )
        self._current_deploy.status = DeployStatus.FAILED.value
        self.db.save_deploy(self._current_deploy)

        # Send failure notification
        msg = self._format_failure_message(self._current_deploy, reason)
        if self._current_deploy.telegram_message_id:
            self.telegram.edit_message(
                self._current_deploy.telegram_message_id,
                msg
            )

        logger.error(f"Deploy failed: {reason}", extra={"deploy_id": self._current_deploy.deploy_id})

    # ============ Helpers ============
    def _get_container_logs_excerpt(self, lines: int = 30) -> str:
        """Get recent container logs for error context"""
        try:
            result = subprocess.run(
                [DOCKER_BIN, "logs", "jarvis-ingestion", "--tail", str(lines)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Filter to error lines
                error_lines = [
                    line for line in result.stdout.split("\n")
                    if "error" in line.lower() or "fail" in line.lower() or "exception" in line.lower()
                ]
                return "\n".join(error_lines[-5:]) if error_lines else result.stdout[-500:]
            return ""
        except Exception as e:
            logger.warning(f"Failed to get container logs: {e}")
            return ""

    def _format_started_message(self, record: DeployRecord) -> str:
        """Format 'deploy started' message"""
        msg = "🚀 <b>Jarvis Deploy: STARTED</b>\n\n"
        if record.commit_sha:
            msg += f"<code>{record.commit_sha[:8]}</code>\n"
        if record.commit_message:
            msg += f"{record.commit_message}\n"
        msg += f"\n⏱️ Started: {record.started_at}\n"
        msg += f"🏠 Host: {record.hostname}"
        return msg

    def _format_phase_update(self, record: DeployRecord, details: Optional[str] = None) -> str:
        """Format phase update message"""
        phase_emoji = {
            DeployPhase.BUILDING.value: "🔨",
            DeployPhase.HEALTH_CHECK.value: "🏥",
        }
        emoji = phase_emoji.get(record.phase, "⏳")

        msg = f"{emoji} <b>Jarvis Deploy: {record.phase.upper()}</b>\n\n"
        if record.commit_message:
            msg += f"<i>{record.commit_message}</i>\n\n"
        if details:
            msg += f"📝 {details}\n"

        elapsed = (datetime.utcnow() - datetime.fromisoformat(record.started_at)).total_seconds()
        msg += f"\n⏱️ Elapsed: {elapsed:.0f}s"
        return msg

    def _format_success_message(self, record: DeployRecord) -> str:
        """Format success message"""
        msg = "✅ <b>Jarvis Deploy: SUCCESS</b>\n\n"
        if record.commit_message:
            msg += f"<i>{record.commit_message}</i>\n\n"
        msg += f"✓ /readyz ok\n"
        msg += f"✓ Capabilities refreshed\n"
        msg += f"\n⏱️ Duration: {record.duration_seconds:.1f}s"
        msg += f"\n🏠 Host: {record.hostname}"
        return msg

    def _format_failure_message(self, record: DeployRecord, reason: str) -> str:
        """Format failure message"""
        msg = "❌ <b>Jarvis Deploy: FAILED</b>\n\n"
        if record.commit_message:
            msg += f"<i>{record.commit_message}</i>\n\n"
        msg += f"❌ Reason: {reason}\n"

        if record.health_check_failures:
            failure = record.health_check_failures[-1]  # Last failure
            msg += f"\n🏥 Health Check: {failure['endpoint']}\n"
            msg += f"   Expected: {failure['expected_status']}\n"
            msg += f"   Got: {failure['actual_status']}\n"
            if failure.get('container_logs_excerpt'):
                msg += f"\n📋 Container logs:\n<pre>{failure['container_logs_excerpt'][:300]}</pre>"

        msg += f"\n⏱️ Duration: {record.duration_seconds:.1f}s"
        return msg

    def _format_rollback_message(self, record: DeployRecord) -> str:
        """Format rollback message"""
        msg = "🔄 <b>Auto-Rollback: INITIATED</b>\n\n"
        msg += f"Reason: {record.rollback_reason}\n"
        msg += f"Restoring: <code>{record.rollback_tag}</code>\n"
        msg += f"\n⏳ Waiting for container to stabilize..."
        return msg

    def get_deploy_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent deploy history for dashboard"""
        records = self.db.get_recent_deploys(limit)
        return [
            {
                "id": r.deploy_id,
                "commit": r.commit_sha[:8] if r.commit_sha else "unknown",
                "status": r.status,
                "duration": r.duration_seconds,
                "started": r.started_at,
                "failures": len(r.health_check_failures),
                "rollback": r.rollback_tag or "none",
            }
            for r in records
        ]


# ============ Global Instance ============
_notifier_instance: Optional[DeployNotifier] = None


def get_deploy_notifier() -> DeployNotifier:
    """Get or create global deploy notifier instance"""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = DeployNotifier()
    return _notifier_instance


# ============ Tool Functions (for Jarvis integration) ============
def start_deploy_notification(
    commit_sha: Optional[str] = None,
    commit_message: Optional[str] = None,
    deployed_by: str = "auto"
) -> Dict[str, Any]:
    """Start a new deploy notification session"""
    notifier = get_deploy_notifier()
    record = notifier.start_deploy(commit_sha, commit_message, deployed_by)
    return {
        "deploy_id": record.deploy_id,
        "status": "started",
        "telegram_message_id": record.telegram_message_id,
    }


def update_deploy_status(
    phase: str,
    details: Optional[str] = None
) -> Dict[str, Any]:
    """Update deploy phase"""
    notifier = get_deploy_notifier()
    try:
        phase_enum = DeployPhase[phase.upper()]
        notifier.update_phase(phase_enum, details)
        return {"status": "updated", "phase": phase}
    except (KeyError, ValueError) as e:
        return {"status": "error", "message": f"Invalid phase: {phase}"}


def report_deploy_failure(
    endpoint: str,
    expected_status: int,
    actual_status: Optional[int],
    error_message: str,
    auto_rollback: bool = False,
    rollback_tag: Optional[str] = None
) -> Dict[str, Any]:
    """Report health check failure and optionally trigger rollback"""
    notifier = get_deploy_notifier()
    notifier.report_health_check_failure(endpoint, expected_status, actual_status, error_message)

    if auto_rollback and rollback_tag:
        notifier.mark_rollback(rollback_tag, f"Health check failed: {endpoint}")

    return {"status": "failure_reported"}


def complete_deploy(
    success: bool,
    duration_seconds: Optional[float] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Mark deploy as complete (success or failure)"""
    notifier = get_deploy_notifier()
    if success:
        notifier.mark_success(duration_seconds)
        return {"status": "success", "deploy_id": notifier._current_deploy.deploy_id if notifier._current_deploy else None}
    else:
        notifier.mark_failed(reason or "Unknown error", duration_seconds)
        return {"status": "failed", "reason": reason}


def get_deploy_history_data(limit: int = 10) -> Dict[str, Any]:
    """Get deploy history for dashboard"""
    notifier = get_deploy_notifier()
    history = notifier.get_deploy_history(limit)
    return {
        "count": len(history),
        "deploys": history,
        "success_rate": sum(1 for d in history if d["status"] == "success") / len(history) if history else 0,
    }
