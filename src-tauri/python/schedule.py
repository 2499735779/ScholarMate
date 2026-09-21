"""Local calendar weeks, pausing, and editable weekly tasks; no model call required."""

import re
import uuid
from datetime import date, timedelta

import db
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


def monday(day=None):
    day = day or date.today()
    return day - timedelta(days=day.weekday())


def number(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip("零一二三四五六七八九", range(10)))
    if "十" in value:
        a, b = value.split("十", 1)
        return digits.get(a, 1) * 10 + digits.get(b, 0)
    return digits.get(value, 0)


def parse_tasks(content):
    tasks, weeks = [], []
    pattern = re.compile(
        r"(?:第\s*([\d一二三四五六七八九十]+)(?:\s*[-–—~至到]\s*第?\s*([\d一二三四五六七八九十]+))?\s*周|weeks?\s*(\d+)(?:\s*[-–—~]\s*(\d+))?)",
        re.I,
    )
    for line in content.splitlines():
        match = pattern.search(line)
        if match:
            start = number(match[1] or match[3])
            end = number(match[2] or match[4] or str(start))
            weeks = list(range(start, min(end, 520) + 1)) if 1 <= start <= end <= 520 else []
            # Markdown table: week | task | deliverable.
            if line.strip().startswith("|"):
                text = "；".join(
                    c.strip() for c in line.strip().strip("|").split("|")[1:] if c.strip()
                )
                tasks.extend((week, text[:1000]) for week in weeks if text)
        elif re.match(r"^#{1,3}\s", line) and not re.match(r"^#{4,}", line):
            # Non-week top-level section ends the preceding weekly block.
            weeks = []
        else:
            action = re.match(r"^\s*(?:[-*+]\s+|\d+[.、]\s*)(?:\[[ xX]\]\s*)?(.+)", line)
            if action and weeks:
                tasks.extend((week, action[1].strip()[:1000]) for week in weeks)
    return list(dict.fromkeys(tasks))[:2000]


def sync_tasks(conn, plan_id, content):
    expected = set(parse_tasks(content))
    old = list(conn.execute("SELECT * FROM plan_tasks WHERE plan_id=? AND generated=1", (plan_id,)))
    retained = set()
    for item in old:
        key = (item["week"], item["title"])
        if key not in expected:
            conn.execute("DELETE FROM plan_tasks WHERE id=?", (item["id"],))
        else:
            retained.add(key)
    for week, title in sorted(expected - retained):
        conn.execute(
            "INSERT INTO plan_tasks(id,plan_id,week,title) VALUES(?,?,?,?)",
            (uuid.uuid4().hex, plan_id, week, title),
        )


def require_plan(id):
    rows = db.rows("SELECT * FROM learning_plans WHERE id=?", (id,))
    if not rows:
        raise HTTPException(404, "计划不存在。")
    return rows[0]


def view(plan, today=None):
    today = today or date.today()
    start = date.fromisoformat(plan["start_date"])
    effective = date.fromisoformat(plan["paused_on"]) if plan["paused_on"] else today
    current = max(0, (monday(effective) - monday(start)).days // 7 + 1)
    tasks = db.rows("SELECT * FROM plan_tasks WHERE plan_id=? ORDER BY week,rowid", (plan["id"],))
    return {
        **plan,
        "current_week": current,
        "tasks": tasks,
        "week_tasks": [t for t in tasks if t["week"] == current],
        "done_count": sum(bool(t["done"]) for t in tasks),
        "task_count": len(tasks),
    }


@router.get("/dashboard")
def dashboard():
    plans = db.rows("SELECT * FROM learning_plans ORDER BY created_at DESC")
    with db.connect() as conn:
        for plan in plans:
            sync_tasks(conn, plan["id"], plan["plan_content"])
    return {
        "week_start": monday().isoformat(),
        "week_end": (monday() + timedelta(days=6)).isoformat(),
        "plans": [view(p) for p in plans if p["status"] == "进行中"],
    }


@router.get("/plan-schedule/{id}")
def get_schedule(id: str):
    p = require_plan(id)
    with db.connect() as conn:
        sync_tasks(conn, id, p["plan_content"])
    return view(p)


class Timing(BaseModel):
    start_date: date | None = None
    paused: bool | None = None


@router.put("/plan-schedule/{id}")
def timing(id: str, body: Timing):
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM learning_plans WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "计划不存在。")
        start = date.fromisoformat(row["start_date"])
        paused = row["paused_on"]
        if body.start_date:
            start = monday(body.start_date)
            if paused:
                paused = date.today().isoformat()
        if body.paused is True and not paused:
            paused = date.today().isoformat()
        elif body.paused is False and paused:
            # Skip calendar boundaries passed while paused, preserving the current week.
            start += monday() - monday(date.fromisoformat(paused))
            paused = None
        conn.execute(
            "UPDATE learning_plans SET start_date=?,paused_on=? WHERE id=?",
            (start.isoformat(), paused, id),
        )
    return get_schedule(id)


class TaskInput(BaseModel):
    week: int = Field(ge=1, le=520)
    title: str = Field(min_length=1, max_length=1000)


@router.post("/plan-schedule/{id}/tasks")
def add_task(id: str, body: TaskInput):
    require_plan(id)
    db.execute(
        "INSERT INTO plan_tasks(id,plan_id,week,title,generated) VALUES(?,?,?,?,0)",
        (uuid.uuid4().hex, id, body.week, body.title.strip()),
    )
    return get_schedule(id)


class Completion(BaseModel):
    done: bool


@router.put("/plan-tasks/{id}")
def complete(id: str, body: Completion):
    if not db.execute("UPDATE plan_tasks SET done=? WHERE id=?", (int(body.done), id)):
        raise HTTPException(404, "任务不存在。")
    return {"ok": True}

