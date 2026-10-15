#!/usr/bin/env bash
# Throughput sweep against the running vllm serve: random prompts, ingest-like input length.
#   ./bench.sh <label> [input_len] [output_len]
set -u
LABEL=$1; IN=${2:-8000}; OUT=${3:-512}
mkdir -p "$HOME/bench"
for C in 1 8 16 32; do
  N=$(( C < 4 ? 4 : C * 3 ))
  "$HOME/vllm-env/bin/vllm" bench serve --backend openai-chat --endpoint /v1/chat/completions \
    --base-url http://127.0.0.1:8000 --model "${NAME:-qwen38}" --tokenizer "$HOME/models/$(cat "$HOME/vllm.model")" \
    --dataset-name random --random-input-len "$IN" --random-output-len "$OUT" --ignore-eos \
    --num-prompts "$N" --max-concurrency "$C" --percentile-metrics ttft,tpot,e2el \
    > "$HOME/bench/$LABEL-c$C.txt" 2>&1
  echo "== $LABEL c=$C"
  grep -E "Successful|Output token throughput|Total Token throughput|Mean TTFT|Median TTFT|Mean TPOT|Median TPOT" "$HOME/bench/$LABEL-c$C.txt"
done
