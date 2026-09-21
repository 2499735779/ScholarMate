"""Isolated manual UI fixture. Never used by the packaged application."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-tauri/python"))
import asyncio
import socket

import ai
import db
import main
import paths
import security
import uvicorn


async def fixture_stream(*args, **kwargs):
    context = kwargs.get("context") or (args[2] if len(args) > 2 else None)
    documents = (context or {}).get("documents") or []
    images = (context or {}).get("unseen_images") or []
    if documents or images:
        if documents:
            names = "、".join(d["name"] for d in documents)
            head = documents[0]["text"][:60].replace("\n", " ")
            content = f"（隔离测试）我读到了附件：{names}。开头内容是「{head}」。"
        else:
            content = "（隔离测试）收到图片，但当前模型未启用图片输入，看不到图中内容。"
    else:
        content = (
            "根据你的目标整理了以下计划：\n```scholarmate-plan\n"
            + json.dumps(
                {
                    "title": "三周 PyTorch 学习计划",
                    "goal": "完成图像分类实验",
                    "plan_content": "## 第一周\n- 学习张量与自动求导\n## 第二周\n- 训练一个分类器\n## 第三周\n- 评估与复盘",
                },
                ensure_ascii=False,
            )
            + "\n```"
        )
    for start in range(0, len(content), 24):
        yield content[start : start + 24]
        await asyncio.sleep(0.05)


ENGLISH_TITLE = "Topological Analysis of Water Distribution Networks for Leak Location"

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="scholarmate-ui-") as directory:
        db.DATA_DIR = Path(directory)
        # Keep the location file inside the fixture: never touch the real one.
        paths.CONFIG_DIR = Path(directory) / "config"
        paths.LOCATION_FILE = paths.CONFIG_DIR / "storage.json"
        main.TOKEN = "isolated-ui-test"
        main.get_key = lambda: None
        security.get_key = lambda: "fixture-key"
        ai.stream_ai = fixture_stream

        async def fixture_call(task, message, context=None):
            if task == "translate":
                blocks = json.loads(message.split("\n", 1)[1])
                return json.dumps([{"id": b["id"], "text": "这是用于验证对照排版的模拟中文译文：供水管网拓扑分析与漏损定位方法研究。"} for b in blocks], ensure_ascii=False)
            if (context or {}).get("isolated"):
                if "Topological Analysis" in message:
                    # Every field below also appears in the PDF body, which is what
                    # allows the application to keep it.
                    return json.dumps(
                        {
                            "title": ENGLISH_TITLE,
                            "title_zh": "供水管网拓扑分析与漏损定位",
                            "category": "工程与材料",
                            "tags": "供水管网,漏损定位,拓扑分析",
                            "authors": "Alice M. Newman, Bob Carter",
                            "published": "2026",
                            "venue": "Journal of Water Resources Planning",
                        },
                        ensure_ascii=False,
                    )
                return json.dumps(
                    {
                        "title_zh": "神经网络与深度学习",
                        "category": "计算机与人工智能",
                        "tags": "神经网络,深度学习",
                    },
                    ensure_ascii=False,
                )
            if (context or {}).get("documents"):
                names = "、".join(d["name"] for d in context["documents"])
                first = context["documents"][0]["text"][:40].replace("\n", " ")
                return f"这是隔离测试中的模拟回复：已读取附件 {names}，开头是「{first}」。"
            if (context or {}).get("unseen_images"):
                return "这是隔离测试中的模拟回复：收到图片，但当前模型看不到图片内容。"
            return "这是隔离测试中的模拟回复。"

        ai.call_ai = fixture_call
        db.init_db()
        main.create_plan(
            main.Plan(
                title="三周 PyTorch 实践",
                goal="完成图像分类实验",
                plan_content="## 第 1 周\n- 阅读张量基础\n- 完成自动求导练习\n## 第 2 周\n- 训练图像分类模型\n## 第 3 周\n- 评估实验并撰写报告",
            )
        )
        from exports import export_pdf

        for id, title, category in [
            ("fixture-en", "Neural networks and deep learning", ""),
            ("fixture-zh", "面向科研的知识管理方法", "教育与社会科学"),
        ]:
            path = Path(directory) / (id + ".pdf")
            path.write_bytes(export_pdf(title, "## Research methods\nNeural networks learn representations from training data. This study evaluates robust models for scientific research.\n\n## Results\nThe results demonstrate improvements in accuracy and generalization."))
            db.execute(
                "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,category,title_zh,publication_type,venue,pages,source) VALUES(?,?,?,'研究背景与方法。','','2026',?,?,?,'journal','学术研究','1-12','local')",
                (id, title, "ZHANG S, LI M", str(path), category, title if category else ""),
            )
        # Random download name: identity has to come from the PDF body.
        unreadable = Path(directory) / "12345.pdf"
        unreadable.write_bytes(
            export_pdf(
                ENGLISH_TITLE,
                "Journal of Water Resources Planning\n\n"
                "Alice M. Newman, Bob Carter\n\n"
                "## Abstract\nLeak location in water distribution networks is studied with "
                "topological analysis in 2026.\n\nKeywords: water network; leak location",
            )
        )
        db.execute(
            "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,source,publication_type) VALUES('fixture-numeric','12345','','','','',?,'local','online')",
            (str(unreadable),),
        )
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        print(json.dumps({"port": sock.getsockname()[1], "token": main.TOKEN}), flush=True)
        uvicorn.Server(uvicorn.Config(main.app, log_level="warning")).run(sockets=[sock])

