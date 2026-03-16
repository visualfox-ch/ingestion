"""
Direkter Wissensimport in die Jarvis-Datenbank (PostgreSQL) aus Python

- Liest strukturierte Ideen aus einer .md- oder .json-Datei
- Verbindet sich direkt mit der Jarvis-DB (z.B. via psycopg2)
- Prüft und importiert nur valide, neue Einträge
- Optional: Validierung gegen bestehende Einträge

Voraussetzung: Zugangsdaten zur DB in Umgebungsvariablen oder .env
"""
import os
import re
import psycopg2
import json
from typing import List, Dict

DB_HOST = os.environ.get("JARVIS_DB_HOST", "localhost")
DB_PORT = os.environ.get("JARVIS_DB_PORT", "5432")
DB_NAME = os.environ.get("JARVIS_DB_NAME", "jarvis")
DB_USER = os.environ.get("JARVIS_DB_USER", "jarvis")
DB_PASS = os.environ.get("JARVIS_DB_PASS", "password")

IDEA_SECTION_PATTERN = re.compile(r"^##?\s+Idee[:\s](.*)$", re.MULTILINE)


def parse_ideas_from_md(md_text: str) -> List[Dict]:
    """Extrahiert Ideen aus Markdown-Text"""
    ideas = []
    for match in IDEA_SECTION_PATTERN.finditer(md_text):
        title = match.group(1).strip()
        desc = ""
        priority = "P2"
        tags = []
        ideas.append({
            "title": title,
            "description": desc,
            "priority": priority,
            "tags": tags,
            "source": "md-import",
        })
    return ideas


def import_ideas_to_db(ideas: List[Dict]):
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    cur = conn.cursor()
    for idea in ideas:
        title = idea.get("title", "").strip()
        if not title:
            print("⚠️  Übersprungen (kein Titel):", idea)
            continue
        # Prüfe auf Duplikate
        cur.execute("SELECT COUNT(*) FROM ideas WHERE title = %s", (title,))
        if cur.fetchone()[0] > 0:
            print(f"⚠️  Übersprungen (Duplikat): {title}")
            continue
        # Insert
        cur.execute(
            """
            INSERT INTO ideas (title, description, priority, source, tags, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (
                title,
                idea.get("description", ""),
                idea.get("priority", "P2"),
                idea.get("source", "manual"),
                json.dumps(idea.get("tags", [])),
                "pending",
            ),
        )
        print(f"✅ Importiert: {title}")
    conn.commit()
    cur.close()
    conn.close()


def main(md_path: str):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    ideas = parse_ideas_from_md(md_text)
    import_ideas_to_db(ideas)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python import_ideas_db.py <file.md>")
        exit(1)
    main(sys.argv[1])
