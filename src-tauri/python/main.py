import asyncio
import base64
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import ai
import attachments
import db
import discovery
import library
import papers
import paths
import schedule
import uvicorn
from exports import export_markdown, export_pdf
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from plan_detection import decorate_message, detect_plan
from pydantic import BaseModel, Field
from security import get_key, save_key
from starlette.concurrency import run_in_threadpool

TOKEN = os.environ.get("SCHOLARMATE_TOKEN") or secrets.token_urlsafe(32)


def authorize(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, "Bearer " + TOKEN):
        raise HTTPException(401, "本地会话已失效，请重启应用。")


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(
    title="ScholarMate local API",
    lifespan=lifespan,
    dependencies=[Depends(authorize)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(schedule.router)
app.include_router(library.router)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "本地操作失败，请检查文件权限、磁盘空间后重试。"},
    )


class Settings(BaseModel):
    model: str = Field(default="deepseek-chat", min_length=1, max_length=100, pattern=r"^\S+$")
    api_key: str | None = Field(default=None, max_length=512)
    # Whether the configured model accepts images as well as text.
    vision: bool | None = None


class StorageLocation(BaseModel):
    data_dir: str = Field(default="", max_length=4000)
    download_dir: str = Field(default="", max_length=4000)
    reset: list[Literal["data_dir", "download_dir"]] = Field(default_factory=list)


def folder_size(path):
    total = 0
    if Path(path).is_dir():
        for item in Path(path).rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    return total


def storage_state():
    folder = Path(db.DATA_DIR)
    saved = paths.location()
    return {
        "data_dir": str(folder),
        "default_data_dir": str(paths.default_data_dir()),
        "data_dir_custom": bool(saved.get("data_dir")),
        "data_dir_bytes": folder_size(folder),
        "download_dir": str(paths.download_dir()),
        "default_download_dir": str(paths.default_download_dir()),
        "download_dir_custom": bool(saved.get("download_dir")),
        "system_drive": paths.system_drive(),
    }


def absolute_folder(value):
    target = Path(value).expanduser()
    if not target.is_absolute():
        raise HTTPException(422, "请填写完整路径（例如 E:\\ScholarMate）。")
    return target.resolve()


def move_storage(target: Path):
    """Copy the database and the app-owned folders to `target`, then switch over.

    The copy is verified before anything is deleted, so a failed move leaves the
    original data untouched.
    """
    current = Path(db.DATA_DIR).resolve()
    if target == current:
        return 0
    if current in target.parents or target in current.parents:
        raise HTTPException(422, "新目录不能是当前数据目录的父目录或子目录。")
    if target.exists() and any(target.iterdir()):
        raise HTTPException(409, "请选择一个空文件夹，或先清空该文件夹后重试。")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(422, "无法创建该文件夹，请检查路径、盘符和权限。") from None
    with db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    copied = []
    folders = []
    try:
        for name in ("scholarmate.db", "scholarmate.db-wal", "scholarmate.db-shm"):
            source = current / name
            if source.is_file():
                shutil.copy2(source, target / name)
                copied.append((source, target / name))
        for name in ("papers", "uploads"):
            source = current / name
            size = folder_size(source)
            if source.is_dir():
                shutil.copytree(source, target / name, dirs_exist_ok=True)
                folders.append((source, target / name, size))
        for source, copy in copied:
            if not copy.is_file() or copy.stat().st_size != source.stat().st_size:
                raise OSError("size mismatch")
        for _, copy, size in folders:
            if size and folder_size(copy) != size:
                raise OSError("size mismatch")
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(
            502, "复制数据失败，原数据未改动。请检查目标磁盘空间与权限。"
        ) from None
    freed = folder_size(current)
    for source, _ in copied:
        source.unlink(missing_ok=True)
    for source, _, _ in folders:
        shutil.rmtree(source, ignore_errors=True)
    db.DATA_DIR = target
    # Only the files inside the app-owned folders moved; every other recorded path
    # still points where the user keeps it. Paths are compared after resolution
    # because the configured form may be a short or relative name.
    roots = {name: (current / name).resolve() for name in ("papers", "uploads")}
    with db.connect() as conn:
        for row in conn.execute(
            "SELECT id,local_path FROM papers WHERE local_path IS NOT NULL"
        ).fetchall():
            moved = rebase(row["local_path"], roots["papers"], target / "papers")
            if moved:
                conn.execute(
                    "UPDATE papers SET local_path=? WHERE id=?", (moved, row["id"])
                )
        for row in conn.execute("SELECT id,path,text_path FROM attachments").fetchall():
            values = [
                rebase(row[column], roots["uploads"], target / "uploads")
                for column in ("path", "text_path")
            ]
            if any(values):
                current_values = (row["path"], row["text_path"])
                conn.execute(
                    "UPDATE attachments SET path=?,text_path=? WHERE id=?",
                    tuple(
                        new or old for new, old in zip(values, current_values)
                    )
                    + (row["id"],),
                )
    try:
        current.rmdir()
    except OSError:
        pass  # Leftover empty folders are the user's business.
    return freed


def rebase(value, old_root, new_root):
    """Return the new path for a record inside a moved folder, else ''."""
    if not value:
        return ""
    try:
        resolved = Path(value).resolve()
    except OSError:
        return ""
    if not resolved.is_relative_to(old_root):
        return ""
    return str(new_root / resolved.relative_to(old_root))


@app.get("/settings/storage")
def read_storage():
    return storage_state()


@app.put("/settings/storage")
def save_storage(body: StorageLocation):
    freed = 0
    if body.data_dir.strip():
        freed = move_storage(absolute_folder(body.data_dir))
        paths.write_location(data_dir=str(Path(db.DATA_DIR).resolve()))
    elif "data_dir" in body.reset:
        freed = move_storage(paths.default_data_dir().resolve())
        paths.write_location(data_dir="")
    if body.download_dir.strip():
        paths.write_location(download_dir=str(absolute_folder(body.download_dir)))
    elif "download_dir" in body.reset:
        paths.write_location(download_dir="")
    return {**storage_state(), "freed_bytes": freed}


class Profile(BaseModel):
    # Only the name is required: a profile may be created empty and filled in
    # later, which is what the "新建画像" button does. The onboarding form still
    # asks for 专业 and 研究领域, and the AI treats missing fields as 未填写.
    major: str = Field(default="", max_length=200)
    degree: Literal["本科", "硕士", "博士", "博士后", "其他"] = "硕士"
    research_field: str = Field(default="", max_length=500)
    specific_interests: list[str] = Field(default_factory=list, max_length=30)
    short_term_goal: str = Field(default="", max_length=2000)
    long_term_goal: str = Field(default="", max_length=2000)
    weekly_hours: int = Field(default=8, ge=1, le=168)
    language_preference: str = Field(default="中文", max_length=100)
    custom_instructions: str = Field(default="", max_length=4000)


@app.get("/status")
def status():
    error = None
    try:
        has_key = bool(get_key())
    except HTTPException as e:
        has_key, error = False, e.detail
    settings_row = db.rows("SELECT * FROM settings")[0]
    active = db.profile()
    return {
        "has_key": has_key,
        "has_profile": bool(active),
        "model": settings_row["model"],
        "vision": bool(settings_row.get("vision")),
        "profile_id": (active or {}).get("id", ""),
        "profile_name": (active or {}).get("name", ""),
        "profile_count": len(db.profiles()),
        "credential_error": error,
    }


def looks_multimodal(model):
    name = str(model or "").casefold()
    return any(token in name for token in ("vision", "-vl", "vl-", "omni", "gpt-4o", "gpt-4.1", "gemini", "qwen-vl", "claude-3", "claude-4"))


@app.put("/settings")
def settings(body: Settings):
    if body.api_key and body.api_key.strip():
        save_key(body.api_key.strip())
    db.execute("UPDATE settings SET model=? WHERE id=1", (body.model,))
    # An explicit choice wins; otherwise follow the model name so images are not
    # silently dropped (or silently sent to a text-only model).
    db.execute(
        "UPDATE settings SET vision=? WHERE id=1",
        (int(body.vision) if body.vision is not None else int(looks_multimodal(body.model)),),
    )
    return {"ok": True}


@app.post("/settings/test")
async def test_connection(body: Settings):
    # Real completion tests model access as well as key validity.
    async for _ in ai.stream_ai(
        "chat", "只回复 OK", {"connection_test": True}, key=body.api_key or None, model=body.model
    ):
        pass
    return {"ok": True, "message": "连接成功，模型可用。"}


@app.get("/profile")
def read_profile():
    return db.profile()


class ProfileUpdate(Profile):
    name: str = Field(default="", max_length=80)


def profile_values(body, existing=None):
    data = body.model_dump()
    data["specific_interests"] = json.dumps(data["specific_interests"], ensure_ascii=False)
    if not data["name"].strip():
        data["name"] = (
            (existing or {}).get("name")
            or data["research_field"].strip()
            or data["major"].strip()
            or "我的画像"
        )[:80]
    return data


def next_profile_name():
    used = {p["name"] for p in db.profiles()}
    index = len(used) + 1
    while f"画像 {index}" in used:
        index += 1
    return f"画像 {index}"


@app.put("/profile")
def save_profile(body: ProfileUpdate):
    """Update the active profile; this is the endpoint older clients use."""
    id = db.active_profile_id()
    if not id:
        return create_profile(body)
    return update_profile(id, body)


@app.get("/profiles")
def list_profiles():
    active = db.active_profile_id()
    # Newest first: a just-created profile is the one the user is looking at.
    return {
        "items": [
            {**db.parse_profile(p), "active": p["id"] == active}
            for p in db.profiles(newest_first=True)
        ],
        "active_id": active,
    }


@app.post("/profiles")
def create_profile(body: ProfileUpdate):
    values = profile_values(body)
    if values["name"] == "我的画像" and not values["research_field"] and not values["major"]:
        # A brand-new empty profile gets a distinguishable default name.
        values["name"] = next_profile_name()
    id = db.new_id("pf-")
    db.execute(
        "INSERT INTO profiles(id,"
        + ",".join(db.PROFILE_FIELDS)
        + ") VALUES(?,"
        + ",".join("?" for _ in db.PROFILE_FIELDS)
        + ")",
        (id, *(values[field] for field in db.PROFILE_FIELDS)),
    )
    db.set_active_profile(id)
    return {**db.profile(id), "active": True}


@app.put("/profiles/{id}")
def update_profile(id: str, body: ProfileUpdate):
    existing = db.profile(id)
    if not existing:
        raise HTTPException(404, "画像不存在。")
    values = profile_values(body, existing)
    db.execute(
        "UPDATE profiles SET "
        + ",".join(field + "=?" for field in db.PROFILE_FIELDS)
        + ",updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (*(values[field] for field in db.PROFILE_FIELDS), id),
    )
    return {**db.profile(id), "active": db.active_profile_id() == id}


@app.post("/profiles/{id}/activate")
def activate_profile(id: str):
    if not db.profile(id):
        raise HTTPException(404, "画像不存在。")
    db.set_active_profile(id)
    return {**db.profile(id), "active": True}


@app.delete("/profiles/{id}")
def delete_profile(id: str):
    if not db.profile(id):
        raise HTTPException(404, "画像不存在。")
    if len(db.profiles()) <= 1:
        raise HTTPException(409, "至少需要保留一个画像。")
    db.execute("DELETE FROM profiles WHERE id=?", (id,))
    active = db.active_profile_id()
    # Conversations keep working: they fall back to the profile that is now active.
    db.execute("UPDATE chat_threads SET profile_id=? WHERE profile_id=?", (active, id))
    db.execute("UPDATE conversations SET profile_id=? WHERE profile_id=?", (active, id))
    return {"ok": True, "active_id": active}


def sse(data):
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


chat_lock = asyncio.Lock()


class Chat(BaseModel):
    # A message may consist of attachments alone, so the text may be empty.
    message: str = Field(default="", max_length=16000)
    attachments: list[str] = Field(default_factory=list, max_length=8)
    thread_id: str = Field(default="", max_length=100)


class Upload(BaseModel):
    filename: str = Field(min_length=1, max_length=1000)
    data: str = Field(max_length=40_000_000)


@app.post("/chat/upload")
def upload(body: Upload):
    try:
        content = base64.b64decode(body.data, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "文件编码无效，请重新选择。") from None
    return attachments.store(body.filename, content)


@app.get("/chat/attachments")
def list_attachments():
    return attachments.recent(30)


@app.get("/chat/attachment")
def read_attachment(id: str):
    row = attachments.get(id)
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(404, "附件文件已移动或删除。")
    return FileResponse(
        path,
        media_type=row["media_type"] or "application/octet-stream",
        filename=row["name"],
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )


@app.delete("/chat/attachment")
def delete_attachment(id: str):
    return attachments.remove(id)


def attachment_payload(ids):
    """Validate ids and split them into stored rows, inlined documents and images."""
    rows, documents, images = [], [], []
    for value in ids[:8]:
        row = attachments.get(value)
        if not Path(row["path"]).is_file():
            raise HTTPException(404, f"附件 {row['name']} 的文件已丢失，请重新上传。")
        rows.append(row)
        if row["kind"] == "image":
            images.append(row)
        else:
            documents.append(attachments.inline_excerpt(row["id"]))
    return rows, documents, images


def message_rows(thread_id=None):
    if thread_id:
        return db.rows(
            "SELECT * FROM conversations WHERE thread_id=? ORDER BY created_at,rowid",
            (thread_id,),
        )
    return db.rows("SELECT * FROM conversations ORDER BY created_at,rowid")


def history(thread_id=None):
    adopted = {
        p["source_message_id"]: p["id"]
        for p in db.rows(
            "SELECT id,source_message_id FROM learning_plans WHERE source_message_id IS NOT NULL"
        )
    }
    result = []
    for message in message_rows(thread_id):
        ids = json.loads(message.get("attachments") or "[]")
        metas = []
        for value in ids:
            found = db.rows("SELECT * FROM attachments WHERE id=?", (value,))
            if found:
                metas.append(attachments.public(found[0]))
        result.append(
            decorate_message({**message, "attachments": metas}, adopted.get(message["id"]))
        )
    return result


@app.get("/conversations")
def all_conversations():
    return history()


def thread_title(text):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:24] if clean else "新对话"


def thread_summary(row):
    # The topic of a conversation is its latest question, not the last reply.
    last = db.rows(
        "SELECT content FROM conversations WHERE thread_id=? AND role='user' "
        "ORDER BY created_at DESC,rowid DESC LIMIT 1",
        (row["id"],),
    )
    count = db.rows(
        "SELECT count(*) AS n FROM conversations WHERE thread_id=?", (row["id"],)
    )[0]["n"]
    profile = db.profile(row["profile_id"]) if row["profile_id"] else None
    return {
        "id": row["id"],
        "title": row["title"] or "新对话",
        "profile_id": row["profile_id"],
        "profile_name": (profile or {}).get("name", ""),
        "message_count": count,
        "preview": (last[0]["content"][:80] if last else ""),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def find_thread(id):
    found = db.rows("SELECT * FROM chat_threads WHERE id=?", (str(id or ""),))
    return found[0] if found else None


class Thread(BaseModel):
    title: str = Field(default="", max_length=120)
    profile_id: str = Field(default="", max_length=100)


@app.get("/threads")
def list_threads():
    return [
        thread_summary(row)
        for row in db.rows(
            "SELECT * FROM chat_threads ORDER BY updated_at DESC, rowid DESC"
        )
    ]


@app.post("/threads")
def create_thread(body: Thread):
    # An empty id means "use the active profile"; db.profile() would silently
    # fall back to it and store nothing, so test the id first.
    profile_id = (
        body.profile_id
        if body.profile_id and db.profile(body.profile_id)
        else db.active_profile_id()
    )
    id = db.new_id("th-")
    db.execute(
        "INSERT INTO chat_threads(id,title,profile_id) VALUES(?,?,?)",
        (id, body.title.strip() or "新对话", profile_id),
    )
    return thread_summary(find_thread(id))


@app.get("/threads/{id}")
def read_thread(id: str):
    thread = find_thread(id)
    if not thread:
        raise HTTPException(404, "对话不存在或已被删除。")
    return {"thread": thread_summary(thread), "messages": history(id)}


@app.put("/threads/{id}")
def update_thread(id: str, body: Thread):
    thread = find_thread(id)
    if not thread:
        raise HTTPException(404, "对话不存在或已被删除。")
    title = body.title.strip() or thread["title"]
    profile_id = thread["profile_id"]
    if body.profile_id:
        if not db.profile(body.profile_id):
            raise HTTPException(404, "画像不存在。")
        profile_id = body.profile_id
    db.execute(
        "UPDATE chat_threads SET title=?,profile_id=? WHERE id=?", (title, profile_id, id)
    )
    return thread_summary(find_thread(id))


@app.delete("/threads/{id}")
async def delete_thread(id: str):
    if not find_thread(id):
        raise HTTPException(404, "对话不存在或已被删除。")
    if chat_lock.locked():
        raise HTTPException(409, "请等待当前回复结束后再删除对话。")
    with db.connect() as conn:
        conn.execute("DELETE FROM conversations WHERE thread_id=?", (id,))
        conn.execute("DELETE FROM chat_threads WHERE id=?", (id,))
    return {"ok": True}


@app.get("/threads/{id}/export")
def export_thread(id: str):
    thread = find_thread(id)
    if not thread:
        raise HTTPException(404, "对话不存在或已被删除。")
    content = "\n\n".join(
        "## "
        + ("你" if m["role"] == "user" else "ScholarMate")
        + "\n\n"
        + m["content"]
        + "".join("\n\n> 附件：" + a["name"] for a in m.get("attachments") or [])
        for m in history(id)
    )
    title = thread["title"] or "学术对话"
    return Response(
        export_markdown(title, content or "（这条对话还没有消息。）"),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/conversations/plan-candidates")
def plan_candidates():
    return [
        m
        for m in history()
        if m["plan_candidate"] and not m["adopted_plan_id"] and not m.get("plan_rejected")
    ]


class Rejection(BaseModel):
    rejected: bool = True


@app.put("/conversations/{id}/proposal")
def reject_proposal(id: str, body: Rejection):
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT id FROM learning_plans WHERE source_message_id=?", (id,)
        ).fetchone():
            raise HTTPException(409, "此计划已采纳，请在学习计划中管理或删除。")
        if not conn.execute(
            "UPDATE conversations SET plan_rejected=? WHERE id=? AND role='assistant'",
            (int(body.rejected), id),
        ).rowcount:
            raise HTTPException(404, "回复不存在。")
    return {"ok": True}


@app.delete("/conversations")
async def clear_history():
    if chat_lock.locked():
        raise HTTPException(409, "请等待当前回复结束后清空历史。")
    with db.connect() as conn:
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM chat_threads")
    return {"ok": True}


@app.get("/conversations/export")
def export_history():
    content = "\n\n".join(
        "## "
        + ("你" if m["role"] == "user" else "ScholarMate")
        + "\n\n"
        + m["content"]
        + "".join("\n\n> 附件：" + a["name"] for a in m.get("attachments") or [])
        for m in history()
    )
    return Response(
        export_markdown("ScholarMate 对话", content),
        media_type="text/markdown; charset=utf-8",
    )


@app.post("/chat")
async def chat(body: Chat):
    if not body.message.strip() and not body.attachments:
        raise HTTPException(422, "请输入内容或上传文件后再发送。")
    if chat_lock.locked():
        raise HTTPException(409, "已有对话正在生成，请稍候。")
    rows, documents, images = attachment_payload(body.attachments)
    vision = bool(db.rows("SELECT vision FROM settings")[0]["vision"])
    # Every message belongs to a conversation; the first one creates it.
    thread = find_thread(body.thread_id)
    if body.thread_id and not thread:
        raise HTTPException(404, "这条对话已被删除，请新建一个对话。")
    if thread:
        thread_id = thread["id"]
        profile_id = thread["profile_id"] or db.active_profile_id()
        title = thread["title"] if thread["title"] not in ("", "新对话") else thread_title(body.message)
    else:
        profile_id = db.active_profile_id()
        title = thread_title(body.message)
        thread_id = db.new_id("th-")
        thread = {
            "id": thread_id,
            "title": title,
            "profile_id": profile_id,
            "created_at": "",
            "updated_at": "",
        }
    profile = db.profile(profile_id) or db.profile()
    await chat_lock.acquire()

    async def generate():
        answer = ""
        try:
            context = {
                "profile": profile,
                "thread_id": thread_id,
                "documents": documents,
                "images": [
                    {
                        "name": row["name"],
                        "media_type": row["media_type"],
                        "path": row["path"],
                    }
                    for row in images
                ]
                if vision
                else [],
                "unseen_images": [row["name"] for row in images] if not vision else [],
            }
            async for part in ai.stream_ai("chat", body.message, context):
                answer += part
                yield sse({"delta": part})
            if not answer.strip():
                raise HTTPException(502, "模型返回空回复，请重试。")
            # A very long answer may still end at the single-response ceiling after
            # the automatic continuations: keep it and say so instead of failing.
            truncated = bool(context.get("truncated"))
            if truncated:
                answer += ai.TRUNCATED_NOTE
                yield sse({"delta": ai.TRUNCATED_NOTE})
            user_id, assistant_id = uuid.uuid4().hex, uuid.uuid4().hex
            stored = json.dumps([row["id"] for row in rows], ensure_ascii=False)
            with db.connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_threads(id,title,profile_id) VALUES(?,?,?)",
                    (thread_id, title, profile_id),
                )
                conn.execute(
                    "UPDATE chat_threads SET title=?,profile_id=?,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (title, profile_id, thread_id),
                )
                conn.execute(
                    "INSERT INTO conversations(id,role,content,attachments,thread_id,profile_id) "
                    "VALUES(?,?,?,?,?,?)",
                    (user_id, "user", body.message.strip(), stored, thread_id, profile_id),
                )
                conn.execute(
                    "INSERT INTO conversations(id,role,content,thread_id,profile_id) "
                    "VALUES(?,?,?,?,?)",
                    (assistant_id, "assistant", answer, thread_id, profile_id),
                )
            metas = [attachments.public(row) for row in rows]
            yield sse(
                {
                    "done": True,
                    "thread": thread_summary(find_thread(thread_id)),
                    "truncated": truncated,
                    "continuations": context.get("continuations", 0),
                    "messages": [
                        decorate_message(
                            {
                                "id": user_id,
                                "role": "user",
                                "content": body.message.strip(),
                                "attachments": metas,
                            }
                        ),
                        decorate_message(
                            {"id": assistant_id, "role": "assistant", "content": answer}
                        ),
                    ],
                }
            )
        except HTTPException as e:
            yield sse({"error": e.detail})
        except Exception:
            yield sse({"error": "对话未保存，请重试。"})
        finally:
            chat_lock.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


class Plan(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(default="", max_length=4000)
    plan_content: str = Field(min_length=1, max_length=200000)
    status: Literal["进行中", "已完成", "已放弃"] = "进行中"


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    period: str = Field(min_length=1, max_length=100)


@app.post("/plans/generate")
async def generate_plan(body: PlanRequest):
    return {"content": await ai.call_ai("plan", body.goal, {"period": body.period})}


@app.get("/plans")
def plans_list():
    return db.rows("SELECT * FROM learning_plans ORDER BY created_at DESC,rowid DESC")


class Adoption(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)


@app.post("/plans/adopt")
def adopt_plan(body: Adoption):
    # One transaction + unique index makes repeated clicks idempotent.
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM learning_plans WHERE source_message_id=?", (body.message_id,)
        ).fetchone()
        if existing:
            return dict(existing)
        message = conn.execute(
            "SELECT * FROM conversations WHERE id=? AND role='assistant'", (body.message_id,)
        ).fetchone()
        candidate = detect_plan(message["content"]) if message else None
        if not candidate:
            raise HTTPException(
                422, "这条回复中未识别到完整学习计划，请让助手生成包含阶段与行动的学习计划。"
            )
        if message["plan_rejected"]:
            raise HTTPException(409, "此计划已拒绝，请先恢复候选计划。")
        id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO learning_plans(id,title,goal,plan_content,source_message_id,source_content,start_date) VALUES(?,?,?,?,?,?,?)",
            (
                id,
                candidate["title"],
                candidate["goal"],
                candidate["plan_content"],
                body.message_id,
                message["content"],
                schedule.monday().isoformat(),
            ),
        )
        schedule.sync_tasks(conn, id, candidate["plan_content"])
        return dict(conn.execute("SELECT * FROM learning_plans WHERE id=?", (id,)).fetchone())


def require_row(table, id):
    if table not in ("papers", "learning_plans"):
        raise ValueError("invalid table")
    result = db.rows(f"SELECT * FROM {table} WHERE id=?", (id,))
    if not result:
        raise HTTPException(404, "记录不存在或已被删除。")
    return result[0]


@app.post("/plans")
def create_plan(body: Plan):
    id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO learning_plans(id,title,goal,plan_content,status,start_date) VALUES(?,?,?,?,?,?)",
        (id, body.title, body.goal, body.plan_content, body.status, schedule.monday().isoformat()),
    )
    return require_row("learning_plans", id)


@app.get("/plans/{id}")
def get_plan(id: str):
    return require_row("learning_plans", id)


@app.put("/plans/{id}")
def update_plan(id: str, body: Plan):
    require_row("learning_plans", id)
    db.execute(
        "UPDATE learning_plans SET title=?,goal=?,plan_content=?,status=? WHERE id=?",
        (body.title, body.goal, body.plan_content, body.status, id),
    )
    return require_row("learning_plans", id)


@app.delete("/plans/{id}")
def delete_plan(id: str):
    p = require_row("learning_plans", id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE conversations SET plan_rejected=1 WHERE id=?", (p["source_message_id"],)
        )
        conn.execute("DELETE FROM plan_tasks WHERE plan_id=?", (id,))
        conn.execute("DELETE FROM learning_plans WHERE id=?", (id,))
    return {"ok": True}


@app.get("/plans/{id}/export")
def export_plan(id: str, format: Literal["md", "pdf"] = "md"):
    p = require_row("learning_plans", id)
    content = (
        export_pdf(p["title"], p["plan_content"])
        if format == "pdf"
        else export_markdown(p["title"], p["plan_content"])
    )
    return Response(
        content,
        media_type="application/pdf" if format == "pdf" else "text/markdown; charset=utf-8",
    )


@app.get("/papers/search")
async def search(keyword: str, max_results: int = 20):
    if not 1 <= len(keyword.strip()) <= 300 or not 1 <= max_results <= 50:
        raise HTTPException(422, "请输入 1–300 字关键词，结果数量范围为 1–50。")
    result = await papers.search_papers(keyword, max_results)
    local = {p["id"]: p for p in db.rows("SELECT * FROM papers")}
    return [
        {
            **p,
            "downloaded": bool(
                local.get(p["id"], {}).get("local_path")
                and Path(local[p["id"]]["local_path"]).is_file()
            ),
        }
        for p in result
    ]


@app.get("/discovery/search")
async def discover(keyword: str, source: str = "all", max_results: int = 20):
    if not 1 <= len(keyword.strip()) <= 300 or not 1 <= max_results <= 50:
        raise HTTPException(422, "请输入 1–300 字关键词。")
    result = await discovery.search(keyword, source, max_results)
    local = library.visible_papers()
    ids = {p["id"] for p in local}
    dois = {p["doi"].lower() for p in local if p["doi"]}
    result["items"] = [
        {**p, "downloaded": p["id"] in ids or bool(p.get("doi") and p["doi"].lower() in dois)}
        for p in result["items"]
    ]
    return result


@app.get("/papers")
def local_papers(q: str = ""):
    return library.visible_papers(q)


class Paper(BaseModel):
    id: str = Field(max_length=100)
    title: str = Field(min_length=1, max_length=2000)
    authors: str = Field(max_length=10000)
    abstract: str = Field(max_length=30000)
    published: str = Field(max_length=100)
    directory: str = Field(default="", max_length=2000)
    source: Literal["arxiv", "crossref", "europepmc"] = "arxiv"
    pdf_url: str = Field(default="", max_length=4000)
    doi: str = Field(default="", max_length=300)
    venue: str = Field(default="", max_length=1000)
    volume: str = Field(default="", max_length=100)
    issue: str = Field(default="", max_length=100)
    pages: str = Field(default="", max_length=100)
    publisher: str = Field(default="", max_length=1000)
    publication_type: str = Field(default="preprint", max_length=50)
    landing_url: str = Field(default="", max_length=4000)


downloads = set()


@app.post("/papers/download")
async def download(body: Paper):
    if body.source == "arxiv":
        papers.valid_id(body.id)
    else:
        discovery.validate_pdf(body.pdf_url)
    if body.id in downloads:
        raise HTTPException(409, "这篇论文正在下载。")
    downloads.add(body.id)

    async def generate():
        try:
            args = (
                (body.id, body.directory)
                if body.source == "arxiv"
                else (body.id, body.directory, body.pdf_url)
            )
            async for progress in papers.download_pdf(*args):
                if progress.get("path"):
                    db.execute(
                        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET local_path=excluded.local_path,downloaded_at=excluded.downloaded_at",
                        (
                            body.id,
                            body.title,
                            body.authors,
                            body.abstract,
                            "https://arxiv.org/pdf/" + body.id
                            if body.source == "arxiv"
                            else body.pdf_url,
                            body.published,
                            progress["path"],
                        ),
                    )
                    db.execute(
                        "UPDATE papers SET source=?,doi=?,venue=?,volume=?,issue=?,pages=?,publisher=?,publication_type=?,landing_url=? WHERE id=?",
                        (
                            body.source,
                            body.doi,
                            body.venue,
                            body.volume,
                            body.issue,
                            body.pages,
                            body.publisher,
                            body.publication_type,
                            body.landing_url,
                            body.id,
                        ),
                    )
                yield sse(progress)
            yield sse({"done": True})
        except HTTPException as e:
            yield sse({"error": e.detail})
        except OSError:
            yield sse({"error": "文件无法保存，请检查目录权限和磁盘空间。"})
        except Exception:
            yield sse({"error": "下载或记录保存失败，请检查本地文件后重试。"})
        finally:
            downloads.discard(body.id)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/paper")
def paper_detail(id: str):
    return require_row("papers", id)


@app.delete("/paper")
def delete_paper(id: str, remove_record: bool = True):
    p = require_row("papers", id)
    if id in downloads:
        raise HTTPException(409, "下载进行中，暂时无法删除。")
    if p["local_path"] and p.get("storage_mode") != "linked":
        Path(p["local_path"]).unlink(missing_ok=True)
    if remove_record:
        db.execute("DELETE FROM papers WHERE id=?", (id,))
    else:
        db.execute("UPDATE papers SET local_path=NULL WHERE id=?", (id,))
    return {"ok": True}


@app.get("/paper/text")
def paper_text(id: str):
    return {"text": papers.extract_text(require_row("papers", id)["local_path"])}


@app.post("/paper/summarize")
async def summarize(id: str, scope: Literal["excerpt", "full"] = "excerpt"):
    """`excerpt` reads the opening and the closing pages; `full` digests the whole text."""
    paper = require_row("papers", id)
    text = await run_in_threadpool(papers.extract_text, paper["local_path"])
    characters = len(text)
    chunks = 0
    if scope == "full":
        sections = papers.digest_chunks(text, ai.DIGEST_BUDGET, ai.DIGEST_LIMIT)
        chunks = len(sections)
        digests = []
        for index, section in enumerate(sections, start=1):
            digests.append(
                await ai.call_ai(
                    "digest",
                    f"（全文第 {index}/{chunks} 段）\n{section}",
                    {"isolated": True},
                )
            )
        summary = await ai.call_ai(
            "summarize",
            "下面是把这篇论文全文分段精读后得到的要点"
            + (f"（覆盖全文 {characters} 字，划分为 {chunks} 段）" if chunks > 1 else "")
            + "，请据此写出总结：\n\n"
            + "\n\n".join(digests),
            {"isolated": True},
        )
        note = f"全文分段精读（{chunks} 段，共 {characters} 字）"
    else:
        excerpt, truncated = papers.summary_excerpt(text, papers.SUMMARY_BUDGET)
        summary = await ai.call_ai("summarize", excerpt, {"excerpt": truncated})
        note = (
            f"开头与结尾节选（全文 {characters} 字）"
            if truncated
            else f"全文（{characters} 字，未超出节选预算）"
        )
    db.execute(
        "UPDATE papers SET summary=?,summary_scope=?,summary_characters=? WHERE id=?",
        (summary, scope, characters, id),
    )
    return {
        "summary": summary,
        "scope": scope,
        "note": note,
        "characters": characters,
        "chunks": chunks,
    }


class Translation(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@app.post("/paper/translate")
async def translate(body: Translation):
    return {"translation": await ai.call_ai("translate", body.text)}


@app.post("/paper/folder")
def open_folder(id: str):
    path = require_row("papers", id)["local_path"]
    if not path or not Path(path).parent.is_dir():
        raise HTTPException(404, "本地目录不存在。")
    folder = str(Path(path).resolve().parent)
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    return {"ok": True}


if __name__ == "__main__":
    # Bind first, then publish port: eliminates free-port races.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    print(json.dumps({"port": sock.getsockname()[1], "token": TOKEN}), flush=True)
    if os.environ.get("SCHOLARMATE_PARENT"):

        def watch_parent():
            sys.stdin.buffer.read()
            os._exit(0)

        threading.Thread(target=watch_parent, daemon=True).start()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", log_level="warning", access_log=False)
    )
    server.run(sockets=[sock])

