#!/bin/bash
# Install the Dave OS calendar ingester systemd unit + timer on Ralph.
# Run this from anywhere with SSH access to Ralph.
# (The Python script is already deployed via scp earlier; this just adds the timer.)

set -euo pipefail

RALPH_HOST="${RALPH_HOST:-100.73.64.27}"
RALPH_USER="${RALPH_USER:-ubuntu}"
RALPH_KEY="${RALPH_KEY:-$HOME/.ssh/LightsailDefaultKey-us-east-1.pem}"
SSH="ssh -i $RALPH_KEY -o ConnectTimeout=15 $RALPH_USER@$RALPH_HOST"
SCP="scp -i $RALPH_KEY"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">>> Copying systemd unit + timer files to /tmp on Ralph"
$SCP -q "$HERE/dave-os-calendar-ingest.service" "$HERE/dave-os-calendar-ingest.timer" \
       "$RALPH_USER@$RALPH_HOST:/tmp/"

echo ">>> Installing as system units"
$SSH 'sudo mv /tmp/dave-os-calendar-ingest.service /etc/systemd/system/ && \
      sudo mv /tmp/dave-os-calendar-ingest.timer   /etc/systemd/system/ && \
      sudo systemctl daemon-reload && \
      sudo systemctl enable --now dave-os-calendar-ingest.timer && \
      systemctl list-timers dave-os-calendar-ingest.timer --no-pager'

echo ">>> Done. Logs at /home/ubuntu/openbrain/logs/calendar-ingest.log"
echo "    Tail with: ssh ralph 'tail -f /home/ubuntu/openbrain/logs/calendar-ingest.log'"
