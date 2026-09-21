import json
import sqlite3
import uuid
from contextlib import contextmanager

import paths

# Resolved from the location file so the database can live on any drive; tests
# and the desktop launcher may still override it through the environment.
DATA_DIR = paths.data_dir()


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "scholarmate.db", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        with db:
            yield db
    finally:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), model TEXT NOT NULL DEFAULT 'deepseek-chat');
INSERT OR IGNORE INTO settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS user_profile (
 id INTEGER PRIMARY KEY CHECK(id=1), major TEXT NOT NULL, degree TEXT NOT NULL,
 research_field TEXT NOT NULL, specific_interests TEXT NOT NULL DEFAULT '[]',
 short_term_goal TEXT NOT NULL, long_term_goal TEXT NOT NULL, weekly_hours INTEGER NOT NULL,
 language_preference TEXT NOT NULL, custom_instructions TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS learning_plans (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL, plan_content TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 status TEXT NOT NULL DEFAULT '进行中' CHECK(status IN ('进行中','已完成','已放弃')));
CREATE TABLE IF NOT EXISTS papers (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT NOT NULL, abstract TEXT NOT NULL,
 pdf_url TEXT NOT NULL, published TEXT NOT NULL, local_path TEXT, summary TEXT,
 downloaded_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS attachments (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, media_type TEXT NOT NULL DEFAULT '',
 path TEXT NOT NULL, text_path TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL DEFAULT 0,
 characters INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS profiles (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, major TEXT NOT NULL DEFAULT '',
 degree TEXT NOT NULL DEFAULT '硕士', research_field TEXT NOT NULL DEFAULT '',
 specific_interests TEXT NOT NULL DEFAULT '[]', short_term_goal TEXT NOT NULL DEFAULT '',
 long_term_goal TEXT NOT NULL DEFAULT '', weekly_hours INTEGER NOT NULL DEFAULT 8,
 language_preference TEXT NOT NULL DEFAULT '中文', custom_instructions TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS chat_threads (
 id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', profile_id TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
"""

PROFILE_FIELDS = (
    "name",
    "major",
    "degree",
    "research_field",
    "specific_interests",
    "short_term_goal",
    "long_term_goal",
    "weekly_hours",
    "language_preference",
    "custom_instructions",
)


def init_db():
    with connect() as db:
        db.executescript(SCHEMA)
        columns = {r["name"] for r in db.execute("PRAGMA table_info(learning_plans)")}
        for name in ("source_message_id", "source_content"):
            if name not in columns:
                db.execute(f"ALTER TABLE learning_plans ADD COLUMN {name} TEXT")
        for name, spec in {"start_date": "TEXT", "paused_on": "TEXT"}.items():
            if name not in columns:
                db.execute(f"ALTER TABLE learning_plans ADD COLUMN {name} {spec}")
        db.execute(
            "UPDATE learning_plans SET start_date=date(created_at, 'localtime', '-6 days', 'weekday 1') WHERE start_date IS NULL"
        )
        cols = {r["name"] for r in db.execute("PRAGMA table_info(conversations)")}
        for name, spec in {
            "plan_rejected": "INTEGER NOT NULL DEFAULT 0",
            "attachments": "TEXT NOT NULL DEFAULT '[]'",
        }.items():
            if name not in cols:
                db.execute(f"ALTER TABLE conversations ADD COLUMN {name} {spec}")
        cols = {r["name"] for r in db.execute("PRAGMA table_info(settings)")}
        for name, spec in {
            "vision": "INTEGER NOT NULL DEFAULT 0",
            "active_profile_id": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in cols:
                db.execute(f"ALTER TABLE settings ADD COLUMN {name} {spec}")
        cols = {r["name"] for r in db.execute("PRAGMA table_info(conversations)")}
        for name in ("thread_id", "profile_id"):
            if name not in cols:
                db.execute(f"ALTER TABLE conversations ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        migrate_single_profile(db)
        migrate_flat_conversations(db)
        cols = {r["name"] for r in db.execute("PRAGMA table_info(papers)")}
        for name, spec in {
            "title_zh": "TEXT DEFAULT ''",
            "category": "TEXT DEFAULT ''",
            "tags": "TEXT DEFAULT ''",
            "language": "TEXT DEFAULT ''",
            "source": "TEXT DEFAULT 'arxiv'",
            "doi": "TEXT DEFAULT ''",
            "venue": "TEXT DEFAULT ''",
            "volume": "TEXT DEFAULT ''",
            "issue": "TEXT DEFAULT ''",
            "pages": "TEXT DEFAULT ''",
            "publisher": "TEXT DEFAULT ''",
            "place": "TEXT DEFAULT ''",
            "publication_type": "TEXT DEFAULT 'preprint'",
            "landing_url": "TEXT DEFAULT ''",
            "enrichment_error": "TEXT DEFAULT ''",
            "storage_mode": "TEXT NOT NULL DEFAULT 'managed'",
            "metadata_evidence": "TEXT DEFAULT ''",
            "content_indexed": "INTEGER NOT NULL DEFAULT 0",
            "citation_checked": "INTEGER NOT NULL DEFAULT 0",
            "summary_scope": "TEXT DEFAULT ''",
            "summary_characters": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in cols:
                db.execute(f"ALTER TABLE papers ADD COLUMN {name} {spec}")
        db.execute("""CREATE TABLE IF NOT EXISTS plan_tasks (
            id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, week INTEGER NOT NULL CHECK(week BETWEEN 1 AND 520),
            title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, generated INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE)""")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS plan_source ON learning_plans(source_message_id) WHERE source_message_id IS NOT NULL"
        )


def rows(sql, args=()):
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def execute(sql, args=()):
    with connect() as db:
        return db.execute(sql, args).rowcount


def new_id(prefix):
    return prefix + uuid.uuid4().hex[:16]


def migrate_single_profile(db):
    """The first profile comes from the single-profile table of earlier versions."""
    if db.execute("SELECT id FROM profiles LIMIT 1").fetchone():
        return
    legacy = db.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    if not legacy:
        return
    id = new_id("pf-")
    name = (legacy["research_field"] or legacy["major"] or "默认画像").strip()[:80]
    db.execute(
        "INSERT INTO profiles(id,name,major,degree,research_field,specific_interests,"
        "short_term_goal,long_term_goal,weekly_hours,language_preference,custom_instructions) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            id,
            name,
            legacy["major"],
            legacy["degree"],
            legacy["research_field"],
            legacy["specific_interests"],
            legacy["short_term_goal"],
            legacy["long_term_goal"],
            legacy["weekly_hours"],
            legacy["language_preference"],
            legacy["custom_instructions"],
        ),
    )
    db.execute("UPDATE settings SET active_profile_id=? WHERE id=1", (id,))


def migrate_flat_conversations(db):
    """Earlier versions kept one endless log; give those messages a thread."""
    if not db.execute(
        "SELECT id FROM conversations WHERE thread_id='' LIMIT 1"
    ).fetchone():
        return
    setting = db.execute("SELECT active_profile_id FROM settings WHERE id=1").fetchone()
    profile = setting["active_profile_id"] if setting else ""
    if not profile:
        first = db.execute("SELECT id FROM profiles LIMIT 1").fetchone()
        profile = first["id"] if first else ""
    thread = new_id("th-")
    db.execute(
        "INSERT INTO chat_threads(id,title,profile_id) VALUES(?,?,?)",
        (thread, "历史对话", profile),
    )
    db.execute(
        "UPDATE conversations SET thread_id=?, profile_id=? WHERE thread_id=''",
        (thread, profile),
    )


def profiles(newest_first=False):
    order = "rowid DESC" if newest_first else "rowid"
    return rows(f"SELECT * FROM profiles ORDER BY {order}")


def parse_profile(row):
    if row is None:
        return None
    result = dict(row)
    try:
        result["specific_interests"] = json.loads(result.get("specific_interests") or "[]")
    except ValueError:
        result["specific_interests"] = []
    return result


def active_profile_id():
    rows_ = rows("SELECT active_profile_id FROM settings WHERE id=1")
    saved = rows_[0]["active_profile_id"] if rows_ else ""
    if saved and rows("SELECT id FROM profiles WHERE id=?", (saved,)):
        return saved
    first = rows("SELECT id FROM profiles ORDER BY created_at, rowid LIMIT 1")
    if not first:
        return ""
    # Self-healing: a missing or deleted pointer falls back to the first profile.
    execute("UPDATE settings SET active_profile_id=? WHERE id=1", (first[0]["id"],))
    return first[0]["id"]


def profile(profile_id=None):
    if profile_id:
        found = rows("SELECT * FROM profiles WHERE id=?", (profile_id,))
    else:
        found = rows("SELECT * FROM profiles WHERE id=?", (active_profile_id(),))
    return parse_profile(found[0] if found else None)


def set_active_profile(profile_id):
    execute("UPDATE settings SET active_profile_id=? WHERE id=1", (profile_id,))

