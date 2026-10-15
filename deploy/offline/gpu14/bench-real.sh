#!/usr/bin/env bash
# Sweep on real documents (entity/relation extraction prompts from the load-test set).
# Real text matters for speculative decoding: random tokens give ~0 draft acceptance.
#   ./bench-real.sh <label> [output_len]
set -u
LABEL=$1; OUT=${2:-1024}
mkdir -p "$HOME/bench"
for C in ${CONC:-1 8 16}; do
  N=$(( C < 4 ? 6 : C * 3 ))
  "$HOME/vllm-env/bin/vllm" bench serve --backend openai-chat --endpoint /v1/chat/completions \
    --base-url http://127.0.0.1:8000 --model "${NAME:-qwen38}" --tokenizer "$HOME/models/$(cat "$HOME/vllm.model")" \
    --dataset-name custom --dataset-path "$HOME/bench/prompts.jsonl" --custom-output-len "$OUT" \
    --extra-body '{"chat_template_kwargs":{"enable_thinking":false},"temperature":0}' \
    --num-prompts "$N" --max-concurrency "$C" --percentile-metrics ttft,tpot,e2el \
    > "$HOME/bench/$LABEL-c$C.txt" 2>&1
  echo "== $LABEL c=$C"
  grep -E "Successful|Total input tokens|Total generated|Output token throughput|Total Token throughput|Median TTFT|Median TPOT|Acceptance rate|Mean acceptance length" "$HOME/bench/$LABEL-c$C.txt"
done
