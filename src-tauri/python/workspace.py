"""Read-only access to all saved plans, paper metadata, summaries, PDF text and uploads."""

import json
from pathlib import Path

import db
from fastapi import HTTPException
from papers import extract_text

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_workspace",
            "description": "读取用户本地学习计划、文献及上传的文档附件。list 分页浏览，search 搜索全部记录；plan 读取计划正文；paper 读取文献元数据摘要总结；pdf 按字符偏移读取本地 PDF 全文；attachment 按字符偏移读取用户上传文档的提取文字。只读，无写入功能。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "search", "plan", "paper", "pdf", "attachment"],
                    },
                    "kind": {"type": "string", "enum": ["plans", "papers"]},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    }
]


def snapshot():
    # Include complete small workspaces; large workspaces remain reachable by tools.
    plans = db.rows(
        "SELECT id,title,goal,status,start_date,paused_on,plan_content FROM learning_plans ORDER BY created_at DESC"
    )
    papers = db.rows(
        "SELECT id,title,title_zh,category,tags,authors,abstract,summary,published,pdf_url FROM papers ORDER BY downloaded_at DESC"
    )
    files = db.rows(
        "SELECT id,name,kind,media_type,bytes,characters,created_at FROM attachments ORDER BY created_at DESC, rowid DESC LIMIT 10"
    )
    result = {
        "plan_count": len(plans),
        "paper_count": len(papers),
        "attachment_count": len(files),
        "plans": [],
        "papers": [],
        "attachments": files,
        "incomplete": False,
    }
    for plan in plans:
        plan["tasks"] = db.rows(
            "SELECT week,title,done FROM plan_tasks WHERE plan_id=? ORDER BY week", (plan["id"],)
        )
    budget = 30000
    for key, items in [("plans", plans), ("papers", papers)]:
        for item in items:
            size = len(json.dumps(item, ensure_ascii=False))
            if size <= budget:
                result[key].append(item)
                budget -= size
            else:
                result["incomplete"] = True
    return json.dumps(result, ensure_ascii=False)


def read_workspace(arguments):
    if not isinstance(arguments, dict):
        return {"error": "参数必须为对象"}
    action = arguments.get("action")
    offset = arguments.get("offset", 0)
    if not isinstance(offset, int) or offset < 0:
        return {"error": "offset 必须是非负整数"}
    if action in ("list", "search"):
        kind = arguments.get("kind", "plans")
        if kind not in ("plans", "papers"):
            return {"error": "kind 应为 plans 或 papers"}
        table = "learning_plans" if kind == "plans" else "papers"
        query = str(arguments.get("query", ""))[:300] if action == "search" else ""
        fields = (
            "title || goal || plan_content"
            if kind == "plans"
            else "title || authors || abstract || coalesce(summary,'')"
        )
        columns = "id,title,status" if kind == "plans" else "id,title,authors"
        count = db.rows(
            f"SELECT count(*) AS n FROM {table} WHERE {fields} LIKE ?", ("%" + query + "%",)
        )[0]["n"]
        items = db.rows(
            f"SELECT {columns} FROM {table} WHERE {fields} LIKE ? ORDER BY rowid LIMIT 20 OFFSET ?",
            ("%" + query + "%", offset),
        )
        return {
            "items": items,
            "total": count,
            "next_offset": offset + len(items) if offset + len(items) < count else None,
        }
    if action not in ("plan", "paper", "pdf", "attachment"):
        return {"error": "不支持的读取操作"}
    if action == "attachment":
        rows = db.rows("SELECT * FROM attachments WHERE id=?", (str(arguments.get("id", "")),))
        if not rows:
            return {"error": "附件不存在"}
        record = rows[0]
        try:
            text = (
                Path(record["text_path"]).read_text(encoding="utf-8", errors="replace")
                if record["text_path"] and Path(record["text_path"]).is_file()
                else ""
            )
        except OSError:
            return {"error": "附件无法读取", "id": record["id"]}
        if not text:
            return {
                "id": record["id"],
                "action": action,
                "name": record["name"],
                "kind": record["kind"],
                "text": "",
                "total_characters": 0,
                "next_offset": None,
                "note": "图片或扫描件没有可提取的文字；不要在回答中编造其内容。",
            }
        return {
            "id": record["id"],
            "action": action,
            "name": record["name"],
            "kind": record["kind"],
            "offset": offset,
            "text": text[offset : offset + 8000],
            "total_characters": len(text),
            "next_offset": offset + 8000 if offset + 8000 < len(text) else None,
        }
    table = "learning_plans" if action == "plan" else "papers"
    rows = db.rows(f"SELECT * FROM {table} WHERE id=?", (str(arguments.get("id", "")),))
    if not rows:
        return {"error": "记录不存在"}
    record = rows[0]
    try:
        if action == "pdf":
            text = extract_text(record["local_path"])
        else:
            # Local paths and source snapshots are not required by the provider.
            record.pop("local_path", None)
            record.pop("source_content", None)
            if action == "plan":
                record["tasks"] = db.rows(
                    "SELECT week,title,done FROM plan_tasks WHERE plan_id=? ORDER BY week",
                    (record["id"],),
                )
            text = json.dumps(record, ensure_ascii=False)
        return {
            "id": record["id"],
            "action": action,
            "offset": offset,
            "text": text[offset : offset + 8000],
            "total_characters": len(text),
            "next_offset": offset + 8000 if offset + 8000 < len(text) else None,
        }
    except HTTPException as e:
        return {"error": e.detail, "id": record["id"]}
    except (OSError, ValueError):
        return {"error": "文献无法读取", "id": record["id"]}

