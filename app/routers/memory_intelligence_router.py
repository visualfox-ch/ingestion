"""
Memory Intelligence Router

API endpoints for intelligent memory operations:
- Smart Retrieval with multi-signal ranking
- Auto-Tagging for automatic categorization
- Confidence Scoring for trust assessment
- Fact Extraction for granular knowledge

All endpoints under /memory/intelligence/
"""

import logging
from datetime import datetime
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory/intelligence", tags=["memory-intelligence"])


# =============================================================================
# Request/Response Models
# =============================================================================

# Smart Retrieval Models
class RetrievalRequest(BaseModel):
    """Request for smart memory retrieval."""
    query: str = Field(..., description="Search query")
    user_id: str = Field(default="0", description="User ID")
    namespace: str = Field(default="private", description="Memory namespace")
    strategy: Optional[str] = Field(None, description="Retrieval strategy: semantic, keyword, hybrid, temporal, contextual, adaptive")
    memory_types: List[str] = Field(default=["all"], description="Types to search: fact, preference, pattern, event, etc.")
    min_confidence: float = Field(default=0.0, ge=0, le=1, description="Minimum confidence threshold")
    max_results: int = Field(default=10, ge=1, le=50, description="Maximum results to return")
    include_scores: bool = Field(default=True, description="Include scoring breakdown")


class RetrievalResultModel(BaseModel):
    """A single retrieval result."""
    id: str
    content: str
    memory_type: str
    source: str
    final_score: float
    confidence: float
    tags: List[str]
    entities: List[str]
    score_breakdown: Optional[Dict[str, float]] = None
    created_at: str


class RetrievalResponse(BaseModel):
    """Response from smart retrieval."""
    query: str
    strategy_used: str
    results: List[RetrievalResultModel]
    total_candidates: int
    retrieval_time_ms: float
    signals_used: List[str]
    query_understanding: Dict[str, Any]


# Auto-Tagging Models
class TaggingRequest(BaseModel):
    """Request for auto-tagging."""
    content: str = Field(..., description="Content to tag")
    use_llm: bool = Field(default=False, description="Use LLM for enhanced tagging")
    min_confidence: float = Field(default=0.3, ge=0, le=1, description="Minimum tag confidence")
    max_tags: int = Field(default=15, ge=1, le=30, description="Maximum tags to return")


class TagModel(BaseModel):
    """A single tag with metadata."""
    name: str
    tag_type: str
    source: str
    confidence: float
    relevance: float
    parent_tag: Optional[str] = None


class TaggingResponse(BaseModel):
    """Response from auto-tagging."""
    content_preview: str
    tags: List[TagModel]
    categories: List[str]
    entities: List[str]
    topics: List[str]
    sentiment: Optional[str]
    processing_time_ms: float
    strategies_used: List[str]


class TagSuggestionRequest(BaseModel):
    """Request for tag suggestions."""
    partial_tag: str = Field(..., min_length=1, description="Partial tag to complete")
    existing_tags: List[str] = Field(default=[], description="Already assigned tags")
    max_suggestions: int = Field(default=5, ge=1, le=10)


# Confidence Scoring Models
class ConfidenceRequest(BaseModel):
    """Request for confidence assessment."""
    item_id: str = Field(..., description="ID of item to assess")
    content: str = Field(..., description="Content of the item")
    source_type: str = Field(default="inferred", description="Source type: user_stated, user_confirmed, inferred, etc.")
    source_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional source info")
    created_at: Optional[str] = Field(None, description="Creation timestamp ISO format")
    source_count: int = Field(default=1, ge=1, description="Number of confirming sources")
    contradictions: int = Field(default=0, ge=0, description="Number of contradicting sources")
    access_count: int = Field(default=0, ge=0, description="Times accessed")
    was_useful: int = Field(default=0, ge=0, description="Times proved useful")


class ConfidenceFactorModel(BaseModel):
    """A single confidence factor."""
    name: str
    weight: float
    raw_value: float
    weighted_value: float
    explanation: str


class ConfidenceResponse(BaseModel):
    """Response from confidence assessment."""
    item_id: str
    final_score: float
    confidence_level: str
    factors: List[ConfidenceFactorModel]
    recommendations: List[str]
    can_be_trusted: bool
    needs_verification: bool
    decay_rate: float
    projected_confidence_7d: float


class QuickConfidenceRequest(BaseModel):
    """Request for quick confidence estimate."""
    content: str
    source_type: str = Field(default="inferred")


class FeedbackRequest(BaseModel):
    """Request to apply feedback to confidence."""
    current_score: float = Field(..., ge=0, le=1)
    feedback_type: str = Field(..., description="confirm, contradict, clarify, ignore")
    weight: float = Field(default=1.0, ge=0, le=2)


# Fact Extraction Models
class ExtractionRequest(BaseModel):
    """Request for fact extraction."""
    text: str = Field(..., description="Text to extract facts from")
    use_llm: bool = Field(default=False, description="Use LLM for enhanced extraction")
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    deduplicate: bool = Field(default=True)


class AtomicFactModel(BaseModel):
    """A single atomic fact."""
    id: str
    content: str
    fact_type: str
    category: str
    subject: str
    predicate: str
    object: str
    source_text: str
    extraction_method: str
    confidence: float
    entities: List[str]
    tags: List[str]


class ExtractionResponse(BaseModel):
    """Response from fact extraction."""
    source_preview: str
    facts: List[AtomicFactModel]
    entities_found: List[str]
    relationships_found: List[List[str]]
    extraction_time_ms: float
    methods_used: List[str]
    summary: str


class ConversationExtractionRequest(BaseModel):
    """Request for conversation-based extraction."""
    messages: List[Dict[str, str]] = Field(..., description="List of {role, content} messages")
    user_id: str = Field(default="user")


# =============================================================================
# Smart Retrieval Endpoints
# =============================================================================

@router.post("/retrieve", response_model=RetrievalResponse)
async def smart_retrieve(request: RetrievalRequest):
    """
    Perform smart memory retrieval with multi-signal ranking.

    Combines semantic search, keyword matching, recency scoring,
    and context relevance for optimal results.
    """
    try:
        from ..services.smart_retrieval import (
            get_smart_retrieval, RetrievalContext, RetrievalStrategy, MemoryType
        )

        retrieval = get_smart_retrieval()

        # Parse strategy
        strategy = None
        if request.strategy:
            try:
                strategy = RetrievalStrategy(request.strategy)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid strategy. Use: {[s.value for s in RetrievalStrategy]}"
                )

        # Parse memory types
        memory_types = []
        for mt in request.memory_types:
            try:
                memory_types.append(MemoryType(mt))
            except ValueError:
                pass  # Skip invalid types
        if not memory_types:
            memory_types = [MemoryType.ALL]

        # Build context
        context = RetrievalContext(
            user_id=request.user_id,
            query=request.query,
            namespace=request.namespace,
            memory_types=memory_types,
            min_confidence=request.min_confidence,
            max_results=request.max_results,
        )

        # Execute retrieval
        result = retrieval.retrieve(context, strategy)

        # Build response
        results = []
        for r in result.results:
            results.append(RetrievalResultModel(
                id=r.id,
                content=r.content[:500],
                memory_type=r.memory_type.value,
                source=r.source,
                final_score=round(r.final_score, 4),
                confidence=r.confidence,
                tags=r.tags,
                entities=r.entities,
                score_breakdown=r.score_breakdown if request.include_scores else None,
                created_at=r.created_at.isoformat(),
            ))

        return RetrievalResponse(
            query=result.query,
            strategy_used=result.strategy_used.value,
            results=results,
            total_candidates=result.total_candidates,
            retrieval_time_ms=round(result.retrieval_time_ms, 2),
            signals_used=result.signals_used,
            query_understanding=result.query_understanding,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Smart retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/retrieve/strategies")
async def get_retrieval_strategies():
    """Get available retrieval strategies."""
    from ..services.smart_retrieval import RetrievalStrategy, STRATEGY_WEIGHTS

    return {
        "strategies": [
            {
                "name": s.value,
                "description": {
                    "semantic": "Vector similarity search (best for conceptual queries)",
                    "keyword": "BM25 keyword matching (best for exact terms)",
                    "hybrid": "Combined semantic + keyword (recommended default)",
                    "temporal": "Prioritize recent memories",
                    "relational": "Follow entity relationships",
                    "contextual": "Match query context patterns",
                    "adaptive": "Auto-select based on query analysis",
                }.get(s.value, ""),
                "weights": STRATEGY_WEIGHTS.get(s, {}),
            }
            for s in RetrievalStrategy
        ]
    }


# =============================================================================
# Auto-Tagging Endpoints
# =============================================================================

@router.post("/tag", response_model=TaggingResponse)
async def auto_tag(request: TaggingRequest):
    """
    Auto-tag content using multiple strategies.

    Combines keyword extraction, entity recognition, topic classification,
    and optional LLM enhancement.
    """
    try:
        from ..services.auto_tagger import get_auto_tagger

        tagger = get_auto_tagger()
        result = tagger.tag(
            content=request.content,
            use_llm=request.use_llm,
            min_confidence=request.min_confidence,
            max_tags=request.max_tags,
        )

        return TaggingResponse(
            content_preview=result.content[:200],
            tags=[
                TagModel(
                    name=t.name,
                    tag_type=t.tag_type.value,
                    source=t.source.value,
                    confidence=round(t.confidence, 3),
                    relevance=round(t.relevance, 3),
                    parent_tag=t.parent_tag,
                )
                for t in result.tags
            ],
            categories=result.categories,
            entities=result.entities,
            topics=result.topics,
            sentiment=result.sentiment,
            processing_time_ms=round(result.processing_time_ms, 2),
            strategies_used=result.strategies_used,
        )

    except Exception as e:
        logger.error(f"Auto-tagging failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tag/suggest")
async def suggest_tags(request: TagSuggestionRequest):
    """Suggest tags based on partial input."""
    try:
        from ..services.auto_tagger import get_auto_tagger

        tagger = get_auto_tagger()
        suggestions = tagger.suggest_tags(
            partial_tag=request.partial_tag,
            existing_tags=request.existing_tags,
            max_suggestions=request.max_suggestions,
        )

        return {"suggestions": suggestions}

    except Exception as e:
        logger.error(f"Tag suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tag/taxonomy")
async def get_tag_taxonomy():
    """Get the tag taxonomy hierarchy."""
    from ..services.auto_tagger import CATEGORY_TAXONOMY

    return {
        "categories": [
            {
                "name": category,
                "keywords": config["keywords"][:10],
                "subcategories": config.get("subcategories", []),
            }
            for category, config in CATEGORY_TAXONOMY.items()
        ]
    }


# =============================================================================
# Confidence Scoring Endpoints
# =============================================================================

@router.post("/confidence/assess", response_model=ConfidenceResponse)
async def assess_confidence(request: ConfidenceRequest):
    """
    Perform full confidence assessment on an item.

    Evaluates source reliability, corroboration, recency,
    specificity, user feedback, and usage patterns.
    """
    try:
        from ..services.confidence_scorer import get_confidence_scorer, SourceType

        scorer = get_confidence_scorer()

        # Parse source type
        try:
            source_type = SourceType(request.source_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source_type. Use: {[s.value for s in SourceType]}"
            )

        # Parse created_at
        created_at = None
        if request.created_at:
            created_at = datetime.fromisoformat(request.created_at)

        assessment = scorer.assess(
            item_id=request.item_id,
            content=request.content,
            source_type=source_type,
            source_metadata=request.source_metadata,
            created_at=created_at,
            source_count=request.source_count,
            contradictions=request.contradictions,
            access_count=request.access_count,
            was_useful=request.was_useful,
        )

        return ConfidenceResponse(
            item_id=assessment.item_id,
            final_score=assessment.final_score,
            confidence_level=assessment.confidence_level.value,
            factors=[
                ConfidenceFactorModel(
                    name=f.name,
                    weight=f.weight,
                    raw_value=round(f.raw_value, 4),
                    weighted_value=round(f.weighted_value, 4),
                    explanation=f.explanation,
                )
                for f in assessment.factors
            ],
            recommendations=assessment.recommendations,
            can_be_trusted=assessment.can_be_trusted,
            needs_verification=assessment.needs_verification,
            decay_rate=assessment.decay_rate,
            projected_confidence_7d=assessment.projected_confidence_7d,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Confidence assessment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/confidence/quick")
async def quick_confidence(request: QuickConfidenceRequest):
    """Quick confidence estimate without full assessment."""
    try:
        from ..services.confidence_scorer import get_confidence_scorer, SourceType

        scorer = get_confidence_scorer()

        try:
            source_type = SourceType(request.source_type)
        except ValueError:
            source_type = SourceType.INFERRED

        score = scorer.quick_score(request.content, source_type)

        return {
            "score": round(score, 4),
            "level": "high" if score >= 0.7 else "medium" if score >= 0.4 else "low",
            "source_type": source_type.value,
        }

    except Exception as e:
        logger.error(f"Quick confidence failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/confidence/feedback")
async def apply_confidence_feedback(request: FeedbackRequest):
    """Apply user feedback to adjust confidence score."""
    try:
        from ..services.confidence_scorer import get_confidence_scorer, FeedbackType

        scorer = get_confidence_scorer()

        try:
            feedback_type = FeedbackType(request.feedback_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid feedback_type. Use: {[f.value for f in FeedbackType]}"
            )

        adjusted = scorer.apply_feedback(
            current_score=request.current_score,
            feedback_type=feedback_type,
            weight=request.weight,
        )

        return {
            "original_score": request.current_score,
            "adjusted_score": round(adjusted, 4),
            "feedback_type": feedback_type.value,
            "change": round(adjusted - request.current_score, 4),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Feedback application failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/confidence/levels")
async def get_confidence_levels():
    """Get confidence level definitions."""
    from ..services.confidence_scorer import ConfidenceLevel

    return {
        "levels": [
            {"name": "very_low", "range": "0.0-0.2", "description": "Speculation, inference with no backing"},
            {"name": "low", "range": "0.2-0.4", "description": "Single weak source, unverified"},
            {"name": "medium", "range": "0.4-0.6", "description": "Plausible but not confirmed"},
            {"name": "high", "range": "0.6-0.8", "description": "Confirmed or corroborated"},
            {"name": "very_high", "range": "0.8-1.0", "description": "Verified from multiple sources"},
        ]
    }


# =============================================================================
# Fact Extraction Endpoints
# =============================================================================

@router.post("/extract", response_model=ExtractionResponse)
async def extract_facts(request: ExtractionRequest):
    """
    Extract atomic facts from text.

    Uses pattern matching, structural analysis, and optional LLM
    for comprehensive fact extraction.
    """
    try:
        from ..services.fact_extractor import get_fact_extractor

        extractor = get_fact_extractor()
        result = extractor.extract(
            text=request.text,
            use_llm=request.use_llm,
            min_confidence=request.min_confidence,
            deduplicate=request.deduplicate,
        )

        return ExtractionResponse(
            source_preview=result.source_text[:200],
            facts=[
                AtomicFactModel(
                    id=f.id,
                    content=f.content,
                    fact_type=f.fact_type.value,
                    category=f.category.value,
                    subject=f.subject,
                    predicate=f.predicate,
                    object=f.object,
                    source_text=f.source_text[:200],
                    extraction_method=f.extraction_method,
                    confidence=round(f.confidence, 3),
                    entities=f.entities,
                    tags=f.tags,
                )
                for f in result.facts
            ],
            entities_found=result.entities_found,
            relationships_found=[list(r) for r in result.relationships_found],
            extraction_time_ms=round(result.extraction_time_ms, 2),
            methods_used=result.methods_used,
            summary=result.summary,
        )

    except Exception as e:
        logger.error(f"Fact extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/conversation", response_model=ExtractionResponse)
async def extract_from_conversation(request: ConversationExtractionRequest):
    """Extract facts from conversation history."""
    try:
        from ..services.fact_extractor import get_fact_extractor

        extractor = get_fact_extractor()
        result = extractor.extract_from_conversation(
            messages=request.messages,
            user_id=request.user_id,
        )

        return ExtractionResponse(
            source_preview=result.source_text[:200],
            facts=[
                AtomicFactModel(
                    id=f.id,
                    content=f.content,
                    fact_type=f.fact_type.value,
                    category=f.category.value,
                    subject=f.subject,
                    predicate=f.predicate,
                    object=f.object,
                    source_text=f.source_text[:200],
                    extraction_method=f.extraction_method,
                    confidence=round(f.confidence, 3),
                    entities=f.entities,
                    tags=f.tags,
                )
                for f in result.facts
            ],
            entities_found=result.entities_found,
            relationships_found=[list(r) for r in result.relationships_found],
            extraction_time_ms=round(result.extraction_time_ms, 2),
            methods_used=result.methods_used,
            summary=result.summary,
        )

    except Exception as e:
        logger.error(f"Conversation extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extract/types")
async def get_fact_types():
    """Get available fact types and categories."""
    from ..services.fact_extractor import FactType, FactCategory

    return {
        "fact_types": [
            {"name": t.value, "description": {
                "biographical": "Personal information about someone",
                "relational": "Relationships between entities",
                "temporal": "Time-related information",
                "declarative": "Statements of fact",
                "procedural": "How-to knowledge",
                "preference": "Likes, dislikes, preferences",
                "quantitative": "Numbers and measurements",
                "contextual": "Situational information",
            }.get(t.value, "")}
            for t in FactType
        ],
        "categories": [
            {"name": c.value}
            for c in FactCategory
        ],
    }


# =============================================================================
# Combined Operations
# =============================================================================

@router.post("/process")
async def process_memory(
    content: str = Body(..., embed=True),
    extract_facts: bool = Body(True, embed=True),
    auto_tag: bool = Body(True, embed=True),
    assess_confidence: bool = Body(False, embed=True),
    use_llm: bool = Body(False, embed=True),
):
    """
    Process content through the full memory intelligence pipeline.

    Optionally extracts facts, generates tags, and assesses confidence.
    """
    try:
        result = {
            "content_preview": content[:200],
            "processing": {},
        }

        # Fact extraction
        if extract_facts:
            from ..services.fact_extractor import get_fact_extractor
            extractor = get_fact_extractor()
            extraction = extractor.extract(content, use_llm=use_llm)
            result["facts"] = {
                "count": len(extraction.facts),
                "facts": [
                    {"subject": f.subject, "predicate": f.predicate, "object": f.object, "confidence": f.confidence}
                    for f in extraction.facts[:10]
                ],
                "entities": extraction.entities_found,
            }

        # Auto-tagging
        if auto_tag:
            from ..services.auto_tagger import get_auto_tagger
            tagger = get_auto_tagger()
            tagging = tagger.tag(content, use_llm=use_llm)
            result["tags"] = {
                "categories": tagging.categories,
                "topics": tagging.topics,
                "entities": tagging.entities,
                "sentiment": tagging.sentiment,
                "all_tags": [{"name": t.name, "type": t.tag_type.value, "confidence": t.confidence} for t in tagging.tags[:15]],
            }

        # Confidence assessment (on the content itself)
        if assess_confidence:
            from ..services.confidence_scorer import get_confidence_scorer, SourceType
            scorer = get_confidence_scorer()
            assessment = scorer.assess(
                item_id="temp",
                content=content,
                source_type=SourceType.INFERRED,
            )
            result["confidence"] = {
                "score": assessment.final_score,
                "level": assessment.confidence_level.value,
                "can_be_trusted": assessment.can_be_trusted,
                "recommendations": assessment.recommendations,
            }

        return result

    except Exception as e:
        logger.error(f"Memory processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
