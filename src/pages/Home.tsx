import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";
import { Empty, ErrorBox, errorText } from "../components/common";
import type { ScheduledPlan } from "../types";
type Dashboard = {
  week_start: string;
  week_end: string;
  plans: ScheduledPlan[];
};
export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function reload() {
    try {
      setData(await api<Dashboard>("/dashboard"));
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
  }
  useEffect(() => {
    reload();
    const timer = window.setInterval(reload, 30000);
    window.addEventListener("focus", reload);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", reload);
    };
  }, []);
  async function toggle(id: string, done: boolean) {
    setBusy(true);
    try {
      await api(`/plan-tasks/${id}`, "PUT", { done });
      await reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const current = data?.plans.filter((p) => !p.paused_on) || [];
  const tasks = current.flatMap((p) => p.week_tasks);
  return (
    <>
      <header className="page-heading">
        <div>
          <span className="eyebrow">YOUR WEEK, ONE STEP AT A TIME</span>
          <h1>本周学习</h1>
          <p>
            {data
              ? `${data.week_start} — ${data.week_end}`
              : "正在整理本周任务…"}
          </p>
        </div>
        <Button variant="outline" onClick={reload}>
          刷新首页
        </Button>
      </header>
      <ErrorBox error={error} />
      <div className="stat-grid">
        <div className="stat-card">
          <strong>{current.length}</strong>
          <span>执行中计划</span>
        </div>
        <div className="stat-card">
          <strong>{tasks.filter((t) => !t.done).length}</strong>
          <span>本周待完成</span>
        </div>
        <div className="stat-card">
          <strong>{tasks.filter((t) => t.done).length}</strong>
          <span>本周已完成</span>
        </div>
      </div>
      {data && !data.plans.length && (
        <Empty title="从一份计划开始本周">
          <Link to="/chat">与助手制定计划 →</Link>
        </Empty>
      )}
      {data?.plans.map((p) => (
        <section className="panel" key={p.id}>
          <div className="section-title">
            <div>
              <span className="badge">
                {p.paused_on
                  ? "已暂停"
                  : p.current_week === 0
                    ? "待开始"
                    : `第 ${p.current_week} 周`}
              </span>
              <h2>{p.title}</h2>
            </div>
            <Link to={`/plans?plan=${p.id}`}>安排 / 暂停 / 删除 →</Link>
          </div>
          <progress
            className="task-progress"
            max={Math.max(p.task_count, 1)}
            value={p.done_count}
          />
          <p className="hint">
            整体完成 {p.done_count} / {p.task_count} 项
          </p>
          {p.paused_on ? (
            <p className="hint">暂停后周数保持不变，恢复后继续。</p>
          ) : p.week_tasks.length ? (
            p.week_tasks.map((t) => (
              <label className="task-check" key={t.id}>
                <input
                  type="checkbox"
                  checked={!!t.done}
                  disabled={busy}
                  onChange={(e) => toggle(t.id, e.target.checked)}
                />
                <span className={t.done ? "task-done" : ""}>{t.title}</span>
              </label>
            ))
          ) : (
            <p className="hint">
              {p.current_week === 0
                ? "计划尚未开始。"
                : "本周暂无已安排任务，可在计划详情补充逐周任务。"}
            </p>
          )}
        </section>
      ))}
    </>
  );
}

