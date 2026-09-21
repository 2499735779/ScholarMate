import { beforeEach, describe, it, expect, vi } from "vitest";
const stored = new Map<string, string>();
beforeEach(() => {
  vi.resetModules();
  stored.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => stored.get(k) || null,
    setItem: (k: string, v: string) => stored.set(k, v),
    removeItem: (k: string) => stored.delete(k),
  });
});
describe("persistent chat draft", () => {
  it("ignores late completion from an older send", async () => {
    const d = await import("./chatDraft");
    const oldSend = d.beginSend("旧消息");
    const newSend = d.beginSend("新消息");
    d.recoverSend("旧消息", oldSend);
    d.finishSend(oldSend);
    expect(d.getDraft()).toBe("");
    expect(stored.get("scholarmate-chat-pending")).toBe("新消息");
    d.recoverSend("新消息", newSend);
    expect(d.getDraft()).toBe("新消息");
  });
  it("retains draft after unsubscribe (page change) and reload", async () => {
    const draft = await import("./chatDraft");
    const listener = vi.fn();
    const unsubscribe = draft.subscribeDraft(listener);
    draft.setDraft("未发送的研究问题");
    unsubscribe();
    expect(draft.getDraft()).toBe("未发送的研究问题");
    vi.resetModules();
    expect((await import("./chatDraft")).getDraft()).toBe("未发送的研究问题");
  });
  it("restores failed outgoing text but preserves a new draft typed during streaming", async () => {
    const d = await import("./chatDraft");
    d.beginSend("原消息");
    d.recoverSend("原消息");
    expect(d.getDraft()).toBe("原消息");
    d.beginSend("原消息");
    d.setDraft("新的草稿");
    d.recoverSend("原消息");
    expect(d.getDraft()).toBe("新的草稿");
  });
  it("recovers pending send after restart and clears it on success", async () => {
    let d = await import("./chatDraft");
    d.beginSend("断开前的问题");
    vi.resetModules();
    d = await import("./chatDraft");
    expect(d.getDraft()).toBe("断开前的问题");
    d.beginSend("断开前的问题");
    d.finishSend();
    vi.resetModules();
    expect((await import("./chatDraft")).getDraft()).toBe("");
  });
});

