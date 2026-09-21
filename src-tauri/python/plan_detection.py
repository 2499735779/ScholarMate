"""Recognize proposals without another paid AI call; adoption always needs a click."""

import json
import re

BLOCK = re.compile(r"```scholarmate-plan\s*\n(.*?)\n```", re.S)
PLAN_INSTRUCTION = """
当用户要求生成或修改一份可执行学习计划时，给出一份完整计划，放入以下代码块（只生成一个）：
```scholarmate-plan
{"title":"具体计划标题","goal":"学习目标","plan_content":"完整 Markdown 计划，包含阶段时间、行动和验收标准"}
```
必须是有效 JSON，字符串中的换行用 \\n 转义。应用会将它显示为可采纳卡片。
plan_content 必须使用“## 第 1 周”、“## 第 2 周”等逐周标题，每周标题下用 - 列出具体任务，不合并周数。采纳当周为第1周。
普通解释、列举已有计划或讨论计划可行性时不要生成该块。
你不能直接新增、修改或删除本地计划；用户点击采纳后才会保存。不要声称已保存。
"""


def detect_plan(content):
    block = BLOCK.search(content)
    if block:
        try:
            data = json.loads(block.group(1))
            if (
                all(
                    isinstance(data.get(k), str) and data[k].strip()
                    for k in ("title", "goal", "plan_content")
                )
                and len(data["plan_content"]) <= 200000
            ):
                return {
                    "title": data["title"][:200],
                    "goal": data["goal"][:4000],
                    "plan_content": data["plan_content"],
                    "detection": "structured",
                }
        except (ValueError, TypeError, AttributeError):
            pass
    # Legacy Markdown proposals are candidates, never silently saved.
    has_plan = re.search(r"学习计划|学习路线|learning plan|study plan", content, re.I)
    has_timing = re.search(
        r"第[一二三四五六七八九十\d]+[周月天阶段]|阶段\s*[一二三\d]+|week\s*\d|month\s*\d",
        content,
        re.I,
    )
    has_actions = len(re.findall(r"^\s*(?:[-*]|\d+[.、]|#{1,6})\s*\S", content, re.M)) >= 2
    if has_plan and has_timing and has_actions and len(content) >= 80:
        title = next(
            (
                line.lstrip("# ").strip()
                for line in content.splitlines()
                if re.match(r"^#{1,3}\s+", line)
            ),
            "对话中的学习计划",
        )
        return {
            "title": title[:200],
            "goal": title[:200],
            "plan_content": content,
            "detection": "markdown",
        }
    return None


def decorate_message(message, adopted=None):
    candidate = detect_plan(message["content"]) if message["role"] == "assistant" else None
    return {
        **message,
        "plan_candidate": candidate,
        "adopted_plan_id": adopted,
        "display_content": BLOCK.sub("", message["content"]).strip()
        if candidate and candidate["detection"] == "structured"
        else message["content"],
    }

