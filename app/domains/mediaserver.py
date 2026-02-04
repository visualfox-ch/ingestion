"""
Mediaserver Coaching Domain

Specialized coaching for Media Server Lead work:
- Pixera show systems (timeline, mapping, output config)
- Synology NAS (storage, networking, Docker)
- Grafana dashboards (monitoring, alerting)
- Show system architecture and integration
- Troubleshooting live event tech

Created as part of Jarvis v1.9 Self-Optimization Loop.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class MediaserverDomain(BaseDomain):
    """Mediaserver and show system coaching domain."""

    @property
    def domain_id(self) -> str:
        return "mediaserver"

    @property
    def name(self) -> str:
        return "Mediaserver Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build mediaserver-specific context."""
        context_parts = [
            "=== MEDIASERVER COACHING MODE ===",
            "",
            "Du bist ein technischer Coach fuer Media Server und Show-Systeme.",
            "Fokus: Pixera, Synology NAS, Grafana, Live Event Technik.",
            "",
            "## Deine Expertise",
            "- **Pixera**: Timeline, Mapping, Output Config, Cues, Scripting",
            "- **Synology NAS**: Storage, RAID, Netzwerk, Docker, Backup",
            "- **Grafana**: Dashboards, Prometheus, Alerting, Visualisierung",
            "- **Show-Systeme**: 4K/8K Content, NDI, SDI, Dante, ArtNet",
            "",
        ]

        # Add user profile if available
        if ctx.user_profile:
            role = ctx.user_profile.get("current_role", "Media Server Lead")
            projects = ctx.user_profile.get("current_projects", [])
            tech_stack = ctx.user_profile.get("tech_stack", [])

            context_parts.append(f"**Rolle:** {role}")
            if projects:
                context_parts.append(f"**Aktuelle Projekte:** {', '.join(projects)}")
            if tech_stack:
                context_parts.append(f"**Tech Stack:** {', '.join(tech_stack)}")
            context_parts.append("")

        context_parts.extend([
            "## Pixera Troubleshooting Checklist",
            "```",
            "1. [ ] Output-Config pruefen (Resolution, Framerate, Colorspace)",
            "2. [ ] Timeline-Sync pruefen (Timecode, Trigger)",
            "3. [ ] Netzwerk-Latenz messen (NDI/SDI Delay)",
            "4. [ ] GPU-Last pruefen (NVIDIA SMI)",
            "5. [ ] Content-Specs validieren (Codec, Bitrate, Aufloesung)",
            "```",
            "",
            "## Synology Best Practices",
            "- RAID6 fuer kritische Medien-Pools",
            "- SSD Cache fuer haeufig genutzte Assets",
            "- 10GbE fuer 4K+ Content Streaming",
            "- Docker mit Resource Limits",
            "- Snapshot Replication fuer Backup",
            "",
            "## Grafana Dashboard Struktur",
            "```",
            "Row 1: System Overview (CPU, RAM, Disk, Network)",
            "Row 2: Pixera Metrics (FPS, GPU, Timeline Position)",
            "Row 3: Content Pipeline (Ingest, Encode, Delivery)",
            "Row 4: Alerts & Events",
            "```",
            "",
            "## Show System Architektur Template",
            "```",
            "+------------------+     +------------------+",
            "|  Content Source  |---->|  Media Server    |",
            "|  (NAS/SAN)       |     |  (Pixera)        |",
            "+------------------+     +--------+---------+",
            "                                  |",
            "                         +--------v---------+",
            "                         |  Output Stage    |",
            "                         |  (LED/Projektor) |",
            "                         +------------------+",
            "```",
            "",
            "## Debugging Workflow",
            "1. **Symptom dokumentieren** — Was passiert genau?",
            "2. **Isolieren** — Welche Komponente ist betroffen?",
            "3. **Logs pruefen** — Pixera, Windows Event, NAS",
            "4. **Baseline vergleichen** — Funktionierte es vorher?",
            "5. **Minimal reproduzieren** — Kleinstes Setup das Problem zeigt",
            "6. **Fix testen** — Eine Aenderung zur Zeit",
            "",
            "## Kommunikation bei Live Events",
            "- **Vor Show:** Setup-Checklist, Backup-Plan dokumentieren",
            "- **Waehrend Show:** Kurze Status-Updates, Eskalationspfad klar",
            "- **Nach Show:** Lessons Learned, Config sichern",
            "",
            "## Antwort-Format fuer technische Fragen",
            "1. **Kurze Diagnose** — Was ist wahrscheinlich das Problem?",
            "2. **Verification Steps** — Commands/Checks zum Bestaetigen",
            "3. **Loesung** — Schritt-fuer-Schritt mit Rollback-Option",
            "4. **Prevention** — Wie in Zukunft vermeiden?",
        ])

        return "\n".join(context_parts)

    def get_suggested_tools(self) -> List[str]:
        """Tools relevant for mediaserver coaching."""
        return [
            "search_knowledge",      # Find past configs/solutions
            "read_project_file",     # Read config files
            "get_recent_activity",   # Recent troubleshooting sessions
        ]

    def get_frameworks(self) -> List[Dict[str, str]]:
        """Frameworks for mediaserver work."""
        return [
            {
                "name": "Pixera Workflow",
                "description": "Content → Timeline → Mapping → Output → Show",
                "when_to_use": "Bei neuen Shows oder Content-Integration"
            },
            {
                "name": "5-Why Analysis",
                "description": "Warum? x5 bis zur Root Cause",
                "when_to_use": "Bei wiederkehrenden Problemen"
            },
            {
                "name": "Pre-Flight Checklist",
                "description": "Systematische Pruefung vor Live-Event",
                "when_to_use": "Vor jeder Show"
            },
            {
                "name": "Hot-Spare Strategy",
                "description": "Backup-System identisch konfiguriert",
                "when_to_use": "Kritische Events ohne Redundanz"
            }
        ]

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Tools enabled for mediaserver domain."""
        return self.get_suggested_tools()


# Export instance for registration
mediaserver_domain = MediaserverDomain()
