import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
import paths
import pytest
import security


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path / "data")
    # Never read or write this machine's real location file during tests.
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "LOCATION_FILE", tmp_path / "config" / "storage.json")
    db.init_db()
    store = {}

    class Vault:
        def get_password(self, service, account):
            return store.get((service, account))

        def set_password(self, service, account, value):
            store[(service, account)] = value

    monkeypatch.setattr(security, "vault", lambda: Vault())
    return store


@pytest.fixture
def client():
    import main
    from fastapi.testclient import TestClient

    with TestClient(main.app, headers={"Authorization": "Bearer " + main.TOKEN}) as client:
        yield client


@pytest.fixture
def profile_data():
    return {
        "major": "计算机科学",
        "degree": "硕士",
        "research_field": "自然语言处理",
        "specific_interests": ["LLM", "PyTorch"],
        "short_term_goal": "复现一篇论文",
        "long_term_goal": "学术研究",
        "weekly_hours": 8,
        "language_preference": "中文",
        "custom_instructions": "先给直观解释",
    }

