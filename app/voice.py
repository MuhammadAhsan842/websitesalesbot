"""Browser media grants and trusted worker bridge; media never enters the graph.

Opt-in, single-API-process pilot. Existing chat APIs are still demo APIs: this
capability protects the new voice endpoints, not the entire legacy application.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import db

router = APIRouter(prefix="/v1/voice", tags=["browser voice"])
LIVE_STATUSES = ("connecting", "connected")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_access(session_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO voice_access(session_id,token_hash) VALUES (?,?)", (session_id, digest(token)))
    return token


def verify_access(session_id: str, token: str | None):
    with db.connect() as conn:
        row = conn.execute("SELECT token_hash FROM voice_access WHERE session_id=?", (session_id,)).fetchone()
    if not row or not token or not hmac.compare_digest(row["token_hash"], digest(token)):
        raise HTTPException(403, "Voice session access is missing. Start a new chat in this browser.")


def verify_worker(authorization: str | None):
    secret = os.getenv("VOICE_WORKER_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(403, "Worker authentication required")


def capabilities() -> dict:
    configured = all(os.getenv(key) for key in (
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "VOICE_WORKER_SECRET"))
    with db.connect() as conn:
        row = conn.execute("SELECT MAX(heartbeat) AS latest FROM voice_workers").fetchone()
    ready = bool(row and row["latest"] and row["latest"] > time.time() - 30)
    enabled = os.getenv("VOICE_ENABLED", "0") == "1"
    return {"available": enabled and configured and ready, "configured": enabled and configured,
            "worker_ready": ready, "profile": os.getenv("VOICE_PROFILE", "owner"),
            "reason": None if enabled and configured and ready else "Browser voice is not ready. You can continue in chat."}


def connection(connection_id: str) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM voice_connections WHERE id=?", (connection_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown voice connection")
    return dict(row)


def require_live(row: dict):
    if row["status"] not in LIVE_STATUSES or row["expires"] <= time.time():
        raise HTTPException(409, "Voice connection ended. Continue in chat or reconnect.")
    session = db.get_session(row["session_id"])
    if not session or session.get("takeover") or session.get("manager_accepted"):
        raise HTTPException(409, "A staff member has taken over this inquiry.")
    return session


def public_connection(row: dict) -> dict:
    live = row["status"] in LIVE_STATUSES and row["expires"] > time.time()
    return {"id": row["id"], "status": row["status"] if live else "ended",
            "connected": live and row["status"] == "connected"}


@asynccontextmanager
async def conversation_lock(session_id: str):
    """Cross-process admission; never keep a SQLite transaction open during inference.

    A bounded invocation finishes before this lease expires. Crashed writers are
    recovered by lease expiry; no speculative transcript is submitted here.
    """
    owner = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM conversation_locks WHERE session_id=? AND expires<?", (session_id, time.time()))
        try:
            conn.execute("INSERT INTO conversation_locks VALUES (?,?,?)", (session_id, owner, time.time() + 190))
        except sqlite3.IntegrityError as error:
            conn.rollback()
            if "UNIQUE constraint failed" not in str(error):
                raise
            raise HTTPException(409, "Another conversation turn is processing. Please wait.") from error
    try:
        async with asyncio.timeout(180):
            yield
    finally:
        db.execute("DELETE FROM conversation_locks WHERE session_id=? AND owner=?", (session_id, owner))


class GrantIn(BaseModel):
    session_id: str


class WorkerEvent(BaseModel):
    sequence: int = Field(ge=1)
    event: str = Field(pattern="^(connected|heartbeat|disconnected|playback_completed|playback_interrupted|failed)$")
    speech_id: str | None = Field(default=None, max_length=150)
    spoken_text: str | None = Field(default=None, max_length=5000)


class VoiceTurn(BaseModel):
    utterance_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)


@router.get("/capabilities")
def get_capabilities():
    return capabilities()


@router.post("/worker/heartbeat")
def worker_heartbeat(authorization: str | None = Header(default=None)):
    verify_worker(authorization)
    db.execute("INSERT INTO voice_workers VALUES (?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat", ("local-agent", time.time()))
    return {"ok": True}


@router.post("/connect")
async def connect(body: GrantIn, x_inquiry_token: str | None = Header(default=None)):
    verify_access(body.session_id, x_inquiry_token)
    if not capabilities()["available"]:
        raise HTTPException(503, "Browser voice is not ready. Continue in chat.")
    session = db.get_session(body.session_id)
    if session.get("takeover") or session.get("manager_accepted"):
        raise HTTPException(409, "A staff member has this inquiry.")
    connection_id = uuid.uuid4().hex
    room = "ayyan-" + connection_id
    worker_token = secrets.token_urlsafe(32)
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # One CPU voice session at a time for the first pilot.
        active = conn.execute("SELECT id FROM voice_connections WHERE status IN ('connecting','connected') AND expires>?", (now,)).fetchone()
        if active:
            raise HTTPException(409, "Voice is busy. Continue in chat or try again shortly.")
        conn.execute("INSERT INTO voice_connections(id,session_id,room,token_hash,status,expires,heartbeat) VALUES (?,?,?,?,?,?,?)",
                     (connection_id, body.session_id, room, digest(worker_token), "connecting", now + 60, now))
    try:
        from livekit import api
        import json
        # Dispatch metadata is never returned to the visitor.
        metadata = json.dumps({"connection_id": connection_id, "worker_token": worker_token})
        async with api.LiveKitAPI() as livekit:
            await livekit.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=60, max_participants=2))
            await livekit.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                room=room, agent_name="ayyan-voice", metadata=metadata))
        grant = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
                 .with_identity("visitor-" + connection_id).with_ttl(timedelta(minutes=5))
                 .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True,
                                              can_subscribe=True, can_publish_data=False, can_publish_sources=["microphone"],
                                              can_update_own_metadata=False)))
        token = grant.to_jwt()
    except Exception as exc:
        db.execute("UPDATE voice_connections SET status='failed',expires=0 WHERE id=?", (connection_id,))
        raise HTTPException(503, "Voice connection could not be prepared. Continue in chat.") from exc
    return {"connection_id": connection_id, "url": os.environ["LIVEKIT_URL"], "token": token,
            "profile": os.getenv("VOICE_PROFILE", "owner"), "expires_in": 60}


@router.get("/{connection_id}")
def progress(connection_id: str, x_inquiry_token: str | None = Header(default=None)):
    row = connection(connection_id)
    verify_access(row["session_id"], x_inquiry_token)
    return public_connection(row)


@router.delete("/{connection_id}")
def disconnect(connection_id: str, x_inquiry_token: str | None = Header(default=None)):
    row = connection(connection_id)
    verify_access(row["session_id"], x_inquiry_token)
    db.execute("UPDATE voice_connections SET status='ended',expires=0 WHERE id=?", (connection_id,))
    return {"status": "ended", "connected": False}


def trusted_connection(connection_id: str, authorization: str | None, x_voice_token: str | None):
    verify_worker(authorization)
    row = connection(connection_id)
    if not x_voice_token or not hmac.compare_digest(digest(x_voice_token), row["token_hash"]):
        raise HTTPException(403, "Connection capability required")
    return row


@router.post("/{connection_id}/events")
def worker_event(connection_id: str, body: WorkerEvent, authorization: str | None = Header(default=None),
                 x_voice_token: str | None = Header(default=None)):
    row = trusted_connection(connection_id, authorization, x_voice_token)
    # Ending an already-ended connection is harmless; nothing may resurrect it.
    if body.event in {"disconnected", "failed"}:
        status, expires = ("ended" if body.event == "disconnected" else "failed"), 0
    else:
        require_live(row)
        status, expires = ("connected" if body.event == "connected" else row["status"]), time.time() + 45
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("UPDATE voice_connections SET status=?,expires=?,heartbeat=?,event_seq=? WHERE id=? AND event_seq<? AND status IN ('connecting','connected')",
                               (status, expires, time.time(), body.sequence, connection_id, body.sequence)).rowcount
        if changed:
            conn.execute("INSERT INTO events(message,extra_json,created_at) VALUES (?,?,?)",
                         ("Voice: " + body.event, db.dumps({"sessionId": row["session_id"], "connectionId": connection_id,
                          "speechId": body.speech_id, "spokenText": body.spoken_text}), db.now()))
    return public_connection(connection(connection_id))


@router.post("/{connection_id}/turn")
async def committed_turn(connection_id: str, body: VoiceTurn, request: Request, background: BackgroundTasks,
                         authorization: str | None = Header(default=None), x_voice_token: str | None = Header(default=None)):
    row = trusted_connection(connection_id, authorization, x_voice_token)
    require_live(row)
    if row["status"] != "connected":
        raise HTTPException(409, "Media is not connected")
    from app.main import TurnIn, turn
    # Same turn endpoint, reducer, graph, action gates and idempotent receipt as chat.
    reply = await turn(TurnIn(session_id=row["session_id"], text=body.text.strip(),
                              turn_id="voice:" + connection_id + ":" + body.utterance_id), background)
    # A disconnect/takeover while inference runs invalidates speech, not an already committed action.
    current = connection(connection_id)
    try:
        require_live(current)
        speak = True
    except HTTPException:
        speak = False
    return {"text": reply["text"], "speak": speak and not reply.get("manager_accepted"),
            "turn_id": body.utterance_id, "state_version": reply["state_version"]}
