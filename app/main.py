import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app import db, docworker, embed, entities, examples, fees, ingest, media, playbook, qwen, requirements, retrieve, second_pass, vision, zoho
from app.graph import _chips, build_graph
from app.knowledge import EQUIP_KEYS, lookup
from app.schema import CHIPS, STAFF_ACTS

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "data" / "checkpoints.db"


class SessionIn(BaseModel):
    page: str | None = None
    equipment: str | None = None


class TurnIn(BaseModel):
    session_id: str
    text: str
    turn_id: str | None = None
    equipment: str | None = None


class StaffAct(BaseModel):
    act: str


class RequirementDecision(BaseModel):
    decision: str
    reviewer: str
    reason: str = ""
    file_id: str | None = None


class FeeIn(BaseModel):
    arrangement: str = "dispatch_service"
    percent: float
    approved_by: str = "Staff desk"


def _ensure_onboarding_case(session: dict) -> dict:
    """Create a draft onboarding case when a document arrives before handoff."""
    if session.get("case_id"):
        current = db.get_case(session["case_id"])
        if current:
            return current
    from app.rules import arrangement_of, task_for
    from app.tasks import persist_human_task

    arrangement = arrangement_of(session.get("facts") or {})
    task = task_for(arrangement, "onboard") or "setup_packet"
    return persist_human_task(
        session,
        task,
        "collecting_documents",
        "Await documents for review — chat stays open",
        "Onboarding draft opened from upload",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT)) as saver:
        app.state.graph = build_graph(saver)

        async def boot():
            await asyncio.to_thread(ingest.seed_reviewed_bank)
            await qwen.warmup()
            # Embeddings use EMBED_URL (MiniLM), never the chat process. Skip unchanged hashes.
            await asyncio.to_thread(examples.reload_index)
            await asyncio.to_thread(examples.ensure_embeddings)
            await asyncio.to_thread(retrieve.build_index)

        boot_task = asyncio.create_task(boot())
        try:
            yield
        finally:
            boot_task.cancel()
            await asyncio.gather(boot_task, return_exceptions=True)
            await qwen.close()


app = FastAPI(title="Ayyan sales assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(qwen.InferenceBusy)
async def inference_busy(request: Request, exc: qwen.InferenceBusy):
    return JSONResponse(status_code=503, headers={"Retry-After": "2"}, content={"detail": str(exc)})


@app.get("/v1/health")
def health():
    n = second_pass.count()
    reviewed = second_pass.reviewed_count()
    return {
        "ok": True,
        "model": (qwen.last_route or {}).get("model") or qwen.MODEL,
        "qwen_ready": qwen.ready,
        "gemma_ready": qwen.gemma_ready,
        "qwen_error": qwen.last_error,
        "last_route": qwen.last_route,
        "qwen_runtime": qwen.status(),
        "retrieve": retrieve.status(),
        "embed": embed.status(),
        "image_embed": vision.status(),
        "vision": {
            "ready": qwen.vision_ready,
            "enabled": qwen.vision_enabled(),
            "model": qwen.VISION_MODEL,
        },
        "hard_turns": n,
        "hard_turns_reviewed": reviewed,
        "peft_ready": reviewed >= 1000,
        "distill_ready": False,
        "zoho": zoho.connection(),
    }


def _seed_equipment(value: str | None) -> dict:
    if not value:
        return {}
    key = value.strip().lower().replace(" ", "_")
    if key not in EQUIP_KEYS:
        return {}
    return {
        "equipment": {
            "value": key,
            "status": "user_stated",
            "sourceChannel": "page",
            "version": 1,
            "previous": None,
        }
    }


@app.post("/v1/session")
def open_session(body: SessionIn | None = None):
    body = body or SessionIn()
    seed = _seed_equipment(body.equipment)
    session = db.create_session(seed)
    zoho.queue_inquiry(session, body.page)
    zoho.drain()
    text = lookup("welcome")
    chips = CHIPS["open"]
    if seed:
        from app.knowledge import lookup as kn

        text = kn(EQUIP_KEYS[seed["equipment"]["value"]]) + " " + kn("welcome").split(". ", 1)[-1]
        chips = CHIPS["primaryProblem"]
    return {
        "session_id": session["id"],
        "opportunity_id": session["opportunity_id"],
        "channel": session["channel"],
        "text": text,
        "chips": chips,
    }


@app.get("/v1/session/{session_id}")
def session_history(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    messages = [{"role": row["role"], "text": row["text"]} for row in db.list_messages(session_id)]
    mem = session.get("memory") or {}
    ask = playbook.next_ask(session.get("facts") or {}, mem, intent=None, repair=mem.get("repair"))
    return {
        "session_id": session["id"],
        "opportunity_id": session["opportunity_id"],
        "case_id": session.get("case_id"),
        "channel": session["channel"],
        "conversation_state": session["conversation_state"],
        "state_version": session["state_version"],
        "takeover": session["takeover"],
        "messages": messages,
        "chips": CHIPS["open"] if not messages else _chips(session, {"next_field": ask}),
        "text": None if messages else lookup("welcome"),
        "memory": session.get("memory") or {},
        "desk": playbook.desk_card(session),
    }


@app.post("/v1/turn")
async def turn(body: TurnIn, background: BackgroundTasks):
    session = db.get_session(body.session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    replay = db.get_turn(body.turn_id)
    if replay:
        return replay
    db.add_message(session["id"], "user", body.text)
    result = await app.state.graph.ainvoke(
        {"session": session, "user_text": body.text, "traces": [{"_reset": True}]},
        {"configurable": {"thread_id": session["id"]}},
    )
    session = result["session"]
    db.save_session(session)
    db.add_message(session["id"], "assistant", result["reply_text"])
    payload = {
        "session_id": session["id"],
        "opportunity_id": session["opportunity_id"],
        "case_id": session.get("case_id"),
        "channel": session["channel"],
        "conversation_state": session["conversation_state"],
        "state_version": session["state_version"],
        "text": result["reply_text"],
        "chips": result.get("chips") or [],
        "traces": result.get("traces") or [],
        "takeover": session["takeover"],
        "fit_summary": session.get("fit_summary"),
        "desk": playbook.desk_card(session),
        "zoho": zoho.sync_status(session_id=session["id"], case_id=session.get("case_id"), opportunity_id=session.get("opportunity_id")),
    }
    if body.turn_id:
        db.save_turn(body.turn_id, session["id"], body.text, payload)
    background.add_task(zoho.drain)
    return payload


@app.get("/v1/cases")
def cases():
    return db.list_cases()


@app.get("/v1/cases/{case_id}")
def case_detail(case_id: str):
    row = db.get_case(case_id)
    if not row:
        raise HTTPException(404, "unknown case")
    row["files"] = db.list_case_files(case_id)
    seen = set()
    attachments = []
    sources = []
    if row.get("session_id"):
        sources.extend(db.list_attachments(session_id=row["session_id"]))
    sources.extend(db.list_attachments(case_id=case_id))
    for att in sources:
        if att["id"] in seen:
            continue
        seen.add(att["id"])
        attachments.append(media.public_row(att))
    row["attachments"] = attachments
    row["blocking"] = db.blocking_files(case_id)
    row["entities"] = entities.resolve(case_id)
    row["packet"] = requirements.snapshot(case_id)
    row["zoho"] = zoho.sync_status(session_id=row.get("session_id"), case_id=case_id, opportunity_id=row.get("opportunity_id"))
    if row.get("session_id"):
        linked = db.get_session(row["session_id"])
        if linked:
            row["desk"] = playbook.desk_card(linked)
    return row


@app.get("/v1/zoho/status")
def zoho_status(session_id: str | None = None, case_id: str | None = None, opportunity_id: str | None = None):
    status = zoho.sync_status(session_id=session_id, case_id=case_id, opportunity_id=opportunity_id)
    status["connection"] = zoho.connection()
    return status


@app.get("/v1/zoho/connect")
def zoho_connect():
    if not zoho.connection()["client_configured"]:
        raise HTTPException(400, "Zoho client id/secret are not configured")
    return RedirectResponse(zoho.auth_url())


@app.get("/v1/zoho/callback")
def zoho_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, error)
    if not code:
        raise HTTPException(400, "missing Zoho authorization code")
    accounts = request.query_params.get("accounts-server")
    try:
        zoho.exchange_code(code, accounts_server=accounts)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    zoho.drain()
    return RedirectResponse("/staff.html?zoho=connected")


class ZohoGrantIn(BaseModel):
    code: str
    accounts_server: str | None = None


@app.post("/v1/zoho/self-client")
def zoho_self_client(body: ZohoGrantIn):
    try:
        zoho.exchange_code(body.code.strip(), accounts_server=body.accounts_server)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    zoho.drain()
    return zoho.connection()


class ExampleReview(BaseModel):
    status: str
    reply: str | None = None
    reviewed_by: str = "Staff desk"


@app.get("/v1/examples")
def list_conversation_examples(status: str | None = None):
    return {
        "index": examples.reload_index(),
        "sources": db.list_example_sources(),
        "examples": db.list_examples(status),
        "published_ids": [row["id"] for row in examples.published() if examples.allowed(row)],
    }


@app.post("/v1/examples/ingest")
async def ingest_example_file(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.bin").suffix or ".bin"
    dest = ROOT / "data" / "example_uploads" / f"{db.uid('up')}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    try:
        result = ingest.ingest_path(dest)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.post("/v1/examples/{example_id}/review")
def review_example(example_id: str, body: ExampleReview):
    if body.status not in {"published", "rejected", "candidate", "reviewed", "withdrawn"}:
        raise HTTPException(400, "status must be candidate, reviewed, published, or withdrawn")
    current = db.get_example(example_id)
    if not current:
        raise HTTPException(404, "unknown example")
    reply = body.reply if body.reply is not None else current["reply"]
    if body.status == "published" and not examples.allowed({**current, "reply": reply, "user": current.get("user_text")}):
        raise HTTPException(400, "example still contains blocked commercial claims")
    saved = db.save_example({**current, "reply": reply, "status": body.status, "reviewed_by": body.reviewed_by})
    examples.reload_index()
    return saved


@app.get("/v1/eval/hard-turns")
def hard_turns():
    n = second_pass.count()
    reviewed = second_pass.reviewed_count()
    return {
        "count": n,
        "reviewed": reviewed,
        "peft_ready": reviewed >= 1000,
        "distill_ready": False,
        "note": "LoRA/distill wait for ~1,000 reviewed failures. Fees are never training labels.",
    }


@app.get("/v1/fees")
def get_fees():
    return {"fees": fees.list_fees(), "quote_dispatch": fees.live_quote("dispatch_service"), "quote_lease": fees.live_quote("lease_on")}


@app.post("/v1/fees")
def post_fee(body: FeeIn):
    try:
        row = fees.publish(body.arrangement, body.percent, body.approved_by)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return row


async def _interpret_later(attachment_id: str) -> None:
    await asyncio.to_thread(media.interpret, attachment_id)


@app.post("/v1/session/{session_id}/attachment")
async def upload_attachment(session_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    suffix = Path(file.filename or "upload.bin").suffix or ".bin"
    dest = ROOT / "data" / "attachments" / session_id / f"{db.uid('up')}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    case = _ensure_onboarding_case(session)
    session = db.get_session(session_id) or session
    result = await asyncio.to_thread(media.process, dest, session_id, case.get("id"), False)
    att_id = result.get("id")
    attachment = result.get("attachment") or (db.get_attachment(att_id) if att_id else None)
    case_file = None
    if attachment and result.get("status") != "duplicate":
        case_file = await asyncio.to_thread(
            docworker.ingest_upload,
            case["id"],
            Path(attachment.get("path") or dest),
            attachment,
        )
        if att_id and case_file:
            db.save_attachment({**attachment, "case_id": case["id"]})
    queue_vision = (
        bool(att_id)
        and result.get("status") != "duplicate"
        and result.get("kind") != "screenshot"
        and result.get("vision_status") == "pending"
    )
    if queue_vision:
        background.add_task(_interpret_later, att_id)
    db.add_message(session_id, "user", f"[attachment] {file.filename}")
    db.save_session(session)
    receipt = lookup("docs_review_pending") if case_file else lookup("photo_unverified")
    return {
        **result,
        "text": receipt,
        "queued_vision": queue_vision,
        "case_id": case.get("id"),
        "case_file_id": (case_file or {}).get("id"),
        "doc_type": (case_file or {}).get("doc_type"),
        "packet": requirements.snapshot(case["id"]),
        "takeover": False,
    }


@app.get("/v1/session/{session_id}/attachments")
def session_attachments(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "unknown session")
    return {"attachments": [media.public_row(row) for row in db.list_attachments(session_id=session_id)]}


@app.get("/v1/cases/{case_id}/files")
def case_files(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "unknown case")
    return db.list_case_files(case_id)


@app.post("/v1/cases/{case_id}/review-packet")
def review_packet(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "unknown case")
    saved = docworker.ingest_sample(case_id)
    case = db.get_case(case_id)
    if case:
        zoho.queue_stage(case, "received", "under_review", "Human review of flagged clauses — not approval")
        zoho.drain()
    return {"files": saved, "blocking": db.blocking_files(case_id), "packet": requirements.snapshot(case_id)}


@app.post("/v1/cases/{case_id}/acknowledge-flags")
def ack_flags(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(404, "unknown case")
    # Acknowledge warnings only — does not approve documents or handoff readiness.
    return {"files": db.acknowledge_case_files(case_id), "packet": requirements.snapshot(case_id), "note": "ack_is_not_approval"}


@app.post("/v1/cases/{case_id}/requirements/{doc_type}/decide")
def decide_requirement(case_id: str, doc_type: str, body: RequirementDecision):
    if not db.get_case(case_id):
        raise HTTPException(404, "unknown case")
    try:
        row = requirements.decide(
            case_id,
            doc_type,
            body.decision,
            reviewer=body.reviewer,
            reason=body.reason,
            file_id=body.file_id,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"requirement": row, "packet": requirements.snapshot(case_id)}


@app.post("/v1/cases/{case_id}/act")
def case_act(case_id: str, body: StaffAct):
    if body.act not in STAFF_ACTS:
        raise HTTPException(400, "unknown act")
    current = db.get_case(case_id)
    if not current:
        raise HTTPException(404, "unknown case")
    if body.act == "approve" and db.blocking_files(case_id):
        raise HTTPException(409, "Acknowledge flagged COI/lease issues before human approval. The worker cannot approve.")
    if body.act == "approve":
        ready, blockers = requirements.ready_for_handoff(case_id)
        if not ready:
            raise HTTPException(
                409,
                "All applicable requirements must be approved or waived before handoff. Outstanding: "
                + ", ".join(blockers),
            )
    if body.act == "packet_sent":
        requirements.issue(case_id, current.get("task"), facts=current.get("facts") or {})
        requirements.mark_due(case_id)
    status, next_action, document = STAFF_ACTS[body.act]
    docs = list(current.get("documents") or [])
    if document:
        docs.append(document)
    saved = db.upsert_case(
        {
            "id": case_id,
            "status": status,
            "next_action": next_action,
            "documents": docs,
            "facts": current.get("facts") or {},
            "session_id": current.get("session_id"),
            "opportunity_id": current.get("opportunity_id"),
            "task": current.get("task"),
            "summary": current.get("summary"),
            "owner": current.get("owner") or "Unassigned desk",
        }
    )
    if body.act == "takeover" and current.get("session_id"):
        session = db.get_session(current["session_id"])
        if session:
            session["takeover"] = True
            db.save_session(session)
    db.add_event(f"Staff: {body.act}", {"caseId": case_id})
    zoho.queue_stage(saved, body.act, status, next_action)
    zoho.drain()
    saved["zoho"] = zoho.sync_status(session_id=saved.get("session_id"), case_id=case_id, opportunity_id=saved.get("opportunity_id"))
    return saved


app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="site")
