import { invoke, isTauri } from "@tauri-apps/api/core";
type Connection = { port: number; token: string };
let connection: Connection | undefined;
export async function initialize() {
  if (isTauri()) connection = await invoke<Connection>("backend_connection");
  else {
    const port = sessionStorage.getItem("scholarmate-port");
    const token = sessionStorage.getItem("scholarmate-token");
    if (port && token) connection = { port: Number(port), token };
  }
  if (!connection)
    throw new Error("浏览器预览需要连接本地后端。请填写启动信息。");
}
export function connectPreview(port: string, token: string) {
  sessionStorage.setItem("scholarmate-port", port);
  sessionStorage.setItem("scholarmate-token", token);
  location.reload();
}
async function request(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
) {
  if (!connection) throw new Error("后端未连接，请重启应用。");
  try {
    const response = await fetch(`http://127.0.0.1:${connection.port}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${connection.token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: signal ?? AbortSignal.timeout(180000),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "输入不符合要求，请检查字段。",
      );
    }
    return response;
  } catch (e) {
    if (e instanceof TypeError)
      throw new Error("无法连接本地服务，请检查应用是否正常运行。");
    if (e instanceof DOMException && e.name === "TimeoutError")
      throw new Error("请求超时，请稍后重试。");
    throw e;
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return (await request(path, method, body, signal)).json();
}
/** An authenticated file as an object URL, for images shown in the conversation. */
export async function blobUrl(path: string) {
  return URL.createObjectURL(await (await request(path)).blob());
}
export async function readBase64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}
export async function selectPDFPaths(): Promise<string[]> {
  if (isTauri()) return invoke<string[]>("select_pdfs");
  const path = window.prompt(
    "浏览器预览：输入本机 PDF 的完整路径（仅关联，不复制）",
  );
  return path?.trim() ? [path.trim().replace(/^"|"$/g, "")] : [];
}
export async function selectFolder(): Promise<string> {
  if (isTauri()) return (await invoke<string | null>("select_folder")) || "";
  return (
    window.prompt("浏览器预览：输入文件夹的完整路径（例如 E:\\ScholarMate）")?.trim() ||
    ""
  );
}
export function pdfSource(id: string) {
  if (!connection) throw new Error("后端未连接");
  return {
    url: `http://127.0.0.1:${connection.port}/paper/file?id=${encodeURIComponent(id)}`,
    httpHeaders: { Authorization: `Bearer ${connection.token}` },
  };
}
export async function stream(
  path: string,
  body: unknown,
  onEvent: (data: Record<string, unknown>) => void,
  signal?: AbortSignal,
) {
  const response = await request(
    path,
    "POST",
    body,
    signal ?? AbortSignal.timeout(300000),
  );
  const reader = response.body?.getReader();
  if (!reader) throw new Error("当前环境不支持流式响应。");
  const decoder = new TextDecoder();
  let buffer = "",
    done = false;
  try {
    while (true) {
      const next = await reader.read();
      buffer = (
        buffer + decoder.decode(next.value, { stream: !next.done })
      ).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const raw = frame
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trim())
          .join("\n");
        if (raw) {
          const data = JSON.parse(raw);
          if (data.error) throw new Error(data.error);
          if (data.done) done = true;
          onEvent(data);
        }
      }
      if (next.done) break;
    }
    if (!done) throw new Error("连接已中断，操作未完成，请重试。");
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError")
      throw new Error("等待回复超时，请稍后重试。");
    if (e instanceof TypeError)
      throw new Error("连接已中断，请检查本地服务后重试。");
    throw e;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export async function download(path: string, name: string) {
  const data = await (await request(path)).arrayBuffer();
  if (isTauri()) {
    await invoke("save_export", {
      name,
      bytes: Array.from(new Uint8Array(data)),
    });
    return;
  }
  const url = URL.createObjectURL(new Blob([data]));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

