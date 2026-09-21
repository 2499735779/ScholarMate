const KEY = "scholarmate-chat-draft";
const PENDING = "scholarmate-chat-pending";
let value = localStorage.getItem(KEY) || localStorage.getItem(PENDING) || "";
const listeners = new Set<() => void>();
let sendVersion = 0;
export const getDraft = () => value;
export function subscribeDraft(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function setDraft(text: string) {
  value = text;
  localStorage.setItem(KEY, text);
  listeners.forEach((fn) => fn());
}
export function beginSend(text: string) {
  localStorage.setItem(PENDING, text);
  setDraft("");
  return ++sendVersion;
}
export function finishSend(version = sendVersion) {
  if (version !== sendVersion) return;
  localStorage.removeItem(PENDING);
}
export function recoverSend(text: string, version = sendVersion) {
  if (version !== sendVersion) return;
  if (!value) setDraft(text);
  finishSend(version);
}

