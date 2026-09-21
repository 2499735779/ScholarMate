"""Checks the packaged backend without touching real application data or keys."""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

executable = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="scholarmate-smoke-") as folder:
    env = {
        **os.environ,
        "SCHOLARMATE_DATA_DIR": folder,
        # Keep this run's location file out of the real configuration folder.
        "SCHOLARMATE_CONFIG_DIR": str(Path(folder) / "config"),
        "SCHOLARMATE_PARENT": "1",
    }
    child = subprocess.Popen(
        [str(executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    try:
        line = child.stdout.readline()
        if not line:
            raise RuntimeError(child.stderr.read())
        connection = json.loads(line)
        url = f"http://127.0.0.1:{connection['port']}/plans"
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + connection["token"]}
        )
        for attempt in range(30):
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert json.load(response) == []
                break
            except OSError:
                if attempt == 29:
                    raise
                time.sleep(0.1)

        # Endpoints that spend the user's real API quota. A packaged smoke test must
        # never call them: the key lives in the OS credential store, not in the
        # throwaway data directory.
        AI_ENDPOINTS = (
            "/chat",
            "/plans/generate",
            "/paper/summarize",
            "/paper/translate",
            "/settings/test",
            "/library/enrich",
        )
        # The only two URL fragments allowed to name an AI endpoint: FastAPI rejects
        # the first before the handler runs, and the second never reaches the model.
        AI_PROBES = ("scope=everything", "id=missing")

        def ai_endpoint(path):
            """`/chat/upload` and friends are file endpoints; `/chat` itself is not."""
            base = path.split("?")[0]
            for point in AI_ENDPOINTS:
                if point == "/chat":
                    if base == "/chat":
                        return True
                elif base.startswith(point):
                    return True
            return False

        def call(path, body=None, method=None, binary=False):
            if ai_endpoint(path) and not any(probe in path for probe in AI_PROBES):
                raise AssertionError("smoke test must not spend API quota: " + path)
            request = urllib.request.Request(
                f"http://127.0.0.1:{connection['port']}" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={
                    "Authorization": "Bearer " + connection["token"],
                    "Content-Type": "application/json",
                },
                method=method,
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read() if binary else json.load(response)

        plan = call(
            "/plans",
            {
                "title": "Packaged test",
                "plan_content": "## Week 1\n- Read a paper\n## Week 2\n- Run experiment",
            },
        )
        dashboard = call("/dashboard")
        assert dashboard["plans"][0]["current_week"] == 1
        task = dashboard["plans"][0]["week_tasks"][0]
        call("/plan-tasks/" + task["id"], {"done": True}, "PUT")
        assert call("/dashboard")["plans"][0]["done_count"] == 1
        paused = call("/plan-schedule/" + plan["id"], {"paused": True}, "PUT")
        assert paused["paused_on"]
        pdf = call("/plans/" + plan["id"] + "/export?format=pdf", binary=True)
        fixture = Path(folder) / "fixture.pdf"
        fixture.write_bytes(pdf)
        paper = call(
            "/library/link", {"path": str(fixture), "cleanup_copy": False}
        )
        assert paper["storage_mode"] == "linked" and not (Path(folder) / "papers").exists()
        assert call("/paper/file?id=" + paper["id"], binary=True) == pdf

        # Importing the very same bytes must not create a second copy.
        again = call(
            "/library/import", {"filename": "fixture.pdf", "data": base64.b64encode(pdf).decode()}
        )
        assert again["id"] == paper["id"] and again["storage_mode"] == "linked"
        assert not (Path(folder) / "papers").exists()
        assert call("/library/storage")["managed_count"] == 0

        second = call(
            "/plans",
            {"title": "Packaged test two", "plan_content": "## Week 1\n- Read another paper"},
        )
        managed_pdf = call("/plans/" + second["id"] + "/export?format=pdf", binary=True)
        imported = call(
            "/library/import",
            {"filename": "managed.pdf", "data": base64.b64encode(managed_pdf).decode()},
        )
        assert len(call("/papers")) == 2
        assert imported["storage_mode"] == "managed" and imported["content_indexed"] == 0

        # A reference must always render, and never as a placeholder.
        citation = call("/paper/citation?id=" + imported["id"])
        assert citation["text"].startswith("[1] ") and "〔" not in citation["text"]
        assert citation["missing"] and citation["complete"] is False

        storage = call("/library/storage")
        assert storage["managed_count"] == 1 and storage["managed_bytes"] > 0
        assert storage["data_dir"].endswith(Path(folder).name)
        # Nothing in this machine's own folders matches the synthetic copy: the
        # sweep must report nothing and delete nothing.
        sweep = call("/library/dedupe?dry_run=false", {}, "POST")
        assert sweep["items"] == [] and sweep["freed_bytes"] == 0
        assert Path(imported["local_path"]).is_file()

        # The data directory and the download folder are the user's choice.
        settings = call("/settings/storage")
        assert settings["data_dir"] == folder
        assert settings["default_download_dir"].endswith("ScholarMate")
        moved_to = Path(folder + "-moved")
        moved = call(
            "/settings/storage",
            {"data_dir": str(moved_to), "download_dir": str(Path(folder) / "pdf")},
            "PUT",
        )
        assert Path(moved["data_dir"]).resolve() == moved_to.resolve()
        assert Path(moved["download_dir"]).resolve() == (Path(folder) / "pdf").resolve()
        assert moved["freed_bytes"] > 0
        assert (moved_to / "scholarmate.db").is_file()
        after = call("/paper?id=" + imported["id"])
        assert Path(after["local_path"]).resolve() == (
            moved_to / "papers" / Path(imported["local_path"]).name
        ).resolve()
        assert len(call("/papers")) == 2
        assert call("/paper/file?id=" + imported["id"], binary=True) == managed_pdf

        # Removing a linked record keeps the user's own file.
        call("/paper?id=" + paper["id"] + "&remove_record=true", method="DELETE")
        assert fixture.is_file()
        Path(after["local_path"]).unlink()
        assert call("/papers") == []

        # Chat attachments: a Word file is read locally, an image is kept as-is.
        import io
        import zipfile

        document = io.BytesIO()
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w='
                '"http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>打包验收文档正文</w:t></w:r></w:p></w:body></w:document>",
            )
        word = call(
            "/chat/upload",
            {"filename": "验收.docx", "data": base64.b64encode(document.getvalue()).decode()},
        )
        assert word["type_label"] == "Word 文档" and word["characters"] == 8
        image = call(
            "/chat/upload",
            {
                "filename": "示意图.png",
                # Smallest valid 1x1 PNG.
                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
            },
        )
        assert image["kind"] == "image" and image["characters"] == 0
        assert call("/chat/attachment?id=" + image["id"], binary=True) == base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        assert call("/chat/attachment?id=" + word["id"], binary=True).startswith(b"PK")
        assert {a["id"] for a in call("/chat/attachments")} == {word["id"], image["id"]}
        assert call("/status")["vision"] is False
        assert call("/chat/attachment?id=" + word["id"], method="DELETE") == {"ok": True}
        assert [a["id"] for a in call("/chat/attachments")] == [image["id"]]

        # Several conversations and several profiles must coexist.
        first_profile = call(
            "/profiles",
            {
                "name": "方向 A",
                "major": "计算机科学",
                "degree": "硕士",
                "research_field": "自然语言处理",
                "specific_interests": ["LLM"],
                "short_term_goal": "复现论文",
                "long_term_goal": "读博",
                "weekly_hours": 8,
                "language_preference": "中文",
                "custom_instructions": "",
            },
            "POST",
        )
        second_profile = call(
            "/profiles",
            {
                "name": "方向 B",
                "major": "临床医学",
                "degree": "博士",
                "research_field": "医学影像",
                "specific_interests": ["分割"],
                "short_term_goal": "写综述",
                "long_term_goal": "读博",
                "weekly_hours": 10,
                "language_preference": "中文",
                "custom_instructions": "",
            },
            "POST",
        )
        assert call("/status")["profile_name"] == "方向 B"
        assert call("/status")["profile_count"] == 2
        # Clicking "新建画像" sends an empty profile: it must be accepted, become
        # active, and be listed first so it is not hidden behind older ones.
        blank = call(
            "/profiles",
            {
                "name": "画像 3",
                "major": "",
                "degree": "硕士",
                "research_field": "",
                "specific_interests": [],
                "short_term_goal": "",
                "long_term_goal": "",
                "weekly_hours": 8,
                "language_preference": "中文",
                "custom_instructions": "",
            },
            "POST",
        )
        assert blank["active"] is True and blank["major"] == ""
        assert [p["name"] for p in call("/profiles")["items"]][0] == "画像 3"
        assert call("/status")["profile_name"] == "画像 3"
        assert call("/profiles/" + blank["id"], method="DELETE")["active_id"]
        assert [p["name"] for p in call("/profiles")["items"]][0] == "方向 B"
        # Back to 方向 B, which the conversation checks below expect.
        call("/profiles/" + second_profile["id"] + "/activate", {}, "POST")
        thread_a = call("/threads", {}, "POST")
        thread_b = call("/threads", {}, "POST")
        assert thread_a["id"] != thread_b["id"]
        assert thread_a["profile_id"] == second_profile["id"]
        assert call("/profiles/" + first_profile["id"] + "/activate", {}, "POST")["active"]
        assert call("/threads/" + thread_a["id"], {"profile_id": first_profile["id"]}, "PUT")[
            "profile_name"
        ] == "方向 A"
        assert call("/threads/" + thread_b["id"], {"title": "影像方向"}, "PUT")["title"] == "影像方向"
        assert sorted(t["id"] for t in call("/threads")) == sorted(
            [thread_a["id"], thread_b["id"]]
        )
        assert "# " in call("/threads/" + thread_b["id"] + "/export", binary=True).decode()
        assert call("/threads/" + thread_a["id"], method="DELETE") == {"ok": True}
        assert [t["id"] for t in call("/threads")] == [thread_b["id"]]
        assert call("/profiles/" + first_profile["id"], method="DELETE")["active_id"]
        assert [p["id"] for p in call("/profiles")["items"]] == [second_profile["id"]]

        def fails(path, code, method="GET"):
            try:
                call(path, None, method)
            except urllib.error.HTTPError as error:
                return error.code == code
            return False

        # The last profile can never be deleted away.
        assert fails("/profiles/" + second_profile["id"], 409, "DELETE")
        assert fails("/threads/th-missing", 404)
        # Summarising has two modes; the scope is validated and a missing paper is
        # rejected before any provider call (see AI_PROBES above).
        assert fails("/paper/summarize?id=" + imported["id"] + "&scope=everything", 422, "POST")
        assert fails("/paper/summarize?id=missing", 404, "POST")

        child.stdin.close()
        child.wait(timeout=15)
        assert child.returncode == 0
        print(
            "PASS: packaged backend handshake, authenticated SQLite, weekly tasks, pause, "
            "linked PDF reading without copies, citation rendering without placeholders, "
            "storage report, duplicate sweep safety, movable data/download folders, "
            "chat attachment upload/serving/deletion, several conversations and profiles, "
            "missing-file refresh, parent-pipe shutdown"
        )
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

