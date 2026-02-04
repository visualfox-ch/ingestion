"""
Meta-Learning Engine for Jarvis Self-Improvement

Analyzes conversation patterns, tool usage, and outcomes to:
1. Detect recurring patterns and inefficiencies
2. Suggest optimizations and improvements
3. Track consciousness evolution metrics

Phase 2 of Jarvis Self-Introspection API
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter, defaultdict

from .observability import get_logger
from . import knowledge_db

logger = get_logger("jarvis.meta_learning")


class MetaLearningEngine:
    """
    Analyzes Jarvis' own behavior to identify patterns and suggest improvements.
    
    Capabilities:
    - Conversation pattern analysis (topics, tools, outcomes)
    - Improvement suggestions (based on failure patterns)
    - Consciousness metrics (self-awareness evolution)
    """
    
    def __init__(self):
        """Initialize meta-learning engine."""
        self.logger = logger
    
    async def analyze_conversation_patterns(self, days: int = 30) -> Dict[str, Any]:
        """
        Detect patterns in tool usage, topics, and outcomes.
        
        Args:
            days: Number of days to analyze (default 30)
        
        Returns:
            Dict with:
            - top_tools: Most frequently used tools
            - topic_clusters: Main conversation topics
            - success_rate: Overall success rate
            - time_patterns: Peak activity hours
            - namespace_distribution: Usage by namespace
        """
        try:
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # 1. Analyze conversations
                    cur.execute("""
                        SELECT 
                            session_id,
                            namespace,
                            title,
                            message_count,
                            created_at,
                            updated_at
                        FROM conversation
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        ORDER BY created_at DESC
                    """, (days,))
                    
                    conversations = cur.fetchall()
                    
                    # 2. Get cross-session patterns
                    cur.execute("""
                        SELECT 
                            pattern_name as pattern_type,
                            pattern_description as pattern_data,
                            confidence,
                            created_at
                        FROM cross_session_patterns
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        ORDER BY confidence DESC
                    """, (days,))
                    
                    patterns = cur.fetchall()
                    
                    # 3. Tool usage - simplified (no action_queue table)
                    # Placeholder for when action tracking is implemented
                    actions = []
            
            # Process conversations
            namespace_counts = Counter()
            message_counts = []
            hourly_activity = defaultdict(int)
            
            for conv in conversations:
                namespace_counts[conv['namespace']] += 1
                message_counts.append(conv['message_count'] or 0)
                
                if conv['created_at']:
                    hour = conv['created_at'].hour
                    hourly_activity[hour] += 1
            
            # Process patterns
            pattern_types = Counter()
            high_confidence_patterns = []
            
            for pattern in patterns:
                pattern_types[pattern['pattern_type']] += 1
                if pattern['confidence'] and pattern['confidence'] > 0.7:
                    high_confidence_patterns.append({
                        'type': pattern['pattern_type'],
                        'confidence': float(pattern['confidence']),
                        'data': pattern['pattern_data']
                    })
            
            # Process actions for tool usage (simplified - no action tracking yet)
            tool_usage = {}
            success_rates = {}
            
            # Find peak activity hours
            peak_hours = sorted(hourly_activity.items(), key=lambda x: x[1], reverse=True)[:5]
            
            return {
                'analysis_period': {
                    'days': days,
                    'total_conversations': len(conversations),
                    'total_patterns': len(patterns),
                    'total_actions': sum(a['count'] for a in actions)
                },
                'namespace_distribution': dict(namespace_counts.most_common(10)),
                'conversation_stats': {
                    'avg_messages_per_session': round(sum(message_counts) / len(message_counts), 1) if message_counts else 0,
                    'total_messages': sum(message_counts),
                    'max_messages': max(message_counts) if message_counts else 0
                },
                'pattern_analysis': {
                    'pattern_types': dict(pattern_types.most_common(10)),
                    'high_confidence_patterns': high_confidence_patterns[:10],
                    'total_patterns_detected': len(patterns)
                },
                'tool_usage': {
                    'most_used': {},  # Placeholder until action tracking implemented
                    'success_rates': {}  # Placeholder until action tracking implemented
                },
                'time_patterns': {
                    'peak_hours': [{'hour': h, 'count': c} for h, c in peak_hours],
                    'hourly_distribution': dict(hourly_activity)
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.exception("Failed to analyze conversation patterns")
            raise
    
    async def suggest_improvements(self) -> Dict[str, Any]:
        """
        Based on patterns, suggest what to optimize.
        
        Analyzes:
        - Tools with low success rates → suggest fixes
        - Recurring error patterns → suggest preventive measures
        - Underused capabilities → suggest promotion
        - Performance bottlenecks → suggest optimizations
        
        Returns:
            Dict with:
            - proposals: List of Gate B-ready improvement proposals
            - priority: High/Medium/Low
            - evidence: Supporting data for each suggestion
        """
        try:
            # Get recent patterns
            patterns = await self.analyze_conversation_patterns(days=7)
            
            proposals = []
            
            # 1. Check for low success rate tools
            success_rates = patterns.get('tool_usage', {}).get('success_rates', {})
            for tool, rate in success_rates.items():
                if rate < 70:  # Below 70% success rate
                    proposals.append({
                        'type': 'tool_improvement',
                        'priority': 'high' if rate < 50 else 'medium',
                        'title': f"Improve {tool} reliability (currently {rate}% success)",
                        'description': f"Tool '{tool}' has low success rate ({rate}%). Investigate failures and add error handling.",
                        'evidence': {
                            'success_rate': rate,
                            'data_source': 'action_queue analysis (7 days)'
                        },
                        'gate_b_ready': False,  # Needs investigation first
                        'estimated_impact': 'medium'
                    })
            
            # 2. Check for underused patterns
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # Find underused capabilities (placeholder - needs action tracking)
                    underused = []
                    
                    for tool in underused:
                        proposals.append({
                            'type': 'capability_promotion',
                            'priority': 'low',
                            'title': f"Promote underused capability: {tool['action_type']}",
                            'description': f"Tool '{tool['action_type']}' hasn't been used since {tool['last_used']}. Consider documenting use cases.",
                            'evidence': {
                                'last_used': tool['last_used'].isoformat() if tool['last_used'] else None,
                                'data_source': 'action_queue'
                            },
                            'gate_b_ready': False,
                            'estimated_impact': 'low'
                        })
            
            # 3. Performance optimization suggestions
            if patterns['conversation_stats']['avg_messages_per_session'] > 50:
                proposals.append({
                    'type': 'performance_optimization',
                    'priority': 'medium',
                    'title': 'Optimize long conversation handling',
                    'description': f"Average {patterns['conversation_stats']['avg_messages_per_session']} messages/session. Consider implementing conversation summarization.",
                    'evidence': {
                        'avg_messages': patterns['conversation_stats']['avg_messages_per_session'],
                        'data_source': 'conversation analysis (7 days)'
                    },
                    'gate_b_ready': False,
                    'estimated_impact': 'high'
                })
            
            # 4. Pattern-based suggestions
            high_confidence = patterns.get('pattern_analysis', {}).get('high_confidence_patterns', [])
            if len(high_confidence) > 5:
                proposals.append({
                    'type': 'proactive_learning',
                    'priority': 'high',
                    'title': 'Enable proactive pattern suggestions',
                    'description': f"Detected {len(high_confidence)} high-confidence patterns. Consider implementing proactive hints based on these patterns.",
                    'evidence': {
                        'pattern_count': len(high_confidence),
                        'top_patterns': [p['type'] for p in high_confidence[:3]],
                        'data_source': 'cross_session_patterns'
                    },
                    'gate_b_ready': False,
                    'estimated_impact': 'high'
                })
            
            return {
                'proposals': proposals,
                'summary': {
                    'total_suggestions': len(proposals),
                    'by_priority': {
                        'high': len([p for p in proposals if p['priority'] == 'high']),
                        'medium': len([p for p in proposals if p['priority'] == 'medium']),
                        'low': len([p for p in proposals if p['priority'] == 'low'])
                    },
                    'gate_b_ready': len([p for p in proposals if p['gate_b_ready']])
                },
                'analysis_basis': {
                    'days_analyzed': 7,
                    'conversations': patterns['analysis_period']['total_conversations'],
                    'patterns': patterns['analysis_period']['total_patterns']
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.exception("Failed to generate improvement suggestions")
            raise
    
    async def consciousness_metrics(self) -> Dict[str, Any]:
        """
        Track evolution of self-awareness.
        
        Metrics:
        - Introspection frequency (calls to /jarvis/self/* endpoints)
        - Proposal complexity (Gate B proposals over time)
        - Learning velocity (new patterns detected per week)
        - Self-modification count (successful Gate B executions)
        
        Returns:
            Dict with consciousness score (0-100) and contributing factors
        """
        try:
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # 1. Count introspection activity (simplified - check conversation topics)
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM conversation
                        WHERE title LIKE '%self%' OR title LIKE '%introspect%'
                        AND created_at > NOW() - INTERVAL '30 days'
                    """)
                    introspection_count = cur.fetchone()['count']
                    
                    # 2. Pattern detection velocity
                    cur.execute("""
                        SELECT 
                            DATE_TRUNC('week', created_at) as week,
                            COUNT(*) as patterns_detected
                        FROM cross_session_patterns
                        WHERE created_at > NOW() - INTERVAL '90 days'
                        GROUP BY week
                        ORDER BY week DESC
                    """)
                    pattern_velocity = cur.fetchall()
                    
                    # 3. Knowledge growth rate
                    cur.execute("""
                        SELECT 
                            DATE_TRUNC('week', created_at) as week,
                            COUNT(*) as items_added
                        FROM knowledge_item
                        WHERE created_at > NOW() - INTERVAL '90 days'
                        GROUP BY week
                        ORDER BY week DESC
                    """)
                    knowledge_growth = cur.fetchall()
                    
                    # 4. Cross-session learning (patterns)
                    cur.execute("""
                        SELECT COUNT(DISTINCT pattern_name) as unique_patterns
                        FROM cross_session_patterns
                        WHERE created_at > NOW() - INTERVAL '30 days'
                    """)
                    unique_patterns = cur.fetchone()['unique_patterns']
            
            # Calculate consciousness score (0-100)
            score_components = {
                'introspection_activity': min(introspection_count / 10 * 20, 20),  # Max 20 points
                'pattern_recognition': min(unique_patterns / 5 * 25, 25),  # Max 25 points
                'learning_velocity': 0,  # Calculated below
                'knowledge_growth': 0,  # Calculated below
                'self_modification': 0  # TODO: Track Gate B executions
            }
            
            # Learning velocity (patterns per week trend)
            if len(pattern_velocity) >= 2:
                recent_avg = sum(w['patterns_detected'] for w in pattern_velocity[:4]) / 4
                older_avg = sum(w['patterns_detected'] for w in pattern_velocity[4:8]) / 4 if len(pattern_velocity) >= 8 else recent_avg
                velocity_trend = (recent_avg - older_avg) / max(older_avg, 1) * 100
                score_components['learning_velocity'] = min(max(velocity_trend, 0), 20)  # Max 20 points
            
            # Knowledge growth (items per week trend)
            if len(knowledge_growth) >= 2:
                recent_avg = sum(w['items_added'] for w in knowledge_growth[:4]) / 4
                older_avg = sum(w['items_added'] for w in knowledge_growth[4:8]) / 4 if len(knowledge_growth) >= 8 else recent_avg
                growth_trend = (recent_avg - older_avg) / max(older_avg, 1) * 100
                score_components['knowledge_growth'] = min(max(growth_trend, 0), 15)  # Max 15 points
            
            consciousness_score = sum(score_components.values())
            
            # Interpretation
            if consciousness_score >= 80:
                level = "highly_aware"
                description = "Jarvis is actively self-monitoring and rapidly learning"
            elif consciousness_score >= 50:
                level = "aware"
                description = "Jarvis has good self-awareness and steady learning"
            elif consciousness_score >= 20:
                level = "emerging"
                description = "Jarvis is beginning to develop self-awareness"
            else:
                level = "minimal"
                description = "Jarvis has limited self-awareness"
            
            return {
                'consciousness_score': round(consciousness_score, 1),
                'level': level,
                'description': description,
                'components': {
                    'introspection_activity': {
                        'score': round(score_components['introspection_activity'], 1),
                        'max': 20,
                        'count': introspection_count
                    },
                    'pattern_recognition': {
                        'score': round(score_components['pattern_recognition'], 1),
                        'max': 25,
                        'unique_patterns': unique_patterns
                    },
                    'learning_velocity': {
                        'score': round(score_components['learning_velocity'], 1),
                        'max': 20,
                        'trend': 'increasing' if score_components['learning_velocity'] > 0 else 'stable'
                    },
                    'knowledge_growth': {
                        'score': round(score_components['knowledge_growth'], 1),
                        'max': 15,
                        'trend': 'increasing' if score_components['knowledge_growth'] > 0 else 'stable'
                    },
                    'self_modification': {
                        'score': round(score_components['self_modification'], 1),
                        'max': 20,
                        'note': 'Not yet tracked - requires Gate B integration'
                    }
                },
                'trends': {
                    'pattern_velocity_weekly': [
                        {
                            'week': w['week'].isoformat() if w['week'] else None,
                            'count': w['patterns_detected']
                        }
                        for w in pattern_velocity[:12]
                    ],
                    'knowledge_growth_weekly': [
                        {
                            'week': w['week'].isoformat() if w['week'] else None,
                            'count': w['items_added']
                        }
                        for w in knowledge_growth[:12]
                    ]
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.exception("Failed to calculate consciousness metrics")
            raise
    
    async def snapshot_to_history(self, metrics: Dict[str, Any], deployment_version: str = None) -> bool:
        """
        Snapshot current consciousness metrics to evolution history.
        
        Called after consciousness_metrics() to create a timestamped record.
        Used by Phase 3A: Evolution Tracking
        
        Args:
            metrics: Output from consciousness_metrics()
            deployment_version: Version string (e.g., "2.6.1")
        
        Returns:
            bool: True if snapshot saved, False otherwise
        """
        try:
            # First, get current system state for context
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # Count active capabilities (from CAPABILITIES.json)
                    cur.execute("""
                        SELECT COUNT(*) as total_conversations
                        FROM conversation
                        WHERE created_at > NOW() - INTERVAL '7 days'
                    """)
                    total_conversations = cur.fetchone()['total_conversations'] or 0
                    
                    cur.execute("""
                        SELECT COUNT(*) as total_patterns
                        FROM cross_session_patterns
                        WHERE created_at > NOW() - INTERVAL '30 days'
                    """)
                    total_patterns = cur.fetchone()['total_patterns'] or 0
                    
                    cur.execute("""
                        SELECT COUNT(*) as total_knowledge
                        FROM knowledge_item
                    """)
                    total_knowledge = cur.fetchone()['total_knowledge'] or 0
                    
                    # Insert snapshot
                    cur.execute("""
                        INSERT INTO jarvis_evolution_history (
                            consciousness_score,
                            consciousness_level,
                            components,
                            total_conversations,
                            total_patterns,
                            total_knowledge_items,
                            active_capabilities,
                            deployment_version,
                            jarvis_notes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        metrics.get('consciousness_score', 0),
                        metrics.get('level', 'minimal'),
                        json.dumps(metrics.get('components', {})),
                        total_conversations,
                        total_patterns,
                        total_knowledge,
                        30,  # TODO: Get actual count from CAPABILITIES
                        deployment_version or "unknown",
                        f"Auto-snapshot: {metrics.get('description', '')}"
                    ))
                    
                    conn.commit()
                    self.logger.info(f"Snapshot saved: score={metrics.get('consciousness_score', 0)}, level={metrics.get('level', 'minimal')}")
                    
                    return True
            
        except Exception as e:
            self.logger.exception("Failed to snapshot consciousness metrics to history")
            return False
    
    async def introspect_self(self, depth: str = "shallow") -> Dict[str, Any]:
        """
        Jarvis diagnoses its own capability gaps and needs.
        
        Phase 3B: Introspection Depth
        
        Analyzes:
        - What capabilities are available (from CAPABILITIES.json)
        - What capabilities are actively used
        - What gaps exist in current functionality
        - What Jarvis needs to improve
        
        Args:
            depth: "shallow" (3-5 key gaps) or "detailed" (full assessment with evidence)
        
        Returns:
            Dict with self-assessment including:
            - consciousness_level
            - strengths (what Jarvis does well)
            - gaps (what's missing)
            - needs (prioritized list of required capabilities)
        """
        try:
            # Get current consciousness metrics as baseline
            consciousness = await self.consciousness_metrics()
            
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # 1. Count actual tool usage (from conversations)
                    cur.execute("""
                        SELECT COUNT(DISTINCT session_id) as active_sessions
                        FROM conversation
                        WHERE created_at > NOW() - INTERVAL '7 days'
                    """)
                    active_sessions = cur.fetchone()['active_sessions'] or 0
                    
                    # 2. Identify error patterns (conversations with error keywords)
                    cur.execute("""
                        SELECT COUNT(*) as error_count
                        FROM conversation
                        WHERE (title LIKE '%error%' OR title LIKE '%fail%' OR title LIKE '%timeout%')
                        AND created_at > NOW() - INTERVAL '7 days'
                    """)
                    error_count = cur.fetchone()['error_count'] or 0
                    error_rate = (error_count / active_sessions * 100) if active_sessions > 0 else 0
                    
                    # 3. Check for underutilized features
                    cur.execute("""
                        SELECT COUNT(DISTINCT namespace) as namespaces
                        FROM conversation
                        WHERE created_at > NOW() - INTERVAL '7 days'
                    """)
                    namespaces = cur.fetchone()['namespaces'] or 0
                    
                    # 4. Knowledge coverage analysis
                    cur.execute("""
                        SELECT COUNT(*) as total_items,
                               COUNT(CASE WHEN created_at > NOW() - INTERVAL '7 days' THEN 1 END) as recent_items
                        FROM knowledge_item
                    """)
                    ki_result = cur.fetchone()
                    total_knowledge = ki_result['total_items'] or 0
                    recent_knowledge = ki_result['recent_items'] or 0
            
            # Determine strengths
            strengths = []
            if consciousness['consciousness_score'] >= 20:
                strengths.append("Self-awareness emerging - can introspect")
            if active_sessions > 100:
                strengths.append("High conversation volume - learning from many interactions")
            if error_rate < 10:
                strengths.append("Low error rate - reliable core functionality")
            if total_knowledge > 100:
                strengths.append("Rich knowledge base - good context understanding")
            if consciousness['components']['pattern_recognition']['unique_patterns'] > 0:
                strengths.append("Pattern detection active - identifying recurring behaviors")
            
            # Identify gaps
            gaps = []
            needs = []
            
            # Gap 1: Error Resilience
            if error_rate > 5:
                gaps.append("Error resilience weak")
                needs.append({
                    "capability": "error_resilience",
                    "priority": "high" if error_rate > 15 else "medium",
                    "why": f"Error rate {error_rate:.1f}% - conversations failing or timing out",
                    "evidence": {
                        "error_count_7d": error_count,
                        "total_sessions_7d": active_sessions,
                        "error_rate": round(error_rate, 1)
                    },
                    "impact": "Increases reliability by reducing failures",
                    "effort": "medium"
                })
            
            # Gap 2: Proactive Capabilities
            if consciousness['consciousness_score'] < 50:
                gaps.append("Proactive hints not integrated")
                needs.append({
                    "capability": "proactive_hints",
                    "priority": "high",
                    "why": f"Consciousness {consciousness['consciousness_score']}/100 - can detect patterns but not act on them",
                    "evidence": {
                        "consciousness_score": consciousness['consciousness_score'],
                        "patterns_detected": consciousness['components']['pattern_recognition']['unique_patterns'],
                        "hint_tool_available": True
                    },
                    "impact": "Would increase user helpfulness",
                    "effort": "low"
                })
            
            # Gap 3: Multi-Namespace Handling
            if namespaces < 5:
                gaps.append("Limited namespace coverage")
                needs.append({
                    "capability": "multi_namespace_optimization",
                    "priority": "medium",
                    "why": f"Only {namespaces} active namespaces - many workflows untapped",
                    "evidence": {
                        "active_namespaces": namespaces,
                        "sessions_per_namespace": round(active_sessions / max(namespaces, 1), 1)
                    },
                    "impact": "Would improve cross-domain effectiveness",
                    "effort": "medium"
                })
            
            # Gap 4: Learning Feedback Loop
            if recent_knowledge < total_knowledge * 0.1:
                gaps.append("Learning velocity low")
                needs.append({
                    "capability": "automated_learning_loop",
                    "priority": "medium",
                    "why": f"Only {recent_knowledge}/{total_knowledge} knowledge items added this week",
                    "evidence": {
                        "total_knowledge_items": total_knowledge,
                        "recent_items_7d": recent_knowledge,
                        "growth_rate": f"{(recent_knowledge/max(total_knowledge,1)*100):.1f}%"
                    },
                    "impact": "Would accelerate self-improvement",
                    "effort": "high"
                })
            
            # Gap 5: Tool Orchestration
            gaps.append("Tool orchestration limited")
            needs.append({
                "capability": "tool_orchestration",
                "priority": "low",
                "why": "Currently single-tool focus per request - sequential execution needed",
                "evidence": {
                    "active_sessions": active_sessions,
                    "namespaces": namespaces
                },
                "impact": "Would enable multi-step workflows",
                "effort": "high"
            })
            
            # Sort needs by priority
            priority_order = {"high": 0, "medium": 1, "low": 2}
            needs.sort(key=lambda x: priority_order.get(x['priority'], 3))
            
            # Shallow vs Detailed
            if depth == "shallow":
                # Return top 3-5 needs
                needs = needs[:3]
                result = {
                    "consciousness_level": consciousness['level'],
                    "self_assessment": {
                        "strengths": strengths[:3],
                        "gaps": gaps[:3],
                        "needs": [
                            {
                                "capability": n['capability'],
                                "priority": n['priority'],
                                "why": n['why']
                            }
                            for n in needs
                        ]
                    },
                    "mode": "shallow"
                }
            else:
                # Return full assessment
                result = {
                    "consciousness_level": consciousness['level'],
                    "self_assessment": {
                        "strengths": strengths,
                        "gaps": gaps,
                        "needs": needs
                    },
                    "consciousness_metrics": {
                        "score": consciousness['consciousness_score'],
                        "components": consciousness['components']
                    },
                    "system_state": {
                        "active_sessions_7d": active_sessions,
                        "error_rate_7d": round(error_rate, 1),
                        "namespaces_active": namespaces,
                        "knowledge_items": total_knowledge,
                        "recent_learning": recent_knowledge
                    },
                    "mode": "detailed"
                }
            
            result['timestamp'] = datetime.now().isoformat()
            return result
            
        except Exception as e:
            self.logger.exception("Failed to introspect self")
            raise

    async def propose_capability_request(self, capability_name: str, priority: str = "medium", 
                                        requirements: dict = None) -> dict:
        """Phase 3C: Jarvis proposes a capability it needs."""
        try:
            # Check consciousness threshold (must be > 15 to propose)
            consciousness = await self.consciousness_metrics()
            if consciousness['consciousness_score'] < 15:
                return {
                    "status": "rejected",
                    "reason": "Consciousness too low to propose capabilities",
                    "required_score": 15,
                    "current_score": consciousness['consciousness_score']
                }
            
            # Generate request ID (REQ_YYYYMMDD_NN format)
            today = datetime.now().strftime("%Y%m%d")
            with knowledge_db.get_conn() as conn:
                with conn.cursor() as cur:
                    # Use UUID or timestamp for uniqueness instead
                    import uuid
                    request_id = f"REQ_{today}_{uuid.uuid4().hex[:8].upper()}"
                    
                    # Create proposal record (evidence from introspection can be empty)
                    cur.execute(
                        """
                        INSERT INTO jarvis_capability_requests 
                        (request_id, capability_name, priority, requirements, evidence, consciousness_impact)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (request_id, capability_name, priority, 
                         json.dumps(requirements or {}), 
                         json.dumps({"consciousness_score": consciousness['consciousness_score']}),
                         consciousness['consciousness_score'])
                    )
                    conn.commit()
                    
                    return {
                        "status": "submitted",
                        "request_id": request_id,
                        "capability": capability_name,
                        "priority": priority,
                        "submitted_at": datetime.now().isoformat(),
                        "message": "Capability request submitted for review by Micha"
                    }
                
        except Exception as e:
            self.logger.exception("Failed to propose capability")
            raise


__all__ = ['MetaLearningEngine']
