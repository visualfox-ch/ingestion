"""
Jarvis Optimization Coach - Intelligent System Suggestions
Phase 16.2: Metrics-Driven Coaching for System Optimization

Integrates optimization recommendations into the coaching workflow.
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import asdict
import logging

from .metrics_analyzer import MetricsAnalyzer, SeverityLevel, CategoryType, Recommendation
from .observability import get_logger

logger = get_logger("jarvis.optimization_coach")


class OptimizationCoach:
    """
    Coach that uses metrics to provide system optimization suggestions.
    
    Analyzes Jarvis performance and generates coaching recommendations
    for continuous improvement.
    """
    
    def __init__(self, analyzer: Optional[MetricsAnalyzer] = None):
        self.analyzer = analyzer or MetricsAnalyzer()
        self.last_analysis_time: Optional[datetime] = None
        self.analysis_interval_minutes = 30  # Run analysis every 30 minutes
        
    async def get_optimization_guidance(self, category: Optional[str] = None) -> Dict[str, Any]:
        """
        Get optimization coaching guidance for Jarvis system.
        
        Can filter by category: performance, reliability, resource, quality, learning
        """
        recommendations = await self.analyzer.analyze_all()
        
        if not recommendations:
            return {
                "status": "optimized",
                "message": "All systems operating within SLO targets. Keep monitoring!",
                "recommendations": [],
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Filter by category if specified
        if category:
            recommendations = [r for r in recommendations if r.category.value == category]
        
        # Group by severity
        critical = [r for r in recommendations if r.severity == SeverityLevel.CRITICAL]
        warnings = [r for r in recommendations if r.severity == SeverityLevel.WARNING]
        info = [r for r in recommendations if r.severity == SeverityLevel.INFO]
        
        return {
            "status": "needs_attention" if critical else ("warning" if warnings else "info"),
            "critical_issues": len(critical),
            "warnings": len(warnings),
            "informational": len(info),
            "recommendations": [asdict(r) for r in recommendations],
            "timestamp": datetime.utcnow().isoformat(),
            "coaching_focus": self._generate_coaching_focus(critical, warnings, info)
        }
    
    def _generate_coaching_focus(self, critical: List, warnings: List, info: List) -> Dict[str, str]:
        """Generate human-readable coaching focus points"""
        focus = {}
        
        if critical:
            focus["immediate_action"] = f"Address {len(critical)} critical issue(s): " + ", ".join(r.title for r in critical[:3])
        
        if warnings:
            focus["near_term"] = f"Monitor {len(warnings)} warning(s) in next 24h"
        
        if info:
            focus["optimization_ideas"] = f"{len(info)} optimization suggestions available for long-term planning"
        
        if not focus:
            focus["status"] = "All systems healthy - continue monitoring"
        
        return focus
    
    async def get_performance_coaching(self) -> Dict[str, Any]:
        """Get specific coaching for performance optimization"""
        recommendations = await self.analyzer.analyze_latency()
        
        if not recommendations:
            return {
                "status": "optimal",
                "message": "API response times meet SLO targets",
                "current_p99": "< 2.5s",
                "current_p95": "< 1.0s"
            }
        
        coaching = {
            "status": "needs_optimization",
            "performance_issues": []
        }
        
        for rec in recommendations:
            coaching["performance_issues"].append({
                "title": rec.title,
                "severity": rec.severity.value,
                "current_value": f"{rec.current_value:.2f}s (P{int(99 if rec.threshold == 2.5 else 95)})",
                "action_plan": rec.action,
                "impact": rec.impact,
                "effort": rec.effort
            })
        
        return coaching
    
    async def get_reliability_coaching(self) -> Dict[str, Any]:
        """Get specific coaching for reliability optimization"""
        recommendations = await self.analyzer.analyze_reliability()
        
        if not recommendations:
            return {
                "status": "robust",
                "message": "Error rates within SLO targets",
                "error_rate": "< 1%",
                "availability": "99%+"
            }
        
        coaching = {
            "status": "issues_detected",
            "reliability_issues": []
        }
        
        for rec in recommendations:
            coaching["reliability_issues"].append({
                "title": rec.title,
                "severity": rec.severity.value,
                "current_error_rate": f"{rec.current_value:.2f}%",
                "slo_threshold": f"< {rec.threshold:.1f}%",
                "action_plan": rec.action,
                "budget_impact": rec.impact,
                "fix_effort": rec.effort
            })
        
        return coaching
    
    async def get_resource_coaching(self) -> Dict[str, Any]:
        """Get specific coaching for resource optimization"""
        recommendations = await self.analyzer.analyze_resources()
        
        if not recommendations:
            return {
                "status": "efficient",
                "message": "Resource usage is healthy",
                "memory_usage": "< 500MB",
                "recommendation": "Continue monitoring for growth patterns"
            }
        
        coaching = {
            "status": "optimization_available",
            "resource_issues": []
        }
        
        for rec in recommendations:
            memory_mb = rec.current_value / 1024 / 1024 if rec.current_value > 1000 else rec.current_value
            coaching["resource_issues"].append({
                "title": rec.title,
                "severity": rec.severity.value,
                "current_memory": f"{memory_mb:.0f}MB",
                "threshold": f"{rec.threshold / 1024 / 1024:.0f}MB",
                "optimization_steps": rec.action,
                "benefit": rec.impact,
                "complexity": rec.effort
            })
        
        return coaching
    
    async def get_learning_coaching(self) -> Dict[str, Any]:
        """Get specific coaching for preference learning optimization"""
        recommendations = await self.analyzer.analyze_quality()
        recommendations.extend(await self.analyzer.analyze_learning_curve())
        
        if not recommendations:
            return {
                "status": "learning_healthy",
                "message": "Preference learning progressing normally",
                "confidence_level": "Building...",
                "recommendation": "Continue gathering user preference data"
            }
        
        coaching = {
            "status": "learning_insights_available",
            "learning_recommendations": []
        }
        
        for rec in recommendations:
            coaching["learning_recommendations"].append({
                "title": rec.title,
                "severity": rec.severity.value,
                "current_confidence": f"{rec.current_value:.1%}",
                "improvement_strategy": rec.action,
                "expected_benefit": rec.impact,
                "implementation_effort": rec.effort
            })
        
        return coaching
    
    async def should_run_analysis(self) -> bool:
        """Check if enough time has passed since last analysis"""
        if not self.last_analysis_time:
            return True
        
        elapsed_minutes = (datetime.utcnow() - self.last_analysis_time).total_seconds() / 60
        return elapsed_minutes >= self.analysis_interval_minutes
    
    async def periodic_coaching_check(self) -> Optional[Dict[str, Any]]:
        """
        Periodic check for coaching recommendations.
        Returns None if not enough time elapsed, otherwise returns coaching data.
        """
        if not await self.should_run_analysis():
            return None
        
        self.last_analysis_time = datetime.utcnow()
        logger.info("Running periodic optimization coaching analysis")
        
        return await self.get_optimization_guidance()


# Singleton instance
_coach_instance: Optional[OptimizationCoach] = None


def get_optimization_coach() -> OptimizationCoach:
    """Get or create optimization coach instance"""
    global _coach_instance
    if _coach_instance is None:
        _coach_instance = OptimizationCoach()
    return _coach_instance
