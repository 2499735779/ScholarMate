import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDocument,
  GlobalWorkerOptions,
  Util,
  type PDFDocumentProxy,
  type PDFPageProxy,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api, pdfSource } from "../lib/api";
import { chunkBlocks, groupText, type TextBox } from "../lib/pdfLayout";
import { Button } from "./ui/button";
import { ErrorBox, errorText } from "./common";
GlobalWorkerOptions.workerSrc = workerUrl;

const DPR = Math.min(window.devicePixelRatio || 1, 2);
const HAN = /[\u4e00-\u9fff]/;

type Blocks = Record<number, string>;
type Sheet = { width: number; height: number };

function Overlay({ box, scale, text }: { box: TextBox; scale: number; text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Shrink to fit, then let the reader scroll a block that is still too long.
    let size = 12 * scale;
    el.style.fontSize = size + "px";
    while (el.scrollHeight > el.clientHeight && size > 6) {
      size -= 0.5;
      el.style.fontSize = size + "px";
    }
  }, [text, box, scale]);
  return (
    <div
      ref={ref}
      className="pdf-overlay"
      title={text}
      style={{
        left: box.x * scale,
        top: box.y * scale,
        width: box.width * scale,
        height: box.height * scale,
      }}
    >
      {text}
    </div>
  );
}

/** Reads the block layout of one page once and keeps it for the session. */
async function pageBlocks(page: PDFPageProxy): Promise<{ sheet: Sheet; boxes: TextBox[] }> {
  const base = page.getViewport({ scale: 1 });
  const content = await page.getTextContent();
  const boxes = groupText(
    content.items.flatMap((item, index) => {
      if (!("str" in item) || !item.str.trim()) return [];
      const t = Util.transform(base.transform, item.transform);
      const height = Math.hypot(t[2], t[3]);
      // Rotated labels and equations stay in the original page image.
      if (Math.abs(t[1]) > 1) return [];
      return [
        {
          id: index,
          text: item.str,
          x: t[4],
          y: Math.max(0, t[5] - height * 0.85),
          width: item.width,
          height: height * 1.15,
        },
      ];
    }),
  );
  return { sheet: { width: base.width, height: base.height }, boxes };
}

function PageRow({
  doc,
  page,
  width,
  zoom,
  bilingual,
  blocks,
  near,
  loadBoxes,
  onVisible,
}: {
  doc: PDFDocumentProxy;
  page: number;
  width: number;
  zoom: number;
  bilingual: boolean;
  blocks?: Blocks;
  near: boolean;
  loadBoxes: (page: number) => Promise<TextBox[]>;
  onVisible: (page: number) => void;
}) {
  const left = useRef<HTMLCanvasElement>(null),
    right = useRef<HTMLCanvasElement>(null),
    holder = useRef<HTMLDivElement>(null);
  const [sheet, setSheet] = useState<Sheet>({ width: 612, height: 792 });
  const [boxes, setBoxes] = useState<TextBox[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    doc
      .getPage(page)
      .then((p) => {
        if (!active) return;
        const view = p.getViewport({ scale: 1 });
        setSheet({ width: view.width, height: view.height });
        setReady(true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      setReady(false);
    };
  }, [doc, page]);

  // Extract the block layout only when a translation exists for this page.
  useEffect(() => {
    if (!blocks || boxes.length) return;
    let active = true;
    loadBoxes(page)
      .then((found) => {
        if (active) setBoxes(found);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [blocks, boxes.length, loadBoxes, page]);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && onVisible(page)),
      { threshold: 0.15 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [page, onVisible]);

  const height = (sheet.height / sheet.width) * width;
  const scale = width / sheet.width;
  useEffect(() => {
    if (!ready || !near) return;
    const tasks: { cancel: () => void }[] = [];
    (async () => {
      const p = await doc.getPage(page);
      const view = p.getViewport({ scale: (width / p.getViewport({ scale: 1 }).width) * DPR });
      for (const canvas of [left.current, bilingual ? right.current : null]) {
        if (!canvas) continue;
        canvas.width = view.width;
        canvas.height = view.height;
        const task = p.render({ canvas, viewport: view });
        tasks.push(task);
        await task.promise;
      }
    })().catch(() => undefined);
    return () => {
      tasks.forEach((t) => t.cancel());
    };
  }, [doc, page, width, bilingual, near, ready]);

  useEffect(() => {
    if (near) return;
    // Release the bitmap of pages that are far away; they re-render on return.
    for (const canvas of [left.current, right.current]) {
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
    }
  }, [near]);

  return (
    <div className="pdf-row" ref={holder} data-page={page}>
      <div
        className="pdf-sheet"
        style={{ width: width * zoom, height: height * zoom }}
      >
        <div
          className="pdf-sheet-inner"
          style={{
            width,
            height,
            transform: `scale(${zoom})`,
            transformOrigin: "top left",
          }}
        >
          <canvas ref={left} style={{ width, height }} />
          {!ready && <span className="pdf-page-tag">第 {page} 页</span>}
        </div>
      </div>
      {bilingual && (
        <div
          className="pdf-sheet"
          style={{ width: width * zoom, height: height * zoom }}
        >
          <div
            className="pdf-sheet-inner"
            style={{
              width,
              height,
              transform: `scale(${zoom})`,
              transformOrigin: "top left",
            }}
          >
            <canvas ref={right} style={{ width, height }} />
            {blocks
              ? boxes.map((b) =>
                  blocks[b.id] ? (
                    <Overlay key={b.id} box={b} scale={scale} text={blocks[b.id]} />
                  ) : null,
                )
              : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default function PDFReader({ id, path }: { id: string; path?: string }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null),
    [page, setPage] = useState(1),
    [zoom, setZoom] = useState(1),
    [bilingual, setBilingual] = useState(false),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [base, setBase] = useState(620),
    [near, setNear] = useState<Set<number>>(new Set()),
    [translations, setTranslations] = useState<Record<number, Blocks>>({}),
    [progress, setProgress] = useState<{ done: number; total: number; current: number } | null>(
      null,
    );
  const scroller = useRef<HTMLDivElement>(null),
    stop = useRef(false),
    abort = useRef<AbortController | null>(null),
    docRef = useRef<PDFDocumentProxy | null>(null),
    blocksCache = useRef(new Map<number, TextBox[]>());
  const [chinese, setChinese] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    setNote("");
    setDoc(null);
    setPage(1);
    setTranslations({});
    setNear(new Set());
    blocksCache.current.clear();
    const task = getDocument({
      ...pdfSource(id),
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      wasmUrl: "/pdfjs/wasm/",
      isEvalSupported: false,
    });
    task.promise
      .then(async (d) => {
        if (!active) return;
        docRef.current = d;
        setDoc(d);
        try {
          const first = await (await d.getPage(1)).getTextContent();
          const sample = first.items
            .flatMap((i) => ("str" in i ? [i.str] : []))
            .join("")
            .slice(0, 600);
          setChinese(sample.length > 40 && (sample.match(/[\u4e00-\u9fff]/g) || []).length / sample.length > 0.2);
        } catch {
          setChinese(false);
        }
      })
      .catch((e) => {
        if (active) setError("PDF 无法打开：" + errorText(e));
      });
    return () => {
      active = false;
      abort.current?.abort();
      docRef.current = null;
      void task.destroy();
    };
  }, [id, path]);

  // Track which pages are close enough to render, and which one is on screen.
  useEffect(() => {
    const el = scroller.current;
    if (!doc || !el) return;
    const rendered = new Set<number>();
    const observer = new IntersectionObserver(
      (entries) => {
        let changed = false;
        for (const entry of entries) {
          const number = Number((entry.target as HTMLElement).dataset.page);
          if (!number) continue;
          if (entry.isIntersecting && !rendered.has(number)) {
            rendered.add(number);
            changed = true;
          } else if (!entry.isIntersecting && rendered.has(number)) {
            rendered.delete(number);
            changed = true;
          }
        }
        if (changed) setNear(new Set(rendered));
      },
      { root: el, rootMargin: "900px 0px" },
    );
    el.querySelectorAll("[data-page]").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [doc]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => {
      const available = el.clientWidth - 40;
      const each = bilingual ? (available - 18) / 2 : available;
      setBase(Math.max(240, Math.min(each, 860)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [bilingual]);

  const blocksFor = useCallback(
    async (number: number) => {
      const cached = blocksCache.current.get(number);
      if (cached) return cached;
      const target = docRef.current;
      if (!target) return [];
      const { boxes } = await pageBlocks(await target.getPage(number));
      blocksCache.current.set(number, boxes);
      return boxes;
    },
    [],
  );

  const translatePage = useCallback(
    async (number: number, signal: AbortSignal) => {
      const boxes = await blocksFor(number);
      if (!boxes.length) {
        setTranslations((v) => ({ ...v, [number]: {} }));
        return 0;
      }
      // Keep each request inside the server's per-request budget.
      const groups = chunkBlocks(boxes);
      const merged: Blocks = {};
      for (const part of groups) {
        const r = await api<{ blocks: { id: number; text: string }[] }>(
          "/paper/translate-page?id=" + encodeURIComponent(id),
          "POST",
          { blocks: part.map((b) => ({ id: b.id, text: b.text })) },
          signal,
        );
        r.blocks.forEach((b) => {
          merged[b.id] = b.text;
        });
      }
      setTranslations((v) => ({ ...v, [number]: merged }));
      return Object.keys(merged).length;
    },
    [blocksFor, id],
  );

  async function runTranslation(numbers: number[]) {
    if (!docRef.current) return;
    stop.current = false;
    setBilingual(true);
    setNote("");
    const controller = new AbortController();
    abort.current = controller;
    const pending = numbers.filter((n) => !translations[n]);
    setProgress({ done: 0, total: pending.length, current: 0 });
    let skipped = 0;
    try {
      for (const [index, number] of pending.entries()) {
        if (stop.current) break;
        setProgress({ done: index, total: pending.length, current: number });
        if (!(await translatePage(number, controller.signal))) skipped += 1;
        setProgress({ done: index + 1, total: pending.length, current: number });
      }
    } catch (e) {
      if (!stop.current) setError(errorText(e));
    } finally {
      if (abort.current === controller) abort.current = null;
      setProgress(null);
      if (skipped && !stop.current) {
        setNote(`有 ${skipped} 页没有可提取的英文段落（可能是扫描页或纯图表页），未生成译文。`);
      }
    }
  }

  const current = doc ? Math.min(page, doc.numPages) : 1;
  const untranslated = useMemo(() => {
    if (!doc) return [];
    return Array.from({ length: doc.numPages }, (_, i) => i + 1).filter(
      (n) => !translations[n],
    );
  }, [doc, translations]);

  function jump(number: number) {
    const row = scroller.current?.querySelector(`[data-page="${number}"]`);
    row?.scrollIntoView({ block: "start" });
    setPage(number);
  }

  return (
    <section className="panel pdf-reader">
      <div className="section-title">
        <div>
          <h2>论文阅读</h2>
          <p>
            打开即读原文件，不复制、不修改 PDF
            {Object.keys(translations).length
              ? ` · 对照译文仅保留在当前会话（已译 ${Object.keys(translations).length} 页）`
              : ""}
          </p>
        </div>
      </div>
      <div className="actions wrap">
        <Button variant="outline" disabled={!doc || current <= 1} onClick={() => jump(current - 1)}>
          上一页
        </Button>
        <span className="pdf-page-count">
          第 {current} / {doc?.numPages || "—"} 页
        </span>
        <Button
          variant="outline"
          disabled={!doc || current >= doc.numPages}
          onClick={() => jump(current + 1)}
        >
          下一页
        </Button>
        <select
          aria-label="阅读缩放"
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
        >
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((v) => (
            <option key={v} value={v}>
              {v * 100}%
            </option>
          ))}
        </select>
        {progress ? (
          <>
            <Button variant="outline" onClick={() => (stop.current = true)}>
              停止翻译
            </Button>
            <span className="hint" role="status">
              正在翻译第 {progress.current} 页 · 已完成 {progress.done}/{progress.total}
            </span>
          </>
        ) : (
          <>
            <Button
              disabled={!doc || chinese || !!progress}
              onClick={() => runTranslation(Array.from({ length: doc?.numPages || 0 }, (_, i) => i + 1))}
            >
              {bilingual ? "翻译全文 · 补齐剩余页" : "翻译全文 · 中英对照"}
            </Button>
            <Button
              variant="outline"
              disabled={!doc || chinese || !!progress}
              onClick={() => runTranslation([current])}
            >
              翻译当前页
            </Button>
            <Button variant="ghost" onClick={() => setBilingual((v) => !v)}>
              {bilingual ? "只看原文" : "左右对照"}
            </Button>
          </>
        )}
      </div>
      {chinese && doc && (
        <p className="hint">
          这篇 PDF 的正文以中文为主，无需翻译；仍可使用缩放和翻页阅读。
        </p>
      )}
      {!chinese && doc && (
        <p className="hint">
          「翻译全文」逐页调用设置中的 AI（会产生服务商费用），已翻译的页面不会重复请求；译文覆盖在右侧页面同一位置，原 PDF
          的排版、图表与文件本身都不改变。复杂公式、表格和旋转文字请以左侧原文为准，较长的译文可在文字块内滚动查看。
        </p>
      )}
      <ErrorBox error={error} />
      {note && <p className="hint">{note}</p>}
      {!doc && !error && <p role="status">正在加载 PDF…</p>}
      <div className={"pdf-scroll" + (bilingual ? " bilingual" : "")} ref={scroller}>
        {doc
          ? Array.from({ length: doc.numPages }, (_, i) => i + 1).map((number) => (
              <PageRow
                key={number}
                doc={doc}
                page={number}
                width={base}
                zoom={zoom}
                bilingual={bilingual}
                blocks={translations[number]}
                near={near.has(number)}
                loadBoxes={blocksFor}
                onVisible={setPage}
              />
            ))
          : null}
      </div>
      {bilingual && doc && !!untranslated.length && !progress && (
        <p className="hint">
          还有 {untranslated.length} 页没有译文；逐页翻译，页码越小越先完成。
        </p>
      )}
      <details>
        <summary>为什么没有直接调用沉浸式翻译插件</summary>
        <p className="hint">
          浏览器插件的官方 PDF 服务需要上传文件到第三方云端，并需要向服务商申请 JS SDK
          合作接入；本应用坚持论文只留在本机，因此内置了同款「左右对照、原地覆盖译文」的阅读方式，使用你自己的
          AI Key 逐页翻译。如需官方服务，可自行在浏览器打开下列入口上传文件。
        </p>
        <Button
          variant="outline"
          onClick={() =>
            api("/library/open", "POST", {
              url: "https://app.immersivetranslate.com/pdf-pro/",
            }).catch((e) => setError(errorText(e)))
          }
        >
          打开沉浸式翻译官方 PDF 服务 ↗
        </Button>
      </details>
    </section>
  );
}

