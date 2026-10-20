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
  # Запись расщеплена: статус обработки живёт в doc_processing, в
  # documents.status остаётся дорасщеплённое значение, а отказ классификатора
  # строку обработки удаляет (intake_status='rejected' → отчётное 'skipped').
  # Выражение повторяет EFFECTIVE_STATUS из src/intake/repository.py; состав
  # колонок CSV при этом не меняется — наблюдения перепостов
  # (intake_status='duplicate') ни в одну колонку не попадают, и для
  # нагрузочного прогона это правильно: работы по ним нет.
  st=$(docker exec kb-postgres-1 psql -U postgres -d kb_llamaindex -tAF, -c "
    select count(*) filter (where s='pending'), count(*) filter (where s='processing'),
           count(*) filter (where s='completed'), count(*) filter (where s='vector_only'),
           count(*) filter (where s='failed'), count(*) filter (where s='skipped')
    from (select coalesce(p.status, case when d.intake_status='rejected'
                                         then 'skipped'
                                         when d.intake_status='duplicate'
                                         then 'duplicate'
                                         else d.status end) as s
            from documents d
            left join doc_processing p on p.doc_id = d.id
           where d.department='$TAG') t")
  q=$(docker exec kb-rabbitmq-1 rabbitmqctl list_queues -q name messages_ready messages_unacknowledged 2>/dev/null |
      awk '$1=="ingest.pending"{r=$2;u=$3} $1=="ingest.dlq"{d=$2} END{print r+0","u+0","d+0}')
  v=$(curl -s -m5 "$VLLM" | awk '
      /^vllm:num_requests_running\{/ {run=$2} /^vllm:num_requests_waiting\{/ {wait=$2}
      /^vllm:kv_cache_usage_perc\{/ {kv=$2} /^vllm:prompt_tokens_total\{/ {pt=$2} /^vllm:generation_tokens_total\{/ {gt=$2}
      END {printf "%s,%s,%s,%.0f,%.0f", run, wait, kv, pt, gt}')
  echo "$ts,$st,$q,$v"
  sleep "$EVERY"
done
