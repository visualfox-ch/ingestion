"""
Causal Knowledge Graph Service - Phase A3 (AGI Evolution)

Based on Pearl's Causal Inference (2009):
- Do-calculus for interventions
- Cause-effect relationship tracking
- Causal reasoning (why, what-if, how-to)

Enables Jarvis to understand causality, not just correlations.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Singleton instance
_causal_service = None


def get_causal_service():
    """Get or create the causal knowledge service singleton."""
    global _causal_service
    if _causal_service is None:
        _causal_service = CausalKnowledgeService()
    return _causal_service


class CausalKnowledgeService:
    """
    Service for managing the causal knowledge graph.

    Implements Pearl's causal framework:
    - Nodes: entities, events, states, actions, concepts
    - Edges: causal relationships (causes, enables, prevents, etc.)
    - Queries: why, what-if, how-to
    - Interventions: do(X) operations
    """

    def __init__(self):
        self.relationship_types = [
            'causes', 'enables', 'prevents', 'influences',
            'requires', 'triggers', 'inhibits', 'correlates',
            'precedes', 'follows'
        ]
        logger.info("CausalKnowledgeService initialized")

    def _get_cursor(self):
        """Get database cursor."""
        from app.services.db_client import get_cursor
        return get_cursor()

    # =========================================================================
    # NODE MANAGEMENT
    # =========================================================================

    def add_node(
        self,
        node_name: str,
        node_type: str,
        domain: str = None,
        description: str = None,
        is_observable: bool = True,
        is_manipulable: bool = False,
        typical_values: List[str] = None
    ) -> Dict[str, Any]:
        """
        Add a causal node to the graph.

        Args:
            node_name: Name of the node
            node_type: Type (event, state, action, entity, concept)
            domain: Domain/category
            description: Description of the node
            is_observable: Can we observe this directly?
            is_manipulable: Can we intervene on this?
            typical_values: Typical values/states

        Returns:
            Dict with node info or error
        """
        try:
            import json

            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_nodes
                    (node_name, node_type, domain, description,
                     is_observable, is_manipulable, typical_values)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (node_name, domain)
                    DO UPDATE SET
                        node_type = EXCLUDED.node_type,
                        description = COALESCE(EXCLUDED.description, causal_nodes.description),
                        is_observable = EXCLUDED.is_observable,
                        is_manipulable = EXCLUDED.is_manipulable,
                        typical_values = EXCLUDED.typical_values,
                        updated_at = NOW()
                    RETURNING id, node_name, node_type, domain
                """, (
                    node_name, node_type, domain, description,
                    is_observable, is_manipulable,
                    json.dumps(typical_values or [])
                ))

                row = cur.fetchone()

                return {
                    "success": True,
                    "node_id": row[0],
                    "node_name": row[1],
                    "node_type": row[2],
                    "domain": row[3]
                }

        except Exception as e:
            logger.error(f"Add node failed: {e}")
            return {"success": False, "error": str(e)}

    def get_node(self, node_id: int = None, node_name: str = None, domain: str = None) -> Dict[str, Any]:
        """Get a causal node by ID or name."""
        try:
            with self._get_cursor() as cur:
                if node_id:
                    cur.execute("SELECT * FROM causal_nodes WHERE id = %s", (node_id,))
                elif node_name:
                    if domain:
                        cur.execute(
                            "SELECT * FROM causal_nodes WHERE node_name = %s AND domain = %s",
                            (node_name, domain)
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM causal_nodes WHERE node_name = %s LIMIT 1",
                            (node_name,)
                        )
                else:
                    return {"success": False, "error": "Must provide node_id or node_name"}

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Node not found"}

                columns = [desc[0] for desc in cur.description]
                node = dict(zip(columns, row))

                return {"success": True, "node": node}

        except Exception as e:
            logger.error(f"Get node failed: {e}")
            return {"success": False, "error": str(e)}

    def find_nodes(
        self,
        search_term: str = None,
        node_type: str = None,
        domain: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Find nodes matching criteria."""
        try:
            with self._get_cursor() as cur:
                conditions = []
                params = []

                if search_term:
                    conditions.append("(node_name ILIKE %s OR description ILIKE %s)")
                    params.extend([f"%{search_term}%", f"%{search_term}%"])

                if node_type:
                    conditions.append("node_type = %s")
                    params.append(node_type)

                if domain:
                    conditions.append("domain = %s")
                    params.append(domain)

                where_clause = " AND ".join(conditions) if conditions else "1=1"
                params.append(limit)

                cur.execute(f"""
                    SELECT id, node_name, node_type, domain, description,
                           is_observable, is_manipulable, occurrence_count
                    FROM causal_nodes
                    WHERE {where_clause}
                    ORDER BY occurrence_count DESC, updated_at DESC
                    LIMIT %s
                """, params)

                columns = [desc[0] for desc in cur.description]
                nodes = [dict(zip(columns, row)) for row in cur.fetchall()]

                return {"success": True, "nodes": nodes, "count": len(nodes)}

        except Exception as e:
            logger.error(f"Find nodes failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # EDGE MANAGEMENT (Causal Relationships)
    # =========================================================================

    def add_causal_edge(
        self,
        cause_node_id: int = None,
        effect_node_id: int = None,
        cause_name: str = None,
        effect_name: str = None,
        relationship_type: str = "causes",
        strength: float = 0.5,
        confidence: float = 0.5,
        mechanism: str = None,
        conditions: List[Dict] = None,
        time_lag_minutes: int = None,
        domain: str = None
    ) -> Dict[str, Any]:
        """
        Add a causal edge between two nodes.

        Can use node IDs or names (names will be resolved/created).
        """
        try:
            import json

            if relationship_type not in self.relationship_types:
                return {
                    "success": False,
                    "error": f"Invalid relationship_type. Must be one of: {self.relationship_types}"
                }

            with self._get_cursor() as cur:
                # Resolve or create cause node
                if cause_node_id is None:
                    if cause_name is None:
                        return {"success": False, "error": "Must provide cause_node_id or cause_name"}
                    result = self.add_node(cause_name, "concept", domain=domain)
                    if not result["success"]:
                        return result
                    cause_node_id = result["node_id"]

                # Resolve or create effect node
                if effect_node_id is None:
                    if effect_name is None:
                        return {"success": False, "error": "Must provide effect_node_id or effect_name"}
                    result = self.add_node(effect_name, "concept", domain=domain)
                    if not result["success"]:
                        return result
                    effect_node_id = result["node_id"]

                # Insert or update edge
                cur.execute("""
                    INSERT INTO causal_edges
                    (cause_node_id, effect_node_id, relationship_type,
                     strength, confidence, mechanism, conditions, time_lag_minutes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cause_node_id, effect_node_id, relationship_type)
                    DO UPDATE SET
                        strength = (causal_edges.strength * causal_edges.observation_count + EXCLUDED.strength)
                                   / (causal_edges.observation_count + 1),
                        confidence = (causal_edges.confidence * causal_edges.observation_count + EXCLUDED.confidence)
                                     / (causal_edges.observation_count + 1),
                        mechanism = COALESCE(EXCLUDED.mechanism, causal_edges.mechanism),
                        observation_count = causal_edges.observation_count + 1,
                        last_observed = NOW(),
                        updated_at = NOW()
                    RETURNING id
                """, (
                    cause_node_id, effect_node_id, relationship_type,
                    strength, confidence, mechanism,
                    json.dumps(conditions or []), time_lag_minutes
                ))

                edge_id = cur.fetchone()[0]

                # Update node occurrence counts
                cur.execute("""
                    UPDATE causal_nodes SET occurrence_count = occurrence_count + 1, last_observed = NOW()
                    WHERE id IN (%s, %s)
                """, (cause_node_id, effect_node_id))

                return {
                    "success": True,
                    "edge_id": edge_id,
                    "cause_node_id": cause_node_id,
                    "effect_node_id": effect_node_id,
                    "relationship_type": relationship_type
                }

        except Exception as e:
            logger.error(f"Add causal edge failed: {e}")
            return {"success": False, "error": str(e)}

    def get_causal_chain(
        self,
        start_node_id: int = None,
        start_node_name: str = None,
        direction: str = "effects",  # effects or causes
        max_depth: int = 3,
        min_confidence: float = 0.3
    ) -> Dict[str, Any]:
        """
        Get the causal chain from a node.

        Args:
            start_node_id: Starting node ID
            start_node_name: Starting node name (resolved to ID)
            direction: "effects" (what does this cause) or "causes" (what causes this)
            max_depth: Maximum chain depth
            min_confidence: Minimum confidence threshold
        """
        try:
            # Resolve node name to ID if needed
            if start_node_id is None:
                if start_node_name is None:
                    return {"success": False, "error": "Must provide start_node_id or start_node_name"}
                result = self.get_node(node_name=start_node_name)
                if not result["success"]:
                    return result
                start_node_id = result["node"]["id"]

            with self._get_cursor() as cur:
                # Recursive CTE to find causal chain
                if direction == "effects":
                    # What does this node cause?
                    cur.execute("""
                        WITH RECURSIVE causal_chain AS (
                            -- Base case: direct effects
                            SELECT
                                e.id as edge_id,
                                e.cause_node_id,
                                e.effect_node_id,
                                e.relationship_type,
                                e.strength,
                                e.confidence,
                                n.node_name as effect_name,
                                1 as depth,
                                ARRAY[e.cause_node_id] as path
                            FROM causal_edges e
                            JOIN causal_nodes n ON e.effect_node_id = n.id
                            WHERE e.cause_node_id = %s AND e.confidence >= %s

                            UNION ALL

                            -- Recursive case: follow the chain
                            SELECT
                                e.id,
                                e.cause_node_id,
                                e.effect_node_id,
                                e.relationship_type,
                                e.strength,
                                e.confidence,
                                n.node_name,
                                cc.depth + 1,
                                cc.path || e.cause_node_id
                            FROM causal_edges e
                            JOIN causal_nodes n ON e.effect_node_id = n.id
                            JOIN causal_chain cc ON e.cause_node_id = cc.effect_node_id
                            WHERE cc.depth < %s
                              AND e.confidence >= %s
                              AND NOT e.effect_node_id = ANY(cc.path)  -- Prevent cycles
                        )
                        SELECT * FROM causal_chain ORDER BY depth, confidence DESC
                    """, (start_node_id, min_confidence, max_depth, min_confidence))
                else:
                    # What causes this node?
                    cur.execute("""
                        WITH RECURSIVE causal_chain AS (
                            -- Base case: direct causes
                            SELECT
                                e.id as edge_id,
                                e.cause_node_id,
                                e.effect_node_id,
                                e.relationship_type,
                                e.strength,
                                e.confidence,
                                n.node_name as cause_name,
                                1 as depth,
                                ARRAY[e.effect_node_id] as path
                            FROM causal_edges e
                            JOIN causal_nodes n ON e.cause_node_id = n.id
                            WHERE e.effect_node_id = %s AND e.confidence >= %s

                            UNION ALL

                            -- Recursive case: follow the chain
                            SELECT
                                e.id,
                                e.cause_node_id,
                                e.effect_node_id,
                                e.relationship_type,
                                e.strength,
                                e.confidence,
                                n.node_name,
                                cc.depth + 1,
                                cc.path || e.effect_node_id
                            FROM causal_edges e
                            JOIN causal_nodes n ON e.cause_node_id = n.id
                            JOIN causal_chain cc ON e.effect_node_id = cc.cause_node_id
                            WHERE cc.depth < %s
                              AND e.confidence >= %s
                              AND NOT e.cause_node_id = ANY(cc.path)
                        )
                        SELECT * FROM causal_chain ORDER BY depth, confidence DESC
                    """, (start_node_id, min_confidence, max_depth, min_confidence))

                columns = [desc[0] for desc in cur.description]
                chain = [dict(zip(columns, row)) for row in cur.fetchall()]

                # Convert path arrays
                for item in chain:
                    if 'path' in item:
                        item['path'] = list(item['path'])

                return {
                    "success": True,
                    "start_node_id": start_node_id,
                    "direction": direction,
                    "chain": chain,
                    "depth_reached": max(item['depth'] for item in chain) if chain else 0
                }

        except Exception as e:
            logger.error(f"Get causal chain failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # CAUSAL QUERIES (Why, What-If, How-To)
    # =========================================================================

    def why_query(
        self,
        effect_name: str,
        domain: str = None,
        max_depth: int = 3,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Answer "Why does X happen?" by finding causal ancestors.

        Returns a reasoning chain explaining what causes the effect.
        """
        try:
            import json

            # Find the effect node
            result = self.get_node(node_name=effect_name, domain=domain)
            if not result["success"]:
                # Node doesn't exist - record as knowledge gap
                return {
                    "success": True,
                    "query_type": "why",
                    "target": effect_name,
                    "answer": f"I don't have causal knowledge about '{effect_name}' yet.",
                    "reasoning_chain": [],
                    "confidence": 0.0
                }

            effect_node = result["node"]

            # Get causal chain (what causes this)
            chain_result = self.get_causal_chain(
                start_node_id=effect_node["id"],
                direction="causes",
                max_depth=max_depth
            )

            if not chain_result["success"]:
                return chain_result

            chain = chain_result["chain"]

            # Build reasoning chain
            reasoning_chain = []
            for item in chain:
                reasoning_chain.append({
                    "step": item["depth"],
                    "cause": item.get("cause_name", f"Node {item['cause_node_id']}"),
                    "relationship": item["relationship_type"],
                    "strength": item["strength"],
                    "confidence": item["confidence"]
                })

            # Generate natural language answer
            if reasoning_chain:
                causes = [r["cause"] for r in reasoning_chain if r["step"] == 1]
                answer = f"'{effect_name}' happens because of: {', '.join(causes)}."
                if len(reasoning_chain) > len(causes):
                    root_causes = [r["cause"] for r in reasoning_chain if r["step"] == max(item["step"] for item in reasoning_chain)]
                    answer += f" The root causes are: {', '.join(root_causes)}."
                overall_confidence = sum(r["confidence"] for r in reasoning_chain) / len(reasoning_chain)
            else:
                answer = f"I don't know what causes '{effect_name}'."
                overall_confidence = 0.0

            # Log the query
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_queries
                    (query_type, query_text, target_node_id, reasoning_chain, answer, confidence, session_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    "why", f"Why does {effect_name} happen?", effect_node["id"],
                    json.dumps(reasoning_chain), answer, overall_confidence, session_id
                ))

            return {
                "success": True,
                "query_type": "why",
                "target": effect_name,
                "answer": answer,
                "reasoning_chain": reasoning_chain,
                "confidence": overall_confidence
            }

        except Exception as e:
            logger.error(f"Why query failed: {e}")
            return {"success": False, "error": str(e)}

    def what_if_query(
        self,
        intervention_name: str,
        intervention_value: str = None,
        domain: str = None,
        max_depth: int = 3,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Answer "What if X happens/changes?" by simulating intervention effects.

        This implements Pearl's do(X) - predicting effects of interventions.
        """
        try:
            import json

            # Find the intervention node
            result = self.get_node(node_name=intervention_name, domain=domain)
            if not result["success"]:
                return {
                    "success": True,
                    "query_type": "what_if",
                    "intervention": intervention_name,
                    "answer": f"I don't have causal knowledge about '{intervention_name}' yet.",
                    "predicted_effects": [],
                    "confidence": 0.0
                }

            intervention_node = result["node"]

            # Get effects chain
            chain_result = self.get_causal_chain(
                start_node_id=intervention_node["id"],
                direction="effects",
                max_depth=max_depth
            )

            if not chain_result["success"]:
                return chain_result

            chain = chain_result["chain"]

            # Build predicted effects
            predicted_effects = []
            seen_effects = set()

            for item in chain:
                effect_id = item["effect_node_id"]
                if effect_id not in seen_effects:
                    seen_effects.add(effect_id)
                    predicted_effects.append({
                        "effect": item.get("effect_name", f"Node {effect_id}"),
                        "relationship": item["relationship_type"],
                        "distance": item["depth"],
                        "strength": item["strength"],
                        "confidence": item["confidence"],
                        "combined_impact": item["strength"] * item["confidence"]
                    })

            # Sort by combined impact
            predicted_effects.sort(key=lambda x: x["combined_impact"], reverse=True)

            # Generate answer
            if predicted_effects:
                direct_effects = [e["effect"] for e in predicted_effects if e["distance"] == 1]
                answer = f"If '{intervention_name}' changes, it would affect: {', '.join(direct_effects[:5])}."
                if len(predicted_effects) > len(direct_effects):
                    answer += f" Downstream effects include {len(predicted_effects) - len(direct_effects)} more nodes."
                overall_confidence = sum(e["confidence"] for e in predicted_effects) / len(predicted_effects)
            else:
                answer = f"I don't know what effects '{intervention_name}' would have."
                overall_confidence = 0.0

            # Log the query
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_queries
                    (query_type, query_text, target_node_id, intervention_node_id,
                     intervention_value, reasoning_chain, answer, confidence, session_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    "what_if", f"What if {intervention_name} changes?",
                    intervention_node["id"], intervention_node["id"],
                    intervention_value, json.dumps(predicted_effects),
                    answer, overall_confidence, session_id
                ))

            return {
                "success": True,
                "query_type": "what_if",
                "intervention": intervention_name,
                "intervention_value": intervention_value,
                "answer": answer,
                "predicted_effects": predicted_effects,
                "confidence": overall_confidence
            }

        except Exception as e:
            logger.error(f"What-if query failed: {e}")
            return {"success": False, "error": str(e)}

    def how_to_query(
        self,
        goal_name: str,
        domain: str = None,
        max_depth: int = 4,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Answer "How to achieve X?" by finding manipulable causes.

        Finds intervention points that lead to the desired outcome.
        """
        try:
            import json

            # Find the goal node
            result = self.get_node(node_name=goal_name, domain=domain)
            if not result["success"]:
                return {
                    "success": True,
                    "query_type": "how_to",
                    "goal": goal_name,
                    "answer": f"I don't have causal knowledge about '{goal_name}' yet.",
                    "intervention_points": [],
                    "confidence": 0.0
                }

            goal_node = result["node"]

            # Get causes chain
            chain_result = self.get_causal_chain(
                start_node_id=goal_node["id"],
                direction="causes",
                max_depth=max_depth
            )

            if not chain_result["success"]:
                return chain_result

            chain = chain_result["chain"]

            # Find manipulable intervention points
            intervention_points = []

            with self._get_cursor() as cur:
                for item in chain:
                    cause_id = item["cause_node_id"]

                    # Check if this cause is manipulable
                    cur.execute("""
                        SELECT id, node_name, is_manipulable, typical_values
                        FROM causal_nodes WHERE id = %s
                    """, (cause_id,))

                    node_row = cur.fetchone()
                    if node_row and node_row[2]:  # is_manipulable
                        intervention_points.append({
                            "node_name": node_row[1],
                            "node_id": node_row[0],
                            "typical_values": node_row[3] if node_row[3] else [],
                            "distance_to_goal": item["depth"],
                            "relationship": item["relationship_type"],
                            "strength": item["strength"],
                            "confidence": item["confidence"],
                            "effectiveness": item["strength"] * item["confidence"] / item["depth"]
                        })

            # Sort by effectiveness
            intervention_points.sort(key=lambda x: x["effectiveness"], reverse=True)

            # Generate answer
            if intervention_points:
                top_interventions = intervention_points[:3]
                actions = [f"manipulate '{i['node_name']}'" for i in top_interventions]
                answer = f"To achieve '{goal_name}', you could: {', '.join(actions)}."
                overall_confidence = sum(i["confidence"] for i in intervention_points) / len(intervention_points)
            else:
                # Check for non-manipulable causes
                if chain:
                    answer = f"I found causes for '{goal_name}', but none are directly manipulable."
                else:
                    answer = f"I don't know how to achieve '{goal_name}'."
                overall_confidence = 0.0

            # Log the query
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_queries
                    (query_type, query_text, target_node_id, reasoning_chain, answer, confidence, session_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    "how_to", f"How to achieve {goal_name}?", goal_node["id"],
                    json.dumps(intervention_points), answer, overall_confidence, session_id
                ))

            return {
                "success": True,
                "query_type": "how_to",
                "goal": goal_name,
                "answer": answer,
                "intervention_points": intervention_points,
                "confidence": overall_confidence
            }

        except Exception as e:
            logger.error(f"How-to query failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # INTERVENTION TRACKING (do(X) Operations)
    # =========================================================================

    def record_intervention(
        self,
        target_name: str,
        intervention_type: str,
        target_value: str,
        original_value: str = None,
        predicted_effects: List[Dict] = None,
        domain: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Record a do(X) intervention for later verification.

        Args:
            target_name: What we're intervening on
            intervention_type: set, increase, decrease, toggle
            target_value: The new value
            original_value: The old value (if known)
            predicted_effects: Expected effects [{node_id/name, predicted_value, confidence}]
            domain: Domain
            session_id: Session ID
        """
        try:
            import json

            # Find or create target node
            result = self.get_node(node_name=target_name, domain=domain)
            if not result["success"]:
                # Create it
                result = self.add_node(target_name, "concept", domain=domain, is_manipulable=True)
                if not result["success"]:
                    return result
                target_node_id = result["node_id"]
            else:
                target_node_id = result["node"]["id"]

            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_interventions
                    (intervention_type, target_node_id, target_value, original_value,
                     predicted_effects, session_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    intervention_type, target_node_id, target_value, original_value,
                    json.dumps(predicted_effects or []), session_id
                ))

                intervention_id = cur.fetchone()[0]

                return {
                    "success": True,
                    "intervention_id": intervention_id,
                    "target": target_name,
                    "intervention_type": intervention_type,
                    "message": "Intervention recorded. Use record_intervention_outcome to verify predictions."
                }

        except Exception as e:
            logger.error(f"Record intervention failed: {e}")
            return {"success": False, "error": str(e)}

    def record_intervention_outcome(
        self,
        intervention_id: int,
        actual_effects: List[Dict]
    ) -> Dict[str, Any]:
        """
        Record the actual outcome of an intervention.

        Compares predicted vs actual effects to improve the causal model.
        """
        try:
            import json

            with self._get_cursor() as cur:
                # Get the intervention
                cur.execute("""
                    SELECT id, predicted_effects, target_node_id
                    FROM causal_interventions WHERE id = %s
                """, (intervention_id,))

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Intervention not found"}

                predicted = row[1] if row[1] else []
                target_node_id = row[2]

                # Calculate prediction accuracy
                if predicted and actual_effects:
                    matches = 0
                    for pred in predicted:
                        for actual in actual_effects:
                            if (pred.get("node_name") == actual.get("node_name") or
                                pred.get("node_id") == actual.get("node_id")):
                                if pred.get("predicted_value") == actual.get("actual_value"):
                                    matches += 1
                                break
                    accuracy = matches / len(predicted) if predicted else 0.0
                else:
                    accuracy = None

                # Update intervention
                cur.execute("""
                    UPDATE causal_interventions
                    SET actual_effects = %s,
                        observation_timestamp = NOW(),
                        prediction_accuracy = %s
                    WHERE id = %s
                """, (json.dumps(actual_effects), accuracy, intervention_id))

                # Record observations for each actual effect
                for effect in actual_effects:
                    effect_node_id = effect.get("node_id")
                    effect_name = effect.get("node_name")

                    if not effect_node_id and effect_name:
                        node_result = self.get_node(node_name=effect_name)
                        if node_result["success"]:
                            effect_node_id = node_result["node"]["id"]

                    if effect_node_id:
                        # Find or create the causal edge
                        cur.execute("""
                            SELECT id FROM causal_edges
                            WHERE cause_node_id = %s AND effect_node_id = %s
                            LIMIT 1
                        """, (target_node_id, effect_node_id))

                        edge_row = cur.fetchone()
                        if edge_row:
                            # Record observation
                            cur.execute("""
                                INSERT INTO causal_observations
                                (edge_id, cause_value, effect_value, was_predicted, prediction_correct, session_id)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (
                                edge_row[0],
                                effect.get("intervention_value"),
                                effect.get("actual_value"),
                                effect.get("was_predicted", False),
                                effect.get("prediction_correct"),
                                None
                            ))

                return {
                    "success": True,
                    "intervention_id": intervention_id,
                    "prediction_accuracy": accuracy,
                    "observations_recorded": len(actual_effects),
                    "message": f"Outcome recorded. Prediction accuracy: {accuracy:.1%}" if accuracy else "Outcome recorded."
                }

        except Exception as e:
            logger.error(f"Record intervention outcome failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # LEARNING FROM OBSERVATIONS
    # =========================================================================

    def learn_causal_relationship(
        self,
        cause_description: str,
        effect_description: str,
        relationship_type: str = "causes",
        confidence: float = 0.5,
        mechanism: str = None,
        source: str = "user_feedback",
        domain: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Learn a new causal relationship from observation or feedback.

        This is the primary way to populate the causal graph.
        """
        try:
            import json

            # Add/get cause node
            cause_result = self.add_node(cause_description, "concept", domain=domain)
            if not cause_result["success"]:
                return cause_result

            # Add/get effect node
            effect_result = self.add_node(effect_description, "concept", domain=domain)
            if not effect_result["success"]:
                return effect_result

            # Add edge
            edge_result = self.add_causal_edge(
                cause_node_id=cause_result["node_id"],
                effect_node_id=effect_result["node_id"],
                relationship_type=relationship_type,
                confidence=confidence,
                mechanism=mechanism,
                domain=domain
            )

            if not edge_result["success"]:
                return edge_result

            # Record as observation
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO causal_observations
                    (edge_id, source, session_id)
                    VALUES (%s, %s, %s)
                """, (edge_result["edge_id"], source, session_id))

            return {
                "success": True,
                "cause": cause_description,
                "effect": effect_description,
                "relationship": relationship_type,
                "edge_id": edge_result["edge_id"],
                "message": f"Learned: '{cause_description}' {relationship_type} '{effect_description}'"
            }

        except Exception as e:
            logger.error(f"Learn causal relationship failed: {e}")
            return {"success": False, "error": str(e)}

    def get_causal_summary(
        self,
        domain: str = None
    ) -> Dict[str, Any]:
        """Get summary statistics of the causal knowledge graph."""
        try:
            with self._get_cursor() as cur:
                # Node stats
                if domain:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_nodes,
                            COUNT(DISTINCT node_type) as node_types,
                            SUM(CASE WHEN is_manipulable THEN 1 ELSE 0 END) as manipulable_nodes
                        FROM causal_nodes WHERE domain = %s
                    """, (domain,))
                else:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_nodes,
                            COUNT(DISTINCT node_type) as node_types,
                            SUM(CASE WHEN is_manipulable THEN 1 ELSE 0 END) as manipulable_nodes
                        FROM causal_nodes
                    """)

                node_stats = cur.fetchone()

                # Edge stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_edges,
                        AVG(confidence) as avg_confidence,
                        AVG(strength) as avg_strength,
                        COUNT(DISTINCT relationship_type) as relationship_types
                    FROM causal_edges
                """)
                edge_stats = cur.fetchone()

                # Query stats
                cur.execute("""
                    SELECT query_type, COUNT(*) as count
                    FROM causal_queries
                    GROUP BY query_type
                """)
                query_stats = {row[0]: row[1] for row in cur.fetchall()}

                # Intervention stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_interventions,
                        AVG(prediction_accuracy) as avg_accuracy
                    FROM causal_interventions
                    WHERE prediction_accuracy IS NOT NULL
                """)
                intervention_stats = cur.fetchone()

                return {
                    "success": True,
                    "nodes": {
                        "total": node_stats[0] if node_stats else 0,
                        "types": node_stats[1] if node_stats else 0,
                        "manipulable": node_stats[2] if node_stats else 0
                    },
                    "edges": {
                        "total": edge_stats[0] if edge_stats else 0,
                        "avg_confidence": round(edge_stats[1], 2) if edge_stats and edge_stats[1] else 0,
                        "avg_strength": round(edge_stats[2], 2) if edge_stats and edge_stats[2] else 0,
                        "relationship_types": edge_stats[3] if edge_stats else 0
                    },
                    "queries": query_stats,
                    "interventions": {
                        "total": intervention_stats[0] if intervention_stats else 0,
                        "avg_prediction_accuracy": round(intervention_stats[1], 2) if intervention_stats and intervention_stats[1] else None
                    },
                    "domain": domain
                }

        except Exception as e:
            logger.error(f"Get causal summary failed: {e}")
            return {"success": False, "error": str(e)}
