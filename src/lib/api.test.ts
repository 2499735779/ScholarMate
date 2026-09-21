import { describe, it, expect, vi, beforeEach } from "vitest";
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke: async () => ({ port: 1234, token: "fixture" }),
}));
import { initialize, stream } from "./api";
describe("SSE transport", () => {
  beforeEach(async () => {
    await initialize();
  });
  it("decodes split UTF-8 and SSE boundaries", async () => {
    const encoded = new TextEncoder().encode(
      'data: {"delta":"你好"}\n\ndata: {"done":true}\n\n',
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            new ReadableStream({
              start(c) {
                for (let i = 0; i < encoded.length; i += 2)
                  c.enqueue(encoded.slice(i, i + 2));
                c.close();
              },
            }),
          ),
      ),
    );
    const events: Record<string, unknown>[] = [];
    await stream("/chat", { message: "hello" }, (e) => events.push(e));
    expect(events).toEqual([{ delta: "你好" }, { done: true }]);
  });
  it("rejects an interrupted reply", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response('data: {"delta":"partial"}\n\n')),
    );
    await expect(stream("/chat", {}, () => {})).rejects.toThrow("中断");
  });
  it("handles CRLF delimiters split across chunks", async () => {
    const chunks = [
      'data: {"delta":"ok"}\r',
      "\n\r",
      '\ndata: {"done":true}\r',
      "\n\r",
      "\n",
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            new ReadableStream({
              start(c) {
                for (const chunk of chunks)
                  c.enqueue(new TextEncoder().encode(chunk));
                c.close();
              },
            }),
          ),
      ),
    );
    const events: Record<string, unknown>[] = [];
    await stream("/chat", {}, (e) => events.push(e));
    expect(events).toEqual([{ delta: "ok" }, { done: true }]);
  });
  it("surfaces server errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response('data: {"error":"Key 无效"}\n\n')),
    );
    await expect(stream("/chat", {}, () => {})).rejects.toThrow("Key 无效");
  });
});

