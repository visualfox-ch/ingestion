# Privacy/Forgetting Endpoints for Jarvis Memory API

## Overview
This document describes the new endpoints for deleting (forgetting) facts and entities from Jarvis' memory, supporting privacy, GDPR, and user control.

---

## Endpoints

### Delete (Forget) a Fact by ID
- **Endpoint:** `DELETE /memory/facts/{fact_id}`
- **Description:** Soft-deletes (deactivates) a fact. Fact remains in DB but is not used.
- **Returns:** `{ "fact_id": ..., "deleted": true/false }`
- **Audit:** All deletions are logged.

### Bulk Delete Facts
- **Endpoint:** `DELETE /memory/facts`
- **Query Params:**
  - `category` (optional): Only delete facts in this category
  - `all_facts` (bool, default false): If true, delete ALL facts (dangerous)
- **Returns:** `{ "deleted": <count>, "category": ..., "all_facts": ... }`
- **Audit:** All bulk deletions are logged.

### Delete (Forget) an Entity by ID
- **Endpoint:** `DELETE /memory/entities/{entity_id}`
- **Description:** Hard-deletes an entity from the DB.
- **Returns:** `{ "entity_id": ..., "deleted": true/false }`
- **Audit:** All deletions are logged.

### Bulk Delete Entities
- **Endpoint:** `DELETE /memory/entities`
- **Query Params:**
  - `entity_type` (optional): Only delete entities of this type
  - `all_entities` (bool, default false): If true, delete ALL entities (dangerous)
- **Returns:** `{ "deleted": <count>, "entity_type": ..., "all_entities": ... }`
- **Audit:** All bulk deletions are logged.

---

## Usage Notes
- All endpoints require explicit parameters for dangerous operations (e.g., `all_facts=true`).
- All delete/forget actions are audit-logged for compliance and traceability.
- Soft-deleted facts are not used in reasoning or recall.
- Hard-deleted entities are removed from the DB.

## Testing
- Test single and bulk deletion for both facts and entities.
- Verify audit logs for all operations.
- Confirm deleted facts/entities are not returned by normal queries.

---

_Last updated: 2026-02-19_
