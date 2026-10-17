#!/usr/bin/env bash
# Real-text sweep: MTP head vs DFlash2 drafter, NVFP4 TP=2 (baseline: real-base-*).
# Speculation needs extra VRAM for draft weights, so context and batch are trimmed.
set -u
M=Unsloth--Qwen3.8-27B-NVFP4
SPEC_ARGS=(--max-model-len 16384 --max-num-seqs 16)
wait_ready() {
  until curl -sf localhost:8000/v1/models >/dev/null; do
    pgrep -f "[v]llm serve" >/dev/null || { echo "DIED $1"; grep -E "Error:|error:" ~/vllm-serve.log | sort -u | tail -4; return 1; }
    sleep 15
  done
}
run() {
  local label=$1; shift
  NVCC=1 KV=fp8 bash ~/serve.sh $M tp "$@"; sleep 5
  wait_ready "$label" && grep -E "KV cache size" ~/vllm-serve.log | tail -1 && bash ~/bench-real.sh "$label"
}
GPU_UTIL=0.93 run real-mtp "${SPEC_ARGS[@]}" --speculative-config '{"method":"mtp","num_speculative_tokens":3}'
GPU_UTIL=0.94 run real-dflash "${SPEC_ARGS[@]}" --speculative-config "{\"method\":\"dflash\",\"model\":\"$HOME/models/drafters/z-lab--Qwen3.8-27B-DFlash2\",\"num_speculative_tokens\":7}"
echo SWEEP-DONE
