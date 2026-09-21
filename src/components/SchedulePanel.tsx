import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ErrorBox, Field, errorText } from "./common";
import type { ScheduledPlan } from "../types";

export default function SchedulePanel({ id }: { id: string }) {
  const [plan, setPlan] = useState<ScheduledPlan | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [week, setWeek] = useState(1);
  const [title, setTitle] = useState("");
  const reload = () => api<ScheduledPlan>(`/plan-schedule/${id}`).then(setPlan);
  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
  }, [id]);
  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <h2>执行安排</h2>
          <p>采纳当周为第 1 周，每周一进入下一周。暂停期间不推进周数。</p>
        </div>
        <Button variant="outline" disabled={busy} onClick={() => act(reload)}>
          刷新安排
        </Button>
      </div>
      <ErrorBox error={error} />
      {plan && (
        <>
          <div className="actions wrap">
            <span className="badge">
              {plan.paused_on
                ? "已暂停"
                : plan.current_week === 0
                  ? "尚未开始"
                  : `第 ${plan.current_week} 周`}
            </span>
            <Button
              disabled={busy || plan.status !== "进行中"}
              onClick={() =>
                act(() =>
                  api(`/plan-schedule/${id}`, "PUT", {
                    paused: !plan.paused_on,
                  }),
                )
              }
            >
              {plan.paused_on ? "恢复计划" : "暂停计划"}
            </Button>
            <Field label="第 1 周起始日期（自动对齐周一）">
              <Input
                type="date"
                value={plan.start_date || ""}
                disabled={busy}
                onChange={(e) => {
                  if (e.target.value)
                    act(() =>
                      api(`/plan-schedule/${id}`, "PUT", {
                        start_date: e.target.value,
                      }),
                    );
                }}
              />
            </Field>
          </div>
          <p className="hint">
            调整起始日期可提前、延后或从中间周开始执行。已完成 {plan.done_count}{" "}
            / {plan.task_count} 项。
          </p>
          <progress
            className="task-progress"
            max={Math.max(1, plan.task_count)}
            value={plan.done_count}
          />
          {!plan.tasks.length && (
            <p className="onboarding">
              还没有识别到逐周任务。可在下方手动添加，或将正文整理为“## 第 1
              周”标题和任务列表后保存。
            </p>
          )}
          <div className="week-timeline">
            {Array.from(new Set(plan.tasks.map((t) => t.week))).map((w) => (
              <section
                key={w}
                className={
                  w === plan.current_week ? "week-block current" : "week-block"
                }
              >
                <h3>
                  第 {w} 周 {w === plan.current_week && "· 当前周"}
                </h3>
                {plan.tasks
                  .filter((t) => t.week === w)
                  .map((t) => (
                    <label className="task-check" key={t.id}>
                      <input
                        type="checkbox"
                        checked={!!t.done}
                        disabled={busy}
                        onChange={(e) =>
                          act(() =>
                            api(`/plan-tasks/${t.id}`, "PUT", {
                              done: e.target.checked,
                            }),
                          )
                        }
                      />
                      <span className={t.done ? "task-done" : ""}>
                        {t.title}
                      </span>
                    </label>
                  ))}
              </section>
            ))}
          </div>
          <form
            className="actions wrap"
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                await api(`/plan-schedule/${id}/tasks`, "POST", {
                  week,
                  title,
                });
                setTitle("");
              });
            }}
          >
            <Field label="任务周数">
              <Input
                type="number"
                min={1}
                max={520}
                value={week}
                onChange={(e) => setWeek(Number(e.target.value))}
              />
            </Field>
            <Field label="新增任务">
              <Input
                value={title}
                maxLength={1000}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="本周要完成的具体行动"
              />
            </Field>
            <Button disabled={busy || !title.trim()}>添加任务</Button>
          </form>
        </>
      )}
    </section>
  );
}

