"""
Generation Tools.

Diagram and image generation.
Extracted from tools.py (Phase S6).
"""
from typing import Dict, Any
from datetime import datetime
import os
import re

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.generation")

BRAIN_PATH = os.getenv("BRAIN_PATH", "/brain")


def tool_generate_diagram(
    diagram_type: str,
    content: Dict[str, Any],
    title: str = None,
    render_image: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate diagrams and visualizations.

    Jarvis can create visual representations of ideas, processes, and relationships.

    Args:
        diagram_type: Type of diagram (flowchart, mindmap, sequence, timeline)
        content: Diagram content structure (varies by type)
        title: Optional title for the diagram
        render_image: If True, render to PNG via Kroki.io (otherwise return Mermaid code)

    Content structure examples:
    - flowchart: {"nodes": [{"id": "a", "label": "Start", "type": "start"}], "edges": [{"from": "a", "to": "b"}]}
    - mindmap: {"root": "Main Topic", "children": [{"label": "Subtopic", "children": [...]}]}
    - sequence: {"actors": ["A", "B"], "messages": [{"from": "A", "to": "B", "text": "Hello"}]}
    - timeline: {"events": [{"date": "2026-01", "label": "Event 1"}]}

    Returns:
        Mermaid code and optionally rendered image (base64)
    """
    log_with_context(logger, "info", "Tool: generate_diagram", diagram_type=diagram_type)
    metrics.inc("tool_generate_diagram")

    try:
        # Generate Mermaid code based on diagram type
        mermaid_code = ""

        if diagram_type == "flowchart":
            mermaid_code = "flowchart TD\n"
            nodes = content.get("nodes", [])
            edges = content.get("edges", [])

            for node in nodes:
                node_id = node.get("id", "")
                label = node.get("label", node_id)
                node_type = node.get("type", "process")

                if node_type == "start" or node_type == "end":
                    mermaid_code += f"    {node_id}(({label}))\n"
                elif node_type == "decision":
                    mermaid_code += f"    {node_id}{{{label}}}\n"
                else:
                    mermaid_code += f"    {node_id}[{label}]\n"

            for edge in edges:
                from_id = edge.get("from", "")
                to_id = edge.get("to", "")
                label = edge.get("label", "")
                if label:
                    mermaid_code += f"    {from_id} -->|{label}| {to_id}\n"
                else:
                    mermaid_code += f"    {from_id} --> {to_id}\n"

        elif diagram_type == "mindmap":
            mermaid_code = "mindmap\n"
            root = content.get("root", "Root")
            mermaid_code += f"  root(({root}))\n"

            def add_children(children, indent=2):
                code = ""
                for child in children:
                    label = child.get("label", "")
                    spaces = "  " * indent
                    code += f"{spaces}{label}\n"
                    if "children" in child:
                        code += add_children(child["children"], indent + 1)
                return code

            if "children" in content:
                mermaid_code += add_children(content["children"])

        elif diagram_type == "sequence":
            mermaid_code = "sequenceDiagram\n"
            actors = content.get("actors", [])
            messages = content.get("messages", [])

            for actor in actors:
                mermaid_code += f"    participant {actor}\n"

            for msg in messages:
                from_actor = msg.get("from", "")
                to_actor = msg.get("to", "")
                text = msg.get("text", "")
                arrow = msg.get("arrow", "->>")  # ->> solid, -->> dashed
                mermaid_code += f"    {from_actor}{arrow}{to_actor}: {text}\n"

        elif diagram_type == "timeline":
            mermaid_code = "timeline\n"
            if title:
                mermaid_code += f"    title {title}\n"
            events = content.get("events", [])
            for event in events:
                date = event.get("date", "")
                label = event.get("label", "")
                mermaid_code += f"    {date} : {label}\n"

        else:
            return {"error": f"Unknown diagram type: {diagram_type}. Supported: flowchart, mindmap, sequence, timeline"}

        result = {
            "diagram_type": diagram_type,
            "mermaid_code": mermaid_code,
            "render_url": f"https://mermaid.live/edit#pako:{mermaid_code[:100]}...",
            "hint": "Dieser Mermaid-Code kann in Obsidian, GitHub, oder mermaid.live gerendert werden"
        }

        # Optionally render via Kroki
        if render_image:
            try:
                import asyncio
                from ..services.diagram_generator import DiagramGenerator
                generator = DiagramGenerator()
                loop = asyncio.new_event_loop()
                image_bytes = loop.run_until_complete(generator.render_mermaid(mermaid_code))
                loop.close()

                if image_bytes:
                    import base64
                    result["image_base64"] = base64.b64encode(image_bytes).decode('utf-8')
                    result["rendered"] = True
            except Exception as render_err:
                result["render_error"] = str(render_err)
                result["rendered"] = False

        return result

    except Exception as e:
        log_with_context(logger, "error", "generate_diagram failed", error=str(e))
        return {"error": str(e)}


# ============ Cross-Session Memory with Timeframe (Jarvis Wish: Deep Memory) ============

def tool_generate_image(
    prompt: str,
    style: str = "natural",
    size: str = "1024x1024",
    quality: str = "standard",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate images using DALL-E 3.

    Jarvis can create images from text descriptions for:
    - Concept visualization
    - Creative projects
    - Mood boards / inspiration
    - Quick mockups

    Args:
        prompt: Description of the image to generate (detailed prompts work best)
        style: Image style - 'natural' (photorealistic) or 'vivid' (artistic/dramatic)
        size: Image size - '1024x1024', '1792x1024' (landscape), '1024x1792' (portrait)
        quality: 'standard' or 'hd' (more detail, higher cost)

    Returns:
        URL to generated image and revised prompt from DALL-E
    """
    log_with_context(logger, "info", "Tool: generate_image", prompt_length=len(prompt), style=style)
    metrics.inc("tool_generate_image")

    try:
        import openai

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"error": "OPENAI_API_KEY not configured"}

        client = openai.OpenAI(api_key=api_key)

        # Validate parameters
        valid_sizes = ["1024x1024", "1792x1024", "1024x1792"]
        if size not in valid_sizes:
            size = "1024x1024"

        valid_styles = ["natural", "vivid"]
        if style not in valid_styles:
            style = "natural"

        valid_qualities = ["standard", "hd"]
        if quality not in valid_qualities:
            quality = "standard"

        # Call DALL-E 3
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
            n=1
        )

        image_data = response.data[0]

        result = {
            "success": True,
            "url": image_data.url,
            "revised_prompt": image_data.revised_prompt,
            "size": size,
            "style": style,
            "quality": quality,
            "expires_info": "URL expires after ~1 hour - download or share immediately"
        }

        log_with_context(logger, "info", "Image generated successfully",
                        revised_prompt_length=len(image_data.revised_prompt or ""))

        return result

    except openai.BadRequestError as e:
        # Content policy violation
        error_msg = str(e)
        log_with_context(logger, "warning", "Image generation blocked by content policy", error=error_msg)
        return {
            "error": "content_policy",
            "message": "Der Prompt wurde von OpenAI's Content Policy blockiert. Bitte formuliere anders.",
            "details": error_msg
        }
    except Exception as e:
        log_with_context(logger, "error", "generate_image failed", error=str(e))
        return {"error": str(e)}


# ============ Phase 21: Intelligent System Evolution Tools ============

# T-21A-01: Smart Tool Chains
