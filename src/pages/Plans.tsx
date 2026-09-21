import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PlanProposal from "../components/PlanProposal";
import SchedulePanel from "../components/SchedulePanel";
import { planText } from "../lib/planText";
import {
  Plus,
  Download,
  ArrowLeft,
  BookOpen,
  Trash2,
  Sparkles,
} from "lucide-react";
import { api, download } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import {
  Confirm,
  Empty,
  ErrorBox,
  Field,
  Markdown,
  errorText,
} from "../components/common";
import type { Plan, Message } from "../types";
const blank: Plan = {
  id: "",
  title: "",
  goal: "",
  plan_content: "",
  status: "进行中",
  created_at: "",
};
function readDraft(): Plan | null {
  try {
    const value = JSON.parse(sessionStorage.getItem("plan-draft") || "null");
    return value && typeof value.plan_content === "string" ? value : null;
  } catch {
    return null;
  }
}
export default function Plans() {
  const [candidates, setCandidates] = useState<Message[]>([]);
  const [searchParams] = useSearchParams();
  const requestedPlan = searchParams.get("plan");
  const [plans, setPlans] = useState<Plan[]>([]),
    [active, setActive] = useState<Plan | null>(readDraft),
    [period, setPeriod] = useState("3个月"),
    [custom, setCustom] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [confirm, setConfirm] = useState(false),
    [editing, setEditing] = useState(false),
    [dirty, setDirty] = useState(() => !!readDraft()),
    [notice, setNotice] = useState("");
  const reload = () => api<Plan[]>("/plans").then(setPlans);
  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
    api<Message[]>("/conversations/plan-candidates")
      .then(setCandidates)
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(() => {
    if (requestedPlan && dirty) {
      setNotice("请先保存或撤销当前草稿，再打开关联的计划。");
      return;
    }
    if (requestedPlan && !dirty) {
      api<Plan>("/plans/" + encodeURIComponent(requestedPlan))
        .then((p) => {
          setActive(p);
          setEditing(false);
        })
        .catch((e) => setError(errorText(e)));
    }
  }, [requestedPlan, dirty]);
  useEffect(() => {
    if (dirty && active)
      sessionStorage.setItem("plan-draft", JSON.stringify(active));
    else sessionStorage.removeItem("plan-draft");
  }, [active, dirty]);
  async function perform(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  function change(data: Partial<Plan>) {
    if (active) {
      setActive({ ...active, ...data });
      setDirty(true);
    }
  }
  return (
    <>
      <header className="page-heading">
        <div>
          <span className="eyebrow">ONE STEP AT A TIME</span>
          <h1>学习计划</h1>
          <p>把远大的目标，变成每周可执行的小步。</p>
        </div>
        {!active && (
          <Button
            onClick={() => {
              setActive({ ...blank });
              setEditing(true);
              setDirty(false);
              setError("");
            }}
          >
            <Plus size={17} />
            新建计划
          </Button>
        )}
      </header>
      {!active && (
        <Button
          variant="outline"
          onClick={() =>
            perform("refresh", async () => {
              await reload();
              setCandidates(
                await api<Message[]>("/conversations/plan-candidates"),
              );
            })
          }
        >
          刷新计划
        </Button>
      )}
      <ErrorBox error={error} />
      {notice && <p className="success">{notice}</p>}
      {!active ? (
        <>
          {!!candidates.length && (
            <section className="panel">
              <h2>对话中发现的学习计划</h2>
              <p className="hint">
                以下计划来自学术对话，点击采纳即可添加到计划库。
              </p>
              {candidates.map((m) => (
                <PlanProposal
                  key={m.id}
                  message={m}
                  onRejected={() =>
                    setCandidates((v) => v.filter((c) => c.id !== m.id))
                  }
                  onAdopted={() => {
                    setCandidates((v) => v.filter((c) => c.id !== m.id));
                    reload().catch((e) => setError(errorText(e)));
                  }}
                />
              ))}
            </section>
          )}
          {!plans.length ? (
            <Empty title="从一个目标开始">
              创建第一份个性化计划，开启你的学习旅程。
            </Empty>
          ) : (
            <div className="plan-grid">
              {plans.map((p) => (
                <button
                  className="plan-card"
                  key={p.id}
                  onClick={() => {
                    setActive(p);
                    setEditing(false);
                    setDirty(false);
                  }}
                >
                  <div className="card-top">
                    <BookOpen size={23} />
                    <span className="badge">
                      {p.paused_on && p.status === "进行中"
                        ? "已暂停"
                        : p.status}
                    </span>
                  </div>
                  <h2>{p.title}</h2>
                  <p>{p.goal}</p>
                  <footer>
                    {new Date(p.created_at).toLocaleDateString()}{" "}
                    <span>查看计划 →</span>
                  </footer>
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="actions">
            <Button
              variant="ghost"
              disabled={!!busy || dirty}
              onClick={() => setActive(null)}
            >
              <ArrowLeft size={16} />
              全部计划
            </Button>
            {dirty && (
              <>
                <span className="hint">草稿暂存于当前窗口，请保存计划。</span>
                <Button
                  variant="ghost"
                  disabled={!!busy}
                  onClick={() => {
                    setActive(
                      active.id
                        ? plans.find((p) => p.id === active.id) || null
                        : null,
                    );
                    setDirty(false);
                  }}
                >
                  撤销修改
                </Button>
              </>
            )}
          </div>
          {active.id && !dirty && (
            <SchedulePanel
              key={active.id + active.plan_content}
              id={active.id}
            />
          )}
          <section className="panel">
            {active.source_message_id && (
              <div className="source-plan">
                <span className="badge">来自学术对话</span>
                <Link
                  to={
                    "/chat?message=" +
                    encodeURIComponent(active.source_message_id)
                  }
                >
                  查看来源对话 →
                </Link>
                <details>
                  <summary>采纳时的原始回复（清空对话后仍保留）</summary>
                  <Markdown>
                    {planText(active.source_content || active.plan_content)}
                  </Markdown>
                </details>
              </div>
            )}
            <div className="form-grid">
              <Field label="计划标题">
                <Input
                  value={active.title}
                  maxLength={200}
                  onChange={(e) => change({ title: e.target.value })}
                  placeholder="为计划起个名字"
                />
              </Field>
              <Field label="状态">
                <select
                  value={active.status}
                  onChange={(e) => change({ status: e.target.value })}
                >
                  {["进行中", "已完成", "已放弃"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="学习目标">
              <Input
                value={active.goal}
                maxLength={4000}
                onChange={(e) => change({ goal: e.target.value })}
                placeholder="例如：三个月掌握 PyTorch 深度学习"
              />
            </Field>
            <div className="actions">
              <select
                aria-label="计划周期"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              >
                {["1个月", "3个月", "6个月", "自定义"].map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
              {period === "自定义" && (
                <Input
                  aria-label="自定义周期"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder="例如：8 周"
                />
              )}
              <Button
                disabled={
                  !!busy ||
                  !active.goal.trim() ||
                  (period === "自定义" && !custom.trim())
                }
                onClick={() =>
                  perform("generate", async () => {
                    const result = await api<{ content: string }>(
                      "/plans/generate",
                      "POST",
                      {
                        goal: active.goal,
                        period: period === "自定义" ? custom : period,
                      },
                    );
                    setActive({
                      ...active,
                      title: active.title || active.goal.slice(0, 100),
                      plan_content: result.content,
                    });
                    setDirty(true);
                    setEditing(false);
                  })
                }
              >
                <Sparkles size={16} />
                {busy === "generate"
                  ? "正在规划…"
                  : active.plan_content
                    ? "重新生成计划"
                    : "生成计划"}
              </Button>
            </div>
            {active.plan_content && (
              <p className="hint">
                重新生成会替换编辑区内容；已保存版本在再次保存前保持不变。
              </p>
            )}
          </section>
          <section className="panel">
            <div className="section-title">
              <h2>计划内容</h2>
              <Button variant="ghost" onClick={() => setEditing(!editing)}>
                {editing ? "预览 Markdown" : "编辑 Markdown"}
              </Button>
            </div>
            {editing ? (
              <textarea
                aria-label="Markdown 计划编辑器"
                className="markdown-editor"
                value={active.plan_content}
                onChange={(e) => change({ plan_content: e.target.value })}
                placeholder="在这里写下计划，或使用 AI 生成…"
              />
            ) : (
              <Markdown>{active.plan_content || "尚未生成内容。"}</Markdown>
            )}
            <div className="actions wrap">
              <Button
                disabled={
                  !!busy || !active.title.trim() || !active.plan_content.trim()
                }
                onClick={() =>
                  perform("save", async () => {
                    setActive(
                      await api<Plan>(
                        active.id ? "/plans/" + active.id : "/plans",
                        active.id ? "PUT" : "POST",
                        active,
                      ),
                    );
                    setDirty(false);
                    await reload();
                    setNotice("计划已保存。");
                  })
                }
              >
                {busy === "save" ? "保存中…" : "保存计划"}
              </Button>
              {active.id && (
                <>
                  {(["md", "pdf"] as const).map((format) => (
                    <Button
                      key={format}
                      variant="outline"
                      disabled={!!busy || dirty}
                      onClick={() =>
                        perform("export", () =>
                          download(
                            `/plans/${active.id}/export?format=${format}`,
                            `ScholarMate-plan.${format}`,
                          ),
                        )
                      }
                    >
                      <Download size={15} />
                      {format.toUpperCase()}
                    </Button>
                  ))}
                  <Button
                    variant="ghost"
                    disabled={!!busy}
                    onClick={() => setConfirm(true)}
                  >
                    <Trash2 size={15} />
                    删除
                  </Button>
                </>
              )}
            </div>
          </section>
        </>
      )}
      {confirm && active && (
        <Confirm
          title="删除这份计划？"
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            perform("delete", async () => {
              await api("/plans/" + active.id, "DELETE");
              setActive(null);
              setDirty(false);
              await reload();
            });
          }}
        >
          计划将从本地数据库永久删除。
        </Confirm>
      )}
    </>
  );
}

