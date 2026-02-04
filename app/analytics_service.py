"""
Analytics Service Module

Phase 21: Jarvis Self-Programming - Analytics Tools
Implements conversation pattern analysis, response quality measurement, and knowledge gap detection.

Tools implemented:
1. analyze_conversation_patterns() - Detect topic shifts, tool usage patterns, session characteristics
2. measure_response_quality() - Per-domain quality scores based on user feedback
3. detect_knowledge_gaps() - Find missing people/concepts, suggest ingestion
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import Counter
import json

from .observability import get_logger
from .db_safety import safe_list_query, safe_aggregate_query

logger = get_logger("jarvis.analytics")


# =============================================================================
# 1. CONVERSATION PATTERN ANALYSIS
# =============================================================================

async def analyze_conversation_patterns(
    namespace: str = "work_projektil",
    days: int = 30,
    min_messages: int = 3
) -> Dict[str, Any]:
    """
    Analyze conversation patterns to detect inefficiencies and optimization opportunities.

    Returns:
        - topic_evolution: How conversations shift between topics
        - tool_usage_patterns: Which tools are frequently used together
        - session_characteristics: Length, intensity, time patterns
        - repeated_questions: Questions asked multiple times (knowledge gaps)
        - inefficiency_indicators: Signs of suboptimal interaction patterns
    """
    result = {
        "status": "success",
        "namespace": namespace,
        "period_days": days,
        "analyzed_at": datetime.now().isoformat(),
        "patterns": {}
    }

    try:
        # 1. Session Statistics
        with safe_aggregate_query('conversation') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_sessions,
                    COUNT(DISTINCT DATE(created_at)) as active_days,
                    AVG(message_count) as avg_messages_per_session,
                    MIN(message_count) as min_messages,
                    MAX(message_count) as max_messages,
                    STDDEV(message_count) as stddev_messages,
                    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60) as avg_session_minutes
                FROM conversation
                WHERE namespace = %s
                  AND created_at > NOW() - INTERVAL '%s days'
                  AND message_count >= %s
            """, (namespace, days, min_messages))
            row = cur.fetchone()

            result["patterns"]["session_stats"] = {
                "total_sessions": row['total_sessions'] or 0,
                "active_days": row['active_days'] or 0,
                "avg_messages_per_session": round(float(row['avg_messages_per_session'] or 0), 1),
                "min_messages": row['min_messages'] or 0,
                "max_messages": row['max_messages'] or 0,
                "stddev_messages": round(float(row['stddev_messages'] or 0), 2),
                "avg_session_minutes": round(float(row['avg_session_minutes'] or 0), 1)
            }

        # 2. Time-of-day patterns
        with safe_aggregate_query('conversation') as cur:
            cur.execute("""
                SELECT
                    EXTRACT(HOUR FROM created_at) as hour,
                    COUNT(*) as session_count,
                    AVG(message_count) as avg_messages
                FROM conversation
                WHERE namespace = %s
                  AND created_at > NOW() - INTERVAL '%s days'
                  AND message_count >= %s
                GROUP BY EXTRACT(HOUR FROM created_at)
                ORDER BY session_count DESC
                LIMIT 10
            """, (namespace, days, min_messages))
            rows = cur.fetchall()

            result["patterns"]["time_distribution"] = [
                {
                    "hour": int(row['hour']),
                    "session_count": row['session_count'],
                    "avg_messages": round(float(row['avg_messages'] or 0), 1)
                }
                for row in rows
            ]

        # 3. Message source distribution (telegram, claude_code, api, etc.)
        with safe_aggregate_query('message') as cur:
            cur.execute("""
                SELECT
                    COALESCE(m.source, 'unknown') as source,
                    COUNT(*) as message_count,
                    COUNT(DISTINCT m.session_id) as session_count
                FROM message m
                JOIN conversation c ON m.session_id = c.session_id
                WHERE c.namespace = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                GROUP BY m.source
                ORDER BY message_count DESC
            """, (namespace, days))
            rows = cur.fetchall()

            result["patterns"]["source_distribution"] = [
                {
                    "source": row['source'],
                    "message_count": row['message_count'],
                    "session_count": row['session_count']
                }
                for row in rows
            ]

        # 4. Token usage patterns (cost optimization)
        with safe_aggregate_query('message') as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                    COALESCE(SUM(tokens_out), 0) as total_tokens_out,
                    COALESCE(AVG(tokens_in), 0) as avg_tokens_in,
                    COALESCE(AVG(tokens_out), 0) as avg_tokens_out,
                    COUNT(*) as total_messages
                FROM message m
                JOIN conversation c ON m.session_id = c.session_id
                WHERE c.namespace = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
            """, (namespace, days))
            row = cur.fetchone()

            result["patterns"]["token_usage"] = {
                "total_tokens_in": row['total_tokens_in'] or 0,
                "total_tokens_out": row['total_tokens_out'] or 0,
                "avg_tokens_in": round(float(row['avg_tokens_in'] or 0), 0),
                "avg_tokens_out": round(float(row['avg_tokens_out'] or 0), 0),
                "total_messages": row['total_messages'] or 0,
                "estimated_cost_usd": round(
                    (row['total_tokens_in'] or 0) * 0.000003 +
                    (row['total_tokens_out'] or 0) * 0.000015, 2
                )  # Claude pricing estimate
            }

        # 5. Repeated question detection (potential knowledge gaps)
        with safe_list_query('message', timeout=20) as cur:
            cur.execute("""
                SELECT
                    LOWER(SUBSTRING(m.content, 1, 200)) as content_prefix,
                    COUNT(*) as occurrence_count
                FROM message m
                JOIN conversation c ON m.session_id = c.session_id
                WHERE c.namespace = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.role = 'user'
                  AND LENGTH(m.content) > 20
                GROUP BY LOWER(SUBSTRING(m.content, 1, 200))
                HAVING COUNT(*) >= 2
                ORDER BY occurrence_count DESC
                LIMIT 10
            """, (namespace, days))
            rows = cur.fetchall()

            result["patterns"]["repeated_queries"] = [
                {
                    "query_prefix": row['content_prefix'][:100] + "..." if len(row['content_prefix']) > 100 else row['content_prefix'],
                    "occurrences": row['occurrence_count']
                }
                for row in rows
            ]

        # 6. Calculate inefficiency indicators
        stats = result["patterns"]["session_stats"]
        inefficiencies = []

        if stats["avg_messages_per_session"] > 20:
            inefficiencies.append({
                "type": "long_sessions",
                "description": f"Average {stats['avg_messages_per_session']} messages per session suggests complex or unclear interactions",
                "suggestion": "Consider breaking down complex queries or improving context retrieval"
            })

        if stats["stddev_messages"] > 15:
            inefficiencies.append({
                "type": "inconsistent_sessions",
                "description": f"High variation (stddev={stats['stddev_messages']}) in session length",
                "suggestion": "Review outlier sessions for patterns"
            })

        if len(result["patterns"]["repeated_queries"]) >= 3:
            inefficiencies.append({
                "type": "repeated_questions",
                "description": f"{len(result['patterns']['repeated_queries'])} questions asked multiple times",
                "suggestion": "Consider adding these to knowledge base for faster retrieval"
            })

        result["patterns"]["inefficiency_indicators"] = inefficiencies

        logger.info(f"Conversation patterns analyzed: {namespace}, {days} days, {stats['total_sessions']} sessions")

    except Exception as e:
        logger.error(f"Failed to analyze conversation patterns: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result


# =============================================================================
# 2. RESPONSE QUALITY MEASUREMENT
# =============================================================================

async def measure_response_quality(
    days: int = 30,
    min_feedback: int = 5
) -> Dict[str, Any]:
    """
    Measure response quality based on user feedback (thumbs up/down, ratings).

    Returns:
        - overall_quality_score: Aggregate quality metric (0-100)
        - by_domain: Quality scores per coaching domain
        - by_context_type: Quality scores by interaction type
        - trend: Quality trend over time
        - improvement_areas: Areas needing attention
    """
    result = {
        "status": "success",
        "period_days": days,
        "analyzed_at": datetime.now().isoformat(),
        "quality": {}
    }

    try:
        # 1. Overall feedback statistics
        with safe_aggregate_query('user_feedback') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_feedback,
                    COUNT(*) FILTER (WHERE thumbs_up = true) as thumbs_up_count,
                    COUNT(*) FILTER (WHERE thumbs_up = false) as thumbs_down_count,
                    AVG(rating) FILTER (WHERE rating IS NOT NULL) as avg_rating,
                    COUNT(*) FILTER (WHERE rating IS NOT NULL) as rated_count
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
            """, (days,))
            row = cur.fetchone()

            total = row['total_feedback'] or 0
            thumbs_up = row['thumbs_up_count'] or 0
            thumbs_down = row['thumbs_down_count'] or 0

            # Calculate quality score (0-100)
            if total > 0:
                thumbs_ratio = thumbs_up / max(thumbs_up + thumbs_down, 1)
                rating_score = (float(row['avg_rating'] or 3) / 5) if row['avg_rating'] else 0.6
                quality_score = round((thumbs_ratio * 0.6 + rating_score * 0.4) * 100, 1)
            else:
                quality_score = None

            result["quality"]["overall"] = {
                "quality_score": quality_score,
                "total_feedback": total,
                "thumbs_up": thumbs_up,
                "thumbs_down": thumbs_down,
                "thumbs_ratio": round(thumbs_ratio, 3) if total > 0 else None,
                "avg_rating": round(float(row['avg_rating']), 2) if row['avg_rating'] else None,
                "rated_count": row['rated_count'] or 0
            }

        # 2. Quality by context type (coaching domain)
        with safe_aggregate_query('user_feedback') as cur:
            cur.execute("""
                SELECT
                    COALESCE(context_type, 'general') as domain,
                    COUNT(*) as feedback_count,
                    COUNT(*) FILTER (WHERE thumbs_up = true) as positive,
                    COUNT(*) FILTER (WHERE thumbs_up = false) as negative,
                    AVG(rating) FILTER (WHERE rating IS NOT NULL) as avg_rating
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                GROUP BY context_type
                HAVING COUNT(*) >= %s
                ORDER BY feedback_count DESC
            """, (days, min_feedback))
            rows = cur.fetchall()

            result["quality"]["by_domain"] = []
            for row in rows:
                total = row['positive'] + row['negative']
                if total > 0:
                    score = round((row['positive'] / total) * 100, 1)
                else:
                    score = None

                result["quality"]["by_domain"].append({
                    "domain": row['domain'],
                    "feedback_count": row['feedback_count'],
                    "positive": row['positive'],
                    "negative": row['negative'],
                    "quality_score": score,
                    "avg_rating": round(float(row['avg_rating']), 2) if row['avg_rating'] else None
                })

        # 3. Quality trend (weekly)
        with safe_aggregate_query('user_feedback') as cur:
            cur.execute("""
                SELECT
                    DATE_TRUNC('week', created_at) as week,
                    COUNT(*) as feedback_count,
                    COUNT(*) FILTER (WHERE thumbs_up = true) as positive,
                    COUNT(*) FILTER (WHERE thumbs_up = false) as negative
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                GROUP BY DATE_TRUNC('week', created_at)
                ORDER BY week DESC
                LIMIT 8
            """, (days,))
            rows = cur.fetchall()

            result["quality"]["weekly_trend"] = [
                {
                    "week": row['week'].isoformat() if row['week'] else None,
                    "feedback_count": row['feedback_count'],
                    "positive": row['positive'],
                    "negative": row['negative'],
                    "quality_score": round((row['positive'] / max(row['positive'] + row['negative'], 1)) * 100, 1)
                }
                for row in rows
            ]

        # 4. Common feedback tags (improvement areas)
        with safe_list_query('user_feedback', timeout=15) as cur:
            cur.execute("""
                SELECT
                    unnest(feedback_tags) as tag,
                    COUNT(*) as tag_count,
                    COUNT(*) FILTER (WHERE thumbs_up = false) as negative_count
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND feedback_tags IS NOT NULL
                GROUP BY unnest(feedback_tags)
                ORDER BY negative_count DESC, tag_count DESC
                LIMIT 10
            """, (days,))
            rows = cur.fetchall()

            result["quality"]["feedback_tags"] = [
                {
                    "tag": row['tag'],
                    "count": row['tag_count'],
                    "negative_count": row['negative_count']
                }
                for row in rows
            ]

        # 5. Identify improvement areas
        improvement_areas = []

        overall = result["quality"]["overall"]
        if overall["quality_score"] and overall["quality_score"] < 70:
            improvement_areas.append({
                "area": "overall_quality",
                "severity": "high" if overall["quality_score"] < 50 else "medium",
                "description": f"Overall quality score is {overall['quality_score']}%",
                "suggestion": "Review recent negative feedback for patterns"
            })

        for domain in result["quality"]["by_domain"]:
            if domain["quality_score"] and domain["quality_score"] < 60:
                improvement_areas.append({
                    "area": f"domain_{domain['domain']}",
                    "severity": "high" if domain["quality_score"] < 40 else "medium",
                    "description": f"{domain['domain']} domain has {domain['quality_score']}% quality",
                    "suggestion": f"Focus on improving {domain['domain']} responses"
                })

        result["quality"]["improvement_areas"] = improvement_areas

        logger.info(f"Response quality measured: {days} days, {total} feedback items, score={quality_score}")

    except Exception as e:
        logger.error(f"Failed to measure response quality: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result


# =============================================================================
# 3. KNOWLEDGE GAP DETECTION
# =============================================================================

async def detect_knowledge_gaps(
    namespace: str = "work_projektil",
    days: int = 30,
    min_occurrences: int = 2
) -> Dict[str, Any]:
    """
    Detect missing knowledge by analyzing failed searches and unclear contexts.

    Returns:
        - missing_people: People mentioned but not in knowledge base
        - missing_concepts: Concepts/topics not well covered
        - failed_searches: Queries that returned poor results
        - suggested_ingestion: Recommended knowledge to add
    """
    result = {
        "status": "success",
        "namespace": namespace,
        "period_days": days,
        "analyzed_at": datetime.now().isoformat(),
        "gaps": {}
    }

    try:
        # 1. Find questions that led to negative feedback (potential gaps)
        with safe_list_query('user_feedback', timeout=15) as cur:
            cur.execute("""
                SELECT
                    original_query,
                    COUNT(*) as negative_count
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND thumbs_up = false
                  AND original_query IS NOT NULL
                  AND LENGTH(original_query) > 10
                GROUP BY original_query
                HAVING COUNT(*) >= %s
                ORDER BY negative_count DESC
                LIMIT 15
            """, (days, min_occurrences))
            rows = cur.fetchall()

            result["gaps"]["failed_queries"] = [
                {
                    "query": row['original_query'][:200] + "..." if len(row['original_query'] or "") > 200 else row['original_query'],
                    "negative_feedback_count": row['negative_count']
                }
                for row in rows
            ]

        # 2. Analyze message content for unknown entities (people, concepts)
        # Look for patterns like "Wer ist X?", "Was ist Y?", questions about unknowns
        with safe_list_query('message', timeout=20) as cur:
            cur.execute("""
                SELECT
                    m.content,
                    m.created_at
                FROM message m
                JOIN conversation c ON m.session_id = c.session_id
                WHERE c.namespace = %s
                  AND m.created_at > NOW() - INTERVAL '%s days'
                  AND m.role = 'user'
                  AND (
                    m.content ILIKE '%%wer ist%%' OR
                    m.content ILIKE '%%who is%%' OR
                    m.content ILIKE '%%was ist%%' OR
                    m.content ILIKE '%%what is%%' OR
                    m.content ILIKE '%%kenne ich%%' OR
                    m.content ILIKE '%%do I know%%' OR
                    m.content ILIKE '%%remember%%' OR
                    m.content ILIKE '%%erinner%%'
                  )
                ORDER BY m.created_at DESC
                LIMIT 50
            """, (namespace, days))
            rows = cur.fetchall()

            # Extract potential entity names from questions
            unknown_entities = []
            for row in rows:
                content = row['content'].lower()
                # Simple extraction (could be improved with NLP)
                for pattern in ['wer ist ', 'who is ', 'was ist ', 'what is ']:
                    if pattern in content:
                        idx = content.find(pattern) + len(pattern)
                        entity = content[idx:idx+50].split('?')[0].split('.')[0].strip()
                        if entity and len(entity) > 2:
                            unknown_entities.append(entity[:50])

            # Count occurrences
            entity_counts = Counter(unknown_entities)
            result["gaps"]["unknown_entities"] = [
                {"entity": entity, "mentions": count}
                for entity, count in entity_counts.most_common(15)
                if count >= min_occurrences
            ]

        # 3. Knowledge items with low salience (rarely accessed)
        with safe_list_query('knowledge_item', timeout=15) as cur:
            cur.execute("""
                SELECT
                    item_type,
                    COUNT(*) as item_count,
                    AVG(salience_score) as avg_salience,
                    COUNT(*) FILTER (WHERE salience_score < 0.3) as low_salience_count
                FROM knowledge_item
                WHERE namespace = %s
                  AND status = 'active'
                GROUP BY item_type
                ORDER BY low_salience_count DESC
            """, (namespace,))
            rows = cur.fetchall()

            result["gaps"]["knowledge_coverage"] = [
                {
                    "type": row['item_type'],
                    "total_items": row['item_count'],
                    "avg_salience": round(float(row['avg_salience'] or 0), 3),
                    "low_salience_items": row['low_salience_count'] or 0
                }
                for row in rows
            ]

        # 4. Topics mentioned frequently but with low knowledge coverage
        # Cross-reference conversation topics with knowledge items
        with safe_aggregate_query('conversation') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_conversations,
                    COUNT(*) FILTER (WHERE title IS NOT NULL) as titled_count
                FROM conversation
                WHERE namespace = %s
                  AND created_at > NOW() - INTERVAL '%s days'
            """, (namespace, days))
            row = cur.fetchone()

            result["gaps"]["conversation_coverage"] = {
                "total_conversations": row['total_conversations'] or 0,
                "titled_conversations": row['titled_count'] or 0
            }

        # 5. Generate ingestion suggestions
        suggestions = []

        # Suggest adding failed query topics
        for query in result["gaps"]["failed_queries"][:5]:
            suggestions.append({
                "type": "add_knowledge",
                "priority": "high",
                "description": f"Add knowledge for: '{query['query'][:80]}...'",
                "reason": f"Query failed {query['negative_feedback_count']} times"
            })

        # Suggest researching unknown entities
        for entity in result["gaps"]["unknown_entities"][:5]:
            suggestions.append({
                "type": "research_entity",
                "priority": "medium",
                "description": f"Research and add info about: '{entity['entity']}'",
                "reason": f"Asked about {entity['mentions']} times"
            })

        # Suggest reviewing low-salience items
        low_salience_total = sum(
            item['low_salience_items']
            for item in result["gaps"]["knowledge_coverage"]
        )
        if low_salience_total > 20:
            suggestions.append({
                "type": "review_stale",
                "priority": "low",
                "description": f"Review {low_salience_total} low-salience knowledge items",
                "reason": "Items may be outdated or irrelevant"
            })

        result["gaps"]["ingestion_suggestions"] = suggestions

        logger.info(
            f"Knowledge gaps detected: {namespace}, {days} days, "
            f"{len(result['gaps']['failed_queries'])} failed queries, "
            f"{len(result['gaps']['unknown_entities'])} unknown entities"
        )

    except Exception as e:
        logger.error(f"Failed to detect knowledge gaps: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result


# =============================================================================
# COMBINED ANALYTICS DASHBOARD
# =============================================================================

async def get_analytics_dashboard(
    namespace: str = "work_projektil",
    days: int = 30
) -> Dict[str, Any]:
    """
    Get a combined analytics dashboard with all metrics.

    This provides Jarvis with a comprehensive self-assessment view.
    """
    result = {
        "status": "success",
        "namespace": namespace,
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
        "dashboard": {}
    }

    try:
        # Run all analytics
        patterns = await analyze_conversation_patterns(namespace, days)
        quality = await measure_response_quality(days)
        gaps = await detect_knowledge_gaps(namespace, days)

        result["dashboard"]["conversation_patterns"] = patterns.get("patterns", {})
        result["dashboard"]["response_quality"] = quality.get("quality", {})
        result["dashboard"]["knowledge_gaps"] = gaps.get("gaps", {})

        # Generate overall health score
        overall_health = 70  # Base score

        # Adjust based on quality
        quality_score = quality.get("quality", {}).get("overall", {}).get("quality_score")
        if quality_score:
            overall_health = (overall_health + quality_score) / 2

        # Penalize for inefficiencies
        inefficiencies = patterns.get("patterns", {}).get("inefficiency_indicators", [])
        overall_health -= len(inefficiencies) * 5

        # Penalize for knowledge gaps
        failed_queries = len(gaps.get("gaps", {}).get("failed_queries", []))
        overall_health -= min(failed_queries * 2, 15)

        result["dashboard"]["overall_health_score"] = max(0, min(100, round(overall_health, 1)))

        # Top 3 action items
        action_items = []

        # From quality improvement areas
        for area in quality.get("quality", {}).get("improvement_areas", [])[:2]:
            action_items.append({
                "source": "quality",
                "priority": area["severity"],
                "action": area["suggestion"]
            })

        # From inefficiencies
        for ineff in inefficiencies[:1]:
            action_items.append({
                "source": "patterns",
                "priority": "medium",
                "action": ineff["suggestion"]
            })

        # From knowledge gaps
        for suggestion in gaps.get("gaps", {}).get("ingestion_suggestions", [])[:1]:
            action_items.append({
                "source": "knowledge",
                "priority": suggestion["priority"],
                "action": suggestion["description"]
            })

        result["dashboard"]["top_action_items"] = action_items[:5]

        logger.info(f"Analytics dashboard generated: health_score={overall_health}")

    except Exception as e:
        logger.error(f"Failed to generate analytics dashboard: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result
