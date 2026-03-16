"""
Connectors Router

Extracted from main.py - Connector State Management endpoints:
- List/get connectors
- Create/enable/disable connectors
- Reset errors
- Update configuration
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict

from ..observability import get_logger

logger = get_logger("jarvis.connectors")
router = APIRouter(prefix="/connectors", tags=["connectors"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class ConnectorCreateRequest(BaseModel):
    connector_type: str  # gmail, whatsapp, gchat, calendar
    namespace: str = "work_projektil"
    config: dict = {}


class ConnectorConfigRequest(BaseModel):
    config: dict


# =============================================================================
# LIST & GET
# =============================================================================

@router.get("")
def list_connectors():
    """List all connector states with health summary"""
    from .. import connector_state
    return {"connectors": connector_state.list_connectors()}


@router.get("/{connector_id}")
def get_connector(connector_id: str):
    """Get detailed connector state"""
    from .. import connector_state
    summary = connector_state.get_connector_summary(connector_id)
    if not summary:
        return {"error": "Connector not found"}, 404
    return summary


# =============================================================================
# CREATE & UPDATE
# =============================================================================

@router.post("/{connector_id}")
def create_connector(connector_id: str, req: ConnectorCreateRequest):
    """Create or update a connector state"""
    from .. import connector_state

    state = connector_state.get_or_create_state(
        connector_id=connector_id,
        connector_type=req.connector_type,
        namespace=req.namespace
    )

    if req.config:
        connector_state.update_config(connector_id, req.config)

    return connector_state.get_connector_summary(connector_id)


@router.patch("/{connector_id}/config")
def update_connector_config(connector_id: str, req: ConnectorConfigRequest):
    """Update connector configuration"""
    from .. import connector_state
    success = connector_state.update_config(connector_id, req.config)
    if not success:
        return {"error": "Connector not found"}, 404
    return connector_state.get_connector_summary(connector_id)


# =============================================================================
# ENABLE/DISABLE/RESET
# =============================================================================

@router.post("/{connector_id}/enable")
def enable_connector(connector_id: str):
    """Enable a connector"""
    from .. import connector_state
    success = connector_state.set_enabled(connector_id, True)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "enabled", "connector_id": connector_id}


@router.post("/{connector_id}/disable")
def disable_connector(connector_id: str):
    """Disable a connector"""
    from .. import connector_state
    success = connector_state.set_enabled(connector_id, False)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "disabled", "connector_id": connector_id}


@router.post("/{connector_id}/reset_errors")
def reset_connector_errors(connector_id: str):
    """Reset error counters for a connector"""
    from .. import connector_state
    success = connector_state.reset_errors(connector_id)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "errors_reset", "connector_id": connector_id}
