# Perplexity Websuche Integration für Jarvis

## Funktionsweise
- Nutzt die Perplexity API für Echtzeit-Websuche mit Quellenangaben.
- Fallback auf DuckDuckGo, falls kein API-Key oder Fehler.
- API-Key wird über `.env` (PERPLEXITY_API_KEY) bereitgestellt.
- Tool-Endpoint: `/tools/web_search` (POST, JSON: `{ "query": "..." }`)

## Voraussetzungen
- Docker-Container muss PERPLEXITY_API_KEY als Umgebungsvariable erhalten (siehe `docker-compose.yml`).
- Key in `.env` im Projektverzeichnis eintragen.
- Docker und Docker Compose müssen im PATH der NAS verfügbar sein.

## Troubleshooting
- **Kein Ergebnis/Fehler:**
  - Prüfe, ob der API-Key korrekt gesetzt ist (`echo $PERPLEXITY_API_KEY` im Container).
  - Prüfe, ob die NAS Internetzugang hat.
  - Logs im Container prüfen: `docker logs jarvis-ingestion`
- **Fallback auf DuckDuckGo:**
  - Perplexity-API nicht erreichbar oder Key ungültig.
- **Docker nicht gefunden:**
  - PATH in `~/.profile` um `/volume1/@appstore/ContainerManager/usr/bin` ergänzen.

## Beispiel-Request
```bash
curl -s http://localhost:8000/tools/web_search -X POST -H 'Content-Type: application/json' -d '{"query": "Was sind Google Ads?"}' | jq .
```

## Weiterführende Links
- [Perplexity API Doku](https://docs.perplexity.ai/)
- [Jarvis Tooling Guide](../../docker/JARVIS_TOOLING.md)
