import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ErrorBox, Field, errorText } from "./common";
import type { Citation, Paper } from "../types";
export default function PaperMetadata({
  paper,
  onSaved,
}: {
  paper: Paper;
  onSaved: (p: Paper) => void;
}) {
  const [form, setForm] = useState<Paper>(paper),
    [editing, setEditing] = useState(false),
    [citation, setCitation] = useState<Citation | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [copied, setCopied] = useState(false);
  const query = "?id=" + encodeURIComponent(paper.id),
    started = useRef("");
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
  const identify = async () => {
    const result = await api<Citation>("/paper/citation/resolve" + query, "POST");
    setCitation(result);
    if (result.paper) onSaved(result.paper);
    setCopied(false);
  };
  // Opening 阅读 / 引用 shows a reference without any extra click: the stored
  // entry renders immediately, and an unchecked paper is identified once.
  useEffect(() => {
    if (started.current === paper.id) return;
    started.current = paper.id;
    act("cite", async () => {
      setCitation(await api<Citation>("/paper/citation" + query));
      if (!paper.citation_checked) await identify();
    });
  }, [paper.id, paper.citation_checked, query, onSaved]);
  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <h2>引用与文献索引</h2>
          <p>
            {citation?.style || "GB/T 7714-2015 顺序编码制"} · 打开即自动识别，无需手改
          </p>
        </div>
        <Button
          variant="outline"
          disabled={!!busy}
          onClick={() => {
            setForm(paper);
            setEditing(!editing);
          }}
        >
          补全 / 修改资料
        </Button>
      </div>
      <ErrorBox error={error} />
      {editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act("save", async () => {
              const p = await api<Paper>("/paper/metadata" + query, "PUT", form);
              onSaved(p);
              setEditing(false);
              setCitation(null);
              started.current = "";
            });
          }}
        >
          <div className="form-grid">
            {(
              [
                ["title", "原文标题"],
                ["title_zh", "中文译名"],
                ["authors", "作者（逗号分隔）"],
                ["category", "分类"],
                ["tags", "检索标签（逗号分隔）"],
                ["language", "语言"],
                ["published", "出版日期 / 年份"],
                ["doi", "DOI"],
                ["venue", "期刊 / 会议论文集名"],
                ["volume", "卷"],
                ["issue", "期"],
                ["pages", "页码 / 文章号"],
                ["publisher", "出版社 / 学位授予单位"],
                ["place", "出版地"],
                ["landing_url", "来源网址"],
              ] as [keyof Paper, string][]
            ).map(([key, label]) => (
              <Field key={key} label={label}>
                <Input
                  required={key === "title"}
                  value={String(form[key] || "")}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                />
              </Field>
            ))}
            <Field label="文献类型">
              <select
                value={form.publication_type || "online"}
                onChange={(e) =>
                  setForm({ ...form, publication_type: e.target.value })
                }
              >
                {[
                  ["journal", "期刊 [J]"],
                  ["thesis", "学位论文 [D]"],
                  ["conference", "会议论文 [C]"],
                  ["book", "图书 [M]"],
                  ["preprint", "预印本 [PP/OL]"],
                  ["online", "网络文献 [EB/OL]"],
                ].map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Button disabled={!!busy}>保存文献资料</Button>
        </form>
      )}
      {citation ? (
        <div className="citation-box">
          <textarea
            aria-label="参考文献引用"
            readOnly
            rows={4}
            value={citation.text}
          />
          <p className="hint">
            依据：{citation.evidence} · {citation.style}
          </p>
          {!!citation.omitted.length && (
            <p className="hint">
              PDF 与开放来源都未提供：{citation.omitted.join("、")}
              。引用已按国标省略这些要素，可以直接使用；也可以用「补全 /
              修改资料」手动补充。
            </p>
          )}
          {!!citation.review.length && (
            <p className="hint">
              需要留意：{citation.review.join("、")}。点击「重新识别引用」可从 PDF
              正文再次识别。
            </p>
          )}
          <div className="actions wrap">
            <Button
              variant="outline"
              disabled={!citation.text}
              onClick={() =>
                act("copy", async () => {
                  await navigator.clipboard.writeText(citation.text);
                  setCopied(true);
                })
              }
            >
              {copied ? "已复制" : "复制引用"}
            </Button>
            <Button variant="ghost" disabled={!!busy} onClick={() => act("cite", identify)}>
              {busy === "cite" ? "识别中…" : "重新识别引用"}
            </Button>
            <Button
              variant="ghost"
              disabled={!!busy || editing}
              onClick={() =>
                act("enrich", async () => {
                  const r = await api<{ errors?: string[] }>(
                    "/library/enrich" + query,
                    "POST",
                  );
                  if (r.errors?.length) throw new Error(r.errors.join("；"));
                  onSaved(await api<Paper>("/paper" + query));
                  await identify();
                })
              }
            >
              {busy === "enrich" ? "整理中…" : "按 PDF 正文重新整理资料"}
            </Button>
          </div>
        </div>
      ) : (
        <p className="hint" role="status">
          {busy === "cite"
            ? "正在读取 PDF 正文与出版来源，自动生成引用…"
            : "正在准备引用…"}
        </p>
      )}
    </section>
  );
}

