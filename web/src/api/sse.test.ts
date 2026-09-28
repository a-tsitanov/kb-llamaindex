import { describe, expect, it } from "vitest";
import { openStream, SSEParser, type SSEMessage } from "./sse";

describe("SSEParser", () => {
  it("parses id/event/multi-line data across chunk borders and skips pings", () => {
    const p = new SSEParser();
    expect(p.feed(": ping\n\nid: 3\nevent: text\ndata: {\"a\":")).toEqual([]);
    expect(p.feed("1}\ndata: x\r\n\r\nevent: ready\ndata: {}\n\n")).toEqual([
      { id: "3", event: "text", data: "{\"a\":1}\nx" },
      { event: "ready", data: "{}" },
    ]);
  });
});

function body(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe("openStream", () => {
  it("reconnects with Last-Event-ID and a fresh URL until finished", async () => {
    const calls: { url: string; lastId?: string }[] = [];
    const replies = [
      ["id: 1\nevent: run_started\ndata: {}\n\n", "id: 2\nevent: text\ndata: {}\n\n"],
      ["id: 3\nevent: done\ndata: {}\n\n"],
    ];
    const fetchImpl = (async (url: string, init: RequestInit) => {
      calls.push({ url, lastId: (init.headers as Record<string, string>)["Last-Event-ID"] });
      return new Response(body(replies[calls.length - 1]), { status: 200 });
    }) as unknown as typeof fetch;
    let n = 0;
    const got: SSEMessage[] = [];
    await openStream({
      url: async () => `/events?token=t${++n}`,
      onMessage: (m) => got.push(m),
      finished: () => got.some((m) => m.event === "done"),
      retryMs: 1,
      fetchImpl,
    });
    expect(got.map((m) => m.id)).toEqual(["1", "2", "3"]);
    expect(calls).toEqual([
      { url: "/events?token=t1", lastId: undefined },
      { url: "/events?token=t2", lastId: "2" },
    ]);
  });

  it("reports errors, retries, and stops on abort", async () => {
    const ctl = new AbortController();
    const errors: unknown[] = [];
    let tries = 0;
    const fetchImpl = (async () => {
      if (++tries === 2) ctl.abort();
      return new Response("nope", { status: 403 });
    }) as unknown as typeof fetch;
    await openStream({
      url: async () => "/x",
      onMessage: () => {},
      onError: (e) => errors.push(e),
      retryMs: 1,
      signal: ctl.signal,
      fetchImpl,
    });
    expect(tries).toBe(2);
    expect(String(errors[0])).toContain("403");
  });
});
