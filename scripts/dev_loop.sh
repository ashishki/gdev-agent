#!/usr/bin/env bash
# dev_loop.sh — Autonomous development loop with rate-limit resilience.
#
# Usage:
#   ./scripts/dev_loop.sh                    # use default orchestrator prompt
#   ./scripts/dev_loop.sh path/to/prompt.md  # use custom prompt file
#   WAIT_SECONDS=1800 ./scripts/dev_loop.sh  # override reset wait time
#
# Environment variables (set in .env or shell):
#   ANTHROPIC_API_KEY   — required
#   TELEGRAM_BOT_TOKEN  — optional, for phase report delivery
#   TELEGRAM_CHAT_ID    — optional, for phase report delivery
#   WAIT_SECONDS        — seconds to wait after rate limit (default: 3600)
#   MAX_RETRIES         — max rate-limit retries before giving up (default: 10)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

PROMPT_FILE="${1:-docs/prompts/ORCHESTRATOR.md}"
WAIT_SECONDS="${WAIT_SECONDS:-3600}"
MAX_RETRIES="${MAX_RETRIES:-10}"
LOG_FILE="dev_loop.log"
CHECKPOINT_FILE="/tmp/gdev_checkpoint.md"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── Helpers ───────────────────────────────────────────────────────────────────

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

notify_telegram() {
    local msg="$1"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d parse_mode="Markdown" \
            --data-urlencode "text=${msg}" > /dev/null 2>&1 || true
    fi
}

is_rate_limit() {
    # Check last 30 lines of log for rate limit signals
    tail -30 "$LOG_FILE" 2>/dev/null \
        | grep -qiE "rate.?limit|429|overloaded|quota.?exceed|too.many.requests|RATE_LIMIT_HIT"
}

is_complete() {
    tail -30 "$LOG_FILE" 2>/dev/null \
        | grep -qiE "PROJECT.COMPLETE|Development cycle complete|MVP ready"
}

is_blocked() {
    tail -30 "$LOG_FILE" 2>/dev/null \
        | grep -qiE "^\[!\]|BLOCKED|blocker|needs human"
}

build_resume_prompt() {
    local checkpoint=""
    if [ -f "$CHECKPOINT_FILE" ]; then
        checkpoint=$(cat "$CHECKPOINT_FILE")
    fi

    cat <<EOF
Continue the development loop.

You are the Orchestrator for gdev-agent.
Project root: ${PROJECT_ROOT}

Session was interrupted (rate limit or restart). Resume from current state.

Checkpoint (may be empty if first resume):
---
${checkpoint}
---

Instructions:
1. Re-read docs/CODEX_PROMPT.md and docs/tasks.md to determine exact current state.
2. Do NOT repeat any task already marked ✅.
3. Continue from the next incomplete task.
4. Follow docs/prompts/ORCHESTRATOR.md exactly.

$(cat "${PROMPT_FILE}")
EOF
}

# ── Main ──────────────────────────────────────────────────────────────────────

cd "$PROJECT_ROOT"

# Load .env if present
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

log "=== dev_loop started. Prompt: ${PROMPT_FILE} ==="
notify_telegram "🚀 *dev_loop started*
Project: gdev-agent
Prompt: \`${PROMPT_FILE}\`
Rate limit wait: ${WAIT_SECONDS}s"

RETRY_COUNT=0
FIRST_RUN=true

while true; do
    if [ "$FIRST_RUN" = true ]; then
        PROMPT_CONTENT=$(cat "$PROMPT_FILE")
        FIRST_RUN=false
    else
        PROMPT_CONTENT=$(build_resume_prompt)
    fi

    log "--- Starting claude session (retry ${RETRY_COUNT}/${MAX_RETRIES}) ---"

    # Run claude. --print makes it non-interactive; output is captured + tee'd to log.
    # --dangerously-skip-permissions is blocked under root.
    # On root: permissions are handled via .claude/settings.json allowlist.
    # On non-root: uncomment the flag below for full auto-mode.
    claude \
        --print \
        -p "$PROMPT_CONTENT" \
        2>&1 | tee -a "$LOG_FILE" || true

    # ── Check exit condition ───────────────────────────────────────────────────

    if is_complete; then
        log "=== PROJECT COMPLETE ==="
        notify_telegram "✅ *PROJECT COMPLETE*
gdev-agent development loop finished.
Check \`dev_loop.log\` for full session log."
        break
    fi

    if is_blocked; then
        log "=== BLOCKED — human input required ==="
        notify_telegram "🔴 *BLOCKED — needs your input*
dev_loop paused. Check \`dev_loop.log\` for details.
Fix the blocker, then restart: \`./scripts/dev_loop.sh\`"
        break
    fi

    if is_rate_limit; then
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ "$RETRY_COUNT" -gt "$MAX_RETRIES" ]; then
            log "=== MAX RETRIES (${MAX_RETRIES}) reached. Stopping. ==="
            notify_telegram "⛔ *dev_loop stopped*
Max retries (${MAX_RETRIES}) reached after repeated rate limits."
            break
        fi

        log "Rate limit hit. Waiting ${WAIT_SECONDS}s before retry ${RETRY_COUNT}/${MAX_RETRIES}..."
        notify_telegram "⏸ *Rate limit hit* (${RETRY_COUNT}/${MAX_RETRIES})
Waiting $((WAIT_SECONDS / 60)) min. Will auto-resume."

        sleep "$WAIT_SECONDS"

        log "Resuming after rate limit wait."
        notify_telegram "▶️ *Resuming dev_loop*
Retry ${RETRY_COUNT}/${MAX_RETRIES}"
        continue
    fi

    # Session ended without a clear signal — treat as done or unknown stop
    log "Session ended without rate limit or completion signal. Stopping."
    notify_telegram "⚠️ *dev_loop stopped* (unknown reason)
Check \`dev_loop.log\` to determine what happened."
    break

done

log "=== dev_loop exited. Total retries: ${RETRY_COUNT} ==="
