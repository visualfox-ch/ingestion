#!/bin/bash
# ============================================================================
# Jarvis API - Curl Test Examples
# ============================================================================
# Run with: bash tests/curl_tests.sh
# Or copy individual commands to test specific endpoints
#
# Prerequisites:
# - Jarvis API running at http://localhost:18000 (or adjust BASE_URL)
# - PostgreSQL initialized with knowledge schema
# ============================================================================

BASE_URL="${JARVIS_URL:-http://localhost:18000}"

echo "=== Jarvis API Curl Tests ==="
echo "Base URL: $BASE_URL"
echo ""

# ============================================================================
# A) KNOWLEDGE STORE - CRUD + Versioning
# ============================================================================

echo "=== A) KNOWLEDGE STORE ==="

# A1. Create a knowledge item
echo "A1. Create knowledge item (pattern)"
curl -s -X POST "$BASE_URL/knowledge/items" \
  -H "Content-Type: application/json" \
  -d '{
    "item_type": "pattern",
    "namespace": "work_projektil",
    "content": {
      "pattern": "responds well to bullet points",
      "context": "email communication"
    },
    "subject_type": "person",
    "subject_id": "alex_projektil",
    "confidence": "medium",
    "evidence_refs": [
      {"type": "email", "source": "inbox", "date": "2026-01-15"}
    ],
    "change_reason": "Observed in email exchanges"
  }' | jq .
echo ""

# A2. Create a fact
echo "A2. Create knowledge item (fact)"
curl -s -X POST "$BASE_URL/knowledge/items" \
  -H "Content-Type: application/json" \
  -d '{
    "item_type": "fact",
    "namespace": "private",
    "content": {
      "fact": "Birthday is March 15",
      "category": "personal"
    },
    "subject_type": "person",
    "subject_id": "anna_friend",
    "confidence": "high",
    "change_reason": "Confirmed in chat"
  }' | jq .
echo ""

# A3. List knowledge items
echo "A3. List knowledge items (work namespace, min relevance 0.5)"
curl -s "$BASE_URL/knowledge/items?namespace=work_projektil&min_relevance=0.5&limit=10" | jq .
echo ""

# A4. Get single item (replace 1 with actual ID)
echo "A4. Get knowledge item by ID"
curl -s "$BASE_URL/knowledge/items/1" | jq .
echo ""

# A5. Update knowledge item (creates new version)
echo "A5. Update knowledge item (new version)"
curl -s -X PUT "$BASE_URL/knowledge/items/1" \
  -H "Content-Type: application/json" \
  -d '{
    "content": {
      "pattern": "prefers bullet points AND short paragraphs",
      "context": "all written communication"
    },
    "confidence": "high",
    "change_reason": "Updated based on additional observations"
  }' | jq .
echo ""

# A6. Get item versions
echo "A6. Get version history for item"
curl -s "$BASE_URL/knowledge/items/1/versions?limit=5" | jq .
echo ""

# A7. Get knowledge stats
echo "A7. Get knowledge items statistics"
curl -s "$BASE_URL/knowledge/items/stats" | jq .
echo ""

# ============================================================================
# B) RELEVANCE ENGINE - Decay/Reinforce/Archive
# ============================================================================

echo "=== B) RELEVANCE ENGINE ==="

# B1. Reinforce an item (used/confirmed)
echo "B1. Reinforce item (boost relevance)"
curl -s -X POST "$BASE_URL/relevance/reinforce/1?boost=0.15&reason=confirmed_in_meeting" | jq .
echo ""

# B2. Mark item as seen
echo "B2. Mark item as seen"
curl -s -X POST "$BASE_URL/relevance/seen/1" | jq .
echo ""

# B3. Decay single item
echo "B3. Decay single item"
curl -s -X POST "$BASE_URL/relevance/decay/1?reason=manual_review" | jq .
echo ""

# B4. Batch decay (items not seen for 7+ days)
echo "B4. Batch decay old items"
curl -s -X POST "$BASE_URL/relevance/decay/batch?namespace=work_projektil&min_days_since_seen=7&limit=50" | jq .
echo ""

# B5. Get archive candidates
echo "B5. Get archive candidates (low relevance items)"
curl -s "$BASE_URL/relevance/candidates?namespace=work_projektil&threshold=0.25&limit=10" | jq .
echo ""

# B6. Archive an item
echo "B6. Archive item"
curl -s -X POST "$BASE_URL/relevance/archive/1?reason=outdated_pattern" | jq .
echo ""

# B7. Unarchive an item
echo "B7. Unarchive item"
curl -s -X POST "$BASE_URL/relevance/unarchive/1?new_relevance=0.6" | jq .
echo ""

# B8. Get relevance distribution
echo "B8. Get relevance score distribution"
curl -s "$BASE_URL/relevance/distribution?namespace=work_projektil" | jq .
echo ""

# ============================================================================
# C) DOMAIN SEPARATION
# ============================================================================

echo "=== C) DOMAIN SEPARATION ==="

# C1. Get domain config
echo "C1. Get domain configuration"
curl -s "$BASE_URL/domain/config" | jq .
echo ""

# C2. Get allowed collections for scope (legacy namespace query param)
echo "C2. Get allowed collections for work_projektil"
curl -s "$BASE_URL/domain/allowed?namespace=work_projektil&include_shared=true" | jq .
echo ""

# C3. Check cross-scope access (legacy namespace identifiers)
echo "C3. Check if private can access work_projektil"
curl -s "$BASE_URL/domain/check?source_namespace=private&target_namespace=work_projektil&operation=read" | jq .
echo ""

# ============================================================================
# D) ADVICE AUTO - Persona Selection + Drafts
# ============================================================================

echo "=== D) ADVICE AUTO ==="

# D1. Generate advice for single person
echo "D1. Generate advice for person"
curl -s -X POST "$BASE_URL/advice_auto" \
  -H "Content-Type: application/json" \
  -d '{
    "person_id": "alex_projektil",
    "goal": "Request deadline extension",
    "context": "Project X is delayed due to external dependencies",
    "namespace": "work_projektil"
  }' | jq .
echo ""

# D2. Generate advice with urgency trigger
echo "D2. Generate advice (urgency trigger)"
curl -s -X POST "$BASE_URL/advice_auto" \
  -H "Content-Type: application/json" \
  -d '{
    "person_id": "ceo_boss",
    "goal": "Urgent budget approval needed",
    "context": "Critical deadline tomorrow, need immediate sign-off",
    "namespace": "work_projektil"
  }' | jq .
echo ""

# D3. Batch advice for multiple stakeholders
echo "D3. Batch advice for stakeholders"
curl -s -X POST "$BASE_URL/advice_auto/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "stakeholders": ["alex_projektil", "lisa_team", "ceo_boss"],
    "goal": "Project update",
    "context": "Sprint completed",
    "namespace": "work_projektil"
  }' | jq .
echo ""

# ============================================================================
# E) DECIDE AND MESSAGE - Decision Logging + Stakeholder Drafts
# ============================================================================

echo "=== E) DECIDE AND MESSAGE ==="

# E1. Create decision with stakeholder messages
echo "E1. Decide and message"
curl -s -X POST "$BASE_URL/decide_and_message" \
  -H "Content-Type: application/json" \
  -d '{
    "decision_topic": "Switch from Slack to Teams",
    "options": [
      {
        "label": "Switch to Teams",
        "description": "Migrate all communication to MS Teams",
        "pros": ["Better integration with Office", "Cost savings"],
        "cons": ["Migration effort", "Learning curve"],
        "recommended": true
      },
      {
        "label": "Stay with Slack",
        "description": "Keep current Slack setup",
        "pros": ["No migration needed", "Team already trained"],
        "cons": ["Increasing costs", "Integration gaps"]
      }
    ],
    "recommendation": "Switch to Teams for better Office integration and 20% cost reduction",
    "stakeholders": ["alex_projektil", "lisa_team"],
    "context": "Current Slack contract ends Q2. Teams already included in M365 license.",
    "namespace": "work_projektil"
  }' | jq .
echo ""

# E2. Get decision brief
echo "E2. Get decision brief by ID"
curl -s "$BASE_URL/decision_brief/switch_from_slack_to_t_202601301200" | jq .
echo ""

# ============================================================================
# F) SENTIMENT ANALYSIS (existing)
# ============================================================================

echo "=== F) SENTIMENT ANALYSIS ==="

# F1. Analyze sentiment with urgency
echo "F1. Analyze urgency sentiment"
curl -s -G "$BASE_URL/sentiment/analyze" \
  --data-urlencode "text=Das ist super dringend, ich brauche sofort Hilfe!" | jq .
echo ""

# F2. Analyze stress sentiment (ASCII-safe)
echo "F2. Analyze stress sentiment"
curl -s -G "$BASE_URL/sentiment/analyze" \
  --data-urlencode "text=Ich bin total ueberfordert mit allem" | jq .
echo ""

# ============================================================================
# G) EXTENDED STATS
# ============================================================================

echo "=== G) EXTENDED STATS ==="

# G1. Get overall stats (includes review queue)
echo "G1. Get overall stats"
curl -s "$BASE_URL/stats" | jq .
echo ""

# G2. Get knowledge health
echo "G2. Knowledge layer health"
curl -s "$BASE_URL/knowledge/health" | jq .
echo ""

# G3. Get review queue
echo "G3. Get pending review queue"
curl -s "$BASE_URL/knowledge/review?status=pending&limit=10" | jq .
echo ""

# ============================================================================
# SUMMARY
# ============================================================================

echo "=== TEST COMPLETE ==="
echo ""
echo "Endpoints tested:"
echo "  - Knowledge Store: /knowledge/items (CRUD + versions)"
echo "  - Relevance Engine: /relevance/* (decay, reinforce, archive)"
echo "  - Domain Separation: /domain/* (config, access checks)"
echo "  - Advice Auto: /advice_auto (persona selection + drafts)"
echo "  - Decide & Message: /decide_and_message (decision log + stakeholder drafts)"
echo ""
echo "Remember:"
echo "  - Private scope blocks LLM by default (ALLOW_LLM_PRIVATE=false)"
echo "  - Cross-scope access blocked by default (ALLOW_CROSS_NAMESPACE=false)"
echo "  - Domain endpoints currently use legacy namespace identifiers"
echo "  - Relevance decays with 30-day half-life"
echo "  - Items below 0.2 relevance are archive candidates"
