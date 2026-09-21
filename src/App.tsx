import { useEffect, useState } from "react";
import { HashRouter, NavLink, Route, Routes, Navigate } from "react-router-dom";
import {
  BookOpen,
  Library,
  MessagesSquare,
  Settings as SettingsIcon,
  Sun,
  Moon,
  HelpCircle,
  GraduationCap,
} from "lucide-react";
import { initialize, api, connectPreview } from "./lib/api";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { ErrorBox, Markdown, errorText } from "./components/common";
import Settings from "./pages/Settings";
import Chat from "./pages/Chat";
import Plans from "./pages/Plans";
import Home from "./pages/Home";
import Papers from "./pages/LibraryPage";
import type { ProfileList, Status } from "./types";
import help from "../docs/QUICKSTART.md?raw";
import faq from "../docs/FAQ.md?raw";
export default function App() {
  const [status, setStatus] = useState<Status | null>(null),
    [profiles, setProfiles] = useState<ProfileList | null>(null),
    [switching, setSwitching] = useState(false),
    [error, setError] = useState(""),
    [dark, setDark] = useState(localStorage.getItem("theme") === "dark"),
    [online, setOnline] = useState(navigator.onLine),
    [port, setPort] = useState(""),
    [token, setToken] = useState("");
  const refresh = async () => {
    const next = await api<Status>("/status");
    setStatus(next);
    setProfiles(await api<ProfileList>("/profiles").catch(() => null));
  };
  useEffect(() => {
    initialize()
      .then(refresh)
      .catch((e) => setError(errorText(e)));
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);
  if (!status)
    return (
      <div className="connect-page">
        <div className="hero-icon">
          <GraduationCap size={34} />
        </div>
        <h1>ScholarMate</h1>
        <p>你的个人学术学习空间</p>
        {error ? (
          <>
            <ErrorBox error={error} />
            <Button onClick={() => location.reload()}>重试连接</Button>
            {!("__TAURI_INTERNALS__" in window) && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  connectPreview(port, token);
                }}
              >
                <p>开发预览：填写 Python 启动输出的端口与本机会话令牌。</p>
                <Input
                  required
                  aria-label="后端端口"
                  placeholder="端口"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
                <Input
                  required
                  aria-label="会话令牌"
                  type="password"
                  placeholder="会话令牌"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
                <Button>连接本地后端</Button>
              </form>
            )}
          </>
        ) : (
          <p>正在启动本地服务…</p>
        )}
      </div>
    );
  return (
    <HashRouter>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-icon">
              <GraduationCap size={24} />
            </div>
            <div>
              ScholarMate<small>让好奇心，走得更远</small>
            </div>
          </div>
          <span className="nav-label">工作空间</span>
          <nav>
            {[
              { to: "/home", icon: GraduationCap, label: "本周学习" },
              { to: "/plans", icon: BookOpen, label: "学习计划" },
              { to: "/papers", icon: Library, label: "文献管理" },
              { to: "/chat", icon: MessagesSquare, label: "学术对话" },
              { to: "/settings", icon: SettingsIcon, label: "设置" },
            ].map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                aria-label={n.label}
                title={n.label}
              >
                <n.icon size={19} />
                <span>{n.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            {profiles && profiles.items.length > 0 && (
              <label className="profile-switch">
                <span>当前画像</span>
                <select
                  aria-label="切换当前画像"
                  value={profiles.active_id}
                  disabled={switching}
                  onChange={async (e) => {
                    setSwitching(true);
                    setError("");
                    try {
                      await api(`/profiles/${e.target.value}/activate`, "POST");
                      await refresh();
                    } catch (err) {
                      setError(errorText(err));
                    } finally {
                      setSwitching(false);
                    }
                  }}
                >
                  {profiles.items.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <small>{profiles.items.length} 个画像 · 对话各自记住所用画像</small>
              </label>
            )}
            <div className="local-note">
              <span className="status-dot" />
              本地优先，安心探索<small>画像与文献保存在这台设备</small>
            </div>
            <NavLink to="/help" aria-label="帮助与入门" title="帮助与入门">
              <HelpCircle size={18} />
              <span>帮助与入门</span>
            </NavLink>
            <Button
              variant="ghost"
              aria-label={dark ? "浅色模式" : "深色模式"}
              title={dark ? "浅色模式" : "深色模式"}
              onClick={() => setDark(!dark)}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
              <span>{dark ? "浅色模式" : "深色模式"}</span>
            </Button>
            <small className="version">ScholarMate · v0.10.0</small>
          </div>
        </aside>
        <main>
          {!online && (
            <div className="onboarding">
              当前处于离线状态。你仍可查看、编辑和导出本地数据；AI 和 arXiv
              需要网络。
            </div>
          )}
          <ErrorBox error={error} />
          <Routes>
            <Route
              path="/"
              element={
                <Navigate
                  to={
                    !status.has_key || !status.has_profile
                      ? "/settings"
                      : "/home"
                  }
                  replace
                />
              }
            />
            <Route
              path="/settings"
              element={<Settings status={status} refresh={refresh} />}
            />
            <Route path="/chat" element={<Chat status={status} refresh={refresh} />} />
            <Route path="/plans" element={<Plans />} />
            <Route path="/home" element={<Home />} />
            <Route path="/papers" element={<Papers />} />
            <Route
              path="/help"
              element={
                <>
                  <header className="page-heading">
                    <div>
                      <span className="eyebrow">A LITTLE GUIDANCE</span>
                      <h1>帮助与入门</h1>
                      <p>从第一份画像，到你的下一项研究。</p>
                    </div>
                  </header>
                  <section className="panel">
                    <Markdown>{help + "\n\n" + faq}</Markdown>
                  </section>
                </>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}

