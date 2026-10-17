#!/usr/bin/env bash
# Load-test monitor, runs on srv01 (Postgres + RabbitMQ live there).
# One CSV row per interval: document statuses for the tag, ingest queue, vLLM load.
#   nohup bash monitor.sh lt-s1 60 > ~/loadtest/mon-lt-s1.csv 2>&1 &
set -u
TAG=$1
EVERY=${2:-60}
VLLM=${VLLM_METRICS:-http://10.10.113.14:8000/metrics}

echo "ts,pending,processing,completed,vector_only,failed,skipped,q_ready,q_unacked,dlq,vllm_running,vllm_waiting,vllm_kv,vllm_prompt_total,vllm_gen_total"
while true; do
  ts=$(date +%FT%T)
  st=$(docker exec kb-postgres-1 psql -U postgres -d kb_llamaindex -tAF, -c "
    select count(*) filter (where status='pending'), count(*) filter (where status='processing'),
           count(*) filter (where status='completed'), count(*) filter (where status='vector_only'),
           count(*) filter (where status='failed'), count(*) filter (where status='skipped')
    from documents where department='$TAG'")
  q=$(docker exec kb-rabbitmq-1 rabbitmqctl list_queues -q name messages_ready messages_unacknowledged 2>/dev/null |
      awk '$1=="ingest.pending"{r=$2;u=$3} $1=="ingest.dlq"{d=$2} END{print r+0","u+0","d+0}')
  v=$(curl -s -m5 "$VLLM" | awk '
      /^vllm:num_requests_running\{/ {run=$2} /^vllm:num_requests_waiting\{/ {wait=$2}
      /^vllm:kv_cache_usage_perc\{/ {kv=$2} /^vllm:prompt_tokens_total\{/ {pt=$2} /^vllm:generation_tokens_total\{/ {gt=$2}
      END {printf "%s,%s,%s,%.0f,%.0f", run, wait, kv, pt, gt}')
  echo "$ts,$st,$q,$v"
  sleep "$EVERY"
done
