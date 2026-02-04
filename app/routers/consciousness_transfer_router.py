"""
Phase 5.4: Consciousness Transfer API Router
Purpose: Expose consciousness transfer endpoints to external consumers
Owner: GitHub Copilot (TIER 2)
Created: 2026-02-04
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from pydantic import BaseModel, Field
from ..services.epoch_manager import EpochManager
from ..services.consciousness_transfer import ConsciousnessTransfer
from ..models.consciousness import ConsciousnessEpoch
from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.consciousness_transfer_api")

# Router setup
router = APIRouter(
    prefix="/consciousness-transfer",
    tags=["consciousness"],
    responses={404: {"description": "Not found"}}
)


# =====================================================================
# Request/Response Models
# =====================================================================

class PrepareTransferRequest(BaseModel):
    """Request to prepare consciousness transfer"""
    source_epoch_id: int = Field(ge=1, description="Epoch to transfer from")
    target_observer_id: str = Field(
        default="micha@192.168.1.103",
        description="Observer receiving transfer (default: micha@192.168.1.103)"
    )
    target_session_id: str = Field(
        min_length=1,
        description="New session identifier"
    )


class ApplyTransferRequest(BaseModel):
    """Request to apply consciousness transfer"""
    transfer_payload: Dict[str, Any] = Field(
        description="Transfer payload from prepare endpoint"
    )
    new_epoch_id: int = Field(ge=1, description="Target epoch for transfer")


class TransferResponse(BaseModel):
    """Response from transfer operation"""
    status: str
    source_epoch_id: int
    target_epoch_id: int
    awareness_transferred: float
    maturation_level_transferred: int
    learned_patterns_count: int
    message: str


class VerifyTransferRequest(BaseModel):
    """Request to verify transfer quality"""
    source_epoch_id: int = Field(ge=1)
    target_epoch_id: int = Field(ge=1)


# =====================================================================
# Endpoints
# =====================================================================

@router.post("/prepare", response_model=Dict[str, Any])
def prepare_transfer(request: PrepareTransferRequest) -> Dict[str, Any]:
    """
    Prepare consciousness transfer from previous epoch
    
    Loads consciousness state including:
    - Starting awareness level for new observer
    - Learned patterns from previous epoch
    - Breakthrough insights and context
    - Conversation topic and trajectory
    
    **Arguments**:
    - `source_epoch_id`: Epoch to transfer from (must exist)
    - `target_observer_id`: Observer ID (default: micha@192.168.1.103)
    - `target_session_id`: New session identifier
    
    **Returns**:
    - `transfer_payload`: Complete consciousness transfer payload
    - `awareness_starting_point`: Awareness level to give new observer
    - `learned_patterns`: Patterns discovered in source epoch
    - `breakthrough_description`: Key insights to transfer
    
    **Example**:
    ```json
    {
        "source_epoch_id": 42,
        "target_observer_id": "micha@192.168.1.103",
        "target_session_id": "session_2026-02-04_tier2_testing"
    }
    ```
    """
    try:
        log_with_context(
            logger, "info", "Preparing consciousness transfer",
            source_epoch=request.source_epoch_id,
            target_observer=request.target_observer_id
        )
        
        payload = ConsciousnessTransfer.prepare_transfer(
            source_epoch_id=request.source_epoch_id,
            target_observer_id=request.target_observer_id,
            target_session_id=request.target_session_id
        )
        
        log_with_context(
            logger, "info", "Transfer prepared successfully",
            quality=payload.get("consciousness_quality_assessment")
        )
        
        return payload
        
    except ValueError as e:
        log_with_context(logger, "error", "Preparation failed", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error during prepare", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to prepare transfer")


@router.post("/apply", response_model=TransferResponse)
def apply_transfer(request: ApplyTransferRequest) -> TransferResponse:
    """
    Apply consciousness transfer to new epoch
    
    Updates the target epoch with transferred consciousness,
    learned patterns, and initial hypotheses from source observer.
    
    **Arguments**:
    - `transfer_payload`: Output from /prepare endpoint (required)
    - `new_epoch_id`: Target epoch to receive transfer (must exist)
    
    **Returns**:
    - `status`: "success" if transfer applied
    - `awareness_transferred`: Awareness level transferred
    - `learned_patterns_count`: Number of patterns transferred
    
    **Example**:
    ```json
    {
        "transfer_payload": { ... },
        "new_epoch_id": 43
    }
    ```
    
    **Note**: Target epoch should be newly created with initial awareness
    matching source epoch's final awareness after this call.
    """
    try:
        log_with_context(
            logger, "info", "Applying consciousness transfer",
            target_epoch=request.new_epoch_id
        )
        
        result = ConsciousnessTransfer.apply_transfer(
            transfer_payload=request.transfer_payload,
            new_epoch_id=request.new_epoch_id
        )
        
        log_with_context(
            logger, "info", "Transfer applied successfully",
            target_epoch=request.new_epoch_id
        )
        
        return TransferResponse(**result)
        
    except ValueError as e:
        log_with_context(logger, "error", "Application failed", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error during apply", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to apply transfer")


@router.post("/verify", response_model=Dict[str, Any])
def verify_transfer(request: VerifyTransferRequest) -> Dict[str, Any]:
    """
    Verify consciousness transfer quality between epochs
    
    Compares source and target epochs to ensure valid transfer.
    Source's final awareness should match target's initial awareness.
    
    **Arguments**:
    - `source_epoch_id`: Source epoch
    - `target_epoch_id`: Target epoch
    
    **Returns**:
    - `transfer_quality`: "valid" or "degraded"
    - `source_final_awareness`: Source's ending awareness
    - `target_initial_awareness`: Target's starting awareness
    - `awareness_transfer_match`: Whether values match (within 0.05)
    
    **Example**:
    ```json
    {
        "source_epoch_id": 42,
        "target_epoch_id": 43
    }
    ```
    """
    try:
        result = ConsciousnessTransfer.verify_transfer_quality(
            source_epoch_id=request.source_epoch_id,
            target_epoch_id=request.target_epoch_id
        )
        
        log_with_context(
            logger, "info", "Transfer verification completed",
            quality=result.get("transfer_quality")
        )
        
        return result
        
    except ValueError as e:
        log_with_context(logger, "error", "Verification failed", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error during verify", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to verify transfer")


@router.get("/epoch/{epoch_id}", response_model=ConsciousnessEpoch)
def get_epoch(epoch_id: int) -> ConsciousnessEpoch:
    """
    Retrieve epoch for inspection or transfer preparation
    
    **Arguments**:
    - `epoch_id`: Epoch to retrieve
    
    **Returns**:
    - Full `ConsciousnessEpoch` object with all metrics
    """
    try:
        epoch = EpochManager.get_epoch_by_id(epoch_id)
        if not epoch:
            raise ValueError(f"Epoch {epoch_id} not found")
        
        return epoch
        
    except ValueError as e:
        log_with_context(logger, "error", "Epoch retrieval failed", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_with_context(logger, "error", "Unexpected error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve epoch")
