#!/usr/bin/env bash
# vLLM on 10.10.113.14 (2x RTX 5060 Ti 16GB) from ~/vllm-env (snap docker can't reach the GPUs).
#   ./serve.sh <model-dir under ~/models> <tp|pp> [extra vllm args...]
# Production runs it via the user unit vllm.service (FOREGROUND=1); for an ad-hoc
# run stop that first: systemctl --user stop vllm
set -eu
MODEL=$1; MODE=$2; shift 2
case $MODE in
  tp) PAR="--tensor-parallel-size 2" ;;
  pp) PAR="--pipeline-parallel-size 2" ;;
  *) echo "mode tp|pp"; exit 1 ;;
esac
# NVCC=1 puts the venv nvcc on PATH so FlashInfer can JIT its kernels (needed for NVFP4).
# nvcc must match the CUDA runtime headers in the venv (pinned to 13.2).
# Without nvcc vLLM treats FlashInfer as absent and uses its own kernels.
if [ "${NVCC:-0}" = 1 ]; then
  CUDA_BIN="$HOME/vllm-env/lib/python3.12/site-packages/nvidia/cu13/bin"
  export PATH="$CUDA_BIN:$PATH" CUDA_HOME="${CUDA_BIN%/bin}"
  # each cicc on the CUTLASS FP4 GEMMs takes ~5 GB; unbounded ninja OOMs the 59 GB host
  export MAX_JOBS="${MAX_JOBS:-6}"
fi
echo "$MODEL" > "$HOME/vllm.model"
CMD=("$HOME/vllm-env/bin/vllm" serve "$HOME/models/$MODEL" --served-model-name "${NAME:-qwen38}"
  --host 0.0.0.0 --port 8000
  $PAR --gpu-memory-utilization "${GPU_UTIL:-0.92}" --kv-cache-dtype "${KV:-auto}"
  --max-model-len "${MAX_LEN:-65536}" --max-num-seqs 32 --enable-prefix-caching --reasoning-parser qwen3
  # tool calls for the web agent (tool_choice=auto); Qwen3.5/3.6 emit the XML
  # <tool_call><function=…><parameter=…> format that qwen3_coder parses
  --enable-auto-tool-choice --tool-call-parser "${TOOL_PARSER:-qwen3_coder}"
  --language-model-only "$@")
if [ "${FOREGROUND:-0}" = 1 ]; then
  exec "${CMD[@]}"
fi
if systemctl --user is-active -q vllm 2>/dev/null; then
  echo "vllm.service is running; systemctl --user stop vllm first"; exit 1
fi
pkill -f "[v]llm serve" || true; sleep 3
setsid nohup "${CMD[@]}" > "$HOME/vllm-serve.log" 2>&1 < /dev/null &
