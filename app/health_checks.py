"""
Enhanced Health Checks for Jarvis
Actionable health monitoring with detailed metrics
"""

import os
import time
import psutil
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
import json
from pathlib import Path

from .observability import log_with_context
import logging

logger = logging.getLogger(__name__)

class HealthStatus:
    """Health status constants"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    
    @staticmethod
    def from_latency(latency_ms: float) -> str:
        """Determine status from latency"""
        if latency_ms < 100:
            return HealthStatus.HEALTHY
        elif latency_ms < 500:
            return HealthStatus.WARNING
        return HealthStatus.CRITICAL
    
    @staticmethod
    def from_percentage(used: float, warning: float = 70, critical: float = 90) -> str:
        """Determine status from percentage"""
        if used < warning:
            return HealthStatus.HEALTHY
        elif used < critical:
            return HealthStatus.WARNING
        return HealthStatus.CRITICAL

def measure_latency(func, *args, **kwargs) -> Tuple[Any, float]:
    """Measure function execution time in milliseconds"""
    start = time.time()
    try:
        result = func(*args, **kwargs)
        latency_ms = (time.time() - start) * 1000
        return result, latency_ms
    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        return e, latency_ms

def get_qdrant_health() -> Dict[str, Any]:
    """Enhanced Qdrant health check with latency"""
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=5)
        
        # Measure collections query latency
        collections, latency_ms = measure_latency(client.get_collections)
        
        if isinstance(collections, Exception):
            return {
                "status": HealthStatus.CRITICAL,
                "error": str(collections),
                "latency_ms": latency_ms
            }
        
        # Count total points across collections
        total_points = 0
        collection_details = []
        
        for collection in collections.collections:
            info = client.get_collection(collection.name)
            points = info.points_count
            total_points += points
            collection_details.append({
                "name": collection.name,
                "points": points,
                "status": info.status
            })
        
        return {
            "status": HealthStatus.from_latency(latency_ms),
            "latency_ms": round(latency_ms, 2),
            "total_points": total_points,
            "collections": len(collections.collections),
            "collection_details": collection_details,
            "host": f"{qdrant_host}:{qdrant_port}",
            "recommendation": "All good!" if latency_ms < 100 else "Consider optimizing queries"
        }
    except Exception as e:
        return {
            "status": HealthStatus.CRITICAL,
            "error": str(e),
            "recommendation": "Check if Qdrant container is running"
        }

def get_postgres_health() -> Dict[str, Any]:
    """Enhanced PostgreSQL health check"""
    try:
        from . import knowledge_db
        
        # Test connection and measure query latency
        test_query = "SELECT COUNT(*) FROM knowledge_items"
        result, latency_ms = measure_latency(knowledge_db.execute_query, test_query)
        
        if isinstance(result, Exception):
            return {
                "status": HealthStatus.CRITICAL,
                "error": str(result),
                "latency_ms": latency_ms
            }
        
        # Get knowledge statistics
        stats_query = """
        SELECT 
            COUNT(*) as total_items,
            COUNT(DISTINCT namespace) as namespaces,
            COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 1 END) as new_today,
            COUNT(CASE WHEN item_type = 'person' THEN 1 END) as person_profiles
        FROM knowledge_items
        """
        
        stats_result = knowledge_db.execute_query(stats_query)
        stats = stats_result[0] if stats_result else {}
        
        return {
            "status": HealthStatus.from_latency(latency_ms),
            "latency_ms": round(latency_ms, 2),
            "knowledge_stats": {
                "total_items": stats.get("total_items", 0),
                "namespaces": stats.get("namespaces", 0),
                "new_today": stats.get("new_today", 0),
                "person_profiles": stats.get("person_profiles", 0)
            },
            "database": "jarvis",
            "recommendation": "All good!" if latency_ms < 50 else "Consider query optimization"
        }
    except Exception as e:
        return {
            "status": HealthStatus.CRITICAL,
            "error": str(e),
            "recommendation": "Check PostgreSQL container and connection"
        }

def get_docker_stats() -> Dict[str, Any]:
    """Get Docker container statistics"""
    try:
        # Use docker stats with JSON output
        cmd = "docker stats --no-stream --format json jarvis-ingestion jarvis-qdrant jarvis-postgres jarvis-meilisearch jarvis-n8n"
        result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            return {"status": HealthStatus.WARNING, "error": "Could not get Docker stats"}
        
        stats = {}
        for line in result.stdout.strip().split('\n'):
            if line:
                container = json.loads(line)
                name = container.get("Name", "").replace("jarvis-", "")
                
                # Parse memory usage
                mem_usage = container.get("MemUsage", "0MiB / 0MiB")
                mem_parts = mem_usage.split(" / ")
                if len(mem_parts) == 2:
                    used = mem_parts[0].replace("MiB", "").replace("GiB", "")
                    limit = mem_parts[1].replace("MiB", "").replace("GiB", "")
                    
                    # Convert to MB
                    if "GiB" in mem_parts[0]:
                        used = float(used) * 1024
                    else:
                        used = float(used)
                        
                    if "GiB" in mem_parts[1]:
                        limit = float(limit) * 1024
                    else:
                        limit = float(limit)
                    
                    mem_percent = (used / limit * 100) if limit > 0 else 0
                else:
                    used = limit = mem_percent = 0
                
                # Parse CPU
                cpu_str = container.get("CPUPerc", "0%").replace("%", "")
                cpu_percent = float(cpu_str) if cpu_str else 0
                
                stats[name] = {
                    "memory": {
                        "used_mb": round(used, 2),
                        "limit_mb": round(limit, 2),
                        "percent": round(mem_percent, 2),
                        "status": HealthStatus.from_percentage(mem_percent)
                    },
                    "cpu": {
                        "percent": cpu_percent,
                        "status": HealthStatus.from_percentage(cpu_percent, warning=80, critical=95)
                    }
                }
        
        return {
            "status": HealthStatus.HEALTHY,
            "containers": stats,
            "recommendation": "Monitor memory usage" if any(
                c["memory"]["percent"] > 70 for c in stats.values()
            ) else "All good!"
        }
    except Exception as e:
        return {
            "status": HealthStatus.WARNING,
            "error": str(e),
            "recommendation": "Check Docker daemon"
        }

def get_backup_status() -> Dict[str, Any]:
    """Check backup status"""
    try:
        backup_dir = Path("/volume1/BRAIN/system/backups")
        if not backup_dir.exists():
            return {
                "status": HealthStatus.WARNING,
                "last_backup": None,
                "recommendation": "No backup directory found"
            }
        
        # Find latest backup
        backups = sorted(backup_dir.glob("*/jarvis.sql"), reverse=True)
        if not backups:
            return {
                "status": HealthStatus.WARNING,
                "last_backup": None,
                "recommendation": "No backups found. Run: make backup"
            }
        
        latest = backups[0]
        age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
        
        status = HealthStatus.HEALTHY
        if age > timedelta(days=7):
            status = HealthStatus.CRITICAL
        elif age > timedelta(days=3):
            status = HealthStatus.WARNING
        
        return {
            "status": status,
            "last_backup": {
                "file": str(latest),
                "timestamp": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
                "age_hours": round(age.total_seconds() / 3600, 1),
                "size_mb": round(latest.stat().st_size / 1024 / 1024, 2)
            },
            "total_backups": len(backups),
            "recommendation": "Schedule daily backups" if status != HealthStatus.HEALTHY else "All good!"
        }
    except Exception as e:
        return {
            "status": HealthStatus.WARNING,
            "error": str(e),
            "recommendation": "Check backup permissions"
        }

def get_system_resources() -> Dict[str, Any]:
    """Get system-wide resource usage"""
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory
        memory = psutil.virtual_memory()
        
        # Disk
        disk = psutil.disk_usage("/")
        
        return {
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(),
                "status": HealthStatus.from_percentage(cpu_percent, warning=80, critical=95)
            },
            "memory": {
                "used_gb": round(memory.used / 1024**3, 2),
                "total_gb": round(memory.total / 1024**3, 2),
                "percent": memory.percent,
                "status": HealthStatus.from_percentage(memory.percent)
            },
            "disk": {
                "used_gb": round(disk.used / 1024**3, 2),
                "total_gb": round(disk.total / 1024**3, 2),
                "percent": disk.percent,
                "status": HealthStatus.from_percentage(disk.percent)
            }
        }
    except Exception as e:
        return {"status": HealthStatus.WARNING, "error": str(e)}

def get_enhanced_health_status() -> Dict[str, Any]:
    """Get comprehensive health status with actionable metrics"""
    start_time = time.time()
    
    health = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
        "system": get_system_resources()
    }
    
    # Run all health checks
    health["checks"]["qdrant"] = get_qdrant_health()
    health["checks"]["postgres"] = get_postgres_health()
    health["checks"]["docker"] = get_docker_stats()
    health["checks"]["backup"] = get_backup_status()
    
    # Overall status
    all_statuses = []
    for check in health["checks"].values():
        if isinstance(check, dict) and "status" in check:
            all_statuses.append(check["status"])
    
    if HealthStatus.CRITICAL in all_statuses:
        health["overall_status"] = HealthStatus.CRITICAL
    elif HealthStatus.WARNING in all_statuses:
        health["overall_status"] = HealthStatus.WARNING
    else:
        health["overall_status"] = HealthStatus.HEALTHY
    
    # Summary
    health["summary"] = {
        "healthy": sum(1 for s in all_statuses if s == HealthStatus.HEALTHY),
        "warning": sum(1 for s in all_statuses if s == HealthStatus.WARNING),
        "critical": sum(1 for s in all_statuses if s == HealthStatus.CRITICAL)
    }
    
    # Total check duration
    health["check_duration_ms"] = round((time.time() - start_time) * 1000, 2)
    
    return health