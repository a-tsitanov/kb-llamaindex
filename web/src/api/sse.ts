// Shared SSE client over fetch (not EventSource): every (re)connect asks for a fresh URL
// (stream tokens live 5 min) and sends Last-Event-ID itself.

export interface SSEMessage {
  id?: string;
  event: string;
  data: string;
}

/** Incremental text/event-stream parser: feed chunks, get complete messages. */
export class SSEParser {
  private buf = "";

  feed(chunk: string): SSEMessage[] {
    this.buf += chunk.replace(/\r\n?/g, "\n");
    const out: SSEMessage[] = [];
    let cut: number;
    while ((cut = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, cut);
      this.buf = this.buf.slice(cut + 2);
      const msg: SSEMessage = { event: "message", data: "" };
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const i = line.indexOf(":");
        const field = i < 0 ? line : line.slice(0, i);
        const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
        if (field === "data") data.push(value);
        else if (field === "event") msg.event = value;
        else if (field === "id") msg.id = value;
      }
      if (!data.length) continue; // comment-only block (ping)
      msg.data = data.join("\n");
      out.push(msg);
    }
    return out;
  }
}

export interface StreamOptions {
  /** Builds the URL for each (re)connect — fetch a fresh token here. */
  url: () => Promise<string>;
  onMessage: (msg: SSEMessage) => void;
  /** Return true when the stream is complete (e.g. after `done`): no reconnect. */
  finished?: () => boolean;
  onError?: (err: unknown) => void;
  lastEventId?: string;
  retryMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });

/** Reads until `finished()` or abort; reconnects with Last-Event-ID after drops. */
export async function openStream(opts: StreamOptions): Promise<void> {
  const doFetch = opts.fetchImpl ?? fetch;
  let lastId = opts.lastEventId;
  while (!opts.signal?.aborted) {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (lastId) headers["Last-Event-ID"] = lastId;
      const res = await doFetch(await opts.url(), { headers, signal: opts.signal });
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      const parser = new SSEParser();
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const msg of parser.feed(value)) {
          if (msg.id) lastId = msg.id;
          opts.onMessage(msg);
        }
      }
    } catch (err) {
      if (opts.signal?.aborted) return;
      opts.onError?.(err);
    }
    if (opts.finished?.()) return;
    await sleep(opts.retryMs ?? 1000, opts.signal);
  }
}
