import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "./ui/button";
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img: () => null,
          a: ({ children }) => <span className="link-text">{children}</span>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-orbit">✧</span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Confirm({
  title,
  children,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2>{title}</h2>
        <p>{children}</p>
        <div className="actions">
          <Button variant="outline" onClick={onCancel} autoFocus>
            取消
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            确认删除
          </Button>
        </div>
      </section>
    </div>
  );
}
export function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
export function errorText(e: unknown) {
  return e instanceof Error ? e.message : "操作失败，请重试。";
}

