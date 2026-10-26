#!/usr/bin/env bash
set -euo pipefail

REGISTRY="$HOME/.agents/mcp/servers.json"
ENV_FILE="${MCP_ENV_FILE:-$HOME/.agents/mcp/.env}"
SKIP_MCPS=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip)
      SKIP_MCPS="$2"
      shift 2
      ;;
    *)
      REGISTRY="$1"
      shift
      ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [ ! -f "$REGISTRY" ]; then
  echo "Registry not found: $REGISTRY" >&2
  exit 1
fi

resolve_env_value() {
  local key="$1"
  local val="${!key:-}"
  if [ -n "$val" ]; then
    printf '%s' "$val"
    return 0
  fi

  if command -v launchctl >/dev/null 2>&1; then
    val="$(launchctl getenv "$key" 2>/dev/null || true)"
    if [ -n "$val" ]; then
      printf '%s' "$val"
      return 0
    fi
  fi

  return 1
}

remove_server() {
  local name="$1"
  if command -v codex >/dev/null 2>&1; then
    codex mcp remove "$name" >/dev/null 2>&1 || true
  fi
  if command -v claude >/dev/null 2>&1; then
    claude mcp remove "$name" >/dev/null 2>&1 || true
  fi
}

count=$(jq '.servers | length' "$REGISTRY")

# Split SKIP_MCPS by comma into array or string matching
skip_str=",${SKIP_MCPS},"

if [ "$count" -gt 0 ]; then
for i in $(seq 0 $((count - 1))); do
  name=$(jq -r ".servers[$i].name" "$REGISTRY")
  type=$(jq -r ".servers[$i].type // \"http\"" "$REGISTRY")

  if [ -z "$name" ] || [ "$name" = "null" ]; then
    echo "skip index:$i missing name" >&2
    continue
  fi

  if [[ "$skip_str" == *",$name,"* ]]; then
    echo "skip $name: excluded by --skip parameter"
    continue
  fi

  required_env=()
  while IFS= read -r key; do
    [ -n "$key" ] && required_env+=("$key")
  done < <(jq -r ".servers[$i].required_env // [] | .[]" "$REGISTRY")

  missing=()
  set +u
  for key in "${required_env[@]}"; do
    if ! resolve_env_value "$key" >/dev/null; then
      missing+=("$key")
    fi
  done
  set -u

  set +u
  if [ ${#missing[@]} -gt 0 ]; then
    echo "skip $name: missing $(IFS=,; echo "${missing[*]}")" >&2
    remove_server "$name"
    set -u
    continue
  fi
  set -u

  if [ "$type" = "http" ]; then
    url=$(jq -r ".servers[$i].url" "$REGISTRY")
    if [ -z "$url" ] || [ "$url" = "null" ]; then
      echo "skip $name: missing url" >&2
      remove_server "$name"
      continue
    fi

    if [ "$name" = "composio" ]; then
      # `codex mcp add` immediately starts OAuth and blocks this noninteractive sync.
      # The Codex entry is managed in ~/.codex/config.toml; Claude's user config
      # can be updated without beginning authentication.
      CLAUDE_USER_CONFIG="$HOME/.claude.json"
      if [ -f "$CLAUDE_USER_CONFIG" ]; then
        temp_file="$(mktemp)"
        jq --arg url "$url" '.mcpServers = (.mcpServers // {}) | .mcpServers.composio = {type: "http", url: $url}' "$CLAUDE_USER_CONFIG" > "$temp_file"
        mv "$temp_file" "$CLAUDE_USER_CONFIG"
      fi
      echo "Composio configured; authenticate separately in each client."
    else
      if command -v codex >/dev/null 2>&1; then
        codex mcp remove "$name" >/dev/null 2>&1 || true
        codex mcp add "$name" --url "$url" || echo "Failed to add $name" >&2
      fi

      if command -v claude >/dev/null 2>&1; then
        claude mcp remove "$name" >/dev/null 2>&1 || true
        claude mcp add --transport http "$name" "$url" || echo "Failed to add $name" >&2
      fi
    fi

  elif [ "$type" = "stdio" ]; then
    cmd=$(jq -r ".servers[$i].command" "$REGISTRY")
    if [ -z "$cmd" ] || [ "$cmd" = "null" ]; then
      echo "skip $name: missing command" >&2
      remove_server "$name"
      continue
    fi

    args=()
    while IFS= read -r arg; do
      args+=("$arg")
    done < <(jq -r ".servers[$i].args // [] | .[]" "$REGISTRY")

    pass_env=()
    while IFS= read -r key; do
      [ -n "$key" ] && pass_env+=("$key")
    done < <(jq -r ".servers[$i].pass_env // [] | .[]" "$REGISTRY")

    codex_env_args=()
    claude_env_args=()
    set +u
    for key in "${pass_env[@]}"; do
      val="$(resolve_env_value "$key" || true)"
      codex_env_args+=(--env "$key=$val")
      claude_env_args+=(-e "$key=$val")
    done
    set -u

    if command -v codex >/dev/null 2>&1; then
      codex mcp remove "$name" >/dev/null 2>&1 || true
      if [ ${#args[@]} -gt 0 ]; then
        if [ ${#codex_env_args[@]} -gt 0 ]; then
          codex mcp add "$name" "${codex_env_args[@]}" -- "$cmd" "${args[@]}"
        else
          codex mcp add "$name" -- "$cmd" "${args[@]}"
        fi
      else
        if [ ${#codex_env_args[@]} -gt 0 ]; then
          codex mcp add "$name" "${codex_env_args[@]}" -- "$cmd"
        else
          codex mcp add "$name" -- "$cmd"
        fi
      fi
    fi

    if command -v claude >/dev/null 2>&1; then
      claude mcp remove "$name" >/dev/null 2>&1 || true
      if [ ${#args[@]} -gt 0 ]; then
        if [ ${#claude_env_args[@]} -gt 0 ]; then
          claude mcp add "$name" "${claude_env_args[@]}" -- "$cmd" "${args[@]}"
        else
          claude mcp add "$name" -- "$cmd" "${args[@]}"
        fi
      else
        if [ ${#claude_env_args[@]} -gt 0 ]; then
          claude mcp add "$name" "${claude_env_args[@]}" -- "$cmd"
        else
          claude mcp add "$name" -- "$cmd"
        fi
      fi
    fi

  else
    echo "skip $name: unsupported type '$type'" >&2
    remove_server "$name"
  fi
done
fi

# ── Antigravity CLI (agy) ─────────────────────────────────────────────────────
# Reads a single JSON file rather than per-server CLI calls.
# Regenerate it from the same registry so all CLIs stay aligned.
AGY_CONFIG="$HOME/.gemini/config/mcp_config.json"
if [ -d "$(dirname "$AGY_CONFIG")" ]; then
  jq --arg skip "$skip_str" '{
    mcpServers: (
      .servers
      | map(select(.name as $n | ($skip | contains("," + $n + ",")) | not))
      | map(
          if (.type // "http") == "http"
          then { (.name): { httpUrl: .url } }
          else { (.name): ({ command: .command }
                 + (if (.args // []) | length > 0 then { args: .args } else {} end)
                 + (if (.pass_env // []) | length > 0 then { env: (reduce .pass_env[] as $k ({}; . + { ($k): (env[$k] // "") })) } else {} end)) }
          end
        )
      | add // {}
    )
  }' "$REGISTRY" > "$AGY_CONFIG" && echo "Antigravity MCP config written: $AGY_CONFIG"
fi

# ── Copilot / VS Code ─────────────────────────────────────────────────────────
# VS Code (Copilot) reads ~/Library/Application Support/Code/User/mcp.json
# Format: { "servers": { "<name>": { "type": "http"|"stdio", "url"|"command": ... } } }
VSCODE_MCP="$HOME/Library/Application Support/Code/User/mcp.json"
if [ -d "$(dirname "$VSCODE_MCP")" ]; then
  jq --arg skip "$skip_str" '{
    servers: (
      .servers
      | map(select(.name as $n | ($skip | contains("," + $n + ",")) | not))
      | map(
          if (.type // "http") == "http"
          then { (.name): { type: "http", url: .url } }
          else
            { (.name): (
                { type: "stdio", command: .command }
                + (if (.args // []) | length > 0 then { args: .args } else {} end)
                + (if (.pass_env // []) | length > 0
                   then { env: (reduce .pass_env[] as $k ({}; . + { ($k): (env[$k] // "") })) }
                   else {} end)
              )
            }
          end
        )
      | add // {}
    )
  }' "$REGISTRY" > "$VSCODE_MCP" && echo "Copilot/VSCode MCP config written: $VSCODE_MCP"
fi

# ── Cursor ───────────────────────────────────────────────────────────────────
# Cursor uses { mcpServers: { name: { type, url|command, args?, env? } } }.
CURSOR_MCP="$HOME/.cursor/mcp.json"
if [ -d "$(dirname "$CURSOR_MCP")" ]; then
  jq --arg skip "$skip_str" '{
    mcpServers: (
      .servers
      | map(select(.name as $n | ($skip | contains("," + $n + ",")) | not))
      | map(
          if (.type // "http") == "http"
          then { (.name): { type: "http", url: .url } }
          else { (.name): ({ type: "stdio", command: .command }
                 + (if (.args // []) | length > 0 then { args: .args } else {} end)
                 + (if (.pass_env // []) | length > 0 then { env: (reduce .pass_env[] as $k ({}; . + { ($k): (env[$k] // "") })) } else {} end)) }
          end
        )
      | add // {}
    )
  }' "$REGISTRY" > "$CURSOR_MCP" && echo "Cursor MCP config written: $CURSOR_MCP"
fi

# ── Hermes ──────────────────────────────────────────────────────────────────
# Hermes reads HTTP MCP servers from ~/.hermes/config.yaml. Preserve any
# user-defined servers; add the shared Composio server only when absent.
HERMES_CONFIG="$HOME/.hermes/config.yaml"
if [ -f "$HERMES_CONFIG" ] && [ "$(jq -r '.servers[] | select(.name == "composio") | .url' "$REGISTRY" | head -n 1)" != "" ]; then
  COMPOSIO_URL="$(jq -r '.servers[] | select(.name == "composio") | .url' "$REGISTRY" | head -n 1)"
  if ! grep -q '^mcp_servers:' "$HERMES_CONFIG"; then
    printf '\n# Shared MCP registry: ~/.agents/mcp/servers.json\nmcp_servers:\n  composio:\n    url: "%s"\n    auth: oauth\n' "$COMPOSIO_URL" >> "$HERMES_CONFIG"
    echo "Hermes MCP config written: $HERMES_CONFIG"
  elif ! grep -q '^  composio:' "$HERMES_CONFIG"; then
    HERMES_TMP="$(mktemp)"
    awk -v url="$COMPOSIO_URL" '
      /^mcp_servers:$/ {
        print
        print "  composio:"
        print "    url: \"" url "\""
        print "    auth: oauth"
        next
      }
      { print }
    ' "$HERMES_CONFIG" > "$HERMES_TMP"
    mv "$HERMES_TMP" "$HERMES_CONFIG"
    echo "Hermes MCP config written: $HERMES_CONFIG"
  fi
fi

echo "MCP sync complete"
