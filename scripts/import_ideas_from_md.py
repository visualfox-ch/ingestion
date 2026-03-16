"""
Python-Skript-Template: Markdown-Ideen automatisch in Jarvis-Ideen-Datenbank importieren

- Liest .md-Dateien mit Ideen-Abschnitten
- Parsed Titel, Beschreibung, Priorität, Tags
- Erstellt IdeaCreate-Objekte
- Importiert via FastAPI-Endpoint (/ideas)
- Optional: LLM-Scoring nach Import

Best Practice: Fehler robust loggen, Duplikate vermeiden, Quelle/Status mitgeben
"""
import os
import re
import requests
from typing import List, Dict

JARVIS_API_URL = os.environ.get("JARVIS_API_URL", "http://localhost:18000/ideas")

IDEA_SECTION_PATTERN = re.compile(r"^##?\s+Idee[:\s](.*)$", re.MULTILINE)


def parse_ideas_from_md(md_text: str) -> List[Dict]:
    """Extrahiert Ideen aus Markdown-Text"""
    ideas = []
    for match in IDEA_SECTION_PATTERN.finditer(md_text):
        title = match.group(1).strip()
        # Suche nach Beschreibung, Priorität, Tags im folgenden Textabschnitt
        desc = ""
        priority = "P2"
        tags = []
        # (Hier: Dummy-Parsing, anpassen für echtes Format)
        ideas.append({
            "title": title,
            "description": desc,
            "priority": priority,
            "tags": tags,
            "source": "md-import",
        })
    return ideas


def import_ideas(ideas: List[Dict]):
    """Sendet Ideen an Jarvis-Ideen-API, prüft Pflichtfelder und Duplikate"""
    imported_titles = set()
    for idea in ideas:
        title = idea.get("title", "").strip()
        if not title:
            print("⚠️  Übersprungen (kein Titel):", idea)
            continue
        if title in imported_titles:
            print(f"⚠️  Übersprungen (Duplikat): {title}")
            continue
        # Pflichtfelder prüfen
        if not idea.get("priority"):
            idea["priority"] = "P2"
        if not isinstance(idea.get("tags"), list):
            idea["tags"] = []
        resp = requests.post(JARVIS_API_URL, json=idea)
        if resp.status_code == 200:
            print(f"✅ Importiert: {title}")
            imported_titles.add(title)
        else:
            print(f"❌ Fehler: {title} ({resp.status_code})")


def main(md_path: str):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    ideas = parse_ideas_from_md(md_text)
    import_ideas(ideas)

    # Nach Import: Datei archivieren
    archive_dir = os.path.join(os.path.dirname(md_path), "archiviert")
    os.makedirs(archive_dir, exist_ok=True)
    base_name = os.path.basename(md_path)
    archive_path = os.path.join(archive_dir, base_name)
    try:
        os.rename(md_path, archive_path)
        print(f"\n📦 Archiviert: {archive_path}")
    except Exception as e:
        print(f"⚠️  Konnte Datei nicht archivieren: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python import_ideas.py <file.md>")
        exit(1)
    main(sys.argv[1])
