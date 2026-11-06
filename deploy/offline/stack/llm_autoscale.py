"""Adaptive cap on our parallel requests to a shared vLLM (AIMD).

The GPU server is shared with other users, so we size our share by its queue:
vLLM requests waiting (or KV cache nearly full) -> cut our LiteLLM
``max_parallel_requests``; queue empty for a while -> raise it by one.

The knob is a LiteLLM deployment stored in the LiteLLM DB (STORE_MODEL_IN_DB),
changed live with PATCH /model/{id}/update — no proxy restart. Requests above
the cap can receive HTTP 429 and should retry or use a fallback.

Stdlib only: runs on the LiteLLM image (`python /app/llm_autoscale.py`).
Env: see the constants below.
"""

import json
import os
import time
import urllib.request

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000").rstrip("/")
LITELLM_KEY = os.environ["LITELLM_MASTER_KEY"]
VLLM_METRICS = os.environ.get("VLLM_METRICS", "http://10.10.151.15:8000/metrics")
MODEL_ID = os.environ.get("AUTOSCALE_MODEL_ID", "ds15-small")
MIN_CAP = int(os.environ.get("AUTOSCALE_MIN", "2"))
MAX_CAP = int(os.environ.get("AUTOSCALE_MAX", "12"))
INTERVAL_S = float(os.environ.get("AUTOSCALE_INTERVAL_S", "15"))
# waiting >= HIGH_WAITING (or kv >= HIGH_KV) for DOWN_AFTER samples -> cut
HIGH_WAITING = float(os.environ.get("AUTOSCALE_HIGH_WAITING", "1"))
HIGH_KV = float(os.environ.get("AUTOSCALE_HIGH_KV", "0.85"))
DOWN_AFTER = int(os.environ.get("AUTOSCALE_DOWN_AFTER", "2"))
DOWN_FACTOR = float(os.environ.get("AUTOSCALE_DOWN_FACTOR", "0.75"))
# waiting == 0 and kv below LOW_KV for UP_AFTER samples -> +1
LOW_KV = float(os.environ.get("AUTOSCALE_LOW_KV", "0.6"))
UP_AFTER = int(os.environ.get("AUTOSCALE_UP_AFTER", "4"))


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if url.startswith(LITELLM_URL):
        req.add_header("Authorization", f"Bearer {LITELLM_KEY}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def read_vllm() -> tuple[float, float, float]:
    """(running, waiting, kv_usage) summed over engines."""
    running = waiting = kv = 0.0
    for line in _http("GET", VLLM_METRICS).decode().splitlines():
        if line.startswith("vllm:num_requests_running{"):
            running += float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:num_requests_waiting{"):
            waiting += float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:kv_cache_usage_perc{"):
            kv = max(kv, float(line.rsplit(" ", 1)[1]))
    return running, waiting, kv


def read_cap() -> int | None:
    info = json.loads(_http("GET", f"{LITELLM_URL}/model/info?litellm_model_id={MODEL_ID}"))
    for d in info.get("data", []):
        if d.get("model_info", {}).get("id") == MODEL_ID:
            return d["litellm_params"].get("max_parallel_requests")
    return None


def set_cap(cap: int) -> None:
    _http(
        "PATCH",
        f"{LITELLM_URL}/model/{MODEL_ID}/update",
        {"litellm_params": {"max_parallel_requests": cap}},
    )


def main() -> None:
    cap = None
    while cap is None:
        try:
            cap = read_cap()
        except Exception as e:  # LiteLLM still booting
            log(f"waiting for LiteLLM model {MODEL_ID}: {e}")
        if cap is None:
            time.sleep(INTERVAL_S)
    cap = max(MIN_CAP, min(MAX_CAP, int(cap)))
    log(f"start cap={cap} range=[{MIN_CAP},{MAX_CAP}] metrics={VLLM_METRICS}")
    hot = calm = 0
    while True:
        time.sleep(INTERVAL_S)
        try:
            running, waiting, kv = read_vllm()
        except Exception as e:  # server unreachable: hold the cap
            log(f"metrics unavailable, hold cap={cap}: {e}")
            hot = calm = 0
            continue
        if waiting >= HIGH_WAITING or kv >= HIGH_KV:
            hot, calm = hot + 1, 0
        elif waiting == 0 and kv < LOW_KV:
            hot, calm = 0, calm + 1
        else:
            hot = calm = 0
        new = cap
        if hot >= DOWN_AFTER and cap > MIN_CAP:
            new = max(MIN_CAP, min(cap - 1, int(cap * DOWN_FACTOR)))
        elif calm >= UP_AFTER and cap < MAX_CAP:
            new = cap + 1
        if new != cap:
            try:
                set_cap(new)
            except Exception as e:
                log(f"update failed, keep cap={cap}: {e}")
                continue
            log(f"cap {cap} -> {new} (running={running:.0f} waiting={waiting:.0f} kv={kv:.3f})")
            cap, hot, calm = new, 0, 0


if __name__ == "__main__":
    main()
