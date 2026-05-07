#!/bin/bash
# Deploy the EFC OpenBrain poller to Ralph.
# Idempotent — safe to re-run.
#
# Usage:
#   bash deploy-to-ralph.sh
#
# Requires:
#   - SSH access to Ralph as ubuntu (default per shared playbook)
#   - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY available locally
#     in the environment (will be pushed to /etc/efc/env on Ralph)

set -euo pipefail

RALPH_HOST="${RALPH_HOST:-100.73.64.27}"
RALPH_USER="${RALPH_USER:-ubuntu}"
RALPH_KEY="${RALPH_KEY:-$HOME/.ssh/LightsailDefaultKey-us-east-1.pem}"
SSH="ssh -i $RALPH_KEY $RALPH_USER@$RALPH_HOST"
SCP="scp -i $RALPH_KEY"

# --- Local checks ----------------------------------------------------
: "${SUPABASE_URL:?Set SUPABASE_URL in your local env before deploy}"
: "${SUPABASE_SERVICE_ROLE_KEY:?Set SUPABASE_SERVICE_ROLE_KEY before deploy}"

REMOTE_DIR=/home/ubuntu/efc/openbrain-poller
ENV_FILE=/etc/efc/env

echo ">>> Creating remote dirs"
$SSH "mkdir -p $REMOTE_DIR && sudo mkdir -p /etc/efc && sudo chown ubuntu:ubuntu /etc/efc"

echo ">>> Copying poller files"
$SCP -q poller.py requirements.txt "$RALPH_USER@$RALPH_HOST:$REMOTE_DIR/"

echo ">>> Setting up Python venv"
$SSH "cd $REMOTE_DIR && python3 -m venv venv && \
      ./venv/bin/pip install --upgrade pip --quiet && \
      ./venv/bin/pip install -r requirements.txt --quiet"

echo ">>> Writing /etc/efc/env (mode 600)"
$SSH "cat > $ENV_FILE <<'EOF'
SUPABASE_URL=$SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY
EOF
chmod 600 $ENV_FILE"

echo ">>> Installing systemd unit + timer"
$SCP -q efc-poller.service efc-poller.timer "$RALPH_USER@$RALPH_HOST:/tmp/"
$SSH "sudo mv /tmp/efc-poller.service /etc/systemd/system/efc-poller.service && \
      sudo mv /tmp/efc-poller.timer  /etc/systemd/system/efc-poller.timer && \
      sudo systemctl daemon-reload && \
      sudo systemctl enable --now efc-poller.timer"

echo ">>> Smoke test (one immediate run)"
$SSH "sudo systemctl start efc-poller.service && sleep 3 && \
      journalctl -u efc-poller.service -n 30 --no-pager"

echo ">>> Timer status"
$SSH "systemctl list-timers efc-poller.timer --no-pager"

echo
echo "Done. Tail logs anytime with:"
echo "  ssh -i $RALPH_KEY $RALPH_USER@$RALPH_HOST 'journalctl -u efc-poller.service -f'"
