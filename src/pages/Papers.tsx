import { useEffect, useState } from "react";
import { ArrowLeft, FolderOpen, FileText, Trash2 } from "lucide-react";
import { api, selectPDFPaths } from "../lib/api";
import { Button } from "../components/ui/button";
import {
  Confirm,
  ErrorBox,
  Field,
  Markdown,
  errorText,
} from "../components/common";
import type { Paper } from "../types";
import PDFReader from "../components/PDFReader";
import PaperMetadata from "../components/PaperMetadata";
export function PaperDetail({
  paper,
  onBack,
  onChange,
}: {
  paper: Paper;
  onBack: () => void;
  onChange: () => void;
}) {
  const [p, setP] = useState(paper),
    [text, setText] = useState(""),
    [source, setSource] = useState(""),
    [translation, setTranslation] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [remove, setRemove] = useState(false),
    [summaryNote, setSummaryNote] = useState(""),
    [record, setRecord] = useState(true);
  const query = "?id=" + encodeURIComponent(p.id);
  useEffect(() => {
    setP(paper);
  }, [paper]);
  async function act(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  const translate = (value: string) =>
    act("translate", async () => {
      const r = await api<{ translation: string }>("/paper/translate", "POST", {
        text: value,
      });
      setTranslation(r.translation);
    });
  return (
    <>
      <Button variant="ghost" disabled={!!busy} onClick={onBack}>
        <ArrowLeft size={16} />
        返回文献库
      </Button>
      <ErrorBox error={error} />
      <section className="panel paper-detail">
        <span className="eyebrow">
          {p.source || "arxiv"} · {p.category || "待分类"}
        </span>
        <h1>{p.title_zh || p.title}</h1>
        {p.title_zh && p.title_zh !== p.title && (
          <p className="original-title">{p.title}</p>
        )}
        <p>{p.authors}</p>
        <p className="hint">
          {p.published.slice(0, 10)} · {p.pdf_url}
        </p>
        <details>
          <summary>摘要与文件位置</summary>
          <h3>摘要</h3>
          <p>{p.abstract}</p>
          <div className="file-path">
            <FileText size={18} />
            <span>{p.local_path || "本地文件已移除"}</span>
          </div>
          <p className="hint">
            {p.storage_mode === "linked"
              ? "已关联你原来的 PDF：应用不复制、不另存，这份文件不计入应用占用空间，也不会在你没确认时被删除。"
              : "这份副本由旧版导入写在应用数据目录（默认在系统盘）。选中原来下载的同一份 PDF 即可关联并清理副本，释放空间。"}
          </p>
          <div className="actions wrap">
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                act("relink", async () => {
                  const paths = await selectPDFPaths();
                  if (!paths.length) return;
                  const next = await api<Paper>("/library/link", "POST", {
                    path: paths[0],
                    replace_id: p.id,
                    cleanup_copy: true,
                  });
                  setP(next);
                  onChange();
                })
              }
            >
              {p.storage_mode === "linked"
                ? "重新关联原文件"
                : "关联原文件并清理旧副本"}
            </Button>
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                act("refresh", async () => {
                  setP(await api<Paper>("/paper" + query));
                  onChange();
                })
              }
            >
              刷新文献
            </Button>
            {!!p.landing_url && (
              <Button
                variant="ghost"
                onClick={() =>
                  act("open", async () => {
                    await api("/library/open", "POST", { url: p.landing_url });
                  })
                }
              >
                出版来源网页
              </Button>
            )}
            <Button
              variant="outline"
              disabled={!!busy || !p.local_path}
              onClick={() =>
                act("folder", async () => {
                  await api("/paper/folder" + query, "POST");
                })
              }
            >
              <FolderOpen size={16} />
              打开文件夹
            </Button>
            <Button
              variant="ghost"
              disabled={!!busy}
              onClick={() => setRemove(true)}
            >
              <Trash2 size={16} />
              {p.storage_mode === "linked" ? "从文献库移除" : "删除文献"}
            </Button>
          </div>
        </details>
      </section>
      <PDFReader id={p.id} path={p.local_path} />
      <PaperMetadata
        paper={p}
        onSaved={(next) => {
          setP(next);
          onChange();
        }}
      />
      <section className="panel">
        <div className="section-title">
          <div>
            <h2>论文总结</h2>
            <p>
              按背景、方法、结论和创新点整理。「生成总结」读论文的开头与结尾（含摘要与结论，快、便宜）；「总结全文」分段精读整篇（慢一些、费用更高）。
            </p>
          </div>
          <div className="actions wrap">
            <Button
              disabled={!!busy || !p.local_path}
              onClick={() =>
                act("summary", async () => {
                  const result = await api<{ summary: string; note: string }>(
                    "/paper/summarize" + query + "&scope=excerpt",
                    "POST",
                  );
                  setP({ ...p, summary: result.summary, summary_scope: "excerpt" });
                  setSummaryNote(result.note);
                  onChange();
                })
              }
            >
              {busy === "summary"
                ? "总结中…"
                : p.summary && p.summary_scope !== "full"
                  ? "重新生成"
                  : "生成总结"}
            </Button>
            <Button
              variant="outline"
              disabled={!!busy || !p.local_path}
              onClick={() =>
                act("summary-full", async () => {
                  const result = await api<{ summary: string; note: string }>(
                    "/paper/summarize" + query + "&scope=full",
                    "POST",
                  );
                  setP({ ...p, summary: result.summary, summary_scope: "full" });
                  setSummaryNote(result.note);
                  onChange();
                })
              }
            >
              {busy === "summary-full" ? "分段精读中…" : "总结全文（分段精读）"}
            </Button>
          </div>
        </div>
        {p.summary ? (
          <>
            <p className="hint">
              本次总结依据：
              {summaryNote ||
                (p.summary_scope === "full"
                  ? "全文分段精读"
                  : "开头与结尾节选（含摘要与结论）")}
            </p>
            <Markdown>{p.summary}</Markdown>
          </>
        ) : (
          <p className="hint">
            生成一份结构化总结，快速理解论文的核心贡献。长篇论文建议用「总结全文」，会覆盖方法与结果正文。
          </p>
        )}
      </section>
      <section className="panel">
        <div className="section-title">
          <div>
            <h2>学术翻译</h2>
            <p>粘贴英文，或从提取的 PDF 文本中选取片段。</p>
          </div>
          <Button
            variant="outline"
            disabled={!!busy || !p.abstract}
            onClick={() => {
              setText(p.abstract.slice(0, 8000));
              translate(p.abstract.slice(0, 8000));
            }}
          >
            翻译摘要
          </Button>
        </div>
        <Button
          variant="ghost"
          disabled={!!busy || !p.local_path}
          onClick={() =>
            act("extract", async () => {
              setSource(
                (await api<{ text: string }>("/paper/text" + query)).text,
              );
            })
          }
        >
          {busy === "extract" ? "提取中…" : "提取 PDF 文本"}
        </Button>
        {source && (
          <Field label="PDF 原文（选中文字后自动填入翻译框，最多 8,000 字符）">
            <textarea
              className="source-text"
              readOnly
              value={source}
              onSelect={(e) => {
                const t = e.currentTarget;
                const selected = t.value.slice(
                  t.selectionStart,
                  t.selectionEnd,
                );
                if (selected) setText(selected.slice(0, 8000));
              }}
            />
          </Field>
        )}
        <Field label="待翻译英文">
          <textarea
            rows={7}
            maxLength={8000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="粘贴英文段落…"
          />
        </Field>
        <div className="actions">
          <Button
            disabled={!!busy || !text.trim()}
            onClick={() => translate(text)}
          >
            {busy === "translate" ? "翻译中…" : "翻译为中文"}
          </Button>
          <span className="hint">{text.length} / 8,000</span>
        </div>
        {translation && (
          <div className="translation">
            <Markdown>{translation}</Markdown>
          </div>
        )}
      </section>
      {remove && (
        <Confirm
          title="删除本地文献？"
          onCancel={() => setRemove(false)}
          onConfirm={() => {
            setRemove(false);
            act("delete", async () => {
              await api(
                "/paper" +
                  query +
                  "&remove_record=" +
                  (p.storage_mode === "linked" || record),
                "DELETE",
              );
              onChange();
              onBack();
            });
          }}
        >
          <span>
            {p.storage_mode === "linked"
              ? "仅移除文献记录，原 PDF 文件会保留。"
              : "应用管理的 PDF 文件会被删除。"}
          </span>
          {p.storage_mode !== "linked" && (
            <label className="check">
              <input
                type="checkbox"
                checked={record}
                onChange={(e) => setRecord(e.target.checked)}
              />
              同时删除元数据和总结记录
            </label>
          )}
        </Confirm>
      )}
    </>
  );
}

