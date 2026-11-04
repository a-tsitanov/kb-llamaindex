#!/usr/bin/env bash
# Restart the Temporal worker when one of its process groups stops polling
# (agent_v2 on .31). Run from cron every 5 minutes:
#   */5 * * * * /home/user/projects/agent_v2/scripts/worker_watchdog.sh >> /home/user/projects/agent_v2/logs/worker_watchdog.cron.log 2>&1
#
# 2026-10-28: the graph_build child sat 14 h in a CPU-bound Leiden pass that
# held the GIL. Its event loop never ran, so kb-graph-build showed "No Workers
# Running", both graph workflows died on heartbeat timeouts and nobody noticed
# until the UI was opened. Leiden now runs in a child process
# (src/graph/communities.py:_run_in_process); this is the net for the next
# hang of any kind.
#
# Only WORKFLOW pollers are checked. An activity poller legitimately goes
# quiet while all its slots are busy (the llm queue at full load), a workflow
# poller does not — it long-polls every <=60 s while its event loop is alive.
# Queues without workflows (kb-ingest-llm, kb-search-large) are not covered.
#
# A queue is stale when its workflow poller is missing or last polled more
# than STALE_S ago. Restart only after STRIKES consecutive stale checks, and
# at most once per COOLDOWN_S (a fresh worker needs a minute to register).
set -uo pipefail

QUEUES="${WATCHDOG_QUEUES:-kb-ingest kb-ingest-merge kb-search-small kb-graph-build kb-monitor}"
WORKER="${WATCHDOG_WORKER:-agent_v2-worker-1}"
TEMPORAL="${WATCHDOG_TEMPORAL:-agent_v2-temporal-1}"
STALE_S="${WATCHDOG_STALE_S:-300}"
STRIKES="${WATCHDOG_STRIKES:-2}"
COOLDOWN_S="${WATCHDOG_COOLDOWN_S:-1800}"

LOG=/home/user/projects/agent_v2/logs/worker_watchdog.log
STATE=/home/user/projects/agent_v2/logs/.worker_watchdog
mkdir -p "$(dirname "$LOG")" "$STATE"
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# Worker deliberately down (memory pressure, deploy) — not our business.
if [ "$(docker inspect -f '{{.State.Running}}' "$WORKER" 2>/dev/null)" != true ]; then
  exit 0
fi

now=$(date -u +%s)
stale=""
for q in $QUEUES; do
  json=$(docker exec "$TEMPORAL" temporal --address "$TEMPORAL:7233" \
    task-queue describe --task-queue "$q" -o json 2>/dev/null)
  if [ -z "$json" ]; then
    # Temporal itself unreachable: a worker restart would not help.
    echo "$(ts) SKIP  temporal not answering for $q" >>"$LOG"
    exit 0
  fi
  last=$(printf '%s' "$json" | jq -r \
    '[.pollers[]? | select(.taskQueueType=="workflow") | .lastAccessTime] | max // ""')
  age=999999
  if [ -n "$last" ]; then
    age=$(( now - $(date -u -d "$last" +%s) ))
  fi
  if [ "$age" -gt "$STALE_S" ]; then
    stale="$stale $q(${age}s)"
  fi
done

if [ -z "$stale" ]; then
  rm -f "$STATE/strikes"
  exit 0
fi

n=$(( $(cat "$STATE/strikes" 2>/dev/null || echo 0) + 1 ))
echo "$n" >"$STATE/strikes"
echo "$(ts) STALE strike $n/$STRIKES:$stale" >>"$LOG"
[ "$n" -lt "$STRIKES" ] && exit 0

last_restart=$(cat "$STATE/last_restart" 2>/dev/null || echo 0)
if [ $(( now - last_restart )) -lt "$COOLDOWN_S" ]; then
  echo "$(ts) HOLD  restarted $(( now - last_restart ))s ago, cooldown ${COOLDOWN_S}s" >>"$LOG"
  exit 0
fi

echo "$(ts) RESTART $WORKER — stale:$stale" >>"$LOG"
if docker restart "$WORKER" >/dev/null 2>&1; then
  echo "$now" >"$STATE/last_restart"
  rm -f "$STATE/strikes"
else
  echo "$(ts) FAIL  docker restart $WORKER" >>"$LOG"
fi
