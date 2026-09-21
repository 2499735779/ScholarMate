import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useSearchParams } from "react-router-dom";
import {
  getDraft,
  subscribeDraft,
  setDraft,
  beginSend,
  finishSend,
  recoverSend,
} from "../lib/chatDraft";
import PlanProposal from "../components/PlanProposal";
import {
  ArrowUp,
  Download,
  Trash2,
  Sparkles,
  Square,
  Paperclip,
  FileText,
  X,
  AlertTriangle,
  Plus,
  PencilLine,
  Check,
} from "lucide-react";
import { api, stream, download, blobUrl, readBase64 } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Confirm, ErrorBox, Markdown, errorText } from "../components/common";
import { formatBytes } from "../lib/utils";
import type {
  Attachment,
  ChatThread,
  Message,
  Profile,
  ProfileList,
  Status,
} from "../types";

const ACCEPT =
  ".docx,.xlsx,.pptx,.pdf,.txt,.md,.markdown,.csv,.tsv,.json,.xml,.yaml,.yml,.html,.htm,.tex,.bib,.py,.js,.ts,.r,.m,.sql,.log,.srt,.png,.jpg,.jpeg,.gif,.bmp";
const MAX_FILES = 8;

function Thumbnail({ id, preview, name }: { id: string; preview?: string; name: string }) {
  const [url, setUrl] = useState(preview || "");
  useEffect(() => {
    if (preview) {
      setUrl(preview);
      return;
    }
    let active = true,
      object = "";
    blobUrl("/chat/attachment?id=" + encodeURIComponent(id))
      .then((value) => {
        object = value;
        if (active) setUrl(value);
        else URL.revokeObjectURL(value);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      if (object) URL.revokeObjectURL(object);
    };
  }, [id, preview]);
  return url ? (
    <img className="attachment-thumb" src={url} alt={name} />
  ) : (
    <span className="attachment-thumb placeholder" aria-hidden="true">
      <FileText size={18} />
    </span>
  );
}

function AttachmentChips({
  items,
  previews,
  onRemove,
}: {
  items: Attachment[];
  previews?: Record<string, string>;
  onRemove?: (id: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="attachment-row">
      {items.map((a) => (
        <div className="attachment-chip" key={a.id}>
          {a.kind === "image" ? (
            <Thumbnail id={a.id} preview={previews?.[a.id]} name={a.name} />
          ) : (
            <span className="attachment-icon" aria-hidden="true">
              <FileText size={16} />
            </span>
          )}
          <span className="attachment-meta">
            <b>{a.name}</b>
            <small>
              {a.type_label} · {formatBytes(a.bytes)}
              {a.characters ? ` · ${a.characters} 字可读` : ""}
            </small>
          </span>
          {onRemove && (
            <button
              type="button"
              className="attachment-remove"
              aria-label={"移除 " + a.name}
              onClick={() => onRemove(a.id)}
            >
              <X size={14} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Chat({
  status,
  refresh,
}: {
  status: Status;
  refresh: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<Message[]>([]),
    [threads, setThreads] = useState<ChatThread[]>([]),
    [threadId, setThreadId] = useState(""),
    [thread, setThread] = useState<ChatThread | null>(null),
    [profiles, setProfiles] = useState<Profile[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [renaming, setRenaming] = useState(""),
    [title, setTitle] = useState(""),
    [confirm, setConfirm] = useState(false);
  const [files, setFiles] = useState<Attachment[]>([]),
    [previews, setPreviews] = useState<Record<string, string>>({}),
    [uploading, setUploading] = useState(0),
    [dragging, setDragging] = useState(false);
  const input = useSyncExternalStore(subscribeDraft, getDraft);
  const [searchParams] = useSearchParams();
  const sourceMessage = searchParams.get("message");
  const end = useRef<HTMLDivElement>(null),
    picker = useRef<HTMLInputElement>(null),
    abort = useRef<AbortController | null>(null);

  async function loadThreads(prefer?: string) {
    const list = await api<ChatThread[]>("/threads");
    setThreads(list);
    const wanted = prefer || threadId || list[0]?.id || "";
    if (wanted && list.some((t) => t.id === wanted)) return openThread(wanted);
    if (list.length) return openThread(list[0].id);
    // A first visit (or a reset) starts a conversation instead of an empty page.
    const created = await api<ChatThread>("/threads", "POST", {});
    setThreads([created]);
    return openThread(created.id);
  }
  async function openThread(id: string) {
    const data = await api<{ thread: ChatThread; messages: Message[] }>(
      "/threads/" + encodeURIComponent(id),
    );
    setThreadId(id);
    setThread(data.thread);
    setMessages(data.messages);
  }
  useEffect(() => {
    Promise.all([loadThreads(), api<ProfileList>("/profiles").then((r) => setProfiles(r.items))])
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
    return () => abort.current?.abort();
    // Loading the first conversation once per visit is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (sourceMessage)
      document
        .getElementById("message-" + sourceMessage)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    else if (messages.length)
      end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sourceMessage]);

  async function act(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    }
  }
  const newThread = () =>
    act(async () => {
      const created = await api<ChatThread>("/threads", "POST", {});
      setThreads((list) => [created, ...list]);
      await openThread(created.id);
    });
  const renameThread = () =>
    act(async () => {
      const updated = await api<ChatThread>(
        "/threads/" + threadId,
        "PUT",
        { title },
      );
      setThread(updated);
      setThreads((list) => list.map((t) => (t.id === updated.id ? updated : t)));
      setRenaming("");
    });
  const switchProfile = (profileId: string) =>
    act(async () => {
      const updated = await api<ChatThread>("/threads/" + threadId, "PUT", {
        profile_id: profileId,
      });
      setThread(updated);
      setThreads((list) => list.map((t) => (t.id === updated.id ? updated : t)));
    });
  const removeThread = () =>
    act(async () => {
      await api("/threads/" + threadId, "DELETE");
      const rest = threads.filter((t) => t.id !== threadId);
      setThreads(rest);
      if (rest.length) await openThread(rest[0].id);
      else await loadThreads();
    });
  async function upload(list: File[]) {
    const room = MAX_FILES - files.length;
    if (room <= 0) {
      setError(`一条消息最多上传 ${MAX_FILES} 个文件。`);
      return;
    }
    const chosen = list.slice(0, room);
    if (list.length > room) setError(`一条消息最多上传 ${MAX_FILES} 个文件，多余文件未添加。`);
    setError("");
    setUploading(chosen.length);
    try {
      const added: Attachment[] = [];
      const local: Record<string, string> = {};
      for (const file of chosen) {
        const meta = await api<Attachment>("/chat/upload", "POST", {
          filename: file.name,
          data: await readBase64(file),
        });
        added.push(meta);
        if (meta.kind === "image") local[meta.id] = URL.createObjectURL(file);
        setUploading((v) => Math.max(0, v - 1));
      }
      setPreviews((v) => ({ ...v, ...local }));
      setFiles((v) => [...v, ...added]);
    } catch (e) {
      setError(errorText(e));
      setUploading(0);
    }
  }
  function drop(id: string) {
    setFiles((v) => v.filter((f) => f.id !== id));
    setPreviews((v) => {
      if (v[id]) URL.revokeObjectURL(v[id]);
      const { [id]: _removed, ...rest } = v;
      return rest;
    });
  }
  async function send(text = input) {
    if ((!text.trim() && !files.length) || busy || loading || !threadId) return;
    const previous = messages;
    const attachments = files;
    const sendVersion = beginSend(text);
    setError("");
    setBusy(true);
    setMessages([
      ...previous,
      { role: "user", content: text, attachments },
      { role: "assistant", content: "" },
    ]);
    setFiles([]);
    Object.values(previews).forEach((url) => URL.revokeObjectURL(url));
    setPreviews({});
    abort.current = new AbortController();
    let content = "";
    try {
      await stream(
        "/chat",
        {
          message: text,
          attachments: attachments.map((a) => a.id),
          thread_id: threadId,
        },
        (data) => {
          if (data.delta) {
            content += String(data.delta);
            setMessages([
              ...previous,
              { role: "user", content: text, attachments },
              { role: "assistant", content },
            ]);
          }
          if (data.done && data.messages) {
            setMessages([...previous, ...(data.messages as Message[])]);
            finishSend(sendVersion);
            const saved = data.thread as ChatThread | undefined;
            if (saved) {
              setThread(saved);
              setThreads((list) => [
                saved,
                ...list.filter((t) => t.id !== saved.id),
              ]);
            }
          }
        },
        AbortSignal.any([abort.current.signal, AbortSignal.timeout(300000)]),
      );
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "AbortError"
          ? "已停止生成，本轮未保存。"
          : errorText(e),
      );
      recoverSend(text, sendVersion);
      setFiles(attachments);
      setMessages(previous);
      try {
        await openThread(threadId);
      } catch {
        /* Preserve already loaded history. */
      }
    } finally {
      setBusy(false);
    }
  }
  const images = files.filter((f) => f.kind === "image");
  return (
    <div className="chat-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">THINK TOGETHER</span>
          <h1>学术对话</h1>
          <p>
            <span className="status-dot" />
            {status.model}{" "}
            <span className="muted">
              · {thread?.profile_name || status.profile_name || "未选择画像"}
              {status.vision ? " · 支持图片输入" : ""}
            </span>
          </p>
        </div>
        <div className="actions">
          <Button
            variant="ghost"
            disabled={busy || !messages.length || !threadId}
            onClick={() =>
              download(
                `/threads/${encodeURIComponent(threadId)}/export`,
                `ScholarMate-${thread?.title || "对话"}.md`,
              ).catch((e) => setError(errorText(e)))
            }
          >
            <Download size={16} />
            导出
          </Button>
          <Button
            variant="ghost"
            disabled={busy || !threadId}
            onClick={() => setConfirm(true)}
          >
            <Trash2 size={16} />
            删除对话
          </Button>
        </div>
      </header>
      <div className="thread-bar">
        <div className="thread-pick">
          {renaming !== "" ? (
            <>
              <Input
                aria-label="对话名称"
                autoFocus
                maxLength={60}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") renameThread();
                  if (e.key === "Escape") setRenaming("");
                }}
              />
              <Button type="button" disabled={busy} onClick={renameThread}>
                <Check size={15} />
                保存
              </Button>
              <Button type="button" variant="ghost" onClick={() => setRenaming("")}>
                取消
              </Button>
            </>
          ) : (
            <>
              <select
                aria-label="切换对话"
                value={threadId}
                disabled={busy || !threads.length}
                onChange={(e) => act(() => openThread(e.target.value))}
              >
                {threads.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}（{t.message_count}）
                  </option>
                ))}
              </select>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={newThread}
              >
                <Plus size={15} />
                新建对话
              </Button>
              <Button
                type="button"
                variant="ghost"
                aria-label="重命名对话"
                title="重命名对话"
                disabled={busy || !thread}
                onClick={() => {
                  setTitle(thread?.title || "");
                  setRenaming(thread?.title || " ");
                }}
              >
                <PencilLine size={15} />
              </Button>
            </>
          )}
        </div>
        <label className="thread-profile">
          <span>这条对话使用的画像</span>
          <select
            value={thread?.profile_id || status.profile_id || ""}
            disabled={busy || !profiles.length || !threadId}
            onChange={(e) => switchProfile(e.target.value)}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.id === status.profile_id ? "（当前）" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="message-list">
        {sourceMessage &&
          !loading &&
          !messages.some((m) => m.id === sourceMessage) && (
            <p className="hint">
              来源对话不在当前这条对话里；可在上方切换到包含该消息的对话。
            </p>
          )}
        {!messages.length && !loading && (
          <div className="chat-welcome">
            <div className="hero-icon">
              <Sparkles size={32} />
            </div>
            <span className="eyebrow">YOUR RESEARCH COMPANION</span>
            <h2>好问题，是探索的开始。</h2>
            <p>
              每条对话彼此独立、各自记住使用的画像；聊乱了就新建一条，不用清空历史。也可以上传
              Word、Excel、PPT、PDF 和图片一起读。
            </p>
            <div className="suggestions">
              {[
                "请自我介绍，并说明你了解到的我的研究背景。",
                "如何系统阅读一篇学术论文？",
                "帮我拆解当前的短期学习目标。",
              ].map((t) => (
                <button key={t} disabled={loading} onClick={() => send(t)}>
                  {t}
                  <ArrowUp size={16} />
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <article
            id={"message-" + m.id}
            className={
              "message " +
              m.role +
              (sourceMessage === m.id ? " source-highlight" : "")
            }
            key={m.id || i}
          >
            <div className="avatar">{m.role === "user" ? "你" : "S"}</div>
            <div className="message-content">
              <b>{m.role === "user" ? "你" : "ScholarMate"}</b>
              {m.role === "user" && !!m.attachments?.length && (
                <AttachmentChips items={m.attachments} />
              )}
              <Markdown>
                {m.display_content ??
                  (m.content.includes("```scholarmate-plan")
                    ? m.content.split("```scholarmate-plan")[0] +
                      "\n\n正在整理学习计划…"
                    : m.content || (busy ? "正在思考…" : ""))}
              </Markdown>
              <PlanProposal message={m} />
            </div>
          </article>
        ))}
        <div ref={end} />
      </div>
      <ErrorBox error={error} />
      {!!images.length && !status.vision && (
        <p className="hint warn">
          <AlertTriangle size={14} /> 当前模型（{status.model}
          ）不支持图片输入：图片会作为附件保存并显示，但 AI
          看不到图中内容。可在「设置 → AI 连接」勾选多模态模型，或改用支持图片的模型名称。
        </p>
      )}
      <form
        className={"composer" + (dragging ? " dropping" : "")}
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (busy || loading) return;
          upload(Array.from(e.dataTransfer.files || []));
        }}
      >
        <AttachmentChips items={files} previews={previews} onRemove={drop} />
        <textarea
          aria-label="对话消息"
          value={input}
          maxLength={16000}
          onChange={(e) => setDraft(e.target.value)}
          onPaste={(e) => {
            const pasted = Array.from(e.clipboardData?.files || []);
            if (pasted.length && !busy && !loading) {
              e.preventDefault();
              upload(pasted);
            }
          }}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="与 ScholarMate 一起探索…（可拖入或粘贴 Word/Excel/PPT/PDF/图片）"
        />
        <div className="composer-bottom">
          <input
            ref={picker}
            className="visually-hidden"
            type="file"
            multiple
            accept={ACCEPT}
            onChange={(e) => {
              upload(Array.from(e.target.files || []));
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="ghost"
            aria-label="上传文档或图片"
            title="上传 Word / Excel / PPT / PDF / 图片 / 文本"
            disabled={busy || loading || uploading > 0}
            onClick={() => picker.current?.click()}
          >
            <Paperclip size={16} />
            {uploading > 0 ? `上传中…（剩 ${uploading}）` : "上传文件"}
          </Button>
          <span>草稿已保存在本机 · Enter 发送</span>
          {busy ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => abort.current?.abort()}
            >
              <Square size={15} />
              停止
            </Button>
          ) : (
            <Button
              disabled={(!input.trim() && !files.length) || loading || uploading > 0}
              aria-label="发送消息"
            >
              <ArrowUp size={18} />
            </Button>
          )}
        </div>
      </form>
      <p className="footnote">
        上传的文件保存在本机数据目录；AI 可能产生错误，请核对重要结论与引用。
      </p>
      {confirm && (
        <Confirm
          title="删除这条对话？"
          onCancel={() => setConfirm(false)}
          onConfirm={async () => {
            setConfirm(false);
            await removeThread();
            await refresh();
          }}
        >
          只会删除「{thread?.title}」这条对话的消息，其他对话和已上传的附件都保留。
        </Confirm>
      )}
    </div>
  );
}

