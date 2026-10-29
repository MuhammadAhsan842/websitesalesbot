import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ayyan.db"
_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init():
    with _lock:
        conn = connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              opportunity_id TEXT NOT NULL,
              case_id TEXT,
              channel TEXT NOT NULL DEFAULT 'chat',
              conversation_state TEXT NOT NULL,
              state_version INTEGER NOT NULL DEFAULT 1,
              takeover INTEGER NOT NULL DEFAULT 0,
              handed_over INTEGER NOT NULL DEFAULT 0,
              identity_confirmed INTEGER NOT NULL DEFAULT 0,
              facts_json TEXT NOT NULL DEFAULT '{}',
              memory_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
              id TEXT PRIMARY KEY,
              session_id TEXT,
              opportunity_id TEXT,
              task TEXT,
              status TEXT NOT NULL,
              owner TEXT NOT NULL DEFAULT 'Unassigned desk',
              summary TEXT,
              next_action TEXT,
              facts_json TEXT NOT NULL DEFAULT '{}',
              documents_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action_id TEXT UNIQUE NOT NULL,
              kind TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message TEXT NOT NULL,
              extra_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fee_schedule (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              arrangement TEXT NOT NULL,
              percent REAL NOT NULL,
              conditions TEXT,
              status TEXT NOT NULL,
              approved_by TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS case_files (
              id TEXT PRIMARY KEY,
              case_id TEXT NOT NULL,
              doc_type TEXT NOT NULL,
              filename TEXT NOT NULL,
              path TEXT,
              extracted_json TEXT NOT NULL DEFAULT '{}',
              flags_json TEXT NOT NULL DEFAULT '[]',
              diff_json TEXT NOT NULL DEFAULT '[]',
              version INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hard_turns (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT,
              user_text TEXT,
              reply TEXT,
              reason TEXT,
              source TEXT,
              reviewed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requirements (
              id TEXT PRIMARY KEY,
              case_id TEXT NOT NULL,
              doc_type TEXT NOT NULL,
              label TEXT NOT NULL,
              status TEXT NOT NULL,
              due_at TEXT,
              current_file_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS example_sources (
              id TEXT PRIMARY KEY,
              filename TEXT NOT NULL,
              sha256 TEXT UNIQUE NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              pages INTEGER NOT NULL DEFAULT 0,
              method TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_examples (
              id TEXT PRIMARY KEY,
              source_id TEXT,
              source TEXT,
              user_text TEXT NOT NULL,
              context TEXT,
              reply TEXT NOT NULL,
              move TEXT,
              variant TEXT,
              tags_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL,
              reviewed_by TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS embeddings (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              doc_id TEXT NOT NULL,
              model TEXT NOT NULL,
              dims INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              vec BLOB NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS embeddings_doc ON embeddings(kind, doc_id, model);
            CREATE TABLE IF NOT EXISTS turns (
              turn_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              user_text TEXT NOT NULL,
              reply_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS zoho_mirror (
              id TEXT PRIMARY KEY,
              module TEXT NOT NULL,
              opportunity_id TEXT,
              case_id TEXT,
              session_id TEXT,
              human_version INTEGER NOT NULL DEFAULT 0,
              stage TEXT,
              data_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
              id TEXT PRIMARY KEY,
              session_id TEXT,
              case_id TEXT,
              filename TEXT NOT NULL,
              path TEXT NOT NULL,
              sha256 TEXT UNIQUE NOT NULL,
              kind TEXT NOT NULL,
              ocr_text TEXT,
              ocr_confidence REAL,
              vision_json TEXT NOT NULL DEFAULT '{}',
              vision_status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        for stmt in (
            "ALTER TABLE case_files ADD COLUMN diff_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE case_files ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE case_files ADD COLUMN method TEXT",
            "ALTER TABLE case_files ADD COLUMN ocr_confidence REAL",
            "ALTER TABLE case_files ADD COLUMN original_path TEXT",
            "ALTER TABLE case_files ADD COLUMN requirement_id TEXT",
            "ALTER TABLE hard_turns ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE outbox ADD COLUMN zoho_id TEXT",
            "ALTER TABLE cases ADD COLUMN related_tasks_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE sessions ADD COLUMN memory_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE conversation_examples ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE conversation_examples ADD COLUMN strategy TEXT",
            "ALTER TABLE conversation_examples ADD COLUMN pattern TEXT",
            "ALTER TABLE conversation_examples ADD COLUMN situation TEXT",
            "ALTER TABLE conversation_examples ADD COLUMN applicability_json TEXT NOT NULL DEFAULT '[]'",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()


def execute(sql, params=(), fetch="none"):
    with _lock:
        conn = connect()
        cur = conn.execute(sql, params)
        if fetch == "one":
            row = cur.fetchone()
            conn.commit()
            conn.close()
            return dict(row) if row else None
        if fetch == "all":
            rows = [dict(r) for r in cur.fetchall()]
            conn.commit()
            conn.close()
            return rows
        conn.commit()
        conn.close()
        return cur.lastrowid


def loads(value, default):
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def uid(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def add_event(message: str, extra: dict | None = None):
    execute(
        "INSERT INTO events (message, extra_json, created_at) VALUES (?, ?, ?)",
        (message, dumps(extra or {}), now()),
    )


def add_message(session_id: str, role: str, text: str):
    execute(
        "INSERT INTO messages (session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, text, now()),
    )


def get_turn(turn_id: str | None) -> dict | None:
    if not turn_id:
        return None
    row = execute("SELECT reply_json FROM turns WHERE turn_id = ?", (turn_id,), fetch="one")
    return loads(row["reply_json"], None) if row else None


def save_turn(turn_id: str, session_id: str, user_text: str, reply: dict):
    execute(
        "INSERT OR REPLACE INTO turns (turn_id, session_id, user_text, reply_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (turn_id, session_id, user_text, dumps(reply), now()),
    )


def list_messages(session_id: str) -> list[dict]:
    return (
        execute(
            "SELECT role, text, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
            fetch="all",
        )
        or []
    )


def create_session(seed_facts: dict | None = None) -> dict:
    session_id = uid("session")
    opportunity_id = uid("opp")
    ts = now()
    execute(
        """INSERT INTO sessions (id, opportunity_id, channel, conversation_state, facts_json, created_at, updated_at)
           VALUES (?, ?, 'chat', 'understand_request', ?, ?, ?)""",
        (session_id, opportunity_id, dumps(seed_facts or {}), ts, ts),
    )
    return get_session(session_id)


def _session_from_row(row: dict) -> dict:
    row["facts"] = loads(row.pop("facts_json"), {})
    row["memory"] = loads(row.pop("memory_json", None), {})
    row["takeover"] = bool(row["takeover"])
    row["handed_over"] = bool(row["handed_over"])
    row["identity_confirmed"] = bool(row["identity_confirmed"])
    # Handoff flags live in memory_json so they survive reload without a schema break.
    mem = row["memory"] or {}
    row["manager_requested"] = bool(mem.get("manager_requested") or row.get("manager_requested"))
    row["manager_accepted"] = bool(mem.get("manager_accepted") or row.get("manager_accepted"))
    return row


def get_session(session_id: str) -> dict | None:
    row = execute("SELECT * FROM sessions WHERE id = ?", (session_id,), fetch="one")
    return _session_from_row(row) if row else None


def save_session(session: dict):
    mem = dict(session.get("memory") or {})
    if "manager_requested" in session:
        mem["manager_requested"] = bool(session.get("manager_requested"))
    if "manager_accepted" in session:
        mem["manager_accepted"] = bool(session.get("manager_accepted"))
    session["memory"] = mem
    execute(
        """UPDATE sessions SET case_id=?, channel=?, conversation_state=?, state_version=?,
           takeover=?, handed_over=?, identity_confirmed=?, facts_json=?, memory_json=?, updated_at=?
           WHERE id=?""",
        (
            session.get("case_id"),
            session["channel"],
            session["conversation_state"],
            session["state_version"],
            int(session.get("takeover") or session.get("manager_accepted") or False),
            int(session["handed_over"]),
            int(session["identity_confirmed"]),
            dumps(session["facts"]),
            dumps(mem),
            now(),
            session["id"],
        ),
    )


def _case_from_row(row: dict) -> dict:
    row["facts"] = loads(row.pop("facts_json"), {})
    row["documents"] = loads(row.pop("documents_json"), [])
    related_raw = row.pop("related_tasks_json", None) if "related_tasks_json" in row else "[]"
    row["related_tasks"] = loads(related_raw or "[]", [])
    return row


def list_cases() -> list[dict]:
    rows = execute("SELECT * FROM cases ORDER BY updated_at DESC", fetch="all") or []
    return [_case_from_row(r) for r in rows]


def get_case(case_id: str) -> dict | None:
    row = execute("SELECT * FROM cases WHERE id = ?", (case_id,), fetch="one")
    return _case_from_row(row) if row else None


def upsert_case(partial: dict) -> dict:
    case_id = partial.get("id") or uid("case")
    existing = get_case(case_id)
    ts = now()
    if existing:
        merged = {**existing, **partial, "id": case_id}
        related = merged.get("related_tasks")
        if related is None:
            related = existing.get("related_tasks") or []
        execute(
            """UPDATE cases SET session_id=?, opportunity_id=?, task=?, status=?, owner=?,
               summary=?, next_action=?, facts_json=?, documents_json=?, related_tasks_json=?, updated_at=?
               WHERE id=?""",
            (
                merged.get("session_id"),
                merged.get("opportunity_id"),
                merged.get("task"),
                merged["status"],
                merged.get("owner") or "Unassigned desk",
                merged.get("summary"),
                merged.get("next_action"),
                dumps(merged.get("facts") or {}),
                dumps(merged.get("documents") or []),
                dumps(related),
                ts,
                case_id,
            ),
        )
        return get_case(case_id)
    execute(
        """INSERT INTO cases (id, session_id, opportunity_id, task, status, owner, summary, next_action,
           facts_json, documents_json, related_tasks_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            case_id,
            partial.get("session_id"),
            partial.get("opportunity_id"),
            partial.get("task"),
            partial.get("status") or "created",
            partial.get("owner") or "Unassigned desk",
            partial.get("summary"),
            partial.get("next_action"),
            dumps(partial.get("facts") or {}),
            dumps(partial.get("documents") or []),
            dumps(partial.get("related_tasks") or []),
            ts,
            ts,
        ),
    )
    return get_case(case_id)


def enqueue_outbox(action_id: str, kind: str, payload: dict) -> dict:
    existing = execute("SELECT * FROM outbox WHERE action_id = ?", (action_id,), fetch="one")
    if existing:
        return existing
    execute(
        """INSERT INTO outbox (action_id, kind, payload_json, status, created_at, updated_at)
           VALUES (?, ?, ?, 'queued', ?, ?)""",
        (action_id, kind, dumps(payload), now(), now()),
    )
    return execute("SELECT * FROM outbox WHERE action_id = ?", (action_id,), fetch="one")


def cancel_unsent(session_id: str, reason: str):
    rows = execute("SELECT * FROM outbox WHERE status = 'queued'", fetch="all") or []
    for row in rows:
        payload = loads(row["payload_json"], {})
        if payload.get("session_id") == session_id:
            execute(
                "UPDATE outbox SET status='cancelled', last_error=?, updated_at=? WHERE id=?",
                (reason, now(), row["id"]),
            )


def mark_outbox(action_id: str, status: str, error: str | None = None):
    execute(
        "UPDATE outbox SET status=?, last_error=?, attempts=attempts+1, updated_at=? WHERE action_id=?",
        (status, error, now(), action_id),
    )


def queued_outbox() -> list[dict]:
    return execute("SELECT * FROM outbox WHERE status = 'queued' ORDER BY id", fetch="all") or []


def set_outbox_zoho(action_id: str, zoho_id: str | None):
    execute("UPDATE outbox SET zoho_id=?, updated_at=? WHERE action_id=?", (zoho_id, now(), action_id))


def list_outbox(session_id: str | None = None, case_id: str | None = None, opportunity_id: str | None = None) -> list[dict]:
    rows = execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 80", fetch="all") or []
    if not session_id and not case_id and not opportunity_id:
        return rows
    matched = []
    for row in rows:
        payload = loads(row.get("payload_json"), {})
        if session_id and payload.get("session_id") == session_id:
            matched.append(row)
            continue
        if case_id and payload.get("case_id") == case_id:
            matched.append(row)
            continue
        if opportunity_id and payload.get("opportunity_id") == opportunity_id:
            matched.append(row)
    return matched


def get_mirror(opportunity_id: str | None) -> dict | None:
    if not opportunity_id:
        return None
    row = execute("SELECT * FROM zoho_mirror WHERE opportunity_id = ?", (opportunity_id,), fetch="one")
    if not row:
        return None
    row["data"] = loads(row.pop("data_json"), {})
    return row


def prefer_zoho_id(incoming: str | None, existing: str | None) -> str:
    """Keep a real Zoho Deal ID once known — never let a synthetic local id replace it."""
    inc = (incoming or "").strip()
    ex = (existing or "").strip()
    if inc and not inc.startswith("zcrm_local_"):
        return inc
    if ex and not ex.startswith("zcrm_local_"):
        return ex
    return inc or ex or uid("zcrm")


def upsert_mirror(partial: dict) -> dict:
    existing = get_mirror(partial.get("opportunity_id"))
    ts = now()
    data = dumps(partial.get("data") or {})
    zoho_id = prefer_zoho_id(partial.get("id"), (existing or {}).get("id"))
    # Drop any stale row that already owns this Deal id under a different inquiry.
    owner = execute("SELECT opportunity_id FROM zoho_mirror WHERE id = ?", (zoho_id,), fetch="one")
    if owner and owner.get("opportunity_id") != partial.get("opportunity_id"):
        execute("DELETE FROM zoho_mirror WHERE id = ?", (zoho_id,))
    if existing:
        old_id = existing.get("id")
        if old_id and old_id != zoho_id:
            # Primary-key change: replace the row so UNIQUE(id) stays consistent.
            execute("DELETE FROM zoho_mirror WHERE opportunity_id = ?", (partial.get("opportunity_id"),))
            execute(
                """INSERT INTO zoho_mirror (id, module, opportunity_id, case_id, session_id, human_version, stage, data_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    zoho_id,
                    partial.get("module") or existing.get("module") or "Deals",
                    partial.get("opportunity_id"),
                    partial.get("case_id") or existing.get("case_id"),
                    partial.get("session_id") or existing.get("session_id"),
                    int(partial.get("human_version") or existing.get("human_version") or 0),
                    partial.get("stage") or existing.get("stage"),
                    data,
                    ts,
                ),
            )
        else:
            execute(
                """UPDATE zoho_mirror SET module=?, case_id=?, session_id=?, human_version=?, stage=?, data_json=?, updated_at=?
                   WHERE opportunity_id=?""",
                (
                    partial.get("module") or existing.get("module"),
                    partial.get("case_id") or existing.get("case_id"),
                    partial.get("session_id") or existing.get("session_id"),
                    int(partial.get("human_version") or existing.get("human_version") or 0),
                    partial.get("stage") or existing.get("stage"),
                    data,
                    ts,
                    partial.get("opportunity_id"),
                ),
            )
        return get_mirror(partial.get("opportunity_id"))
    execute(
        """INSERT INTO zoho_mirror (id, module, opportunity_id, case_id, session_id, human_version, stage, data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            zoho_id,
            partial.get("module") or "Deals",
            partial.get("opportunity_id"),
            partial.get("case_id"),
            partial.get("session_id"),
            int(partial.get("human_version") or 0),
            partial.get("stage"),
            data,
            ts,
        ),
    )
    return get_mirror(partial.get("opportunity_id"))


def add_case_file(case_id: str, review: dict, path: str) -> dict:
    file_id = uid("file")
    execute(
        """INSERT INTO case_files (id, case_id, doc_type, filename, path, extracted_json, flags_json, diff_json,
           version, status, method, ocr_confidence, original_path, requirement_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            file_id,
            case_id,
            review.get("doc_type") or "unknown",
            review.get("filename") or Path(path).name,
            path,
            dumps(review.get("extracted") or {}),
            dumps(review.get("flags") or []),
            dumps(review.get("diff") or []),
            int(review.get("version") or 1),
            review.get("status") or "received",
            review.get("method"),
            review.get("ocr_confidence"),
            review.get("original_path") or path,
            review.get("requirement_id"),
            now(),
        ),
    )
    return get_case_file(file_id)


def get_case_file(file_id: str) -> dict | None:
    row = execute("SELECT * FROM case_files WHERE id = ?", (file_id,), fetch="one")
    return _file_from_row(row) if row else None


def _file_from_row(row: dict) -> dict:
    row["extracted"] = loads(row.pop("extracted_json"), {})
    row["flags"] = loads(row.pop("flags_json"), [])
    row["diff"] = loads(row.pop("diff_json", None), [])
    return row


def list_case_files(case_id: str) -> list[dict]:
    rows = execute("SELECT * FROM case_files WHERE case_id = ? ORDER BY created_at", (case_id,), fetch="all") or []
    return [_file_from_row(r) for r in rows]


def acknowledge_case_files(case_id: str) -> list[dict]:
    execute(
        "UPDATE case_files SET status = 'acknowledged' WHERE case_id = ? AND status = 'flagged'",
        (case_id,),
    )
    execute(
        "UPDATE requirements SET status = 'acknowledged', updated_at = ? WHERE case_id = ? AND status IN ('flagged', 'reopened', 'received')",
        (now(), case_id),
    )
    add_event("Staff acknowledged document flags", {"caseId": case_id})
    return list_case_files(case_id)


def blocking_files(case_id: str) -> list[dict]:
    return [f for f in list_case_files(case_id) if f["status"] == "flagged"]


def latest_file(case_id: str, doc_type: str) -> dict | None:
    row = execute(
        "SELECT * FROM case_files WHERE case_id = ? AND doc_type = ? ORDER BY created_at DESC LIMIT 1",
        (case_id, doc_type),
        fetch="one",
    )
    return _file_from_row(row) if row else None


def add_requirement(partial: dict) -> dict:
    req_id = partial.get("id") or uid("req")
    ts = now()
    execute(
        """INSERT INTO requirements (id, case_id, doc_type, label, status, due_at, current_file_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            req_id,
            partial["case_id"],
            partial["doc_type"],
            partial.get("label") or partial["doc_type"],
            partial.get("status") or "issued",
            partial.get("due_at"),
            partial.get("current_file_id"),
            ts,
            ts,
        ),
    )
    return get_requirement_by_id(req_id)


def get_requirement_by_id(req_id: str) -> dict | None:
    return execute("SELECT * FROM requirements WHERE id = ?", (req_id,), fetch="one")


def get_requirement(case_id: str, doc_type: str) -> dict | None:
    return execute(
        "SELECT * FROM requirements WHERE case_id = ? AND doc_type = ?",
        (case_id, doc_type),
        fetch="one",
    )


def list_requirements(case_id: str) -> list[dict]:
    return execute(
        "SELECT * FROM requirements WHERE case_id = ? ORDER BY created_at",
        (case_id,),
        fetch="all",
    ) or []


def update_requirement(req_id: str, partial: dict) -> dict | None:
    current = get_requirement_by_id(req_id)
    if not current:
        return None
    merged = {**current, **partial}
    execute(
        """UPDATE requirements SET status=?, due_at=?, current_file_id=?, updated_at=? WHERE id=?""",
        (merged.get("status"), merged.get("due_at"), merged.get("current_file_id"), now(), req_id),
    )
    return get_requirement_by_id(req_id)


def get_example_source_by_hash(digest: str) -> dict | None:
    return execute("SELECT * FROM example_sources WHERE sha256 = ?", (digest,), fetch="one")


def save_example_source(partial: dict) -> dict:
    existing = get_example_source_by_hash(partial["sha256"])
    if existing:
        return existing
    row_id = partial.get("id") or uid("exsrc")
    execute(
        """INSERT INTO example_sources (id, filename, sha256, kind, status, pages, method, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row_id,
            partial["filename"],
            partial["sha256"],
            partial.get("kind") or "other",
            partial.get("status") or "ingested",
            int(partial.get("pages") or 0),
            partial.get("method"),
            now(),
        ),
    )
    return execute("SELECT * FROM example_sources WHERE id = ?", (row_id,), fetch="one")


def list_example_sources() -> list[dict]:
    return execute("SELECT * FROM example_sources ORDER BY created_at DESC", fetch="all") or []


def _example_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    row = dict(row)
    row["tags"] = loads(row.pop("tags_json", None), [])
    row["applicability"] = loads(row.pop("applicability_json", None), [])
    row["user"] = row.get("user_text")
    if row.get("status") == "rejected":
        row["status"] = "withdrawn"
    return row


def save_example(partial: dict) -> dict:
    row_id = partial.get("id") or uid("ex")
    current = execute("SELECT * FROM conversation_examples WHERE id = ?", (row_id,), fetch="one")
    status = partial.get("status") or "candidate"
    if status == "rejected":
        status = "withdrawn"
    payload = (
        partial.get("source_id"),
        partial.get("source"),
        partial.get("user_text") or partial.get("user") or "",
        partial.get("context"),
        partial.get("reply") or "",
        partial.get("move"),
        partial.get("variant"),
        dumps(list(partial.get("tags") or [])),
        status,
        partial.get("reviewed_by"),
        int(partial.get("version") or (current or {}).get("version") or 1),
        partial.get("strategy"),
        partial.get("pattern"),
        partial.get("situation") or partial.get("context"),
        dumps(list(partial.get("applicability") or partial.get("tags") or [])),
    )
    if current:
        execute(
            """UPDATE conversation_examples SET source_id=?, source=?, user_text=?, context=?, reply=?,
               move=?, variant=?, tags_json=?, status=?, reviewed_by=?, version=?, strategy=?, pattern=?,
               situation=?, applicability_json=? WHERE id=?""",
            (*payload, row_id),
        )
    else:
        execute(
            """INSERT INTO conversation_examples
               (id, source_id, source, user_text, context, reply, move, variant, tags_json, status, reviewed_by, created_at,
                version, strategy, pattern, situation, applicability_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row_id, *payload[:10], now(), *payload[10:]),
        )
    return _example_from_row(execute("SELECT * FROM conversation_examples WHERE id = ?", (row_id,), fetch="one"))


def list_examples(status: str | None = None) -> list[dict]:
    if status:
        rows = execute(
            "SELECT * FROM conversation_examples WHERE status = ? ORDER BY created_at DESC",
            (status,),
            fetch="all",
        )
    else:
        rows = execute("SELECT * FROM conversation_examples ORDER BY created_at DESC", fetch="all")
    return [_example_from_row(row) for row in rows or []]


def get_example(example_id: str) -> dict | None:
    return _example_from_row(execute("SELECT * FROM conversation_examples WHERE id = ?", (example_id,), fetch="one"))


def _attachment_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    row = dict(row)
    row["vision"] = loads(row.pop("vision_json", None), {})
    return row


def save_attachment(partial: dict) -> dict:
    row_id = partial.get("id") or uid("att")
    current = execute("SELECT * FROM attachments WHERE id = ?", (row_id,), fetch="one")
    payload = (
        partial.get("session_id"),
        partial.get("case_id"),
        partial.get("filename") or "",
        partial.get("path") or "",
        partial.get("sha256") or "",
        partial.get("kind") or "unknown",
        partial.get("ocr_text"),
        partial.get("ocr_confidence"),
        dumps(partial.get("vision") or {}),
        partial.get("vision_status") or "pending",
        now(),
    )
    if current:
        execute(
            """UPDATE attachments SET session_id=?, case_id=?, filename=?, path=?, sha256=?, kind=?,
               ocr_text=?, ocr_confidence=?, vision_json=?, vision_status=?, updated_at=? WHERE id=?""",
            (*payload, row_id),
        )
    else:
        execute(
            """INSERT INTO attachments
               (id, session_id, case_id, filename, path, sha256, kind, ocr_text, ocr_confidence,
                vision_json, vision_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row_id, *payload[:-1], now(), payload[-1]),
        )
    return get_attachment(row_id)


def get_attachment(attachment_id: str) -> dict | None:
    return _attachment_from_row(execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,), fetch="one"))


def get_attachment_by_hash(digest: str, session_id: str | None = None) -> dict | None:
    if session_id:
        return _attachment_from_row(
            execute(
                "SELECT * FROM attachments WHERE session_id = ? AND (sha256 = ? OR sha256 = ?) ORDER BY created_at DESC",
                (session_id, digest, f"{digest}:{session_id}"),
                fetch="one",
            )
        )
    return _attachment_from_row(execute("SELECT * FROM attachments WHERE sha256 = ?", (digest,), fetch="one"))


def list_attachments(session_id: str | None = None, case_id: str | None = None) -> list[dict]:
    if session_id:
        rows = execute(
            "SELECT * FROM attachments WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
            fetch="all",
        )
    elif case_id:
        rows = execute(
            "SELECT * FROM attachments WHERE case_id = ? ORDER BY created_at DESC",
            (case_id,),
            fetch="all",
        )
    else:
        rows = []
    return [_attachment_from_row(row) for row in rows or []]


