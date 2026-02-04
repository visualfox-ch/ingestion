"""
Session memory and state tracking for Jarvis consciousness.

Phase 1: Persistent session state across conversations.
Enables Jarvis to "remember" context, emotional state, and work patterns.

Phase 1.5: Session Snapshots (Feb 3, 2026)
Added SessionSnapshot for structured consciousness continuity.
"""
from .memory_store import MemoryStore, SessionSnapshot
from .state_machine import StateInference

__all__ = ['MemoryStore', 'SessionSnapshot', 'StateInference']
