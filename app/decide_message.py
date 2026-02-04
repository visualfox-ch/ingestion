"""
Combined decision logging + stakeholder-specific messaging.

Implements /decide_and_message:
1. Store versioned decision_brief in Postgres
2. Generate stakeholder-specific message drafts using advice_auto
3. Create follow-up plan

Constraints:
- No diagnosing people, patterns only
- Every claim links to evidence refs
- Private namespace = no external LLM by default
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any

from .observability import get_logger, log_with_context
from . import advice_auto

logger = get_logger("jarvis.decide_message")


# ============ Database Schema Extension ============

DECISION_BRIEF_DDL = """
-- Versioned decision brief (for team/stakeholder decisions)
CREATE TABLE IF NOT EXISTS decision_brief (
    id SERIAL PRIMARY KEY,
    brief_id VARCHAR(100) NOT NULL UNIQUE,
    topic VARCHAR(500) NOT NULL,
    status VARCHAR(50) DEFAULT 'draft',
    current_version_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS decision_brief_version (
    id SERIAL PRIMARY KEY,
    brief_id INTEGER NOT NULL REFERENCES decision_brief(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,
    changed_by VARCHAR(100) NOT NULL,
    change_reason TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brief_id, version_number)
);

CREATE TABLE IF NOT EXISTS decision_stakeholder_draft (
    id SERIAL PRIMARY KEY,
    brief_version_id INTEGER NOT NULL REFERENCES decision_brief_version(id) ON DELETE CASCADE,
    person_id VARCHAR(100) NOT NULL,
    persona_id VARCHAR(100),
    strategy VARCHAR(50),
    drafts JSONB NOT NULL,
    rationale TEXT,
    evidence_refs JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_brief_id ON decision_brief(brief_id);
CREATE INDEX IF NOT EXISTS idx_decision_brief_status ON decision_brief(status);
CREATE INDEX IF NOT EXISTS idx_dbv_brief_id ON decision_brief_version(brief_id);
CREATE INDEX IF NOT EXISTS idx_dsd_version_id ON decision_stakeholder_draft(brief_version_id);
CREATE INDEX IF NOT EXISTS idx_dsd_person_id ON decision_stakeholder_draft(person_id);
"""


def init_decision_brief_schema():
    """Initialize decision_brief tables in Postgres"""
    from . import knowledge_db

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            for statement in DECISION_BRIEF_DDL.split(";"):
                statement = statement.strip()
                if statement and not statement.startswith("--"):
                    cur.execute(statement)
        log_with_context(logger, "info", "Decision brief schema initialized")
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to init decision brief schema", error=str(e))
        return False


# ============ Data Classes ============

@dataclass
class DecisionOption:
    """A single decision option"""
    label: str
    description: str
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    recommended: bool = False


@dataclass
class StakeholderDraft:
    """Drafts for a single stakeholder"""
    person_id: str
    person_name: str
    persona_id: str
    strategy: str
    drafts: List[advice_auto.DraftResult]
    rationale: str
    evidence_refs: List[Dict[str, str]]


@dataclass
class FollowUpItem:
    """A follow-up action item"""
    action: str
    owner: str
    due: Optional[str] = None
    depends_on: Optional[str] = None


@dataclass
class DecisionBriefResult:
    """Complete result of decide_and_message"""
    brief_id: str
    decision_log_id: int
    topic: str
    options: List[DecisionOption]
    recommendation: str
    decision_summary: str
    stakeholder_drafts: Dict[str, StakeholderDraft]
    follow_up_plan: List[FollowUpItem]
    why_this_decision: str = ""
    confidence: str = "medium"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "brief_id": self.brief_id,
            "decision_log_id": self.decision_log_id,
            "topic": self.topic,
            "options": [asdict(o) for o in self.options],
            "recommendation": self.recommendation,
            "decision_summary": self.decision_summary,
            "why_this_decision": self.why_this_decision,
            "confidence": self.confidence,
            "stakeholder_drafts": {
                k: {
                    "person_id": v.person_id,
                    "person_name": v.person_name,
                    "persona_id": v.persona_id,
                    "strategy": v.strategy,
                    "drafts": [asdict(d) for d in v.drafts],
                    "rationale": v.rationale,
                    "evidence_refs": v.evidence_refs
                }
                for k, v in self.stakeholder_drafts.items()
            },
            "follow_up_plan": [asdict(f) for f in self.follow_up_plan],
            "warnings": self.warnings
        }


# ============ Database Operations ============

def _generate_brief_id(topic: str) -> str:
    """Generate a brief ID from topic"""
    import hashlib
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d%H%M")
    topic_slug = topic[:30].lower().replace(" ", "_").replace("-", "_")
    topic_slug = "".join(c for c in topic_slug if c.isalnum() or c == "_")
    return f"{topic_slug}_{ts}"


def create_decision_brief(
    topic: str,
    options: List[Dict],
    recommendation: str,
    context: str,
    stakeholders: List[str],
    namespace: str,
    created_by: str = "system"
) -> Optional[int]:
    """
    Create a new decision brief with first version.

    Returns: version_id
    """
    from . import knowledge_db

    brief_id = _generate_brief_id(topic)

    content = {
        "topic": topic,
        "options": options,
        "recommendation": recommendation,
        "context": context,
        "stakeholders": stakeholders,
        "namespace": namespace,
        "created_at": datetime.now().isoformat()
    }

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Create brief
            cur.execute("""
                INSERT INTO decision_brief (brief_id, topic, created_by)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (brief_id, topic, created_by))
            db_brief_id = cur.fetchone()["id"]

            # Create first version
            cur.execute("""
                INSERT INTO decision_brief_version
                (brief_id, version_number, content, changed_by, status)
                VALUES (%s, 1, %s, %s, 'draft')
                RETURNING id
            """, (db_brief_id, json.dumps(content), created_by))
            version_id = cur.fetchone()["id"]

            # Update current version
            cur.execute("""
                UPDATE decision_brief SET current_version_id = %s
                WHERE id = %s
            """, (version_id, db_brief_id))

            log_with_context(
                logger, "info", "Decision brief created",
                brief_id=brief_id, version_id=version_id
            )

            return version_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to create decision brief", error=str(e))
        return None


def save_stakeholder_drafts(
    version_id: int,
    stakeholder_drafts: Dict[str, StakeholderDraft]
) -> bool:
    """Save stakeholder drafts for a brief version"""
    from . import knowledge_db

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            for person_id, draft in stakeholder_drafts.items():
                cur.execute("""
                    INSERT INTO decision_stakeholder_draft
                    (brief_version_id, person_id, persona_id, strategy, drafts, rationale, evidence_refs)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    version_id,
                    person_id,
                    draft.persona_id,
                    draft.strategy,
                    json.dumps([asdict(d) for d in draft.drafts]),
                    draft.rationale,
                    json.dumps(draft.evidence_refs)
                ))

            log_with_context(
                logger, "info", "Stakeholder drafts saved",
                version_id=version_id, count=len(stakeholder_drafts)
            )
            return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to save stakeholder drafts", error=str(e))
        return False


def get_decision_brief(brief_id: str) -> Optional[Dict]:
    """Get a decision brief by ID"""
    from . import knowledge_db

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT b.*, v.content, v.version_number, v.status as version_status
                FROM decision_brief b
                JOIN decision_brief_version v ON b.current_version_id = v.id
                WHERE b.brief_id = %s
            """, (brief_id,))

            row = cur.fetchone()
            if not row:
                return None

            # Get stakeholder drafts
            cur.execute("""
                SELECT * FROM decision_stakeholder_draft
                WHERE brief_version_id = %s
            """, (row["current_version_id"],))

            drafts = [dict(r) for r in cur.fetchall()]

            result = dict(row)
            result["stakeholder_drafts"] = drafts
            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to get decision brief", error=str(e))
        return None


# ============ Main API ============

def _generate_follow_up_plan(
    topic: str,
    stakeholders: List[str],
    recommendation: str
) -> List[FollowUpItem]:
    """Generate a basic follow-up plan"""
    plan = []

    # Always: Communicate decision
    plan.append(FollowUpItem(
        action=f"Stakeholder-Kommunikation zu '{topic}'",
        owner="self",
        due="heute/morgen"
    ))

    # If multiple stakeholders: Schedule sync
    if len(stakeholders) > 2:
        plan.append(FollowUpItem(
            action="Sync-Meeting für Alignment",
            owner="self",
            due="diese Woche",
            depends_on="Stakeholder-Kommunikation"
        ))

    # Track outcome
    plan.append(FollowUpItem(
        action="Outcome tracken nach Implementation",
        owner="self",
        due="2 Wochen"
    ))

    return plan


def _generate_decision_summary(
    topic: str,
    options: List[DecisionOption],
    recommendation: str
) -> str:
    """Generate a brief decision summary"""
    opt_count = len(options)
    rec_opt = next((o for o in options if o.recommended), None)

    summary = f"Entscheidung zu '{topic}': "
    if rec_opt:
        summary += f"Empfehlung ist '{rec_opt.label}'. "
    summary += f"{opt_count} Optionen evaluiert. "
    summary += recommendation[:200] if len(recommendation) > 200 else recommendation

    return summary


def decide_and_message(
    decision_topic: str,
    options: List[Dict[str, Any]],
    recommendation: str,
    stakeholders: List[str],
    context: str,
    namespace: str = "work_projektil",
    user_id: Optional[int] = None
) -> DecisionBriefResult:
    """
    Combined decision logging and stakeholder messaging.

    Args:
        decision_topic: What the decision is about
        options: List of options with label, description, pros, cons, recommended
        recommendation: Why the recommended option is best
        stakeholders: List of person_ids to communicate with
        context: Additional context
        namespace: Namespace (private = no LLM)
        user_id: Optional user ID for tracking

    Returns:
        DecisionBriefResult with brief, drafts, and follow-up plan
    """
    warnings = []

    # Initialize schema if needed
    init_decision_brief_schema()

    # Parse options
    parsed_options = []
    for opt in options:
        parsed_options.append(DecisionOption(
            label=opt.get("label", "Option"),
            description=opt.get("description", ""),
            pros=opt.get("pros", []),
            cons=opt.get("cons", []),
            recommended=opt.get("recommended", False)
        ))

    # Create decision brief in Postgres
    version_id = create_decision_brief(
        topic=decision_topic,
        options=options,
        recommendation=recommendation,
        context=context,
        stakeholders=stakeholders,
        namespace=namespace
    )

    if not version_id:
        warnings.append("Failed to create decision brief in database")
        version_id = 0

    # Also log to simple decision_log in SQLite for personal tracking
    from . import state_db
    decision_log_id = state_db.log_decision(
        context_summary=f"[Decision Brief] {decision_topic}: {recommendation[:100]}",
        tags=["decision_brief", "stakeholder_comm"],
        options=json.dumps([o.label for o in parsed_options]),
        chosen_option=next((o.label for o in parsed_options if o.recommended), None),
        user_id=user_id
    )

    # Generate stakeholder drafts using advice_auto
    stakeholder_drafts = {}
    goal = f"Entscheidung kommunizieren: {decision_topic}"
    combined_context = f"{recommendation}\n\nKontext: {context}"

    for person_id in stakeholders:
        try:
            advice = advice_auto.generate_advice(
                person_id=person_id,
                goal=goal,
                context=combined_context,
                namespace=namespace
            )

            stakeholder_drafts[person_id] = StakeholderDraft(
                person_id=person_id,
                person_name=advice.person_name,
                persona_id=advice.selected_persona_id,
                strategy=advice.selected_strategy,
                drafts=advice.drafts,
                rationale=advice.rationale,
                evidence_refs=advice.evidence_refs
            )

            if advice.warnings:
                warnings.extend(advice.warnings)

        except Exception as e:
            log_with_context(
                logger, "error", "Failed to generate advice for stakeholder",
                person_id=person_id, error=str(e)
            )
            warnings.append(f"Failed to generate advice for {person_id}")

    # Output contract: At least one stakeholder must have drafts
    if not stakeholder_drafts:
        raise ValueError(
            f"Failed to generate drafts for any stakeholder. "
            f"Stakeholders: {stakeholders}. Check person profiles and advice_auto logs."
        )

    # Check that all stakeholders have drafts (output contract)
    missing_drafts = [s for s in stakeholders if s not in stakeholder_drafts]
    if missing_drafts:
        warnings.append(f"Missing drafts for: {', '.join(missing_drafts)}")

    # Save stakeholder drafts to DB
    if version_id and stakeholder_drafts:
        save_stakeholder_drafts(version_id, stakeholder_drafts)

    # Generate follow-up plan
    follow_up = _generate_follow_up_plan(decision_topic, stakeholders, recommendation)

    # Generate decision summary
    decision_summary = _generate_decision_summary(decision_topic, parsed_options, recommendation)

    brief_id = _generate_brief_id(decision_topic)

    # Generate why_this_decision
    rec_opt = next((o for o in parsed_options if o.recommended), None)
    why_parts = []
    if rec_opt:
        why_parts.append(f"Option '{rec_opt.label}' gewählt")
        if rec_opt.pros:
            why_parts.append(f"Vorteile: {', '.join(rec_opt.pros[:3])}")
        if rec_opt.cons:
            why_parts.append(f"Bekannte Risiken: {', '.join(rec_opt.cons[:2])}")
    why_parts.append(f"Begründung: {recommendation[:150]}")
    why_this_decision = ". ".join(why_parts)

    # Determine confidence based on data quality
    confidence = "medium"
    if all(s in stakeholder_drafts for s in stakeholders):
        confidence = "high"
    if missing_drafts:
        confidence = "low"

    log_with_context(
        logger, "info", "Decision and message generated",
        brief_id=brief_id,
        stakeholder_count=len(stakeholder_drafts),
        follow_up_count=len(follow_up),
        confidence=confidence
    )

    return DecisionBriefResult(
        brief_id=brief_id,
        decision_log_id=decision_log_id,
        topic=decision_topic,
        options=parsed_options,
        recommendation=recommendation,
        decision_summary=decision_summary,
        stakeholder_drafts=stakeholder_drafts,
        follow_up_plan=follow_up,
        why_this_decision=why_this_decision,
        confidence=confidence,
        warnings=warnings
    )
