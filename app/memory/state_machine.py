"""
Infer emotional and cognitive state from interaction patterns.

Implements ADHD-aware state inference based on conversation analysis.
Tracks: energy, focus, stress, emotional regulation (Jarvis feedback).
"""
from typing import Dict, Any, List
import logging
import re

logger = logging.getLogger(__name__)


class StateInference:
    """Infer user state from conversation patterns."""
    
    @staticmethod
    def infer_energy_level(messages: List[Dict], timing: Dict) -> int:
        """
        Infer energy level (1-10) from message patterns.
        
        Signals:
        - Short messages + rapid responses = high energy
        - Long detailed messages = focused energy
        - Slow responses = low energy
        - Many typos/abbreviations = rushed/low energy
        
        Args:
            messages: List of conversation messages
            timing: Timing metadata dict
            
        Returns:
            Energy level 1-10
        """
        if not messages:
            return 5  # neutral
        
        recent = messages[-5:]  # Last 5 messages
        
        # Extract message lengths (content can be string or list of dicts)
        lengths = []
        command_matches = []
        for m in recent:
            content = m.get("content", "")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # Claude API format: [{"type": "text", "text": "..."}]
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                text = " ".join(texts)
            
            lengths.append(len(text))
            command_matches.append(
                1 if any(cmd in text.lower() for cmd in ["do", "make", "build", "run", "fix", "start"]) else 0
            )
        
        avg_length = sum(lengths) / len(lengths) if lengths else 100
        avg_response_time = timing.get("avg_response_seconds", 30)
        
        energy = 5  # Start neutral
        
        # Long messages = engaged
        if avg_length > 200:
            energy += 2
        
        # Fast responses = high energy
        if avg_response_time < 10:
            energy += 1
        elif avg_response_time > 60:
            energy -= 2
        
        # Commands vs questions
        command_ratio = sum(command_matches) / len(recent)
        
        if command_ratio > 0.6:
            energy += 1  # Directive = energized
        
        return max(1, min(10, energy))
    
    @staticmethod
    def infer_focus_score(context_switches: int, tools_used: List[str]) -> int:
        """
        Infer focus (1-10) from context switching patterns.
        
        Signals:
        - Few context switches = high focus
        - Repeated use of same tools = focused workflow
        - Many domain jumps = scattered focus
        
        Args:
            context_switches: Number of topic/domain switches
            tools_used: List of tools used in session
            
        Returns:
            Focus score 1-10
        """
        focus = 8  # Start high
        
        # Penalize context switches
        if context_switches > 5:
            focus -= 3
        elif context_switches > 2:
            focus -= 1
        
        # Reward tool consistency
        if tools_used:
            unique_tools = len(set(tools_used))
            if unique_tools <= 2:
                focus += 1
            elif unique_tools > 5:
                focus -= 1
        
        return max(1, min(10, focus))
    
    @staticmethod
    def infer_stress_indicators(
        urgency_words: int,
        error_count: int,
        retry_count: int
    ) -> int:
        """
        Infer stress level (1-10) from urgency and errors.
        
        Signals:
        - Urgency words ("asap", "urgent", "now") = stress
        - Repeated errors = frustration
        - Many retries = blocked/stressed
        
        Args:
            urgency_words: Count of urgency indicators
            error_count: Number of errors encountered
            retry_count: Number of retry attempts
            
        Returns:
            Stress level 1-10
        """
        stress = 1  # Start low
        
        # Urgency language
        stress += min(urgency_words, 3)
        
        # Errors/failures
        stress += min(error_count, 3)
        
        # Retries
        stress += min(retry_count, 2)
        
        return max(1, min(10, stress))
    
    @staticmethod
    def infer_emotional_regulation(
        retry_count: int,
        error_recovery_time: float,
        task_abandonment_rate: float,
        frustration_keywords: int
    ) -> int:
        """
        Infer emotional regulation (1-10) for ADHD patterns.
        
        **JARVIS FEEDBACK**: Critical metric for ADHD - how well user handles
        frustration, overwhelm, and emotional peaks.
        
        Signals:
        - Low retries + fast error recovery = good regulation
        - Many retries + slow recovery = frustration
        - High task abandonment = overwhelm
        - Frustration keywords ("argh", "damn", "wtf") = low regulation
        
        Args:
            retry_count: Number of retry attempts
            error_recovery_time: Seconds to recover from error
            task_abandonment_rate: Ratio of abandoned tasks (0-1)
            frustration_keywords: Count of frustration language
            
        Returns:
            Emotional regulation score 1-10
        """
        regulation = 7  # Start optimistic
        
        # Penalize excessive retries
        if retry_count > 3:
            regulation -= 2
        
        # Penalize slow error recovery
        if error_recovery_time > 60:  # >1 min to recover from error
            regulation -= 1
        
        # Penalize task abandonment
        if task_abandonment_rate > 0.3:  # >30% tasks abandoned
            regulation -= 2
        
        # Penalize frustration language
        regulation -= min(frustration_keywords, 2)
        
        return max(1, min(10, regulation))
    
    @staticmethod
    def infer_conversation_tone(messages: List[Dict]) -> str:
        """
        Classify conversation tone.
        
        Returns: collaborative | directive | exploratory | troubleshooting
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Tone classification string
        """
        if not messages:
            return "collaborative"
        
        # Extract text from messages (content can be string or list of dicts)
        recent_texts = []
        for m in messages[-5:]:
            content = m.get("content", "")
            if isinstance(content, str):
                recent_texts.append(content)
            elif isinstance(content, list):
                # Claude API format: [{"type": "text", "text": "..."}]
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        recent_texts.append(block.get("text", ""))
        
        recent = " ".join(recent_texts).lower()
        
        # Keyword-based classification
        if any(word in recent for word in ["fix", "error", "broken", "issue", "problem", "failing"]):
            return "troubleshooting"
        
        if any(word in recent for word in ["explore", "what if", "could we", "consider", "maybe", "alternatively"]):
            return "exploratory"
        
        if any(word in recent for word in ["do", "make", "build", "create", "implement", "start", "go"]):
            return "directive"
        
        return "collaborative"
    
    @staticmethod
    def extract_active_domains(tools_used: List[str], topics: List[str]) -> List[str]:
        """
        Extract active work domains from tools and topics.
        
        Args:
            tools_used: List of tool names used
            topics: List of topics discussed
            
        Returns:
            List of active domain strings
        """
        domains = set()
        
        # Map tools to domains
        tool_domain_map = {
            "search_knowledge": "research",
            "recall_facts": "memory",
            "file_operations": "code",
            "run_terminal": "ops",
            "docker": "infrastructure",
            "git": "version_control",
            "test": "testing"
        }
        
        for tool in tools_used:
            if tool in tool_domain_map:
                domains.add(tool_domain_map[tool])
        
        # Add topics directly
        domains.update(topics)
        
        return list(domains)
    
    @staticmethod
    def count_frustration_keywords(messages: List[Dict]) -> int:
        """
        Count frustration language indicators.
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Count of frustration keywords
        """
        frustration_patterns = [
            r'\b(argh|ugh|damn|wtf|ffs|shit|fuck|goddamn)\b',
            r'\b(warum\s+nicht|wieso\s+nicht|geht\s+nicht)\b',
            r'!!!+',  # Multiple exclamation marks
            r'\b(nervt|nervös|frustriert|gestresst)\b'
        ]
        
        count = 0
        # Extract text from messages (content can be string or list of dicts)
        recent_texts = []
        for m in messages[-10:]:
            content = m.get("content", "")
            if isinstance(content, str):
                recent_texts.append(content)
            elif isinstance(content, list):
                # Claude API format: [{"type": "text", "text": "..."}]
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        recent_texts.append(block.get("text", ""))
        
        recent = " ".join(recent_texts).lower()
        
        for pattern in frustration_patterns:
            count += len(re.findall(pattern, recent))
        
        return count
    
    @staticmethod
    def count_urgency_keywords(messages: List[Dict]) -> int:
        """
        Count urgency language indicators.
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Count of urgency keywords
        """
        urgency_patterns = [
            r'\b(asap|urgent|now|immediately|schnell|sofort|dringend)\b',
            r'\b(heute|today|jetzt|right\s+now)\b'
        ]
        
        count = 0
        # Extract text from messages (content can be string or list of dicts)
        recent_texts = []
        for m in messages[-10:]:
            content = m.get("content", "")
            if isinstance(content, str):
                recent_texts.append(content)
            elif isinstance(content, list):
                # Claude API format: [{"type": "text", "text": "..."}]
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        recent_texts.append(block.get("text", ""))
        
        recent = " ".join(recent_texts).lower()
        
        for pattern in urgency_patterns:
            count += len(re.findall(pattern, recent))
        
        return count
