from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

@dataclass
class MemoryFact:
    """Persistente Wissenseinheit für Jarvis Memory."""
    id: str
    user_id: str
    namespace: str
    key: str
    value: Any
    confidence: float
    source: str
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    status: str = "active"
    tags: Optional[list] = field(default_factory=list)
    hygiene_metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status,
            "tags": self.tags,
            "hygiene_metadata": self.hygiene_metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryFact":
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            namespace=data["namespace"],
            key=data["key"],
            value=data["value"],
            confidence=data["confidence"],
            source=data["source"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None,
            status=data.get("status", "active"),
            tags=data.get("tags", []),
            hygiene_metadata=data.get("hygiene_metadata", {}),
        )
