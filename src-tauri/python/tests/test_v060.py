"""v0.6: the data directory and the default download folder are the user's choice."""

from pathlib import Path

import db
import main
import papers
import paths
import pytest
from fastapi import HTTPException


def test_location_file_drives_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("SCHOLARMATE_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "APP_DIRS", type("D", (), {"user_data_dir": tmp_path / "fallback"})())
    assert paths.data_dir() == tmp_path / "fallback"
    paths.write_location(data_dir=str(tmp_path / "E-drive"))
    assert paths.data_dir() == tmp_path / "E-drive"
    # A drive that is not mounted must not send the database somewhere unreachable.
    monkeypatch.setattr(paths, "mounted", lambda _: False)
    assert paths.data_dir() == tmp_path / "fallback"


def test_config_directory_matches_the_desktop_launcher(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("SCHOLARMATE_CONFIG_DIR", str(tmp_path / "config"))
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.CONFIG_DIR == tmp_path / "config"
        assert reloaded.LOCATION_FILE == tmp_path / "config" / "storage.json"
    finally:
        monkeypatch.delenv("SCHOLARMATE_CONFIG_DIR", raising=False)
        importlib.reload(paths)


def test_system_environment_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOLARMATE_DATA_DIR", str(tmp_path / "explicit"))
    paths.write_location(data_dir=str(tmp_path / "saved"))
    assert paths.data_dir() == tmp_path / "explicit"


def test_download_folder_defaults_to_the_user_downloads_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "APP_DIRS", type("D", (), {"user_data_dir": tmp_path / "fallback"})())
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    assert paths.download_dir() == tmp_path / "Downloads" / "ScholarMate"
    paths.write_location(download_dir=str(tmp_path / "papers-on-E"))
    assert paths.download_dir() == tmp_path / "papers-on-E"
    paths.write_location(download_dir="")
    assert paths.download_dir() == tmp_path / "Downloads" / "ScholarMate"


def test_storage_settings_report_and_change_both_folders(client, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    state = client.get("/settings/storage").json()
    assert state["data_dir"] == str(db.DATA_DIR)
    assert state["data_dir_custom"] is False
    assert state["download_dir"] == str(tmp_path / "Downloads" / "ScholarMate")
    assert state["system_drive"].endswith(("\\", "/"))

    moved = tmp_path / "E" / "ScholarMate-data"
    updated = client.put(
        "/settings/storage",
        json={"data_dir": str(moved), "download_dir": str(tmp_path / "E" / "papers")},
    ).json()
    assert Path(updated["data_dir"]) == moved.resolve()
    assert updated["data_dir_custom"] is True
    assert updated["download_dir"] == str((tmp_path / "E" / "papers").resolve())
    # The pointer file decides where the next launch looks.
    assert Path(paths.location()["data_dir"]) == moved.resolve()
    assert Path(paths.location()["download_dir"]) == (tmp_path / "E" / "papers").resolve()


def test_moving_the_data_directory_carries_records_and_pdfs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    import base64

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    source = tmp_path / "imported.pdf"
    writer.write(source)
    payload = source.read_bytes()
    paper = client.post(
        "/library/import",
        json={"filename": "imported.pdf", "data": base64.b64encode(payload).decode()},
    ).json()
    old_copy = Path(paper["local_path"])
    assert old_copy.is_file()
    plan = client.post(
        "/plans", json={"title": "迁移测试", "plan_content": "## 第 1 周\n- 读文献"}
    ).json()

    target = tmp_path / "D" / "ScholarMate-data"
    result = client.put("/settings/storage", json={"data_dir": str(target)}).json()
    assert result["freed_bytes"] > 0
    assert Path(result["data_dir"]) == target.resolve()
    assert not old_copy.exists()
    moved_copy = target / "papers" / old_copy.name
    assert moved_copy.is_file() and moved_copy.read_bytes() == payload
    # Records follow their files, so the library stays visible after the move.
    after = client.get("/paper", params={"id": paper["id"]}).json()
    assert Path(after["local_path"]) == moved_copy.resolve()
    assert len(client.get("/papers").json()) == 1
    assert client.get("/paper/file", params={"id": paper["id"]}).content == payload
    assert [p["id"] for p in client.get("/plans").json()] == [plan["id"]]
    # A second database file also lands in the new directory.
    assert (target / "scholarmate.db").is_file()


def test_move_leaves_files_outside_the_managed_folder_where_they_are(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    outside = Path(db.DATA_DIR) / "kept-by-the-user.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"%PDF-outside")
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,source,publication_type) "
        "VALUES('kept','Kept outside','','','','2000',?,'local','online')",
        (str(outside),),
    )
    target = tmp_path / "E" / "moved"
    client.put("/settings/storage", json={"data_dir": str(target)})
    # A file that was never part of <data>/papers must not be reported as moved.
    assert outside.is_file()
    assert client.get("/paper", params={"id": "kept"}).json()["local_path"] == str(outside)
    assert len(client.get("/papers").json()) == 1
    assert client.get("/paper/file", params={"id": "kept"}).content == b"%PDF-outside"


def test_move_handles_a_non_canonical_data_path(client, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    # A configured path may contain "..", a short name or a symlink; records then
    # store that text form while the real folder is the resolved one.
    awkward = tmp_path / "data" / ".." / "data"
    monkeypatch.setattr(db, "DATA_DIR", awkward)
    db.init_db()
    managed = awkward / "papers"
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "local-abc.pdf").write_bytes(b"%PDF-managed")
    db.execute(
        "INSERT INTO papers(id,title,authors,abstract,pdf_url,published,local_path,source,publication_type,storage_mode) "
        "VALUES('awkward','Awkward','','','','2000',?,'local','online','managed')",
        (str(managed / "local-abc.pdf"),),
    )
    target = tmp_path / "E" / "moved"
    client.put("/settings/storage", json={"data_dir": str(target)})
    after = client.get("/paper", params={"id": "awkward"}).json()
    assert Path(after["local_path"]) == (target / "papers" / "local-abc.pdf").resolve()
    assert Path(after["local_path"]).read_bytes() == b"%PDF-managed"
    assert not (tmp_path / "data" / "papers" / "local-abc.pdf").exists()


def test_move_refuses_unsafe_targets(client, tmp_path):
    parent = db.DATA_DIR.parent
    assert client.put(
        "/settings/storage", json={"data_dir": "relative\\folder"}
    ).status_code == 422
    assert client.put(
        "/settings/storage", json={"data_dir": str(parent)}
    ).status_code == 422
    busy = tmp_path / "not-empty"
    busy.mkdir()
    (busy / "keep.txt").write_text("keep", encoding="utf-8")
    assert client.put(
        "/settings/storage", json={"data_dir": str(busy)}
    ).status_code == 409
    assert (busy / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_reset_returns_to_the_default_location(client, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "APP_DIRS", type("D", (), {"user_data_dir": tmp_path / "default"})())
    monkeypatch.setattr(paths, "downloads_dir", lambda: tmp_path / "Downloads")
    custom = tmp_path / "custom"
    client.put("/settings/storage", json={"data_dir": str(custom)})
    assert Path(paths.location()["data_dir"]) == custom.resolve()
    back = client.put("/settings/storage", json={"reset": ["data_dir", "download_dir"]}).json()
    assert Path(back["data_dir"]) == (tmp_path / "default").resolve()
    assert back["data_dir_custom"] is False
    assert paths.location() == {}
    assert Path(back["download_dir"]) == tmp_path / "Downloads" / "ScholarMate"


def test_move_failure_keeps_the_original_data(client, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(main.shutil, "copy2", broken)
    with pytest.raises(HTTPException):
        main.move_storage((tmp_path / "broken").resolve())
    assert Path(db.DATA_DIR).is_dir() and main.storage_state()["data_dir"] == str(db.DATA_DIR)
    assert not (tmp_path / "broken").exists()


@pytest.mark.asyncio
async def test_download_uses_the_configured_folder(tmp_path, monkeypatch):
    target = tmp_path / "deep" / "papers"
    monkeypatch.setattr(paths, "download_dir", lambda: target)

    class Response:
        is_redirect = False
        headers = {"content-length": "16"}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, size):
            yield b"%PDF-1.7 fixture"

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *args):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return Stream()

    monkeypatch.setattr(papers.httpx, "AsyncClient", lambda **kwargs: Client())
    progress = [p async for p in papers.download_pdf("1234.5678", "", None)]
    assert progress[-1]["path"] == str((target / "1234.5678.pdf").resolve())
    assert (target / "1234.5678.pdf").read_bytes().startswith(b"%PDF-")

