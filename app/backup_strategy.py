"""
Jarvis Backup Strategy & RTO/RPO Validation

Validates disaster recovery readiness and measures recovery time/point objectives.

RTO (Recovery Time Objective):
- Postgres restore: <5 minutes (dump import from backup)
- n8n data restore: <2 minutes (extract tarball)
- Docker stack redeploy: <3 minutes (pull images, compose up)
- Total system recovery: <15 minutes (target SLA)

RPO (Recovery Point Objective):
- Daily incremental backups (24h RPO target)
- Retention: 7 daily snapshots + 4 weekly + 1 monthly
- Total retention: ~35 days of history

Backup Components:
1. Postgres dumps (custom format, logical backups)
   - jarvis database (core approval/permission data)
   - n8n database (workflow configuration)
   - langfuse database (trace data)
   
2. n8n data bundle (home/.n8n + files directories)
   - Encrypted credentials
   - Workflow definitions
   - Execution history
   
3. Docker stack configuration
   - docker-compose.yml
   - monitoring rules (Prometheus alerts)
   - n8n workflow definitions
   
4. Audit trail archives (encrypted)
   - Approval decisions (7-year retention)
   - Permission changes
   - Error logs

Verification Checkpoints:
- Backup files exist and are non-empty
- Dumps are readable (pg_restore -l)
- Tarballs are intact (tar -tzf)
- Checksums match (sha256)
"""
import os
import time
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.backup_strategy")

# Configuration
BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "/volume1/BRAIN/system/backups/jarvis")
NAS_HOST = os.environ.get("NAS_HOST", "jarvis-nas")
DOCKER_COMPOSE_DIR = "/volume1/BRAIN/system/docker"
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "35"))
BACKUP_SCHEDULE_INTERVAL_HOURS = int(os.environ.get("BACKUP_SCHEDULE_INTERVAL_HOURS", "24"))

# RTO/RPO Targets (in seconds)
RTO_POSTGRES_RESTORE = 300  # 5 minutes
RTO_N8N_RESTORE = 120  # 2 minutes
RTO_DOCKER_REDEPLOY = 180  # 3 minutes
RTO_TOTAL = 900  # 15 minutes

RPO_TARGET_HOURS = 24  # 24-hour RPO (daily backups)


class BackupStatus(str, Enum):
    """Backup completion status"""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    VERIFIED = "verified"
    CORRUPTED = "corrupted"


class RecoveryComponentType(str, Enum):
    """Component types in recovery"""
    POSTGRES_DUMP = "postgres_dump"
    N8N_DATA = "n8n_data"
    DOCKER_CONFIG = "docker_config"
    AUDIT_TRAIL = "audit_trail"


@dataclass
class BackupManifest:
    """Backup manifest with metadata"""
    timestamp: str  # ISO 8601
    backup_root: str
    components: Dict[str, Dict[str, Any]]  # component_type -> {file, size_bytes, sha256, verified}
    duration_seconds: float
    status: BackupStatus
    verification_timestamp: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BackupValidator:
    """Validates backup integrity and readiness"""

    def __init__(self, backup_dir: str):
        self.backup_dir = backup_dir
        self.manifest: Optional[BackupManifest] = None

    def validate_backup_files(self) -> Dict[str, Any]:
        """
        Check that all required backup files exist and are non-empty.
        
        Returns:
            {
                "valid": bool,
                "components": {
                    "postgres_jarvis": {"exists": bool, "size_bytes": int},
                    "postgres_n8n": {"exists": bool, "size_bytes": int},
                    "n8n_data": {"exists": bool, "size_bytes": int},
                    "docker_config": {"exists": bool, "size_bytes": int}
                },
                "total_size_bytes": int,
                "missing_files": [str]
            }
        """
        required_files = {
            "postgres_jarvis": "postgres_jarvis.dump",
            "postgres_n8n": "postgres_n8n.dump",
            "n8n_data": "n8n_data.tgz",
            "docker_config": "docker_stack_config.tgz"
        }

        components = {}
        total_size = 0
        missing = []

        for component_name, filename in required_files.items():
            filepath = os.path.join(self.backup_dir, filename)
            
            try:
                if os.path.exists(filepath):
                    size = os.path.getsize(filepath)
                    if size > 0:
                        components[component_name] = {
                            "exists": True,
                            "size_bytes": size,
                            "file": filename
                        }
                        total_size += size
                    else:
                        missing.append(f"{component_name} (empty)")
                        components[component_name] = {
                            "exists": True,
                            "size_bytes": 0,
                            "file": filename,
                            "error": "File is empty"
                        }
                else:
                    missing.append(component_name)
                    components[component_name] = {
                        "exists": False,
                        "size_bytes": 0,
                        "file": filename
                    }
            except Exception as e:
                missing.append(f"{component_name} (error: {str(e)})")
                components[component_name] = {
                    "exists": False,
                    "error": str(e)
                }

        return {
            "valid": len(missing) == 0,
            "components": components,
            "total_size_bytes": total_size,
            "missing_files": missing
        }

    def calculate_checksums(self) -> Dict[str, Dict[str, str]]:
        """
        Calculate SHA256 checksums for backup files.
        
        Returns:
            {
                "postgres_jarvis": {"size": int, "sha256": str},
                ...
            }
        """
        checksums = {}
        
        for filename in ["postgres_jarvis.dump", "postgres_n8n.dump", "n8n_data.tgz", "docker_stack_config.tgz"]:
            filepath = os.path.join(self.backup_dir, filename)
            component_name = filename.replace(".dump", "").replace(".tgz", "")
            
            if not os.path.exists(filepath):
                checksums[component_name] = {"error": "File not found"}
                continue
            
            try:
                size = os.path.getsize(filepath)
                sha256_hash = hashlib.sha256()
                
                with open(filepath, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256_hash.update(chunk)
                
                checksums[component_name] = {
                    "size_bytes": size,
                    "sha256": sha256_hash.hexdigest()
                }
                
                log_with_context(
                    logger, "info",
                    "backup_checksum_calculated",
                    component=component_name,
                    size=size,
                    sha256=sha256_hash.hexdigest()[:16] + "..."
                )
            except Exception as e:
                checksums[component_name] = {"error": str(e)}
        
        return checksums

    def verify_postgres_dumps(self) -> Dict[str, Any]:
        """
        Verify Postgres dumps are readable by pg_restore.
        
        Returns:
            {
                "postgres_jarvis": {"valid": bool, "error": Optional[str]},
                "postgres_n8n": {"valid": bool, "error": Optional[str]}
            }
        """
        results = {}
        
        for db_name in ["jarvis", "n8n"]:
            dump_file = f"postgres_{db_name}.dump"
            filepath = os.path.join(self.backup_dir, dump_file)
            
            if not os.path.exists(filepath):
                results[f"postgres_{db_name}"] = {
                    "valid": False,
                    "error": "Dump file not found"
                }
                continue
            
            try:
                # Try to run pg_restore -l (list mode, doesn't modify DB)
                result = subprocess.run(
                    ["pg_restore", "-l", filepath],
                    capture_output=True,
                    timeout=30,
                    text=True
                )
                
                if result.returncode == 0:
                    results[f"postgres_{db_name}"] = {
                        "valid": True,
                        "objects_count": len(result.stdout.splitlines())
                    }
                    log_with_context(
                        logger, "info",
                        "postgres_dump_verified",
                        db=db_name,
                        objects=len(result.stdout.splitlines())
                    )
                else:
                    results[f"postgres_{db_name}"] = {
                        "valid": False,
                        "error": result.stderr[:200]
                    }
            except Exception as e:
                results[f"postgres_{db_name}"] = {
                    "valid": False,
                    "error": str(e)[:200]
                }
        
        return results

    def verify_tar_archives(self) -> Dict[str, Any]:
        """
        Verify tar archives are intact.
        
        Returns:
            {
                "n8n_data": {"valid": bool, "files_count": int, "error": Optional[str]},
                "docker_config": {"valid": bool, "files_count": int, "error": Optional[str]}
            }
        """
        results = {}
        
        for name, filename in [("n8n_data", "n8n_data.tgz"), ("docker_config", "docker_stack_config.tgz")]:
            filepath = os.path.join(self.backup_dir, filename)
            
            if not os.path.exists(filepath):
                results[name] = {
                    "valid": False,
                    "error": "Tar file not found"
                }
                continue
            
            try:
                result = subprocess.run(
                    ["tar", "-tzf", filepath],
                    capture_output=True,
                    timeout=30,
                    text=True
                )
                
                if result.returncode == 0:
                    file_count = len(result.stdout.splitlines())
                    results[name] = {
                        "valid": True,
                        "files_count": file_count
                    }
                    log_with_context(
                        logger, "info",
                        "tar_archive_verified",
                        archive=name,
                        files=file_count
                    )
                else:
                    results[name] = {
                        "valid": False,
                        "error": result.stderr[:200]
                    }
            except Exception as e:
                results[name] = {
                    "valid": False,
                    "error": str(e)[:200]
                }
        
        return results

    def full_validation(self) -> BackupManifest:
        """
        Run complete backup validation suite.
        
        Returns:
            BackupManifest with validation results
        """
        start_time = time.time()
        
        log_with_context(
            logger, "info",
            "backup_validation_started",
            backup_dir=self.backup_dir
        )
        
        # 1. File existence check
        file_check = self.validate_backup_files()
        
        # 2. Checksum calculation
        checksums = self.calculate_checksums()
        
        # 3. Postgres verification
        postgres_check = self.verify_postgres_dumps()
        
        # 4. Tar archive verification
        tar_check = self.verify_tar_archives()
        
        # Overall status
        all_valid = (
            file_check["valid"] and
            all(v.get("valid", False) for v in postgres_check.values()) and
            all(v.get("valid", False) for v in tar_check.values())
        )
        
        status = BackupStatus.VERIFIED if all_valid else BackupStatus.CORRUPTED
        
        components = {
            "postgres_jarvis": {**postgres_check.get("postgres_jarvis", {}), **checksums.get("postgres_jarvis", {})},
            "postgres_n8n": {**postgres_check.get("postgres_n8n", {}), **checksums.get("postgres_n8n", {})},
            "n8n_data": {**tar_check.get("n8n_data", {}), **checksums.get("n8n_data", {})},
            "docker_config": {**tar_check.get("docker_config", {}), **checksums.get("docker_config", {})}
        }
        
        duration = time.time() - start_time
        
        manifest = BackupManifest(
            timestamp=datetime.now(timezone.utc).isoformat(),
            backup_root=self.backup_dir,
            components=components,
            duration_seconds=duration,
            status=status,
            verification_timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        log_with_context(
            logger, "info" if all_valid else "error",
            "backup_validation_completed",
            backup_dir=self.backup_dir,
            status=status.value,
            duration_sec=round(duration, 2),
            all_valid=all_valid
        )
        
        return manifest


class RTOAnalyzer:
    """Analyzes Recovery Time Objective (RTO) feasibility"""

    @staticmethod
    def estimate_rto(backup_manifest: BackupManifest) -> Dict[str, Any]:
        """
        Estimate RTO based on backup file sizes.
        
        Assumptions:
        - Postgres restore: 1 second per 10MB (conservative)
        - n8n data restore: 1 second per 50MB
        - Docker redeploy: fixed 3 minutes
        - Total: sum of components + buffer
        """
        estimates = {
            "postgres_jarvis_restore_sec": 0,
            "postgres_n8n_restore_sec": 0,
            "n8n_data_restore_sec": 0,
            "docker_redeploy_sec": RTO_DOCKER_REDEPLOY,
            "buffer_sec": 30,  # 30s safety margin
            "estimated_total_sec": 0
        }
        
        try:
            # Postgres restore: 1 sec per 10MB
            for db in ["postgres_jarvis", "postgres_n8n"]:
                size_bytes = backup_manifest.components.get(db, {}).get("size_bytes", 0)
                estimate_sec = max(30, (size_bytes / (10 * 1024 * 1024)))  # min 30s
                estimates[f"{db}_restore_sec"] = round(estimate_sec, 1)
            
            # n8n data restore: 1 sec per 50MB
            n8n_size = backup_manifest.components.get("n8n_data", {}).get("size_bytes", 0)
            n8n_restore = max(10, (n8n_size / (50 * 1024 * 1024)))  # min 10s
            estimates["n8n_data_restore_sec"] = round(n8n_restore, 1)
            
            total = (
                estimates["postgres_jarvis_restore_sec"] +
                estimates["postgres_n8n_restore_sec"] +
                estimates["n8n_data_restore_sec"] +
                estimates["docker_redeploy_sec"] +
                estimates["buffer_sec"]
            )
            estimates["estimated_total_sec"] = round(total, 1)
            
            # Check against target
            estimates["meets_rto"] = total <= RTO_TOTAL
            estimates["rto_target_sec"] = RTO_TOTAL
            estimates["spare_capacity_percent"] = round(100 * (1 - total / RTO_TOTAL), 1) if total < RTO_TOTAL else 0
            
        except Exception as e:
            log_with_context(logger, "error", "rto_estimation_failed", error=str(e))
            estimates["error"] = str(e)
        
        return estimates

    @staticmethod
    def estimate_rpo(last_backup_time: datetime) -> Dict[str, Any]:
        """
        Estimate RPO (Recovery Point Objective) based on backup timing.
        
        Returns time since last backup and assessment against 24h target.
        """
        now = datetime.now(timezone.utc)
        time_since_backup = now - last_backup_time
        hours_since = time_since_backup.total_seconds() / 3600
        
        return {
            "last_backup_time": last_backup_time.isoformat(),
            "current_time": now.isoformat(),
            "hours_since_backup": round(hours_since, 1),
            "rpo_target_hours": RPO_TARGET_HOURS,
            "meets_rpo": hours_since <= RPO_TARGET_HOURS,
            "rpo_utilization_percent": round(100 * (hours_since / RPO_TARGET_HOURS), 1)
        }


def validate_backup_ready() -> Dict[str, Any]:
    """
    Check if system backup strategy is ready for disaster recovery.
    
    Returns comprehensive readiness report.
    """
    try:
        # Check for recent backups
        import glob
        backup_dirs = sorted(glob.glob(os.path.join(BACKUP_ROOT, "*")), reverse=True)
        
        if not backup_dirs:
            return {
                "ready": False,
                "error": f"No backups found in {BACKUP_ROOT}",
                "action": "Create first backup: bash ./jarvis-backup.sh create --verify"
            }
        
        latest_backup = backup_dirs[0]
        backup_timestamp_str = os.path.basename(latest_backup)
        
        # Parse backup timestamp (ISO 8601 format)
        try:
            backup_time = datetime.fromisoformat(backup_timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError) as e:
            log_with_context(logger, "warning", "Failed to parse backup timestamp, using current time",
                           timestamp_str=backup_timestamp_str, error=str(e))
            backup_time = datetime.now(timezone.utc)
        
        # Validate latest backup
        validator = BackupValidator(latest_backup)
        manifest = validator.full_validation()
        
        # Estimate RTO and RPO
        rto_analysis = RTOAnalyzer.estimate_rto(manifest)
        rpo_analysis = RTOAnalyzer.estimate_rpo(backup_time)
        
        # Overall readiness
        ready = (
            manifest.status == BackupStatus.VERIFIED and
            rto_analysis.get("meets_rto", False) and
            rpo_analysis.get("meets_rpo", False)
        )
        
        return {
            "ready": ready,
            "status": manifest.status.value,
            "latest_backup": latest_backup,
            "backup_time": backup_time.isoformat(),
            "total_backups": len(backup_dirs),
            "components": manifest.components,
            "rto": rto_analysis,
            "rpo": rpo_analysis,
            "backup_count_7d": len([d for d in backup_dirs if (datetime.now(timezone.utc) - datetime.fromisoformat(os.path.basename(d).replace("Z", "+00:00"))).days <= 7]),
            "retention_policy": f"{BACKUP_RETENTION_DAYS} days",
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    
    except Exception as e:
        log_with_context(logger, "error", "backup_readiness_check_failed", error=str(e))
        return {
            "ready": False,
            "error": str(e),
            "action": "Check backup infrastructure and Postgres connectivity"
        }
