"""
Token Budget Manager for Context Assembly.

Implements token budgeting policy from /brain/system/docs/CONTEXT_POLICY.md
to control latency and cost by enforcing hard caps on prompt component sizes.

Budget allocation:
- System prompt: 20-25% 
- Memory (session + snapshots): 15-20%
- Retrieval (RAG): 35-45%
- User input: 10-20%
- Tool outputs: 10-15%

Author: GitHub Copilot
Created: 2026-02-04
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.token_budget")


class ComponentType(Enum):
    """Categories of prompt components for budget allocation."""
    SYSTEM = "system"
    MEMORY = "memory"
    RETRIEVAL = "retrieval"
    USER_INPUT = "user_input"
    TOOL_OUTPUT = "tool_output"


@dataclass
class BudgetAllocation:
    """Budget allocation percentages for each component type."""
    system_min: float = 0.20
    system_max: float = 0.25
    memory_min: float = 0.15
    memory_max: float = 0.20
    retrieval_min: float = 0.35
    retrieval_max: float = 0.45
    user_input_min: float = 0.10
    user_input_max: float = 0.20
    tool_output_min: float = 0.10
    tool_output_max: float = 0.15

    def get_range(self, component: ComponentType) -> tuple[float, float]:
        """Get min/max budget percentages for a component."""
        mapping = {
            ComponentType.SYSTEM: (self.system_min, self.system_max),
            ComponentType.MEMORY: (self.memory_min, self.memory_max),
            ComponentType.RETRIEVAL: (self.retrieval_min, self.retrieval_max),
            ComponentType.USER_INPUT: (self.user_input_min, self.user_input_max),
            ComponentType.TOOL_OUTPUT: (self.tool_output_min, self.tool_output_max),
        }
        return mapping.get(component, (0.0, 0.0))


@dataclass
class TokenUsage:
    """Tracks token usage for a component."""
    component: ComponentType
    tokens: int
    content_preview: str = ""  # First 100 chars for debugging


@dataclass
class BudgetReport:
    """Report of budget usage and enforcement actions."""
    total_budget: int
    total_used: int
    by_component: Dict[ComponentType, int] = field(default_factory=dict)
    trimmed: List[str] = field(default_factory=list)  # Components that were trimmed
    warnings: List[str] = field(default_factory=list)
    over_budget: bool = False

    def get_usage_percentage(self, component: ComponentType) -> float:
        """Get percentage of total budget used by component."""
        if self.total_budget == 0:
            return 0.0
        return (self.by_component.get(component, 0) / self.total_budget) * 100


class TokenBudgetManager:
    """
    Manages token budget allocation and enforcement.
    
    Usage:
        budget = TokenBudgetManager(total_budget=100000)
        budget.allocate(ComponentType.SYSTEM, system_prompt, priority=1)
        budget.allocate(ComponentType.MEMORY, session_memory, priority=2)
        # ... etc
        report = budget.get_report()
        if report.over_budget:
            budget.enforce()  # Trim lowest priority items
    """

    # Rough estimation: 1 token ≈ 4 characters for English, ~3 for German
    CHARS_PER_TOKEN = 3.5

    def __init__(
        self,
        total_budget: int = 100000,  # Claude Sonnet 4 context window: 200k
        allocation: Optional[BudgetAllocation] = None,
        enforce_on_add: bool = False
    ):
        """
        Initialize budget manager.
        
        Args:
            total_budget: Maximum tokens for entire prompt
            allocation: Budget allocation rules (defaults to CONTEXT_POLICY.md spec)
            enforce_on_add: If True, enforce budget immediately when adding components
        """
        self.total_budget = total_budget
        self.allocation = allocation or BudgetAllocation()
        self.enforce_on_add = enforce_on_add

        # Tracking
        self._components: List[tuple[ComponentType, str, int]] = []  # (type, content, priority)
        self._usage_by_type: Dict[ComponentType, int] = {}
        self._trimmed: List[str] = []
        self._warnings: List[str] = []

    def allocate(
        self,
        component_type: ComponentType,
        content: str,
        priority: int = 5
    ) -> bool:
        """
        Allocate budget for a component.
        
        Args:
            component_type: Type of component (SYSTEM, MEMORY, etc.)
            content: Text content
            priority: Priority level (1=highest, 10=lowest). Lower priority items trimmed first.
            
        Returns:
            True if added successfully, False if rejected
        """
        tokens = self._estimate_tokens(content)
        
        # Check if adding this would exceed component budget
        current_usage = self._usage_by_type.get(component_type, 0)
        new_usage = current_usage + tokens
        min_pct, max_pct = self.allocation.get_range(component_type)
        max_tokens = int(self.total_budget * max_pct)

        if new_usage > max_tokens:
            self._warnings.append(
                f"{component_type.value} would exceed budget: "
                f"{new_usage} tokens > {max_tokens} max ({max_pct*100:.0f}%)"
            )
            
            if self.enforce_on_add:
                # Try to trim existing lower-priority items of same type
                self._trim_component_type(component_type, tokens_needed=new_usage - max_tokens)
                
                # Recalculate after trimming
                current_usage = self._usage_by_type.get(component_type, 0)
                new_usage = current_usage + tokens
                
                if new_usage > max_tokens:
                    log_with_context(
                        logger, "warning",
                        f"Rejecting {component_type.value} component",
                        tokens=tokens, max_tokens=max_tokens
                    )
                    return False

        # Add component
        self._components.append((component_type, content, priority))
        self._usage_by_type[component_type] = new_usage

        log_with_context(
            logger, "debug",
            f"Allocated {component_type.value}",
            tokens=tokens, priority=priority,
            total_usage=sum(self._usage_by_type.values())
        )

        return True

    def enforce(self) -> None:
        """Enforce budget by trimming lowest priority components."""
        total_used = sum(self._usage_by_type.values())
        
        if total_used <= self.total_budget:
            return  # Within budget
        
        tokens_to_remove = total_used - self.total_budget
        log_with_context(
            logger, "info",
            "Enforcing token budget",
            total_used=total_used,
            total_budget=self.total_budget,
            tokens_to_remove=tokens_to_remove
        )

        # Sort components by priority (lowest priority first)
        sorted_components = sorted(self._components, key=lambda x: x[2], reverse=True)
        
        removed_tokens = 0
        components_to_keep = []
        
        for comp_type, content, priority in sorted_components:
            tokens = self._estimate_tokens(content)
            
            if removed_tokens < tokens_to_remove:
                # Remove this component
                self._trimmed.append(f"{comp_type.value} (priority {priority}, {tokens} tokens)")
                self._usage_by_type[comp_type] = max(0, self._usage_by_type.get(comp_type, 0) - tokens)
                removed_tokens += tokens
                log_with_context(
                    logger, "debug",
                    f"Trimmed {comp_type.value} component",
                    priority=priority, tokens=tokens
                )
            else:
                components_to_keep.append((comp_type, content, priority))
        
        self._components = components_to_keep
        log_with_context(
            logger, "info",
            "Budget enforcement complete",
            trimmed_count=len(self._trimmed),
            removed_tokens=removed_tokens
        )

    def get_report(self) -> BudgetReport:
        """Generate budget usage report."""
        total_used = sum(self._usage_by_type.values())
        
        return BudgetReport(
            total_budget=self.total_budget,
            total_used=total_used,
            by_component=self._usage_by_type.copy(),
            trimmed=self._trimmed.copy(),
            warnings=self._warnings.copy(),
            over_budget=(total_used > self.total_budget)
        )

    def get_final_content(self) -> Dict[ComponentType, List[str]]:
        """Get final content organized by component type after budget enforcement."""
        result: Dict[ComponentType, List[str]] = {}
        
        for comp_type, content, _ in self._components:
            if comp_type not in result:
                result[comp_type] = []
            result[comp_type].append(content)
        
        return result

    def _trim_component_type(self, component_type: ComponentType, tokens_needed: int) -> None:
        """Trim lowest priority items of a specific component type."""
        # Get all components of this type, sorted by priority (lowest first)
        same_type = [
            (content, priority, i)
            for i, (ct, content, priority) in enumerate(self._components)
            if ct == component_type
        ]
        same_type.sort(key=lambda x: x[1], reverse=True)  # Lowest priority first
        
        removed_tokens = 0
        indices_to_remove = []
        
        for content, priority, idx in same_type:
            if removed_tokens >= tokens_needed:
                break
            
            tokens = self._estimate_tokens(content)
            indices_to_remove.append(idx)
            removed_tokens += tokens
            self._trimmed.append(f"{component_type.value} (priority {priority}, {tokens} tokens)")
        
        # Remove components (in reverse order to preserve indices)
        for idx in sorted(indices_to_remove, reverse=True):
            comp_type, content, _ = self._components[idx]
            tokens = self._estimate_tokens(content)
            self._usage_by_type[comp_type] = max(0, self._usage_by_type.get(comp_type, 0) - tokens)
            del self._components[idx]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count from text length."""
        if not text:
            return 0
        return int(len(text) / TokenBudgetManager.CHARS_PER_TOKEN)
