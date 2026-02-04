"""
Simplified health checks without psutil dependency.
Falls back to this if psutil installation fails.
"""
import os
import time
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

def run_command(cmd: list[str]) -> Optional[str]:
    """Run a command safely (shell=False) and return output."""
    try:
        result = subprocess.run(cmd, shell=False, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, ValueError):
        return None
    return None

def get_simple_health_status() -> Dict[str, Any]:
    """Get health status without psutil."""
    start_time = time.time()
    health_data = {
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "qdrant": {"status": "unknown"},
        "postgres": {"status": "unknown"},
        "ssh": {"status": "unknown"},
        "n8n": {"status": "unknown"},
        "telegram": {"status": "unknown"},
        "docker": {},
        "system": {
            "memory_usage_percent": 0,
            "cpu_usage_percent": 0
        },
        "backup": {
            "status": "unknown",
            "last_backup": None,
            "next_due": None
        }
    }
    
    # Check Qdrant
    try:
        from .qdrant_client import get_client as get_qdrant_client
        start = time.time()
        client = get_qdrant_client()
        collections = client.get_collections().collections
        latency = int((time.time() - start) * 1000)
        
        health_data["qdrant"] = {
            "status": "healthy",
            "collections": {},
            "latency_ms": latency
        }
        
        for collection in collections:
            info = client.get_collection(collection.name)
            health_data["qdrant"]["collections"][collection.name] = {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count
            }
    except Exception as e:
        health_data["qdrant"]["status"] = "unhealthy"
        health_data["qdrant"]["error"] = str(e)
    
    # Check PostgreSQL
    try:
        from .connector_state import get_db_connection
        start = time.time()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM data_sources")
        cursor.close()
        conn.close()
        latency = int((time.time() - start) * 1000)
        
        health_data["postgres"] = {
            "status": "healthy",
            "latency_ms": latency
        }
    except Exception as e:
        health_data["postgres"]["status"] = "unhealthy"
        health_data["postgres"]["error"] = str(e)
    
    # Check SSH (if configured)
    ssh_host = os.getenv("SSH_HOST")
    if ssh_host:
        # Simple ping test
        result = run_command(["ping", "-c", "1", "-W", "2", ssh_host])
        health_data["ssh"]["status"] = "healthy" if result else "unhealthy"
    
    # Check n8n
    try:
        import requests
        n8n_url = os.getenv("N8N_URL", "http://n8n:5678")
        response = requests.get(f"{n8n_url}/rest/workflows", 
                               headers={"X-N8N-API-KEY": os.getenv("N8N_API_KEY", "")},
                               timeout=5)
        workflows = response.json()
        active_count = sum(1 for w in workflows if w.get("active"))
        
        health_data["n8n"] = {
            "status": "healthy",
            "workflows": len(workflows),
            "active_workflows": active_count
        }
    except (requests.RequestException, ValueError) as e:
        health_data["n8n"]["status"] = "error"
        health_data["n8n"]["error"] = str(e)
    
    # Check Telegram bot
    try:
        from . import telegram_notifier
        if hasattr(telegram_notifier, 'bot') and telegram_notifier.bot:
            health_data["telegram"]["status"] = "healthy"
        else:
            health_data["telegram"]["status"] = "not_configured"
    except Exception as e:
        health_data["telegram"]["status"] = "error"
        health_data["telegram"]["error"] = str(e)
    
    # Simple backup check
    backup_dir = "/volume1/BRAIN_BACKUP"
    if os.path.exists(backup_dir):
        try:
            # Get latest backup time
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("jarvis_backup_")])
            if backups:
                latest = backups[-1]
                # Extract date from filename (jarvis_backup_YYYYMMDD_HHMMSS.tar.gz)
                date_str = latest.replace("jarvis_backup_", "").split(".")[0]
                health_data["backup"]["last_backup"] = date_str
                health_data["backup"]["status"] = "healthy"
        except (OSError, ValueError) as e:
            health_data["backup"]["status"] = "error"
            health_data["backup"]["error"] = str(e)
    
    # Calculate total duration
    health_data["check_duration_ms"] = int((time.time() - start_time) * 1000)
    
    return health_data