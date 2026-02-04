"""
Health Alerts via Telegram Integration

Sends proactive system health notifications to Telegram:
- Daily health summaries (08:00)
- Anomaly alerts (real-time)
- Performance degradation warnings
- Resource usage alerts
- Recovery notifications

Author: GitHub Copilot + Jarvis
Created: 2026-02-04
"""

import os
import asyncio
from datetime import datetime, time as dtime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json

from .observability import get_logger

logger = get_logger("jarvis.health_alerts_telegram")


@dataclass
class HealthAlert:
    """Health alert message."""
    title: str
    message: str
    severity: str  # "info", "warning", "critical"
    timestamp: str
    metric_name: str
    suggested_action: str


class HealthAlertManager:
    """
    Manages health alerts and sends them via Telegram.
    
    Features:
    - Alert deduplication (don't spam same alert)
    - Severity-based formatting
    - Smart scheduling (daily digest vs. real-time)
    - Alert history tracking
    """
    
    def __init__(self):
        """Initialize health alert manager."""
        self.alert_history: List[HealthAlert] = []
        self.suppressed_alerts: Dict[str, datetime] = {}  # metric_name -> datetime
        self.suppression_ttl_minutes = 30
        self.daily_digest_hour = 8  # 08:00
        
    def should_suppress_alert(self, metric_name: str) -> bool:
        """Check if alert should be suppressed to avoid spam."""
        if metric_name not in self.suppressed_alerts:
            return False
        
        last_alert_time = self.suppressed_alerts[metric_name]
        time_since = (datetime.now() - last_alert_time).total_seconds() / 60
        
        if time_since > self.suppression_ttl_minutes:
            del self.suppressed_alerts[metric_name]
            return False
        
        return True
    
    def mark_alert_sent(self, metric_name: str):
        """Mark alert as sent for suppression tracking."""
        self.suppressed_alerts[metric_name] = datetime.now()
    
    def format_alert_message(self, alert: HealthAlert) -> str:
        """
        Format health alert for Telegram.
        
        Returns:
            Formatted message with emoji and markdown
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨"
        }
        
        emoji = emoji_map.get(alert.severity, "📢")
        
        message = f"{emoji} *{alert.title}*\n\n"
        message += f"{alert.message}\n\n"
        message += f"🔧 *Suggested Action:*\n{alert.suggested_action}\n\n"
        message += f"⏰ {alert.timestamp}"
        
        return message
    
    def format_daily_digest(self, metrics: Dict[str, Any], hints: List[Dict[str, Any]]) -> str:
        """
        Format daily health digest for Telegram.
        
        Returns:
            Formatted digest message
        """
        status = metrics.get("overall_status", "UNKNOWN")
        
        message = f"🌅 *Daily Jarvis Health Report*\n\n"
        message += f"Status: {status}\n\n"
        
        # Add key metrics
        message += "*📊 Key Metrics (24h):*\n"
        message += f"• API Response: {metrics['metrics']['api_response_time_ms']:.0f}ms\n"
        message += f"• Memory Usage: {metrics['metrics']['memory_usage_percent']:.1f}%\n"
        message += f"• CPU Usage: {metrics['metrics']['cpu_usage_percent']:.1f}%\n"
        message += f"• Error Rate: {metrics['metrics']['error_rate_percent']:.2f}%\n"
        message += f"• Containers: {metrics['metrics']['containers_healthy']}/{metrics['metrics']['containers_total']} healthy\n\n"
        
        # Add trends if any
        if metrics.get("trends"):
            message += "*📈 Trends:*\n"
            for trend in metrics["trends"][:3]:  # Top 3 trends
                message += f"• {trend['metric_name']}: {trend['trend']} {trend['change_percent']:.1f}%\n"
            message += "\n"
        
        # Add alerts if any
        critical_hints = [h for h in hints if h.get("severity") == "critical"]
        warning_hints = [h for h in hints if h.get("severity") == "warning"]
        
        if critical_hints or warning_hints:
            message += "*⚠️ Active Alerts:*\n"
            for hint in critical_hints + warning_hints:
                message += f"• {hint['title']}: {hint['message']}\n"
        else:
            message += "✅ *No active alerts - system operating normally*\n"
        
        message += f"\n_Generated: {datetime.now().strftime('%H:%M:%S UTC')}_"
        
        return message
    
    async def send_alert_to_telegram(
        self,
        alert: HealthAlert,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Send alert to Telegram.
        
        Args:
            alert: Alert to send
            chat_id: Telegram chat ID (default from env)
        
        Returns:
            Success status
        """
        if self.should_suppress_alert(alert.metric_name):
            logger.debug(f"Alert suppressed (recent): {alert.metric_name}")
            return True  # Silently suppressed
        
        try:
            from ..telegram_bot import send_message
            
            chat_id = chat_id or os.environ.get("JARVIS_TELEGRAM_CHAT_ID")
            if not chat_id:
                logger.warning("JARVIS_TELEGRAM_CHAT_ID not set")
                return False
            
            message = self.format_alert_message(alert)
            
            # Send message
            success = await send_message(chat_id, message)
            
            if success:
                self.alert_history.append(alert)
                self.mark_alert_sent(alert.metric_name)
                logger.info(f"Alert sent: {alert.title}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False
    
    async def send_daily_digest(
        self,
        metrics: Dict[str, Any],
        hints: List[Dict[str, Any]],
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Send daily health digest to Telegram.
        
        Args:
            metrics: Health metrics
            hints: Health hints
            chat_id: Telegram chat ID (default from env)
        
        Returns:
            Success status
        """
        try:
            from ..telegram_bot import send_message
            
            chat_id = chat_id or os.environ.get("JARVIS_TELEGRAM_CHAT_ID")
            if not chat_id:
                logger.warning("JARVIS_TELEGRAM_CHAT_ID not set")
                return False
            
            message = self.format_daily_digest(metrics, hints)
            
            success = await send_message(chat_id, message)
            
            if success:
                logger.info("Daily health digest sent")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to send daily digest: {e}")
            return False
    
    async def send_critical_alert(
        self,
        title: str,
        message: str,
        action: str,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Send critical alert immediately.
        
        Args:
            title: Alert title
            message: Alert message
            action: Suggested action
            chat_id: Telegram chat ID (default from env)
        
        Returns:
            Success status
        """
        alert = HealthAlert(
            title=title,
            message=message,
            severity="critical",
            timestamp=datetime.now().isoformat(),
            metric_name=title.lower().replace(" ", "_"),
            suggested_action=action
        )
        
        return await self.send_alert_to_telegram(alert, chat_id)


class HealthAlertScheduler:
    """
    Schedules health checks and alerts.
    
    Runs:
    - Continuous health monitoring
    - Daily digest at 08:00
    - Real-time anomaly alerts
    """
    
    def __init__(self, alert_manager: HealthAlertManager):
        """Initialize scheduler."""
        self.alert_manager = alert_manager
        self.check_interval_seconds = 60  # Check every minute
        self.running = False
    
    async def start(self):
        """Start health monitoring loop."""
        self.running = True
        logger.info("Health alert scheduler started")
        
        try:
            while self.running:
                await self.check_health()
                await asyncio.sleep(self.check_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Health alert scheduler cancelled")
        except Exception as e:
            logger.error(f"Health alert scheduler error: {e}")
    
    async def check_health(self):
        """Check system health and send alerts if needed."""
        try:
            from .health_insights import get_health_insights
            from .prometheus_metrics import get_prometheus_client
            
            insights = get_health_insights()
            prometheus = get_prometheus_client()
            
            # Get current metrics
            prometheus_data = prometheus.get_health_summary()
            additional_metrics = {
                "error_rate_percent": prometheus_data["api"]["error_rate"] * 100,
                "requests_per_minute": prometheus_data["api"]["request_rate_per_sec"] * 60,
            }
            
            # Generate health report
            report = insights.get_full_health_report(additional_metrics)
            
            # Check for critical issues
            critical_hints = [h for h in report["proactive_hints"] if h.get("severity") == "critical"]
            
            for hint in critical_hints:
                alert = HealthAlert(
                    title=hint["title"],
                    message=hint["message"],
                    severity="critical",
                    timestamp=datetime.now().isoformat(),
                    metric_name=hint["metric_source"],
                    suggested_action=hint["recommendation"]
                )
                
                await self.alert_manager.send_alert_to_telegram(alert)
            
            # Send daily digest at 08:00
            current_time = datetime.now().time()
            daily_digest_time = dtime(self.alert_manager.daily_digest_hour, 0)
            
            if (current_time.hour == daily_digest_time.hour and 
                current_time.minute < 5):  # Within first 5 minutes of the hour
                await self.alert_manager.send_daily_digest(
                    report,
                    report["proactive_hints"]
                )
            
        except Exception as e:
            logger.error(f"Health check error: {e}")
    
    def stop(self):
        """Stop health monitoring."""
        self.running = False
        logger.info("Health alert scheduler stopped")


# Singleton instances
_alert_manager: Optional[HealthAlertManager] = None
_alert_scheduler: Optional[HealthAlertScheduler] = None


def get_alert_manager() -> HealthAlertManager:
    """Get or create singleton alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = HealthAlertManager()
    return _alert_manager


def get_alert_scheduler() -> HealthAlertScheduler:
    """Get or create singleton alert scheduler."""
    global _alert_scheduler, _alert_manager
    if _alert_scheduler is None:
        _alert_manager = get_alert_manager()
        _alert_scheduler = HealthAlertScheduler(_alert_manager)
    return _alert_scheduler
