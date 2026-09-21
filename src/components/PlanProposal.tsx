import { useState } from "react";
import { Link } from "react-router-dom";
import type { Message, Plan } from "../types";
import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Markdown, ErrorBox, errorText } from "./common";
export default function PlanProposal({
  message,
  onAdopted,
  onRejected,
}: {
  message: Message;
  onAdopted?: (plan: Plan) => void;
  onRejected?: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [adopted, setAdopted] = useState(message.adopted_plan_id);
  const [rejected, setRejected] = useState(!!message.plan_rejected);
  const candidate = message.plan_candidate;
  if (!candidate || !message.id) return null;
  return (
    <section className="plan-proposal">
      <span className="badge">
        {adopted ? "已采纳" : rejected ? "已拒绝" : "识别到学习计划"}
      </span>
      <h3>{candidate.title}</h3>
      <p className="hint">{candidate.goal}</p>
      <details>
        <summary>预览完整计划</summary>
        <Markdown>{candidate.plan_content}</Markdown>
      </details>
      <ErrorBox error={error} />
      <div className="actions">
        {adopted ? (
          <Link to={"/plans?plan=" + encodeURIComponent(adopted)}>
            查看已保存计划 →
          </Link>
        ) : rejected ? (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api(`/conversations/${message.id}/proposal`, "PUT", {
                  rejected: false,
                });
                setRejected(false);
              } catch (e) {
                setError(errorText(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            恢复候选计划
          </Button>
        ) : (
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const p = await api<Plan>("/plans/adopt", "POST", {
                  message_id: message.id,
                });
                setAdopted(p.id);
                onAdopted?.(p);
              } catch (e) {
                setError(errorText(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "正在添加…" : "采纳学习计划"}
          </Button>
        )}
        {!adopted && !rejected && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api(`/conversations/${message.id}/proposal`, "PUT", {
                  rejected: true,
                });
                setRejected(true);
                onRejected?.();
              } catch (e) {
                setError(errorText(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            拒绝计划
          </Button>
        )}
      </div>
    </section>
  );
}

