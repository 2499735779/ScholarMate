import { useEffect, useState } from "react";
import {
  KeyRound,
  UserRound,
  Check,
  HardDriveDownload,
  Plus,
  Copy,
  Trash2,
  Star,
} from "lucide-react";
import { api, selectFolder } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Field, ErrorBox, Confirm, errorText } from "../components/common";
import { formatBytes } from "../lib/utils";
import type { Profile, ProfileList, Status, StorageSettings } from "../types";
const initial: Profile = {
  name: "",
  major: "",
  degree: "硕士",
  research_field: "",
  specific_interests: [],
  short_term_goal: "",
  long_term_goal: "",
  weekly_hours: 8,
  language_preference: "中文",
  custom_instructions: "",
};
export function ProfilesPanel({ onSaved }: { onSaved: () => Promise<void> }) {
  const [items, setItems] = useState<Profile[]>([]),
    [activeId, setActiveId] = useState(""),
    [selected, setSelected] = useState(""),
    [p, setP] = useState<Profile>(initial),
    [tags, setTags] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [confirm, setConfirm] = useState(false);
  async function load(prefer?: string) {
    const data = await api<ProfileList>("/profiles");
    setItems(data.items);
    setActiveId(data.active_id);
    const wanted =
      prefer && data.items.some((x) => x.id === prefer)
        ? prefer
        : data.items.some((x) => x.id === selected)
          ? selected
          : data.active_id || data.items[0]?.id || "";
    setSelected(wanted);
    const found = data.items.find((x) => x.id === wanted);
    if (found) {
      setP({ ...found });
      setTags(found.specific_interests.join("，"));
    } else {
      setP(initial);
      setTags("");
    }
    return data;
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
    // Load the list once per visit; every later change goes through the actions below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function act(name: string, fn: () => Promise<void>) {
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
  const payload = () => ({
    ...p,
    specific_interests: tags
      .split(/[,，\n]/)
      .map((t) => t.trim())
      .filter(Boolean),
  });
  const create = (copy: boolean) =>
    act(copy ? "copy" : "create", async () => {
      const body = copy
        ? payload()
        : {
            ...initial,
            // An empty profile is fine: it is created first and filled in below.
            name: `画像 ${items.length + 1}`,
          };
      const created = await api<Profile>("/profiles", "POST", body);
      await load(created.id);
      await onSaved();
      setNotice(
        copy
          ? "已复制为新画像并设为当前画像，可在下方修改名称与领域。"
          : "已新建画像并设为当前画像，请在下方填写名称与研究方向。",
      );
    });
  const remove = () =>
    act("delete", async () => {
      await api("/profiles/" + selected, "DELETE");
      await load();
      await onSaved();
      setNotice("画像已删除，使用它的对话已改为使用当前画像。");
    });
  const activate = (id: string) =>
    act("activate", async () => {
      await api("/profiles/" + id + "/activate", "POST");
      await load(id);
      await onSaved();
      setNotice("已切换当前画像；新对话与计划、总结等任务会使用它。");
    });
  const save = () =>
    act("save", async () => {
      await api("/profiles/" + selected, "PUT", payload());
      await load(selected);
      await onSaved();
      setNotice("画像已保存。");
    });
  const editable = selected !== "";
  return (
    <section className="panel">
      <div className="section-title">
        <UserRound size={20} />
        <div>
          <h2>学术画像</h2>
          <p>
            可以同时维护多个研究方向：每条对话记住自己使用的画像，侧边栏随时切换当前画像。
          </p>
        </div>
        <span className="badge">{items.length} 个画像</span>
      </div>
      <div className="profile-tabs">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={"profile-tab" + (item.id === selected ? " active" : "")}
            onClick={() => {
              setSelected(item.id || "");
              setP({ ...item });
              setTags(item.specific_interests.join("，"));
              setNotice("");
            }}
          >
            {item.name || item.research_field || "未命名"}
            {item.id === activeId && <em>当前</em>}
          </button>
        ))}
      </div>
      <div className="actions wrap">
        <Button disabled={!!busy} onClick={() => create(false)}>
          <Plus size={15} />
          {busy === "create" ? "新建中…" : "新建画像"}
        </Button>
        <Button
          variant="outline"
          disabled={!!busy || !editable}
          onClick={() => create(true)}
        >
          <Copy size={15} />
          {busy === "copy" ? "复制中…" : "复制当前编辑的画像"}
        </Button>
        {editable && selected !== activeId && (
          <Button
            variant="outline"
            disabled={!!busy}
            onClick={() => activate(selected)}
          >
            <Star size={15} />
            {busy === "activate" ? "切换中…" : "设为当前画像"}
          </Button>
        )}
        <Button
          variant="ghost"
          disabled={!!busy || !editable || items.length <= 1}
          onClick={() => setConfirm(true)}
        >
          <Trash2 size={15} />
          {busy === "delete" ? "删除中…" : "删除画像"}
        </Button>
      </div>
      {!editable && (
        <p className="hint">还没有画像，先点「新建画像」填写你的研究方向。</p>
      )}
      {editable && (
        <>
          <div className="form-grid">
            <Field label="画像名称 *">
              <Input
                required
                maxLength={80}
                value={p.name || ""}
                onChange={(e) => setP({ ...p, name: e.target.value })}
                placeholder="例如：方向 A · 供水管网"
              />
            </Field>
            <Field label="专业 *">
              <Input
                required
                maxLength={200}
                value={p.major}
                onChange={(e) => setP({ ...p, major: e.target.value })}
                placeholder="例如：计算机科学"
              />
            </Field>
            <Field label="学历阶段">
              <select
                value={p.degree}
                onChange={(e) => setP({ ...p, degree: e.target.value })}
              >
                {["本科", "硕士", "博士", "博士后", "其他"].map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </Field>
            <Field label="研究领域 *">
              <Input
                required
                maxLength={500}
                value={p.research_field}
                onChange={(e) => setP({ ...p, research_field: e.target.value })}
                placeholder="例如：自然语言处理"
              />
            </Field>
            <Field label="兴趣方向（逗号分隔，可多选）">
              <Input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="大语言模型，机器学习，知识图谱"
              />
            </Field>
            <Field label="短期目标">
              <textarea
                maxLength={2000}
                value={p.short_term_goal}
                onChange={(e) => setP({ ...p, short_term_goal: e.target.value })}
                placeholder="未来 1–3 个月，你想完成什么？"
              />
            </Field>
            <Field label="长期目标">
              <textarea
                maxLength={2000}
                value={p.long_term_goal}
                onChange={(e) => setP({ ...p, long_term_goal: e.target.value })}
                placeholder="你希望走向怎样的研究方向？"
              />
            </Field>
            <Field label="每周可用小时数">
              <Input
                type="number"
                min={1}
                max={168}
                required
                value={p.weekly_hours}
                onChange={(e) =>
                  setP({ ...p, weekly_hours: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="语言偏好">
              <select
                value={p.language_preference}
                onChange={(e) => setP({ ...p, language_preference: e.target.value })}
              >
                <option>中文</option>
                <option>English</option>
                <option>中英双语</option>
              </select>
            </Field>
          </div>
          <Field label="自定义指令">
            <textarea
              maxLength={4000}
              value={p.custom_instructions}
              onChange={(e) => setP({ ...p, custom_instructions: e.target.value })}
              placeholder="例如：先给出直观解释，再介绍数学推导。"
            />
          </Field>
          <ErrorBox error={error} />
          <div className="actions">
            <Button disabled={!!busy} onClick={save}>
              {busy === "save" ? "保存中…" : "保存画像"}
            </Button>
            {selected === activeId && <span className="badge">当前使用的画像</span>}
          </div>
        </>
      )}
      {!editable && <ErrorBox error={error} />}
      {notice && <p className="success">{notice}</p>}
      {confirm && (
        <Confirm
          title="删除这个画像？"
          onCancel={() => setConfirm(false)}
          onConfirm={async () => {
            setConfirm(false);
            await remove();
          }}
        >
          「{p.name}」会被删除；正在使用它的对话会自动改为使用当前画像，消息与附件都保留。
        </Confirm>
      )}
    </section>
  );
}
export function StorageLocation() {
  const [state, setState] = useState<StorageSettings | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const load = () =>
    api<StorageSettings>("/settings/storage")
      .then(setState)
      .catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  async function act(name: string, body: Record<string, unknown>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      const next = await api<StorageSettings>("/settings/storage", "PUT", body);
      setState(next);
      setNotice(
        name === "data"
          ? `数据目录已切换，${next.freed_bytes ? `释放 ${formatBytes(next.freed_bytes)}，` : ""}原目录内容已迁移。新位置从下次启动起同样生效。`
          : "默认 PDF 下载目录已更新，之后下载的论文会保存到新位置。",
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  async function choose(key: "data_dir" | "download_dir") {
    const folder = await selectFolder();
    if (!folder) return;
    await act(key === "data_dir" ? "data" : "download", { [key]: folder });
  }
  if (!state)
    return (
      <section className="panel">
        <ErrorBox error={error} />
        <p className="hint" role="status">
          正在读取存储位置…
        </p>
      </section>
    );
  const onSystemDrive = (value: string) =>
    value.toLowerCase().startsWith(state.system_drive.toLowerCase());
  return (
    <section className="panel">
      <div className="section-title">
        <HardDriveDownload size={20} />
        <div>
          <h2>存储位置</h2>
          <p>
            数据库、旧版副本和下载的 PDF
            都可以放在任意盘符，不一定要留在系统盘。
          </p>
        </div>
      </div>
      <div className="storage-grid">
        <div className="storage-card">
          <strong>
            {state.data_dir_custom ? "自定义" : "系统默认"} ·{" "}
            {formatBytes(state.data_dir_bytes)}
          </strong>
          <span>数据目录（数据库、旧版导入副本）</span>
          <p className="storage-path">{state.data_dir}</p>
          {onSystemDrive(state.data_dir) && (
            <p className="hint">当前位于系统盘，可改到其他盘符。</p>
          )}
          <div className="actions wrap">
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() => choose("data_dir")}
            >
              {busy === "data" ? "迁移中…" : "更改数据目录"}
            </Button>
            {state.data_dir_custom && (
              <Button
                variant="ghost"
                disabled={!!busy}
                onClick={() => act("data", { reset: ["data_dir"] })}
              >
                恢复默认位置
              </Button>
            )}
          </div>
        </div>
        <div className="storage-card">
          <strong>默认 PDF 下载目录</strong>
          <span>「发现文献」下载时留空就保存到这里</span>
          <p className="storage-path">{state.download_dir}</p>
          {onSystemDrive(state.download_dir) && (
            <p className="hint">当前位于系统盘，可改到其他盘符。</p>
          )}
          <div className="actions wrap">
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() => choose("download_dir")}
            >
              {busy === "download" ? "保存中…" : "更改下载目录"}
            </Button>
            {state.download_dir_custom && (
              <Button
                variant="ghost"
                disabled={!!busy}
                onClick={() => act("download", { reset: ["download_dir"] })}
              >
                恢复默认位置
              </Button>
            )}
          </div>
        </div>
      </div>
      <p className="hint">
        更改数据目录会把数据库和旧版副本一起迁移到新文件夹，复制校验成功后才删除原文件；请选择空文件夹。图片、笔记等其他文件不会被移动。系统凭据管理器里的
        API Key 与磁盘位置无关，不受影响。
      </p>
      <ErrorBox error={error} />
      {notice && <p className="success">{notice}</p>}
    </section>
  );
}
export default function Settings({
  status,
  refresh,
}: {
  status: Status;
  refresh: () => Promise<void>;
}) {
  const [key, setKey] = useState(""),
    [model, setModel] = useState(status.model),
    [vision, setVision] = useState(!!status.vision),
    [custom, setCustom] = useState(
      !["deepseek-chat", "deepseek-reasoner"].includes(status.model),
    ),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  async function act(test: boolean) {
    setBusy(test ? "test" : "save");
    setError("");
    setNotice("");
    try {
      await api(test ? "/settings/test" : "/settings", test ? "POST" : "PUT", {
        model,
        api_key: key || null,
        vision,
      });
      if (!test) {
        setKey("");
        await refresh();
      }
      setNotice(test ? "连接成功，模型可用。" : "配置已安全保存。");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <header className="page-heading">
        <div>
          <span className="eyebrow">MAKE IT YOURS</span>
          <h1>设置</h1>
          <p>连接你的 AI，建立专属学术助手。</p>
        </div>
      </header>
      {(!status.has_key || !status.has_profile) && (
        <div className="onboarding">
          <b>欢迎使用 ScholarMate</b>
          <span>① 配置 API Key　→　② 填写学术画像　→　开始探索</span>
        </div>
      )}
      <section className="panel">
        <div className="section-title">
          <KeyRound size={20} />
          <div>
            <h2>AI 连接</h2>
            <p>Key 保存在系统凭据管理器中，不写入数据库。</p>
          </div>
          <span className="badge">{status.has_key ? "已配置" : "未配置"}</span>
        </div>
        <div className="form-grid">
          <Field label="DeepSeek API Key">
            <Input
              type="password"
              autoComplete="new-password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                status.has_key ? "已安全保存 · 输入新 Key 可替换" : "sk-…"
              }
            />
          </Field>
          <Field label="模型">
            <select
              value={custom ? "custom" : model}
              onChange={(e) => {
                setCustom(e.target.value === "custom");
                setModel(e.target.value === "custom" ? "" : e.target.value);
              }}
            >
              <option>deepseek-chat</option>
              <option>deepseek-reasoner</option>
              <option value="custom">自定义模型名称</option>
            </select>
            {custom && (
              <Input
                aria-label="自定义模型名称"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="输入 DeepSeek 支持的模型 ID"
              />
            )}
          </Field>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={vision}
            onChange={(e) => setVision(e.target.checked)}
          />
          当前模型支持图片输入（多模态）：勾选后，对话中上传的图片会作为图片内容发送给模型
        </label>
        <p className="hint">
          测试连接会发送一次简短 AI
          请求，可能产生少量服务商费用。自定义模型仍使用 DeepSeek 接口；模型名含 vision /
          omni / gpt-4o 等字样时会默认勾选上面这一项。未勾选时图片仍会保存为本地附件，但 AI
          看不到图中内容。
        </p>
        <ErrorBox error={error || status.credential_error || ""} />
        {notice && <p className="success">{notice}</p>}
        <div className="actions">
          <Button disabled={!!busy || !model.trim()} onClick={() => act(false)}>
            {busy === "save" ? "保存中…" : "保存配置"}
          </Button>
          <Button
            variant="outline"
            disabled={!!busy || !model.trim()}
            onClick={() => act(true)}
          >
            {busy === "test" ? "连接中…" : "测试连接"}
          </Button>
        </div>
      </section>
      <ProfilesPanel onSaved={refresh} />
      <StorageLocation />
    </>
  );
}

