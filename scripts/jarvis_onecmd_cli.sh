#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CANONICAL_OPS_ROOT="${JARVIS_CANONICAL_OPS_ROOT:-/Volumes/BRAIN/system/docker}"
OPS_ROOT="$ROOT_DIR"
if [[ -d "$CANONICAL_OPS_ROOT" ]]; then
  OPS_ROOT="$CANONICAL_OPS_ROOT"
fi
BOLT_DIR="$OPS_ROOT/bolt-diy"

registry() {
  cat <<'EOF'
bolt.verify|bolt|Verify bolt container, health, endpoint and configured model
bolt.open|bolt|Open bolt UI in browser
bolt.prepare.md|bolt|Prepare markdown payload and copy to clipboard
bolt.use.nas-ollama|bolt|Use NAS Ollama with qwen2.5-coder:7b
bolt.use.laptop-ollama|bolt|Use laptop Ollama endpoint
bolt.use.api.openai|bolt|Use OpenAI provider
bolt.use.api.anthropic|bolt|Use Anthropic provider
bolt.use.api.openrouter|bolt|Use OpenRouter provider
bolt.key.openai|bolt|Set OPENAI_API_KEY and restart bolt
bolt.key.anthropic|bolt|Set ANTHROPIC_API_KEY and restart bolt
bolt.key.openrouter|bolt|Set OPEN_ROUTER_API_KEY and restart bolt
jarvis.status|core|Show core stack status
jarvis.logs.ingestion|core|Show ingestion logs
jarvis.restart.ingestion|core|Restart ingestion service
jarvis.doctor|gate|Run the workspace doctor report
jarvis.validate.fast|gate|Run fast local validation before deploy work
jarvis.verify.targeted|gate|Run the pre-deploy gate with focused verification
jarvis.deploy.smart|gate|Run the preferred smart deploy entrypoint
jarvis.confidence|gate|Run post-deploy smokes and reality snapshot on NAS
jarvis.deploy.check|deploy|Check if deployment is already running
jarvis.deploy.ingestion|deploy|Build/deploy ingestion (BuildKit)
jarvis.docs.preflight|docs|Run docs preflight checks
docs.cleanup.check|docs|Check and propose docs cleanup (frontmatter, domains, duplicates)
jarvis.reality.check|ops|Run reality checks script
jarvis.safety.parallel|ops|Run parallel guardrails+sandbox runtime safety probes
jarvis.ci.pipeline.status|ops|Show pipeline-contract run status with gh/API fallback
jarvis.ssh.pq.strict|ops|Run strict PQ audit (exit non-zero unless PQ KEX negotiated)
jarvis.ssh.pq.upgrade.preflight|ops|Run NAS preflight checks for OpenSSH PQ upgrade track
onecmd.doctor|meta|Run onecmd health checks and sanity report
profile.bolt|profile|Run bolt verification profile
profile.deploy|profile|Run deploy-safety profile
profile.dev|profile|Run daily dev profile
EOF
}

cmd_list() {
  printf "%-28s | %-8s | %s\n" "ID" "GROUP" "DESCRIPTION"
  printf "%s\n" "-----------------------------+----------+---------------------------------------------"
  registry | while IFS='|' read -r id grp desc; do
    printf "%-28s | %-8s | %s\n" "$id" "$grp" "$desc"
  done
}

cmd_search() {
  local q="${1:-}"
  if [[ -z "$q" ]]; then
    echo "Usage: $0 search <text>"
    exit 1
  fi
  registry | awk -F'|' -v q="$q" 'BEGIN{IGNORECASE=1} $0 ~ q {printf "%-28s | %-8s | %s\n", $1, $2, $3}'
}

run_id() {
  local dry_run="$1"
  shift
  local id="${1:-}"
  shift || true

  if [[ -z "$id" ]]; then
    echo "Usage: $0 run [--dry-run] <id> [args...]"
    exit 1
  fi

  local cmd=""
  local joined_args="$*"
  case "$id" in
    bolt.verify) cmd="cd '$BOLT_DIR' && ./verify-bolt-stack.sh" ;;
    bolt.open) cmd="cd '$BOLT_DIR' && ./open-bolt.sh" ;;
    bolt.prepare.md) cmd="cd '$BOLT_DIR' && ./prepare-md-for-bolt.sh '${1:-}'" ;;
    bolt.use.nas-ollama) cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh nas-ollama" ;;
    bolt.use.laptop-ollama) cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh laptop-ollama '${1:-}'" ;;
    bolt.use.api.openai) cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-openai" ;;
    bolt.use.api.anthropic) cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-anthropic" ;;
    bolt.use.api.openrouter) cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-openrouter" ;;
    bolt.key.openai) cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh OPENAI_API_KEY '${1:-}'" ;;
    bolt.key.anthropic) cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh ANTHROPIC_API_KEY '${1:-}'" ;;
    bolt.key.openrouter) cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh OPEN_ROUTER_API_KEY '${1:-}'" ;;
    jarvis.status) cmd="cd '$OPS_ROOT' && ./jarvis-docker.sh status" ;;
    jarvis.logs.ingestion) cmd="cd '$OPS_ROOT' && ./jarvis-docker.sh logs ingestion" ;;
    jarvis.restart.ingestion) cmd="cd '$OPS_ROOT' && ./jarvis-docker.sh restart ingestion" ;;
    jarvis.doctor) cmd="cd '$OPS_ROOT' && bash ./scripts/jarvis_onecmd_doctor.sh" ;;
    jarvis.validate.fast) cmd="cd '$OPS_ROOT' && bash ./scripts/fast-preflight.sh" ;;
    jarvis.verify.targeted) cmd="cd '$OPS_ROOT' && ALLOW_NON_NAS=1 TARGETED_TEST_FILES=\"$joined_args\" bash ./scripts/jarvis_pre_deploy_gate.sh" ;;
    jarvis.deploy.smart) cmd="cd '$OPS_ROOT' && bash ./deploy-smart.sh" ;;
    jarvis.confidence) cmd="cd '$OPS_ROOT' && ./jarvis-ssh.sh \"cd /volume1/BRAIN/system/docker && bash ./scripts/jarvis_post_deploy_smoke.sh && bash ./scripts/jarvis_reality_check.sh\"" ;;
    jarvis.deploy.check) cmd="cd '$OPS_ROOT' && ps aux | grep -E 'deploy-smart|build-ingestion-fast|agent-deploy' | grep -v grep || true" ;;
    jarvis.deploy.ingestion) cmd="cd '$OPS_ROOT' && bash ./deploy-smart.sh --tier3" ;;
    jarvis.docs.preflight) cmd="cd '$OPS_ROOT' && bash ./preflight-docs.sh" ;;
    docs.cleanup.check) cmd="cd '$OPS_ROOT' && python3 ./scripts/docs_cleanup_propose.py && bash ./preflight-docs.sh" ;;
    jarvis.reality.check) cmd="cd '$OPS_ROOT' && ./jarvis-ssh.sh \"cd /volume1/BRAIN/system/docker && bash ./scripts/jarvis_reality_check.sh\"" ;;
    jarvis.safety.parallel) cmd="cd '$OPS_ROOT' && bash ./scripts/jarvis_safety_parallel.sh" ;;
    jarvis.ci.pipeline.status) cmd="cd '$OPS_ROOT' && bash ./scripts/github_pipeline_status.sh $joined_args" ;;
    jarvis.ssh.pq.strict) cmd="cd '$OPS_ROOT' && bash ./scripts/ssh_pq_audit.sh --strict" ;;
    jarvis.ssh.pq.upgrade.preflight) cmd="cd '$OPS_ROOT' && bash ./scripts/ssh_pq_upgrade_preflight.sh" ;;
    onecmd.doctor) cmd="cd '$OPS_ROOT' && bash ./scripts/jarvis_onecmd_doctor.sh" ;;
    profile.bolt)
      cmd="cd '$OPS_ROOT' && ./scripts/jarvis_onecmd_cli.sh run bolt.use.nas-ollama && ./scripts/jarvis_onecmd_cli.sh run bolt.verify"
      ;;
    profile.deploy)
      cmd="cd '$OPS_ROOT' && ./scripts/jarvis_onecmd_cli.sh run jarvis.doctor && ./scripts/jarvis_onecmd_cli.sh run jarvis.validate.fast && ./scripts/jarvis_onecmd_cli.sh run jarvis.deploy.check"
      ;;
    profile.dev)
      cmd="cd '$OPS_ROOT' && ./scripts/jarvis_onecmd_cli.sh run jarvis.status && ./scripts/jarvis_onecmd_cli.sh run jarvis.validate.fast"
      ;;
    *)
      echo "Unknown id: $id"
      exit 1
      ;;
  esac

  if [[ "$dry_run" == "1" ]]; then
    echo "$cmd"
    return
  fi

  echo "[onecmd] running: $id"
  eval "$cmd"
}

print_help() {
  cat <<EOF
jarvis_onecmd_cli - central command library

Commands:
  list
  search <text>
  run <id> [args...]
  run --dry-run <id> [args...]
EOF
}

main() {
  local sub="${1:-help}"
  case "$sub" in
    list) cmd_list ;;
    search) shift; cmd_search "$@" ;;
    run)
      shift
      if [[ "${1:-}" == "--dry-run" ]]; then
        shift
        run_id 1 "$@"
      else
        run_id 0 "$@"
      fi
      ;;
    help|-h|--help) print_help ;;
    *) print_help; exit 1 ;;
  esac
}

main "$@"
