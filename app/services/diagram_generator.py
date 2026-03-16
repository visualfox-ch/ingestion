"""
Diagram Generator Service

Generates diagrams using matplotlib for simple cases,
and Mermaid syntax for complex diagrams (renderable via kroki.io or mermaid-cli).

Supported diagram types:
- flowchart: Process flows, decision trees
- sequence: Message sequence diagrams
- mindmap: Hierarchical mind maps
- timeline: Event timelines
"""

import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import tempfile
import aiohttp
import asyncio

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

logger = logging.getLogger(__name__)

# Kroki.io service URL (free diagram rendering service)
KROKI_URL = "https://kroki.io"


@dataclass
class DiagramResult:
    """Result of diagram generation."""
    success: bool
    image_bytes: Optional[bytes] = None
    image_base64: Optional[str] = None
    mermaid_code: Optional[str] = None
    file_path: Optional[str] = None
    error: Optional[str] = None
    diagram_type: str = ""


class DiagramGenerator:
    """
    Generates diagrams using matplotlib or Mermaid/Kroki.

    For simple diagrams (flowchart, timeline), uses matplotlib directly.
    For complex diagrams, generates Mermaid code and optionally renders via Kroki.
    """

    def __init__(self, style: str = "dark", use_kroki: bool = True):
        self.style = style
        self.use_kroki = use_kroki
        self._colors = {
            'background': '#1e1e2e' if style == 'dark' else '#ffffff',
            'text': '#cdd6f4' if style == 'dark' else '#333333',
            'node': '#89b4fa' if style == 'dark' else '#4a90d9',
            'node_text': '#1e1e2e' if style == 'dark' else '#ffffff',
            'arrow': '#cdd6f4' if style == 'dark' else '#333333',
            'decision': '#f9e2af' if style == 'dark' else '#f0c674',
            'process': '#a6e3a1' if style == 'dark' else '#8dc891',
            'start_end': '#f38ba8' if style == 'dark' else '#e06c75',
        }

    async def render_mermaid(self, mermaid_code: str) -> Optional[bytes]:
        """Render Mermaid code to PNG using Kroki.io."""
        if not self.use_kroki:
            return None

        try:
            # Kroki expects base64-encoded, deflate-compressed code
            import zlib
            compressed = zlib.compress(mermaid_code.encode('utf-8'), 9)
            encoded = base64.urlsafe_b64encode(compressed).decode('utf-8')

            url = f"{KROKI_URL}/mermaid/png/{encoded}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.warning(f"Kroki returned {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"Failed to render via Kroki: {e}")
            return None

    # =========================================================================
    # Flowchart
    # =========================================================================

    def generate_flowchart(
        self,
        nodes: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        title: Optional[str] = None,
        direction: str = "TD",  # TD (top-down) or LR (left-right)
        figsize: Tuple[int, int] = (12, 8),
        save_to_file: bool = False,
    ) -> DiagramResult:
        """
        Generate a flowchart.

        Args:
            nodes: [{"id": "A", "label": "Start", "type": "start|process|decision|end"}]
            connections: [{"from": "A", "to": "B", "label": "yes"}]
            direction: "TD" (top-down) or "LR" (left-right)

        Returns:
            DiagramResult with image and Mermaid code
        """
        try:
            # Generate Mermaid code
            mermaid = self._generate_flowchart_mermaid(nodes, connections, direction)

            # Also generate matplotlib version
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_facecolor(self._colors['background'])
            ax.set_facecolor(self._colors['background'])

            # Calculate positions
            node_positions = self._calculate_flowchart_positions(nodes, connections, direction)

            # Draw connections first (so nodes are on top)
            for conn in connections:
                self._draw_connection(ax, conn, node_positions)

            # Draw nodes
            for node in nodes:
                self._draw_node(ax, node, node_positions)

            ax.set_xlim(-1, 11)
            ax.set_ylim(-1, 9)
            ax.set_aspect('equal')
            ax.axis('off')

            if title:
                ax.set_title(title, color=self._colors['text'], fontsize=14, pad=20)

            return self._finalize_diagram(fig, mermaid, "flowchart", save_to_file)

        except Exception as e:
            logger.error(f"Failed to generate flowchart: {e}")
            return DiagramResult(success=False, error=str(e), diagram_type="flowchart")

    def _generate_flowchart_mermaid(
        self,
        nodes: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        direction: str
    ) -> str:
        """Generate Mermaid flowchart code."""
        lines = [f"flowchart {direction}"]

        # Define nodes
        for node in nodes:
            node_id = node["id"]
            label = node.get("label", node_id)
            node_type = node.get("type", "process")

            if node_type == "start" or node_type == "end":
                lines.append(f"    {node_id}(({label}))")
            elif node_type == "decision":
                lines.append(f"    {node_id}{{{label}}}")
            else:
                lines.append(f"    {node_id}[{label}]")

        # Define connections
        for conn in connections:
            from_id = conn["from"]
            to_id = conn["to"]
            label = conn.get("label", "")

            if label:
                lines.append(f"    {from_id} -->|{label}| {to_id}")
            else:
                lines.append(f"    {from_id} --> {to_id}")

        return "\n".join(lines)

    def _calculate_flowchart_positions(
        self,
        nodes: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        direction: str
    ) -> Dict[str, Tuple[float, float]]:
        """Calculate node positions for matplotlib rendering."""
        positions = {}
        n = len(nodes)

        if direction == "TD":
            for i, node in enumerate(nodes):
                # Simple vertical layout
                x = 5
                y = 8 - (i * 8 / max(n - 1, 1))
                positions[node["id"]] = (x, y)
        else:  # LR
            for i, node in enumerate(nodes):
                x = i * 10 / max(n - 1, 1)
                y = 4
                positions[node["id"]] = (x, y)

        return positions

    def _draw_node(self, ax, node: Dict[str, Any], positions: Dict[str, Tuple[float, float]]):
        """Draw a flowchart node."""
        node_id = node["id"]
        label = node.get("label", node_id)
        node_type = node.get("type", "process")
        x, y = positions.get(node_id, (0, 0))

        if node_type in ("start", "end"):
            color = self._colors['start_end']
            circle = plt.Circle((x, y), 0.5, color=color, ec=self._colors['arrow'], linewidth=2)
            ax.add_patch(circle)
        elif node_type == "decision":
            color = self._colors['decision']
            diamond = mpatches.RegularPolygon((x, y), 4, 0.7, color=color,
                                              ec=self._colors['arrow'], linewidth=2)
            ax.add_patch(diamond)
        else:
            color = self._colors['process']
            rect = FancyBboxPatch((x - 0.8, y - 0.4), 1.6, 0.8,
                                  boxstyle="round,pad=0.05", color=color,
                                  ec=self._colors['arrow'], linewidth=2)
            ax.add_patch(rect)

        ax.text(x, y, label, ha='center', va='center',
               color=self._colors['node_text'], fontsize=10, fontweight='bold')

    def _draw_connection(self, ax, conn: Dict[str, Any], positions: Dict[str, Tuple[float, float]]):
        """Draw a connection arrow."""
        from_id = conn["from"]
        to_id = conn["to"]
        label = conn.get("label", "")

        if from_id not in positions or to_id not in positions:
            return

        x1, y1 = positions[from_id]
        x2, y2 = positions[to_id]

        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                   arrowprops=dict(arrowstyle="->", color=self._colors['arrow'],
                                  lw=1.5, connectionstyle="arc3,rad=0"))

        if label:
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            ax.text(mid_x + 0.2, mid_y, label, fontsize=8, color=self._colors['text'])

    # =========================================================================
    # Sequence Diagram
    # =========================================================================

    def generate_sequence(
        self,
        participants: List[str],
        messages: List[Dict[str, Any]],
        title: Optional[str] = None,
        figsize: Tuple[int, int] = (12, 8),
        save_to_file: bool = False,
    ) -> DiagramResult:
        """
        Generate a sequence diagram.

        Args:
            participants: ["Client", "Server", "Database"]
            messages: [{"from": "Client", "to": "Server", "label": "Request", "type": "sync|async|return"}]

        Returns:
            DiagramResult with image and Mermaid code
        """
        try:
            # Generate Mermaid code
            mermaid = self._generate_sequence_mermaid(participants, messages)

            # Generate matplotlib version
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_facecolor(self._colors['background'])
            ax.set_facecolor(self._colors['background'])

            n_participants = len(participants)
            n_messages = len(messages)

            # Draw participant boxes and lifelines
            participant_x = {}
            for i, p in enumerate(participants):
                x = i * 3 + 1
                participant_x[p] = x

                # Box at top
                rect = FancyBboxPatch((x - 0.8, n_messages + 1), 1.6, 0.6,
                                      boxstyle="round,pad=0.05", color=self._colors['node'],
                                      ec=self._colors['arrow'], linewidth=2)
                ax.add_patch(rect)
                ax.text(x, n_messages + 1.3, p, ha='center', va='center',
                       color=self._colors['node_text'], fontsize=10, fontweight='bold')

                # Lifeline
                ax.plot([x, x], [n_messages + 0.8, 0.5], '--', color=self._colors['arrow'],
                       linewidth=1, alpha=0.5)

            # Draw messages
            for i, msg in enumerate(messages):
                y = n_messages - i
                from_x = participant_x.get(msg["from"], 1)
                to_x = participant_x.get(msg["to"], 4)
                label = msg.get("label", "")
                msg_type = msg.get("type", "sync")

                # Arrow style based on type
                if msg_type == "return":
                    style = "-->"
                    linestyle = "--"
                elif msg_type == "async":
                    style = "->>"
                    linestyle = "-"
                else:
                    style = "->"
                    linestyle = "-"

                ax.annotate("", xy=(to_x, y), xytext=(from_x, y),
                           arrowprops=dict(arrowstyle="->", color=self._colors['arrow'],
                                          lw=1.5, linestyle=linestyle))

                # Label above arrow
                mid_x = (from_x + to_x) / 2
                ax.text(mid_x, y + 0.15, label, ha='center', va='bottom',
                       color=self._colors['text'], fontsize=9)

            ax.set_xlim(-0.5, n_participants * 3 + 0.5)
            ax.set_ylim(0, n_messages + 2)
            ax.axis('off')

            if title:
                ax.set_title(title, color=self._colors['text'], fontsize=14, pad=20)

            return self._finalize_diagram(fig, mermaid, "sequence", save_to_file)

        except Exception as e:
            logger.error(f"Failed to generate sequence diagram: {e}")
            return DiagramResult(success=False, error=str(e), diagram_type="sequence")

    def _generate_sequence_mermaid(
        self,
        participants: List[str],
        messages: List[Dict[str, Any]]
    ) -> str:
        """Generate Mermaid sequence diagram code."""
        lines = ["sequenceDiagram"]

        # Participants
        for p in participants:
            lines.append(f"    participant {p}")

        # Messages
        for msg in messages:
            from_p = msg["from"]
            to_p = msg["to"]
            label = msg.get("label", "")
            msg_type = msg.get("type", "sync")

            if msg_type == "return":
                arrow = "-->>"
            elif msg_type == "async":
                arrow = "->>"
            else:
                arrow = "->>"

            lines.append(f"    {from_p}{arrow}{to_p}: {label}")

        return "\n".join(lines)

    # =========================================================================
    # Timeline
    # =========================================================================

    def generate_timeline(
        self,
        events: List[Dict[str, Any]],
        title: Optional[str] = None,
        figsize: Tuple[int, int] = (14, 6),
        save_to_file: bool = False,
    ) -> DiagramResult:
        """
        Generate a timeline diagram.

        Args:
            events: [{"date": "2024-01", "label": "Event 1", "description": "Details"}]

        Returns:
            DiagramResult with image
        """
        try:
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_facecolor(self._colors['background'])
            ax.set_facecolor(self._colors['background'])

            n = len(events)
            colors = ['#89b4fa', '#f38ba8', '#a6e3a1', '#fab387', '#cba6f7', '#94e2d5']

            # Draw timeline
            ax.plot([0, n + 1], [0, 0], color=self._colors['arrow'], linewidth=3)

            for i, event in enumerate(events):
                x = i + 1
                y_offset = 0.5 if i % 2 == 0 else -0.5
                color = colors[i % len(colors)]

                # Marker on timeline
                ax.scatter([x], [0], s=150, color=color, zorder=5, edgecolors=self._colors['arrow'])

                # Vertical line to label
                ax.plot([x, x], [0, y_offset * 0.8], color=self._colors['arrow'], linewidth=1)

                # Event box
                rect = FancyBboxPatch((x - 0.4, y_offset - 0.15 if y_offset > 0 else y_offset + 0.05),
                                      0.8, 0.3, boxstyle="round,pad=0.02",
                                      color=color, alpha=0.3, ec=color, linewidth=1)
                ax.add_patch(rect)

                # Date
                ax.text(x, y_offset, event.get("date", ""), ha='center', va='center',
                       color=self._colors['text'], fontsize=10, fontweight='bold')

                # Label
                label_y = y_offset + 0.35 if y_offset > 0 else y_offset - 0.35
                ax.text(x, label_y, event.get("label", ""), ha='center',
                       va='bottom' if y_offset > 0 else 'top',
                       color=self._colors['text'], fontsize=9)

            ax.set_xlim(-0.5, n + 1.5)
            ax.set_ylim(-1.5, 1.5)
            ax.axis('off')

            if title:
                ax.set_title(title, color=self._colors['text'], fontsize=14, pad=20)

            # No Mermaid for timeline (not well supported)
            return self._finalize_diagram(fig, None, "timeline", save_to_file)

        except Exception as e:
            logger.error(f"Failed to generate timeline: {e}")
            return DiagramResult(success=False, error=str(e), diagram_type="timeline")

    # =========================================================================
    # Mind Map
    # =========================================================================

    def generate_mindmap_mermaid(
        self,
        root: str,
        branches: Dict[str, Any],
    ) -> str:
        """
        Generate Mermaid mindmap code.

        Args:
            root: Central topic
            branches: {"Topic1": ["Sub1", "Sub2"], "Topic2": {"SubA": ["Detail1"]}}

        Returns:
            Mermaid code string
        """
        lines = ["mindmap", f"  root(({root}))"]

        def add_branches(items: Any, indent: int = 2):
            prefix = "  " * indent
            if isinstance(items, dict):
                for key, value in items.items():
                    lines.append(f"{prefix}{key}")
                    add_branches(value, indent + 1)
            elif isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        add_branches(item, indent)
                    else:
                        lines.append(f"{prefix}{item}")

        add_branches(branches)
        return "\n".join(lines)

    # =========================================================================
    # Utilities
    # =========================================================================

    def _finalize_diagram(
        self,
        fig,
        mermaid_code: Optional[str],
        diagram_type: str,
        save_to_file: bool
    ) -> DiagramResult:
        """Finalize diagram and return result."""
        try:
            plt.tight_layout()

            # Save to bytes
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                       facecolor=fig.get_facecolor(), edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()

            # Optionally save to file
            file_path = None
            if save_to_file:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(image_bytes)
                    file_path = f.name

            plt.close(fig)

            return DiagramResult(
                success=True,
                image_bytes=image_bytes,
                image_base64=base64.b64encode(image_bytes).decode('utf-8'),
                mermaid_code=mermaid_code,
                file_path=file_path,
                diagram_type=diagram_type,
            )

        except Exception as e:
            plt.close(fig)
            logger.error(f"Failed to finalize diagram: {e}")
            return DiagramResult(success=False, error=str(e), diagram_type=diagram_type)

    async def generate_from_mermaid(
        self,
        mermaid_code: str,
        save_to_file: bool = False,
    ) -> DiagramResult:
        """
        Generate diagram from raw Mermaid code using Kroki.

        Args:
            mermaid_code: Valid Mermaid diagram code

        Returns:
            DiagramResult with rendered image
        """
        try:
            image_bytes = await self.render_mermaid(mermaid_code)

            if image_bytes:
                file_path = None
                if save_to_file:
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                        f.write(image_bytes)
                        file_path = f.name

                return DiagramResult(
                    success=True,
                    image_bytes=image_bytes,
                    image_base64=base64.b64encode(image_bytes).decode('utf-8'),
                    mermaid_code=mermaid_code,
                    file_path=file_path,
                    diagram_type="mermaid",
                )
            else:
                return DiagramResult(
                    success=False,
                    error="Failed to render Mermaid via Kroki",
                    mermaid_code=mermaid_code,
                    diagram_type="mermaid",
                )

        except Exception as e:
            logger.error(f"Failed to generate from Mermaid: {e}")
            return DiagramResult(success=False, error=str(e), diagram_type="mermaid")


# Singleton instance
_diagram_generator: Optional[DiagramGenerator] = None


def get_diagram_generator(style: str = "dark") -> DiagramGenerator:
    """Get the singleton DiagramGenerator instance."""
    global _diagram_generator
    if _diagram_generator is None:
        _diagram_generator = DiagramGenerator(style=style)
    return _diagram_generator
