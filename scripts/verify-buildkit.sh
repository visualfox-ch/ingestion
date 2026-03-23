#!/bin/bash
#
# Verify BuildKit is enabled in all build scripts
#
# Usage: bash ./scripts/verify-buildkit.sh
#

set -euo pipefail

echo "🔍 Verifying BuildKit enforcement..."
echo ""

FAIL=0

# Check 1: build-ingestion-fast.sh has DOCKER_BUILDKIT=1
echo "✓ Check 1: build-ingestion-fast.sh"
if grep -q "DOCKER_BUILDKIT=1" ./build-ingestion-fast.sh; then
  echo "  ✅ DOCKER_BUILDKIT=1 found"
else
  echo "  ❌ DOCKER_BUILDKIT=1 NOT found"
  FAIL=1
fi

# Check 2: All build scripts in repo
echo ""
echo "✓ Check 2: All *.sh scripts with 'docker build'"
BUILD_SCRIPTS=$(grep -l "docker build" ./*.sh 2>/dev/null || true)

if [ -z "$BUILD_SCRIPTS" ]; then
  echo "  ℹ️  No scripts with 'docker build' found"
else
  for script in $BUILD_SCRIPTS; do
    if grep -q "DOCKER_BUILDKIT=1" "$script"; then
      echo "  ✅ $script has BuildKit"
    else
      echo "  ❌ $script MISSING BuildKit"
      FAIL=1
    fi
  done
fi

# Check 3: docs/agents/AGENT_ROUTING.md mentions BuildKit
echo ""
echo "✓ Check 3: docs/agents/AGENT_ROUTING.md"
if grep -q "DOCKER_BUILDKIT" ./docs/agents/AGENT_ROUTING.md; then
  echo "  ✅ BuildKit documented in docs/agents/AGENT_ROUTING.md"
else
  echo "  ❌ BuildKit NOT documented in docs/agents/AGENT_ROUTING.md"
  FAIL=1
fi

# Check 4: JARVIS_TOOLING.md mentions BuildKit
echo ""
echo "✓ Check 4: JARVIS_TOOLING.md"
if grep -q "BuildKit.*MANDATORY" ./JARVIS_TOOLING.md; then
  echo "  ✅ BuildKit MANDATORY in JARVIS_TOOLING.md"
else
  echo "  ❌ BuildKit NOT mandatory in JARVIS_TOOLING.md"
  FAIL=1
fi

# Check 5: NAS has BuildKit available (if SSH works)
echo ""
echo "✓ Check 5: NAS BuildKit availability"
if ssh jarvis-nas '/var/packages/ContainerManager/target/usr/bin/docker buildx version' 2>/dev/null >/dev/null; then
  echo "  ✅ BuildKit available on NAS"
else
  echo "  ⚠️  Cannot verify NAS BuildKit (SSH failed or buildx not available)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$FAIL" -eq 0 ]; then
  echo "✅ ALL CHECKS PASSED - BuildKit properly enforced"
  exit 0
else
  echo "❌ CHECKS FAILED - BuildKit not properly enforced"
  echo ""
  echo "Fix:"
  echo "1. Add DOCKER_BUILDKIT=1 to all build scripts"
  echo "2. Update docs/agents/AGENT_ROUTING.md with BuildKit requirement"
  echo "3. Update JARVIS_TOOLING.md with BuildKit mandate"
  exit 1
fi
