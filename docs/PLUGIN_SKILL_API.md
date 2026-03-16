# Jarvis Dynamic Skill/Plugin API

This document describes the API for dynamic registration, unregistration, and listing of skills/plugins in Jarvis.

## Endpoints

### List Skills
- **GET** `/api/v1/skills/`
- **Headers:** `X-API-Key: jarvis-secret-key`
- **Response:** List of all registered skills (tools)

### Register Skill
- **POST** `/api/v1/skills/register`
- **Headers:** `X-API-Key: jarvis-secret-key`
- **Body (JSON):**
  ```json
  {
    "name": "my_skill",
    "description": "A demo skill that echoes input.",
    "input_schema": {
      "type": "object",
      "properties": {
        "text": {"type": "string", "description": "Text to echo"}
      },
      "required": ["text"]
    }
  }
  ```
- **Response:** `{ "status": "registered", "name": "my_skill" }`

### Unregister Skill
- **POST** `/api/v1/skills/unregister/{name}`
- **Headers:** `X-API-Key: jarvis-secret-key`
- **Response:** `{ "status": "unregistered", "name": "my_skill" }`

## Notes
- Registered skills are available immediately for agent/tool use.
- The default handler for API-registered skills is a dummy that echoes input (for demo/testing). For production, handler upload or code injection must be implemented securely.
- API key is static for demo; use secure auth in production.

---

See also: `app/tools.py` for registration logic, `app/api/skills_api.py` for API implementation.
