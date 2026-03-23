#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible wrapper. Use jarvis_onecmd_cli.sh as canonical script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/jarvis_onecmd_cli.sh" "$@"
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BOLT_DIR="$ROOT_DIR/bolt-diy"

registry() {
  cat <<'EOF'
bolt.verify|bolt|Verify bolt container, health, endpoint and configured model|cd bolt-diy && ./verify-bolt-stack.sh
bolt.open|bolt|Open bolt UI in browser|cd bolt-diy && ./open-bolt.sh
bolt.prepare.md|bolt|Prepare markdown payload and copy to clipboard|cd bolt-diy && ./prepare-md-for-bolt.sh <abs-md-path>
bolt.use.nas-ollama|bolt|Use NAS Ollama with qwen2.5-coder:7b|cd bolt-diy && ./switch-bolt-provider.sh nas-ollama
bolt.use.laptop-ollama|bolt|Use laptop Ollama endpoint|cd bolt-diy && ./switch-bolt-provider.sh laptop-ollama <laptop-ip>
bolt.use.api.openai|bolt|Use OpenAI provider|cd bolt-diy && ./switch-bolt-provider.sh api-openai
bolt.use.api.anthropic|bolt|Use Anthropic provider|cd bolt-diy && ./switch-bolt-provider.sh api-anthropic
bolt.use.api.openrouter|bolt|Use OpenRouter provider|cd bolt-diy && ./switch-bolt-provider.sh api-openrouter
bolt.key.openai|bolt|Set OPENAI_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh OPENAI_API_KEY <key>
bolt.key.anthropic|bolt|Set ANTHROPIC_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh ANTHROPIC_API_KEY <key>
bolt.key.openrouter|bolt|Set OPEN_ROUTER_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh OPEN_ROUTER_API_KEY <key>
jarvis.status|core|Show core stack status|./jarvis-docker.sh status
jarvis.logs.ingestion|core|Show ingestion logs|./jarvis-docker.sh logs ingestion
jarvis.restart.ingestion|core|Restart ingestion service|./jarvis-docker.sh restart ingestion
jarvis.deploy.check|deploy|Check if deployment is already running|ps aux | grep -E "deploy-smart|build-ingestion-fast|agent-deploy" | grep -v grep || true
jarvis.deploy.ingestion|deploy|Full rebuild deploy via smart wrapper|bash ./deploy-smart.sh --tier3
jarvis.docs.preflight|docs|Run docs preflight checks|bash ./preflight-docs.sh
jarvis.reality.check|ops|Run reality checks script|bash ./scripts/jarvis_reality_check.sh
EOF
}

print_help() {
  cat <<EOF
jarvis_onecmd - centralized one-command library

Commands:
  list
  search <text>
  run <id> [args...]
  run --dry-run <id> [args...]
EOF
}

cmd_list() {
  printf "%-28s | %-8s | %s\n" "ID" "GROUP" "DESCRIPTION"
  printf "%s\n" "-----------------------------+----------+---------------------------------------------"
  registry | while IFS='|' read -r id grp desc _; do
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
    jarvis.status) cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh status" ;;
    jarvis.logs.ingestion) cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh logs ingestion" ;;
    jarvis.restart.ingestion) cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh restart ingestion" ;;
    jarvis.deploy.check) cmd="cd '$ROOT_DIR' && ps aux | grep -E 'deploy-smart|build-ingestion-fast|agent-deploy' | grep -v grep || true" ;;
    jarvis.deploy.ingestion) cmd="cd '$ROOT_DIR' && bash ./deploy-smart.sh --tier3" ;;
    jarvis.docs.preflight) cmd="cd '$ROOT_DIR' && bash ./preflight-docs.sh" ;;
    jarvis.reality.check) cmd="cd '$ROOT_DIR' && bash ./scripts/jarvis_reality_check.sh" ;;
    *)
      echo "Unknown id: $id"
      exit 1
      ;;
  esac

  if [[ "$dry_run" == "1" ]]; then
    echo "$cmd"
    exit 0
  fi

  echo "[onecmd] running: $id"
  eval "$cmd"
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
#!/usr/bin/env bash
set -euo pipefail

# Unified command library for Jarvis + VS Code terminal usage.
# Usage examples:
#   ./scripts/jarvis_onecmd.sh list
#   ./scripts/jarvis_onecmd.sh search bolt
#   ./scripts/jarvis_onecmd.sh run bolt.verify
#   ./scripts/jarvis_onecmd.sh run bolt.use.laptop-ollama 192.168.1.50

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BOLT_DIR="$ROOT_DIR/bolt-diy"

registry() {
  cat <<'EOF'
bolt.verify|bolt|Verify bolt container, health, endpoint and configured model|cd bolt-diy && ./verify-bolt-stack.sh
bolt.open|bolt|Open bolt UI in browser|cd bolt-diy && ./open-bolt.sh
bolt.prepare.md|bolt|Prepare markdown payload and copy to clipboard|cd bolt-diy && ./prepare-md-for-bolt.sh <abs-md-path>
bolt.use.nas-ollama|bolt|Use NAS Ollama with qwen2.5-coder:7b|cd bolt-diy && ./switch-bolt-provider.sh nas-ollama
bolt.use.laptop-ollama|bolt|Use laptop Ollama endpoint|cd bolt-diy && ./switch-bolt-provider.sh laptop-ollama <laptop-ip>
bolt.use.api.openai|bolt|Use OpenAI provider|cd bolt-diy && ./switch-bolt-provider.sh api-openai
bolt.use.api.anthropic|bolt|Use Anthropic provider|cd bolt-diy && ./switch-bolt-provider.sh api-anthropic
bolt.use.api.openrouter|bolt|Use OpenRouter provider|cd bolt-diy && ./switch-bolt-provider.sh api-openrouter
bolt.key.openai|bolt|Set OPENAI_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh OPENAI_API_KEY <key>
bolt.key.anthropic|bolt|Set ANTHROPIC_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh ANTHROPIC_API_KEY <key>
bolt.key.openrouter|bolt|Set OPEN_ROUTER_API_KEY and restart bolt|cd bolt-diy && ./set-bolt-api-key.sh OPEN_ROUTER_API_KEY <key>
jarvis.status|core|Show core stack status|./jarvis-docker.sh status
jarvis.logs.ingestion|core|Show ingestion logs|./jarvis-docker.sh logs ingestion
jarvis.restart.ingestion|core|Restart ingestion service|./jarvis-docker.sh restart ingestion
jarvis.deploy.check|deploy|Check if deployment is already running|ps aux | grep -E "deploy-smart|build-ingestion-fast|agent-deploy" | grep -v grep || true
jarvis.deploy.ingestion|deploy|Full rebuild deploy via smart wrapper|bash ./deploy-smart.sh --tier3
jarvis.docs.preflight|docs|Run docs preflight checks|bash ./preflight-docs.sh
jarvis.reality.check|ops|Run reality checks script|bash ./scripts/jarvis_reality_check.sh
EOF
}

print_help() {
  cat <<EOF
jarvis_onecmd - centralized one-command library

Commands:
  list
  search <text>
  run <id> [args...]
  run --dry-run <id> [args...]

Examples:
  ./scripts/jarvis_onecmd.sh list
  ./scripts/jarvis_onecmd.sh search ollama
  ./scripts/jarvis_onecmd.sh run bolt.verify
  ./scripts/jarvis_onecmd.sh run bolt.prepare.md /abs/path/file.md
EOF
}

cmd_list() {
  printf "%-28s | %-8s | %s\n" "ID" "GROUP" "DESCRIPTION"
  printf "%s\n" "-----------------------------+----------+---------------------------------------------"
  registry | while IFS='|' read -r id grp desc _; do
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

resolve_id() {
  local id="$1"
  registry | awk -F'|' -v id="$id" '$1==id {print $0}'
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

  local row
  row="$(resolve_id "$id")"
  if [[ -z "$row" ]]; then
    echo "Unknown id: $id"
    exit 1
  fi

  local cmd
  cmd=""
  case "$id" in
    bolt.verify)
      cmd="cd '$BOLT_DIR' && ./verify-bolt-stack.sh"
      ;;
    bolt.open)
      cmd="cd '$BOLT_DIR' && ./open-bolt.sh"
      ;;
    bolt.prepare.md)
      cmd="cd '$BOLT_DIR' && ./prepare-md-for-bolt.sh '${1:-}'"
      ;;
    bolt.use.nas-ollama)
      cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh nas-ollama"
      ;;
    bolt.use.laptop-ollama)
      cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh laptop-ollama '${1:-}'"
      ;;
    bolt.use.api.openai)
      cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-openai"
      ;;
    bolt.use.api.anthropic)
      cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-anthropic"
      ;;
    bolt.use.api.openrouter)
      cmd="cd '$BOLT_DIR' && ./switch-bolt-provider.sh api-openrouter"
      ;;
    bolt.key.openai)
      cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh OPENAI_API_KEY '${1:-}'"
      ;;
    bolt.key.anthropic)
      cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh ANTHROPIC_API_KEY '${1:-}'"
      ;;
    bolt.key.openrouter)
      cmd="cd '$BOLT_DIR' && ./set-bolt-api-key.sh OPEN_ROUTER_API_KEY '${1:-}'"
      ;;
    jarvis.status)
      cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh status"
      ;;
    jarvis.logs.ingestion)
      cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh logs ingestion"
      ;;
    jarvis.restart.ingestion)
      cmd="cd '$ROOT_DIR' && ./jarvis-docker.sh restart ingestion"
      ;;
    jarvis.deploy.check)
      cmd="cd '$ROOT_DIR' && ps aux | grep -E 'deploy-smart|build-ingestion-fast|agent-deploy' | grep -v grep || true"
      ;;
    jarvis.deploy.ingestion)
      cmd="cd '$ROOT_DIR' && bash ./deploy-smart.sh --tier3"
      ;;
    jarvis.docs.preflight)
      cmd="cd '$ROOT_DIR' && bash ./preflight-docs.sh"
      ;;
    jarvis.reality.check)
      cmd="cd '$ROOT_DIR' && bash ./scripts/jarvis_reality_check.sh"
      ;;
    *)
      echo "Unimplemented id handler: $id"
      exit 1
      ;;
  esac

  if [[ "$dry_run" == "1" ]]; then
    echo "$cmd"
    exit 0
  fi

  echo "[onecmd] running: $id"
  eval "$cmd"
}

main() {
  local sub="${1:-help}"
  case "$sub" in
    list)
      cmd_list
      ;;
    search)
      shift
      cmd_search "$@"
      ;;
    run)
      shift
      if [[ "${1:-}" == "--dry-run" ]]; then
        shift
        run_id 1 "$@"
      else
        run_id 0 "$@"
      fi
      ;;
    help|-h|--help)
      print_help
      ;;
    *)
      print_help
      exit 1
      ;;
  esac
}

main "$@"
