#!/bin/bash
# Odysseus Home Assistant add-on entrypoint.
#
# Translates /data/options.json into the environment variables Odysseus reads,
# then starts the server. Home Assistant runs add-ons as root and maps the
# persistent volume at /data; all Odysseus state is redirected there.
set -euo pipefail

OPTIONS=/data/options.json
mkdir -p /data

log() { echo "[odysseus] $*"; }

# --- options.json helpers ---------------------------------------------------
_opt() {
    # Print a scalar option or the empty string when absent/null.
    jq -r --arg k "$1" '.[$k] // empty' "$OPTIONS" 2>/dev/null || true
}

_flag() {
    # Print "true"/"false" for a boolean option, falling back to $2 when the
    # option is absent (defaults match config.yaml).
    local value
    value="$(jq -r --arg k "$1" --arg d "$2" \
        'if .[$k] == null then $d else (.[$k] | tostring) end' \
        "$OPTIONS" 2>/dev/null || echo "$2")"
    [ "$value" = "true" ] && echo "true" || echo "false"
}

_list() {
    # Print a newline-separated list option.
    jq -r --arg k "$1" '(. [$k] // []) | .[]' "$OPTIONS" 2>/dev/null || true
}

# --- core paths -------------------------------------------------------------
export ODYSSEUS_DATA_DIR=/data
export HOME=/data
export APP_PORT=7000
export LOCALHOST_BYPASS=false
export ODYSSEUS_SKIP_ADMIN_PROMPT=1

# --- Home Assistant authentication bridge -----------------------------------
export ODYSSEUS_HA_INGRESS_AUTH="$(_flag ha_ingress_auth true)"
export ODYSSEUS_HA_AUTH_API="$(_flag ha_password_auth true)"
export ODYSSEUS_HA_BOOTSTRAP_ADMIN="$(_flag ha_bootstrap_admin true)"
export ODYSSEUS_HA_TRUSTED_IPS="172.30.32.2"
export ODYSSEUS_HA_ADMIN_USERS="$(jq -r '(.ha_admin_users // []) | join(",")' "$OPTIONS" 2>/dev/null || true)"

# --- Odysseus native auth ---------------------------------------------------
export AUTH_ENABLED="$(_flag auth_enabled true)"

ADMIN_USER="$(_opt admin_user)"
ADMIN_PASSWORD="$(_opt admin_password)"
if [ -n "$ADMIN_USER" ]; then export ODYSSEUS_ADMIN_USER="$ADMIN_USER"; fi
if [ -n "$ADMIN_PASSWORD" ]; then export ODYSSEUS_ADMIN_PASSWORD="$ADMIN_PASSWORD"; fi

# --- Model / network options ------------------------------------------------
LLM_HOST="$(_opt llm_host)"
[ -n "$LLM_HOST" ] && export LLM_HOST="$LLM_HOST"
OLLAMA_BASE_URL="$(_opt ollama_base_url)"
[ -n "$OLLAMA_BASE_URL" ] && export OLLAMA_BASE_URL="$OLLAMA_BASE_URL"

# Provider dropdown + API key. The seed script (run after DB init) turns these
# into a ready-to-use model endpoint; openai additionally feeds OPENAI_API_KEY
# so model discovery sees it immediately.
SEED_PROVIDER="$(_opt llm_provider)"
SEED_KEY="$(_opt llm_api_key)"
SEED_MODEL="$(_opt llm_model)"
if [ -n "$SEED_PROVIDER" ] && [ "$SEED_PROVIDER" != "none" ] && [ -n "$SEED_KEY" ]; then
    export ODYSSEUS_SEED_PROVIDER="$SEED_PROVIDER"
    export ODYSSEUS_SEED_API_KEY="$SEED_KEY"
    export ODYSSEUS_SEED_MODEL="$SEED_MODEL"
    if [ "$SEED_PROVIDER" = "openai" ]; then
        export OPENAI_API_KEY="$SEED_KEY"
    fi
fi

# --- Home Assistant MQTT (live activity entity) -----------------------------
# Broker credentials live behind the Supervisor services API. Declaring the
# mqtt service in config.yaml is what makes this endpoint return data; without a
# broker the call fails and the activity publisher simply stays disabled.
MQTT_JSON="$(curl -fsS -H "Authorization: Bearer ${SUPERVISOR_TOKEN:-}" \
    http://supervisor/services/mqtt 2>/dev/null || true)"
if [ -n "$MQTT_JSON" ]; then
    export ODYSSEUS_MQTT_HOST="$(printf '%s' "$MQTT_JSON" | jq -r '.data.host // empty')"
    export ODYSSEUS_MQTT_PORT="$(printf '%s' "$MQTT_JSON" | jq -r '.data.port // empty')"
    export ODYSSEUS_MQTT_USERNAME="$(printf '%s' "$MQTT_JSON" | jq -r '.data.username // empty')"
    export ODYSSEUS_MQTT_PASSWORD="$(printf '%s' "$MQTT_JSON" | jq -r '.data.password // empty')"
    if [ -n "$ODYSSEUS_MQTT_HOST" ]; then
        export ODYSSEUS_MQTT_ENABLED=true
        log "MQTT broker at ${ODYSSEUS_MQTT_HOST}:${ODYSSEUS_MQTT_PORT}; activity entity enabled"
    fi
fi

ALLOWED_ORIGINS="$(jq -r '(.allowed_origins // []) | join(",")' "$OPTIONS" 2>/dev/null || true)"
[ -n "$ALLOWED_ORIGINS" ] && export ALLOWED_ORIGINS="$ALLOWED_ORIGINS"

# --- Free-form extra environment -------------------------------------------
while IFS= read -r line; do
    [ -n "$line" ] && export "$line"
done < <(_list extra_env)

# --- First-time setup -------------------------------------------------------
# Importing the database layer creates the data directory and runs
# create_all() so the app never boots against a missing schema.
python - <<'PY' || log "database bootstrap skipped"
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("ODYSSEUS_DATA_DIR", "/data")
import core.database  # noqa: F401  (import side effect: create_all)
PY

# Seed the provider model endpoint chosen in the add-on options.
if [ -n "${ODYSSEUS_SEED_PROVIDER:-}" ]; then
    python /seed_provider.py || log "provider seed failed (continuing)"
fi

# Create the initial admin only when the operator supplied credentials.
# Otherwise the first Home Assistant user is promoted by the ingress bridge
# (ha_bootstrap_admin), or the operator uses the first-run setup screen.
if [ -n "$ADMIN_USER" ] && [ -n "$ADMIN_PASSWORD" ]; then
    python /app/setup.py || log "setup.py reported an error (continuing)"
fi

log "Starting Odysseus on 0.0.0.0:7000 (data=/data, AUTH_ENABLED=${AUTH_ENABLED})"
exec python -m uvicorn app:app --host 0.0.0.0 --port 7000