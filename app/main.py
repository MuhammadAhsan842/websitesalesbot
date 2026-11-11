import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app import db, docworker, embed, entities, examples, fees, ingest, media, playbook, llm, requirements, retrieve, second_pass, vision, workflows, zoho, voice
from app.graph import _chips, build_graph
from app.knowledge import EQUIP_KEYS, lookup
from app.schema import CHIPS, STAFF_ACTS, chip_options
from app.site import PublicSite

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "data" / "checkpoints.db"


class SessionIn(BaseModel):
    page: str | None = None
    equipment: str | None = None
    name: str | None = None
    email: str | None = None


class ChipIn(BaseModel):
    label: str | None = None
    field: str | None = None
    value: str | int | float | None = None
    autoLiabilityCoverage: str | None = None
    cargoCoverage: str | None = None
    requestedArrangement: str | None = None


class TurnIn(BaseModel):
    session_id: str
    text: str
    turn_id: str | None = None
    equipment: str | None = None
    chip: ChipIn | None = None


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

    facts = session.get("facts") or {}
    arrangement = arrangement_of(facts)
    task = task_for(arrangement, "onboard", facts) or "setup_packet"
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

        # Warm the chat model before accepting turns — background warmup used to hold the
        # single CPU slot while the UI already sent /v1/turn, causing 60–120s hangs then 503.
        await asyncio.to_thread(ingest.seed_reviewed_bank)
        await asyncio.to_thread(fees.ensure_own_mc_equipment_schedule)
        await llm.warmup()

        async def boot_index():
            # Embeddings use EMBED_URL (nomic-embed-text), never the chat process. Skip unchanged hashes.
            await asyncio.to_thread(examples.reload_index)
            await asyncio.to_thread(examples.ensure_embeddings)
            await asyncio.to_thread(retrieve.build_index)

        boot_task = asyncio.create_task(boot_index())
        try:
            yield
        finally:
            boot_task.cancel()
            await asyncio.gather(boot_task, return_exceptions=True)
            await llm.close()


app = FastAPI(title="Ayyan sales assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(voice.router)


@app.exception_handler(llm.InferenceBusy)
async def inference_busy(request: Request, exc: llm.InferenceBusy):
    return JSONResponse(status_code=503, headers={"Retry-After": "2"}, content={"detail": str(exc)})


@app.exception_handler(db.WorkflowConflict)
async def workflow_conflict(request: Request, exc: db.WorkflowConflict):
    return JSONResponse(status_code=409, content={"detail": "This inquiry changed during your request. Reload its progress and retry."})


@app.get("/v1/health")
def health():
    n = second_pass.count()
    reviewed = second_pass.reviewed_count()
    return {
        "ok": True,
        "model": (llm.last_route or {}).get("model") or llm.MODEL,
        "llm_ready": llm.ready,
        "gemma_ready": llm.gemma_ready,
        "llm_error": llm.last_error,
        "last_route": llm.last_route,
        "llm_runtime": llm.status(),
        "gemini": __import__("app.gemini", fromlist=["status"]).status(),
        "retrieve": retrieve.status(),
        "embed": embed.status(),
        "image_embed": vision.status(),
        "vision": {
            "ready": llm.vision_ready,
            "enabled": llm.vision_enabled(),
            "model": llm.VISION_MODEL,
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
    seed = _seed_equipment(body.equipment) or {}
    name = (body.name or "").strip() or None
    email = (body.email or "").strip().lower() or None
    if name:
        seed["name"] = {"value": name, "status": "user_stated"}
    if email:
        seed["email"] = {"value": email, "status": "user_stated"}
    session = db.create_session(seed or None)
    zoho.queue_inquiry(session, body.page)
    try:
        zoho.drain()
    except Exception:
        # Never block opening chat on CRM/sqlite contention — outbox retries later.
        pass
    ask = "open"
    if name:
        first = name.split()[0]
        text = lookup("welcome_lead").format(name=first)
    else:
        text = lookup("welcome")
    if body.equipment and seed.get("equipment"):
        from app.knowledge import lookup as kn

        text = kn(EQUIP_KEYS[seed["equipment"]["value"]]) + " How can I help you today?"
        ask = "primaryProblem"
    session["manager_requested"] = False
    session["manager_accepted"] = False
    db.save_session(session)
    return {
        "session_id": session["id"],
        "voice_access_token": voice.issue_access(session["id"]),
        "opportunity_id": session["opportunity_id"],
        "channel": session["channel"],
        "text": text,
        "chips": chip_options(ask) if ask != "open" else [
            {"label": label, "field": None, "value": label} for label in CHIPS["open"]
        ],
        "manager_requested": False,
        "manager_accepted": False,
        "name": name,
        "email": email,
    }


@app.get("/v1/session/{session_id}")
def session_history(session_id: str):
    from app.tasks import fact_value

    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    messages = [{"role": row["role"], "text": row["text"]} for row in db.list_messages(session_id)]
    mem = session.get("memory") or {}
    ask = playbook.next_ask(session.get("facts") or {}, mem, intent=None, repair=mem.get("repair"))
    name = fact_value(session.get("facts") or {}, "name")
    email = fact_value(session.get("facts") or {}, "email")
    if messages:
        intro = None
    elif name:
        intro = lookup("welcome_lead").format(name=str(name).split()[0])
    else:
        intro = lookup("welcome")
    return {
        "session_id": session["id"],
        "opportunity_id": session["opportunity_id"],
        "case_id": session.get("case_id"),
        "channel": session["channel"],
        "conversation_state": session["conversation_state"],
        "state_version": session["state_version"],
        "takeover": session["takeover"],
        "manager_requested": bool(session.get("manager_requested")),
        "manager_accepted": bool(session.get("manager_accepted")),
        "messages": messages,
        "chips": [] if workflows.callback_pending(session) else (
            [{"label": label, "field": None, "value": label} for label in CHIPS["open"]]
            if not messages
            else chip_options(ask) if ask else [{"label": label, "field": None, "value": label} for label in _chips(session, {"next_field": ask})]
        ),
        "text": intro,
        "memory": session.get("memory") or {},
        "desk": playbook.desk_card(session),
        "workflows": workflows.public_state(session),
        "name": name,
        "email": email,
    }


@app.post("/v1/turn")
async def turn(body: TurnIn, background: BackgroundTasks):
    if not db.get_session(body.session_id):
        raise HTTPException(404, "unknown session")
    async with voice.conversation_lock(body.session_id):
        return await _turn(body, background)


async def _turn(body: TurnIn, background: BackgroundTasks):
    session = db.get_session(body.session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    replay = db.get_turn(body.turn_id, session["id"])
    if replay:
        return replay
    db.add_message(session["id"], "user", body.text)
    chip_payload = body.chip.model_dump(exclude_none=True) if body.chip else None
    result = await app.state.graph.ainvoke(
        {
            "session": session,
            "user_text": body.text,
            "chip": chip_payload,
            "traces": [{"_reset": True}],
        },
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
        "manager_requested": bool(session.get("manager_requested")),
        "manager_accepted": bool(session.get("manager_accepted")),
        "fit_summary": session.get("fit_summary"),
        "desk": playbook.desk_card(session),
        "workflows": workflows.public_state(session),
        "zoho": zoho.sync_status(session_id=session["id"], case_id=session.get("case_id"), opportunity_id=session.get("opportunity_id")),
    }
    propose = next((t for t in (result.get("traces") or []) if t.get("stage") == "propose"), {})
    if propose.get("thinking"):
        payload["thinking"] = propose["thinking"]
        payload["model_wording"] = propose.get("wording")
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
    row["components"] = db.list_document_components(case_id)
    row["verifications"] = db.list_verification_records(case_id)
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
            row["workflows"] = workflows.public_state(linked)
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


_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
_UPLOAD_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
_UPLOAD_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "application/octet-stream",
}


def _upload_magic_ok(data: bytes, suffix: str) -> bool:
    if not data:
        return False
    low = suffix.lower()
    if low == ".pdf":
        return data.startswith(b"%PDF")
    if low in {".png"}:
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if low in {".jpg", ".jpeg"}:
        return data[:3] == b"\xff\xd8\xff"
    return False


def _doc_label(doc_type: str | None, packet: dict | None = None) -> str:
    wanted = str(doc_type or "unknown")
    for row in (packet or {}).get("requirements") or []:
        if row.get("doc_type") == wanted and row.get("label"):
            return row["label"]
    labels = {
        "coi": "certificate of insurance",
        "licence": "driving licence",
        "registration": "truck registration",
        "equipment_photos": "truck photos",
        "w9": "W-9",
        "authority": "operating-authority evidence",
        "notice_of_assignment": "notice of assignment",
        "voided_check": "voided check",
        "unknown": "document",
    }
    return labels.get(wanted, wanted.replace("_", " "))


@app.get("/v1/session/{session_id}/upload-options")
def session_upload_options(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    case = db.get_case(session["case_id"]) if session.get("case_id") else None
    task = (case or {}).get("task")
    facts = session.get("facts") or {}
    options = requirements.customer_upload_options(task, facts)
    return {
        "session_id": session_id,
        "case_id": (case or {}).get("id"),
        "task": task,
        "options": options,
        "accept": ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png",
        "max_bytes": _UPLOAD_MAX_BYTES,
        "note": "Upload completion means received, not approved.",
    }


@app.post("/v1/session/{session_id}/attachment")
async def upload_attachment(
    session_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str | None = Form(None),
):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    raw_name = file.filename or "upload.bin"
    suffix = Path(raw_name).suffix.lower() or ".bin"
    if suffix not in _UPLOAD_EXT:
        raise HTTPException(400, "Only PDF, JPG, or PNG files are accepted.")
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in _UPLOAD_MIME:
        raise HTTPException(400, "Unsupported file type. Use PDF, JPG, or PNG.")
    data = await file.read()
    if len(data) > _UPLOAD_MAX_BYTES:
        raise HTTPException(400, "File is too large. Maximum size is 10 MB.")
    if not _upload_magic_ok(data, suffix):
        raise HTTPException(400, "File content does not match a PDF, JPG, or PNG.")
    # Lightweight scan gate — reject obvious script payloads in image/pdf wrappers.
    head = data[:512].lower()
    if b"<script" in head or b"<?php" in head:
        raise HTTPException(400, "File failed the upload safety check.")
    dest = ROOT / "data" / "attachments" / session_id / f"{db.uid('up')}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    case = _ensure_onboarding_case(session)
    # Persist case linkage before any reload; a DB reload must not wipe case_id.
    session["case_id"] = case["id"]
    db.save_session(session)
    session = db.get_session(session_id) or session
    if not session.get("case_id"):
        session["case_id"] = case["id"]
        db.save_session(session)
    suggested = (doc_type or "").strip().lower() or None
    result = await asyncio.to_thread(media.store_stub, dest, session_id, case.get("id"))
    att_id = result.get("id")
    attachment = result.get("attachment") or (db.get_attachment(att_id) if att_id else None)
    if attachment:
        db.save_attachment({**attachment, "case_id": case["id"]})
    requirements.issue(case["id"], case.get("task"), facts=case.get("facts") or {})
    resolved_type = suggested or "unknown"
    if suggested and suggested not in {"unknown", "none", "null"}:
        requirements.receive(case["id"], suggested, None, "checking")
    job = db.add_review_job(
        {
            "case_id": case["id"],
            "session_id": session_id,
            "attachment_id": att_id,
            "path": str((attachment or {}).get("path") or dest),
            "suggested_doc_type": suggested,
            "status": "queued",
        }
    )
    background.add_task(docworker.run_review_job, job["id"])
    packet = requirements.snapshot(case["id"])
    label = _doc_label(resolved_type, packet)
    if resolved_type in {None, "", "unknown"}:
        receipt = lookup("docs_upload_unknown")
    else:
        receipt = lookup("docs_upload_received").format(label=label.lower())
    db.add_message(session_id, "user", f"[attachment] {raw_name} ({resolved_type})")
    db.add_message(session_id, "assistant", receipt)
    session["case_id"] = case["id"]
    db.save_session(session)
    return {
        **result,
        "text": receipt,
        "queued_vision": False,
        "queued_review": True,
        "review_job_id": job["id"],
        "case_id": case.get("id"),
        "case_file_id": None,
        "doc_type": resolved_type,
        "doc_label": label,
        "requirement_status": requirements.customer_status_label("checking"),
        "packet": packet,
        "takeover": False,
        "not_approval": True,
        "unverified": True,
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
async def case_act(case_id: str, body: StaffAct):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(404, "unknown case")
    if case.get("session_id"):
        async with voice.conversation_lock(case["session_id"]):
            return await asyncio.to_thread(_case_act, case_id, body)
    return await asyncio.to_thread(_case_act, case_id, body)


def _case_act(case_id: str, body: StaffAct):
    if body.act not in STAFF_ACTS:
        raise HTTPException(400, "unknown act")
    current = db.get_case(case_id)
    if not current:
        raise HTTPException(404, "unknown case")
    if body.act in {"approve", "production"} and db.blocking_files(case_id):
        raise HTTPException(409, "Acknowledge flagged COI/lease issues before human approval. The worker cannot approve.")
    if body.act in {"approve", "production"}:
        ready, blockers = requirements.ready_for_handoff(case_id)
        if not ready:
            raise HTTPException(
                409,
                "All applicable requirements must be approved or waived before handoff. Outstanding: "
                + ", ".join(blockers),
            )
    if body.act == "production" and current.get("status") not in {"approved_for_handoff", "production_accepted"}:
        raise HTTPException(409, "Authorized onboarding approval must precede production acceptance.")
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
            session["manager_accepted"] = True
            session["manager_requested"] = True
            mem = session.get("memory") or {}
            mem["manager_accepted"] = True
            mem["manager_requested"] = True
            session["memory"] = mem
            db.save_session(session)
            db.execute("UPDATE voice_connections SET status='ended',expires=0 WHERE session_id=? AND status IN ('connecting','connected')", (session["id"],))
    db.add_event(f"Staff: {body.act}", {"caseId": case_id})
    zoho.queue_stage(saved, body.act, status, next_action)
    zoho.drain()
    saved["zoho"] = zoho.sync_status(session_id=saved.get("session_id"), case_id=case_id, opportunity_id=saved.get("opportunity_id"))
    return saved


app.mount("/", PublicSite(directory=str(ROOT), html=True), name="site")
