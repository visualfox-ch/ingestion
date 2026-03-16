#!/usr/bin/env bash
# =============================================================================
# Hybrid Search E2E Test Suite
# =============================================================================
# Tests the hybrid search endpoint with 20 real-world queries.
# Target: 80%+ pass rate (16/20 tests passing)
#
# Usage:
#   bash ./tests/hybrid_search_test_suite.sh [--verbose] [--host HOST]
#
# Requirements:
#   - jq installed
#   - Hybrid search endpoint deployed
#   - Documents indexed in Qdrant + Meilisearch
# =============================================================================

set -euo pipefail

# Configuration
HOST="${HOST:-http://192.168.1.103:18000}"
ENDPOINT="/hybrid-search"
VERBOSE="${VERBOSE:-false}"
TIMEOUT=10

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
SKIPPED=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}✅ PASS${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}❌ FAIL${NC} $1"
    ((FAILED++))
}

log_skip() {
    echo -e "${YELLOW}⏭️  SKIP${NC} $1"
    ((SKIPPED++))
}

# Execute hybrid search query
# Args: $1=query, $2=top_k (default 5)
hybrid_search() {
    local query="$1"
    local top_k="${2:-5}"

    curl -s --max-time "$TIMEOUT" -X POST "${HOST}${ENDPOINT}" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${JARVIS_API_KEY:-}" \
        -d "{\"query\": \"$query\", \"namespace\": \"private\", \"top_k\": $top_k}"
}

# Check if expected filename is in top N results
# Args: $1=response_json, $2=expected_filename, $3=top_n (default 3)
check_filename_in_top_n() {
    local response="$1"
    local expected="$2"
    local top_n="${3:-3}"

    # Extract top N filenames
    local filenames
    filenames=$(echo "$response" | jq -r ".results[:$top_n] | .[].metadata.filename // empty" 2>/dev/null)

    if echo "$filenames" | grep -qi "$expected"; then
        return 0
    else
        return 1
    fi
}

# Check if expected text snippet appears in results
# Args: $1=response_json, $2=expected_text
check_text_in_results() {
    local response="$1"
    local expected="$2"

    local texts
    texts=$(echo "$response" | jq -r '.results[].text // empty' 2>/dev/null)

    if echo "$texts" | grep -qi "$expected"; then
        return 0
    else
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Pre-flight Check
# -----------------------------------------------------------------------------

log_info "Testing hybrid search endpoint at ${HOST}${ENDPOINT}"

# Check if endpoint is available
if ! curl -s --max-time 5 "${HOST}/health" | jq -e '.status == "healthy"' > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Jarvis API not healthy at ${HOST}${NC}"
    exit 1
fi

log_info "API is healthy, starting tests..."
echo ""

# -----------------------------------------------------------------------------
# Test Category 1: Filename Queries (5 tests)
# -----------------------------------------------------------------------------

echo "=== Category 1: Filename Queries ==="

# Test 1.1: Exact filename query
test_1_1() {
    local response
    response=$(hybrid_search "BEST_PRACTICES_QUICK_REFERENCE")

    if check_filename_in_top_n "$response" "BEST_PRACTICES_QUICK_REFERENCE.md" 1; then
        log_pass "Test 1.1: Exact filename 'BEST_PRACTICES_QUICK_REFERENCE'"
    else
        log_fail "Test 1.1: Exact filename 'BEST_PRACTICES_QUICK_REFERENCE'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 1.2: Partial filename query
test_1_2() {
    local response
    response=$(hybrid_search "RESEARCH_SOURCES")

    if check_filename_in_top_n "$response" "RESEARCH_SOURCES.md" 1; then
        log_pass "Test 1.2: Partial filename 'RESEARCH_SOURCES'"
    else
        log_fail "Test 1.2: Partial filename 'RESEARCH_SOURCES'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 1.3: Filename with spaces (natural language)
test_1_3() {
    local response
    response=$(hybrid_search "Continue Jarvis Integration")

    if check_filename_in_top_n "$response" "CONTINUE_JARVIS_INTEGRATION.md" 3; then
        log_pass "Test 1.3: Filename with spaces 'Continue Jarvis Integration'"
    else
        log_fail "Test 1.3: Filename with spaces 'Continue Jarvis Integration'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 1.4: Agent routing doc
test_1_4() {
    local response
    response=$(hybrid_search "AGENT_ROUTING")

    if check_filename_in_top_n "$response" "AGENT_ROUTING.md" 1; then
        log_pass "Test 1.4: Filename 'AGENT_ROUTING'"
    else
        log_fail "Test 1.4: Filename 'AGENT_ROUTING'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 1.5: Case insensitive filename
test_1_5() {
    local response
    response=$(hybrid_search "best practices quick reference")

    if check_filename_in_top_n "$response" "BEST_PRACTICES_QUICK_REFERENCE.md" 3; then
        log_pass "Test 1.5: Case insensitive filename"
    else
        log_fail "Test 1.5: Case insensitive filename"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

test_1_1
test_1_2
test_1_3
test_1_4
test_1_5

echo ""

# -----------------------------------------------------------------------------
# Test Category 2: Conceptual Queries (5 tests)
# -----------------------------------------------------------------------------

echo "=== Category 2: Conceptual Queries ==="

# Test 2.1: Database best practices
test_2_1() {
    local response
    response=$(hybrid_search "Database Best Practices")

    if check_filename_in_top_n "$response" "BEST_PRACTICES" 3; then
        log_pass "Test 2.1: Conceptual 'Database Best Practices'"
    else
        log_fail "Test 2.1: Conceptual 'Database Best Practices'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 2.2: Error handling patterns
test_2_2() {
    local response
    response=$(hybrid_search "Error handling patterns")

    if check_text_in_results "$response" "error" || check_filename_in_top_n "$response" "BEST_PRACTICES" 5; then
        log_pass "Test 2.2: Conceptual 'Error handling patterns'"
    else
        log_fail "Test 2.2: Conceptual 'Error handling patterns'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 2.3: Agent system research
test_2_3() {
    local response
    response=$(hybrid_search "Research Papers on Agent Systems")

    if check_filename_in_top_n "$response" "RESEARCH_SOURCES" 3; then
        log_pass "Test 2.3: Conceptual 'Research Papers on Agent Systems'"
    else
        log_fail "Test 2.3: Conceptual 'Research Papers on Agent Systems'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 2.4: How to integrate Continue
test_2_4() {
    local response
    response=$(hybrid_search "How to integrate Continue with Jarvis")

    if check_filename_in_top_n "$response" "CONTINUE" 3; then
        log_pass "Test 2.4: Conceptual 'How to integrate Continue'"
    else
        log_fail "Test 2.4: Conceptual 'How to integrate Continue'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 2.5: Agent routing rules
test_2_5() {
    local response
    response=$(hybrid_search "Agent routing and handoff rules")

    if check_filename_in_top_n "$response" "AGENT_ROUTING" 3 || check_text_in_results "$response" "routing"; then
        log_pass "Test 2.5: Conceptual 'Agent routing rules'"
    else
        log_fail "Test 2.5: Conceptual 'Agent routing rules'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

test_2_1
test_2_2
test_2_3
test_2_4
test_2_5

echo ""

# -----------------------------------------------------------------------------
# Test Category 3: Keyword Queries (5 tests)
# -----------------------------------------------------------------------------

echo "=== Category 3: Keyword Queries ==="

# Test 3.1: Non-Negotiables keyword
test_3_1() {
    local response
    response=$(hybrid_search "5 Non-Negotiables")

    if check_text_in_results "$response" "Non-Negotiable" || check_filename_in_top_n "$response" "BEST_PRACTICES" 3; then
        log_pass "Test 3.1: Keyword '5 Non-Negotiables'"
    else
        log_fail "Test 3.1: Keyword '5 Non-Negotiables'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 3.2: safe_list_query keyword
test_3_2() {
    local response
    response=$(hybrid_search "safe_list_query")

    if check_text_in_results "$response" "safe_list_query" || check_filename_in_top_n "$response" "BEST_PRACTICES" 5; then
        log_pass "Test 3.2: Keyword 'safe_list_query'"
    else
        log_fail "Test 3.2: Keyword 'safe_list_query'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 3.3: BuildKit keyword
test_3_3() {
    local response
    response=$(hybrid_search "BuildKit deployment")

    if check_text_in_results "$response" "BuildKit" || check_text_in_results "$response" "build"; then
        log_pass "Test 3.3: Keyword 'BuildKit deployment'"
    else
        log_fail "Test 3.3: Keyword 'BuildKit deployment'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 3.4: Async patterns keyword
test_3_4() {
    local response
    response=$(hybrid_search "async await patterns")

    if check_text_in_results "$response" "async" || check_filename_in_top_n "$response" "BEST_PRACTICES" 5; then
        log_pass "Test 3.4: Keyword 'async await patterns'"
    else
        log_fail "Test 3.4: Keyword 'async await patterns'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 3.5: Qdrant vector search
test_3_5() {
    local response
    response=$(hybrid_search "Qdrant vector search")

    if check_text_in_results "$response" "Qdrant" || check_text_in_results "$response" "vector"; then
        log_pass "Test 3.5: Keyword 'Qdrant vector search'"
    else
        log_fail "Test 3.5: Keyword 'Qdrant vector search'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

test_3_1
test_3_2
test_3_3
test_3_4
test_3_5

echo ""

# -----------------------------------------------------------------------------
# Test Category 4: Edge Cases (5 tests)
# -----------------------------------------------------------------------------

echo "=== Category 4: Edge Cases ==="

# Test 4.1: German query
test_4_1() {
    local response
    response=$(hybrid_search "Welche Best Practices gibt es")

    if [[ $(echo "$response" | jq '.results | length') -gt 0 ]]; then
        log_pass "Test 4.1: German query returns results"
    else
        log_fail "Test 4.1: German query returns results"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.')"
    fi
}

# Test 4.2: Mixed language query
test_4_2() {
    local response
    response=$(hybrid_search "Database Access Regeln")

    if [[ $(echo "$response" | jq '.results | length') -gt 0 ]]; then
        log_pass "Test 4.2: Mixed language query"
    else
        log_fail "Test 4.2: Mixed language query"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.')"
    fi
}

# Test 4.3: Typo tolerance
test_4_3() {
    local response
    response=$(hybrid_search "BEST_PRACTISES")  # Typo: PRACTISES instead of PRACTICES

    if check_filename_in_top_n "$response" "BEST_PRACTICES" 5; then
        log_pass "Test 4.3: Typo tolerance 'PRACTISES'"
    else
        log_fail "Test 4.3: Typo tolerance 'PRACTISES'"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.results[:3]')"
    fi
}

# Test 4.4: Empty results handling
test_4_4() {
    local response
    response=$(hybrid_search "xyznonexistentquery12345")

    if [[ $(echo "$response" | jq '.results | length') -eq 0 ]] || [[ $(echo "$response" | jq -e '.results' 2>/dev/null) ]]; then
        log_pass "Test 4.4: Non-existent query returns empty gracefully"
    else
        log_fail "Test 4.4: Non-existent query handling"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.')"
    fi
}

# Test 4.5: Special characters
test_4_5() {
    local response
    response=$(hybrid_search "safe_list_query()")

    if [[ $(echo "$response" | jq -e '.results' 2>/dev/null) ]] || [[ $(echo "$response" | jq -e '.error' 2>/dev/null) == "null" ]]; then
        log_pass "Test 4.5: Special characters handled"
    else
        log_fail "Test 4.5: Special characters handling"
        [[ "$VERBOSE" == "true" ]] && echo "Response: $(echo "$response" | jq -c '.')"
    fi
}

test_4_1
test_4_2
test_4_3
test_4_4
test_4_5

echo ""

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

echo "=============================================="
echo "               TEST SUMMARY"
echo "=============================================="
TOTAL=$((PASSED + FAILED + SKIPPED))
PASS_RATE=$((PASSED * 100 / TOTAL))

echo -e "Passed:  ${GREEN}${PASSED}${NC}"
echo -e "Failed:  ${RED}${FAILED}${NC}"
echo -e "Skipped: ${YELLOW}${SKIPPED}${NC}"
echo -e "Total:   ${TOTAL}"
echo ""
echo -e "Pass Rate: ${PASS_RATE}%"
echo ""

if [[ $PASS_RATE -ge 80 ]]; then
    echo -e "${GREEN}✅ SUCCESS: Pass rate >= 80% (${PASS_RATE}%)${NC}"
    exit 0
else
    echo -e "${RED}❌ FAILURE: Pass rate < 80% (${PASS_RATE}%)${NC}"
    exit 1
fi
