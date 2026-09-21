import { useEffect, useState } from "react";
import { api, stream, selectPDFPaths } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Empty, ErrorBox, Field, errorText } from "../components/common";
import { formatBytes } from "../lib/utils";
import { PaperDetail } from "./Papers";
import type { DuplicateCopy, Paper, StorageReport } from "../types";

export default function LibraryPage() {
  const [mode, setMode] = useState("local"),
    [q, setQ] = useState(""),
    [language, setLanguage] = useState(""),
    [category, setCategory] = useState(""),
    [provider, setProvider] = useState("all");
  const [local, setLocal] = useState<Paper[]>([]),
    [results, setResults] = useState<Paper[]>([]),
    [active, setActive] = useState<Paper | null>(null),
    [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [loading, setLoading] = useState(true),
    [organizing, setOrganizing] = useState(false);
  const [directory, setDirectory] = useState(
    localStorage.getItem("papers-directory") || "",
  );
  const [progress, setProgress] = useState<Record<string, string>>({});
  const [storage, setStorage] = useState<StorageReport | null>(null),
    [dupes, setDupes] = useState<DuplicateCopy[] | null>(null);
  async function reload() {
    const items = await api<Paper[]>("/papers");
    setLocal(items);
    setActive((p) => (p ? items.find((i) => i.id === p.id) || null : null));
    setLoading(false);
  }
  function inspect() {
    return api<StorageReport>("/library/storage")
      .then(setStorage)
      .catch(() => undefined);
  }
  async function findDuplicates() {
    await act(async () => {
      const r = await api<{ items: DuplicateCopy[] }>(
        "/library/dedupe?dry_run=true",
        "POST",
      );
      setDupes(r.items);
      setNote(
        r.items.length
          ? `发现 ${r.items.length} 份与原有文件完全相同的副本，可以清理。`
          : "没有发现重复副本：应用没有在你的磁盘上多存 PDF。",
      );
    });
  }
  async function removeDuplicates() {
    await act(async () => {
      const r = await api<{ items: DuplicateCopy[]; freed_bytes: number }>(
        "/library/dedupe?dry_run=false",
        "POST",
      );
      setDupes([]);
      await reload();
      await inspect();
      setNote(
        `已清理 ${r.items.length} 份重复副本，释放 ${formatBytes(r.freed_bytes)}，原文件保持在原来的位置。`,
      );
    });
  }
  useEffect(() => {
    let disposed = false,
      running = false;
    async function update() {
      if (running) return;
      running = true;
      try {
        await reload();
        if (disposed) return;
        setOrganizing(true);
        const r = await api<{ updated: number; errors?: string[] }>(
          "/library/enrich",
          "POST",
        );
        if (!disposed) {
          if (r.updated) await reload();
          if (r.errors?.length) setNote(r.errors.join("；"));
        }
      } catch (e) {
        if (!disposed) setError(errorText(e));
      } finally {
        running = false;
        if (!disposed) {
          setLoading(false);
          setOrganizing(false);
        }
      }
    }
    update();
    const timer = window.setInterval(() => {
      reload().catch((e) => setError(errorText(e)));
      update();
    }, 30000);
    const focus = () => reload().catch((e) => setError(errorText(e)));
    window.addEventListener("focus", focus);
    return () => {
      disposed = true;
      clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, []);
  useEffect(() => {
    inspect();
  }, [local.length]);
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function search() {
    await act(async () => {
      const r = await api<{ items: Paper[]; warnings: string[] }>(
        `/discovery/search?keyword=${encodeURIComponent(q)}&source=${provider}`,
      );
      setResults(r.items);
      setNote(r.warnings.join("；"));
      setSelected([]);
    });
  }
  async function download(items: Paper[]) {
    await act(async () => {
      const errors: string[] = [];
      for (const p of items) {
        try {
          setProgress((v) => ({ ...v, [p.id]: "连接中…" }));
          await stream("/papers/download", { ...p, directory }, (d) => {
            if (d.bytes)
              setProgress((v) => ({
                ...v,
                [p.id]:
                  d.progress == null
                    ? `${Math.round(Number(d.bytes) / 1024)} KB`
                    : `${d.progress}%`,
              }));
          });
          setProgress((v) => ({ ...v, [p.id]: "已下载" }));
        } catch (e) {
          setProgress((v) => ({ ...v, [p.id]: "下载失败" }));
          errors.push(p.title + "：" + errorText(e));
        }
      }
      await reload();
      setSelected([]);
      if (errors.length) throw new Error(errors.join("；"));
    });
  }
  async function importFiles() {
    await act(async () => {
      const paths = await selectPDFPaths();
      for (const path of paths) await api("/library/link", "POST", { path });
      await reload();
      if (paths.length)
        setNote(
          "已关联原 PDF，未复制文件。正在从内容识别标题和关键词，分类将在后台整理。",
        );
    });
  }
  if (active)
    return (
      <PaperDetail
        key={active.id}
        paper={active}
        onBack={() => setActive(null)}
        onChange={() => reload().catch((e) => setError(errorText(e)))}
      />
    );
  const list =
    mode === "search"
      ? results
      : local.filter(
          (p) =>
            (!language || p.language === language) &&
            (!category || (p.category || "待分类") === category) &&
            q
              .toLocaleLowerCase()
              .split(/\s+/)
              .every((w) =>
                [
                  p.title,
                  p.title_zh,
                  p.authors,
                  p.abstract,
                  p.summary,
                  p.tags,
                  p.doi,
                  p.category,
                ]
                  .join(" ")
                  .toLocaleLowerCase()
                  .includes(w),
              ),
        );
  const categories = Array.from(
    new Set(local.map((p) => p.category || "待分类")),
  );
  return (
    <>
      <header className="page-heading">
        <div>
          <span className="eyebrow">YOUR RESEARCH LIBRARY</span>
          <h1>文献管理</h1>
          <p>中英双语索引 · 智能分类 · 引用与阅读</p>
        </div>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() =>
            act(async () => {
              await reload();
              setNote("已刷新本地文件状态。");
            })
          }
        >
          刷新文献
        </Button>
      </header>
      <div className="stat-grid">
        <div className="stat-card">
          <strong>{local.length}</strong>
          <span>本地文献</span>
        </div>
        <div className="stat-card">
          <strong>{local.filter((p) => p.language === "中文").length}</strong>
          <span>中文文献</span>
        </div>
        <div className="stat-card">
          <strong>{local.filter((p) => p.language === "英文").length}</strong>
          <span>英文文献</span>
        </div>
      </div>
      <div className="tabs">
        {[
          ["local", "我的文献"],
          ["search", "发现文献"],
        ].map(([v, t]) => (
          <button
            key={v}
            disabled={busy}
            className={mode === v ? "active" : ""}
            onClick={() => {
              setMode(v);
              setQ("");
              setNote("");
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      {note && (
        <p className="hint" role="status">
          {note}
        </p>
      )}
      <form
        className="search-bar"
        onSubmit={(e) => {
          e.preventDefault();
          if (mode === "search") search();
        }}
      >
        <Input
          aria-label="文献关键词"
          maxLength={300}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={
            mode === "local"
              ? "搜索中英文标题、作者、标签、摘要、总结或 DOI"
              : "输入中文或英文主题 / DOI"
          }
        />
        {mode === "search" && (
          <Button disabled={busy || !q.trim()}>
            {busy ? "检索中…" : "搜索"}
          </Button>
        )}
      </form>
      {mode === "local" ? (
        <>
          <div className="actions wrap">
            <select
              aria-label="文献语言"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {["", "中文", "英文"].map((x) => (
                <option key={x} value={x}>
                  {x || "全部语言"}
                </option>
              ))}
            </select>
            <select
              aria-label="文献分类"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">全部分类</option>
              {categories.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
            <Button variant="outline" disabled={busy} onClick={importFiles}>
              关联本地 PDF（不复制）
            </Button>
            <Button variant="ghost" disabled={busy} onClick={findDuplicates}>
              检查重复副本
            </Button>
          </div>
          <p className="hint">
            {organizing
              ? "正在自动翻译标题并整理分类…"
              : "自动整理使用已配置的 AI，可能产生服务商费用。"}{" "}
            每 30 秒及返回窗口时检查文件，已移除的文件不再显示。
          </p>
          {storage && (
            <section className="panel">
              <div className="section-title">
                <div>
                  <h2>本地存储</h2>
                  <p>
                    导入只关联原文件，不再复制；下面的数字说明磁盘上实际放了多少东西。
                  </p>
                </div>
              </div>
              <div className="storage-grid">
                <div className="storage-card">
                  <strong>{storage.linked_count}</strong>
                  <span>关联的原文件（不占应用空间）</span>
                </div>
                <div className="storage-card">
                  <strong>{formatBytes(storage.managed_bytes)}</strong>
                  <span>应用数据目录里的 PDF 副本（{storage.managed_count} 个）</span>
                </div>
                <div className="storage-card">
                  <strong>{local.length}</strong>
                  <span>文献条目（含元数据）</span>
                </div>
              </div>
              <p className="storage-path">
                应用数据目录：{storage.data_dir}（数据库与旧版副本）
              </p>
              <p className="storage-path">
                默认 PDF 下载目录：{storage.download_dir}
              </p>
              <p className="hint">
                这两个位置都可以改到其他盘符：「设置 → 存储位置」可更改数据目录（会连同数据库一起迁移）和默认下载目录，更改后不再占用系统盘。
              </p>
              {dupes && (
                <>
                  {dupes.length ? (
                    <>
                      <ul className="dedupe-list">
                        {dupes.slice(0, 8).map((d) => (
                          <li key={d.id}>
                            {d.title}：{d.copy} → 保留 {d.original}
                          </li>
                        ))}
                        {dupes.length > 8 && <li>另有 {dupes.length - 8} 份…</li>}
                      </ul>
                      <Button disabled={busy} onClick={removeDuplicates}>
                        清理 {dupes.length} 份副本（释放{" "}
                        {formatBytes(dupes.reduce((n, d) => n + d.bytes, 0))}）
                      </Button>
                    </>
                  ) : (
                    <p className="hint">
                      没有发现重复副本，磁盘上每篇文献只保留一份 PDF。
                    </p>
                  )}
                </>
              )}
              {!dupes && storage.managed_count > 0 && (
                <p className="hint">
                  检出 {storage.managed_count} 份旧版导入副本；点击「检查重复副本」确认它们是否与你原有的
                  PDF 完全相同，再决定是否清理。
                </p>
              )}
            </section>
          )}
          <div className="category-strip">
            {categories.map((c) => (
              <button
                key={c}
                className={category === c ? "badge selected" : "badge"}
                onClick={() => setCategory(category === c ? "" : c)}
              >
                {c} ·{" "}
                {local.filter((p) => (p.category || "待分类") === c).length}
              </button>
            ))}
          </div>
        </>
      ) : (
        <section className="panel">
          <div className="actions wrap">
            <Field label="检索来源">
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                {[
                  ["all", "综合检索"],
                  ["crossref", "Crossref · 跨学科 / 中英文"],
                  ["arxiv", "arXiv · 预印本"],
                  ["europepmc", "Europe PMC · 生物医学"],
                ].map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="PDF 下载目录">
              <Input
                value={directory}
                placeholder={storage ? `留空则保存到 ${storage.download_dir}` : "留空使用默认目录"}
                onChange={(e) => {
                  setDirectory(e.target.value);
                  localStorage.setItem("papers-directory", e.target.value);
                }}
              />
            </Field>
          </div>
          <p className="hint">
            检索范围包含中英文元数据；可下载性取决于开放全文和来源支持。订阅资源请通过机构权限访问，下载后可导入本机。
          </p>
          <div className="actions wrap">
            {[
              ["知网", "https://kns.cnki.net/kns8s/"],
              [
                "万方",
                "https://s.wanfangdata.com.cn/paper?q=" + encodeURIComponent(q),
              ],
              ["国家哲学社会科学文献中心", "https://www.ncpssd.cn/"],
            ].map(([t, url]) => (
              <Button
                key={t}
                variant="ghost"
                onClick={() =>
                  act(async () => {
                    await api("/library/open", "POST", { url });
                  })
                }
              >
                {t} ↗
              </Button>
            ))}
            {!!selected.length && (
              <Button
                disabled={busy}
                onClick={() =>
                  download(results.filter((p) => selected.includes(p.id)))
                }
              >
                下载选中（{selected.length}）
              </Button>
            )}
          </div>
        </section>
      )}
      {loading ? (
        <p>正在读取文献…</p>
      ) : !list.length ? (
        <Empty
          title={mode === "local" ? "暂无匹配的本地文献" : "搜索你感兴趣的研究"}
        >
          可更换关键词，或导入本地中英文 PDF。
        </Empty>
      ) : (
        <div className="library-grid">
          {list.map((p) => {
            const downloaded = local.some(
              (l) => l.id === p.id || !!(p.doi && l.doi === p.doi),
            );
            return (
              <article className="paper-card" key={p.id}>
                <div className="paper-card-top">
                  <span className="badge">
                    {p.language ||
                      (/\p{Script=Han}/u.test(p.title) ? "中文" : "英文")}
                  </span>
                  <span className="eyebrow">
                    {p.source || "arxiv"} ·{" "}
                    {p.published.slice(0, 10) || "日期待补"}
                  </span>
                </div>
                <h2>{p.title_zh || p.title}</h2>
                {p.title_zh && p.title_zh !== p.title && (
                  <p className="original-title">{p.title}</p>
                )}
                <p className="authors">{p.authors || "作者待补"}</p>
                <p className="abstract">
                  {p.abstract || "可在详情提取正文、生成总结。"}
                </p>
                <div className="category-strip">
                  <span className="badge">{p.category || "待分类"}</span>
                  {p.tags
                    ?.split(/[,，]/)
                    .filter(Boolean)
                    .map((t) => (
                      <span className="tag" key={t}>
                        {t}
                      </span>
                    ))}
                </div>
                {p.enrichment_error && (
                  <p className="hint">自动整理未完成，可在详情重试。</p>
                )}
                <footer>
                  <span className="hint">{progress[p.id] || ""}</span>
                  <div className="actions wrap">
                    {mode === "local" ? (
                      <Button variant="outline" onClick={() => setActive(p)}>
                        阅读 / 引用 →
                      </Button>
                    ) : downloaded ? (
                      <span className="badge">已下载</span>
                    ) : (
                      <>
                        {p.pdf_url && (
                          <>
                            <input
                              type="checkbox"
                              aria-label={"选择 " + p.title}
                              disabled={busy}
                              checked={selected.includes(p.id)}
                              onChange={(e) =>
                                setSelected(
                                  e.target.checked
                                    ? [...selected, p.id]
                                    : selected.filter((id) => id !== p.id),
                                )
                              }
                            />
                            <Button
                              disabled={busy}
                              onClick={() => download([p])}
                            >
                              下载 PDF
                            </Button>
                          </>
                        )}
                        {p.landing_url && (
                          <Button
                            variant="outline"
                            onClick={() =>
                              act(async () => {
                                await api("/library/open", "POST", {
                                  url: p.landing_url,
                                });
                              })
                            }
                          >
                            {p.pdf_url ? "来源网页" : "前往获取全文 ↗"}
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                </footer>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}

