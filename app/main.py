import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app import db, docworker, entities, fees, qwen, requirements, retrieve, second_pass, zoho
from app.graph import build_graph
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


class FeeIn(BaseModel):
    arrangement: str = "dispatch_service"
    percent: float
    approved_by: str = "Staff desk"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT)) as saver:
        app.state.graph = build_graph(saver)

        async def boot():
            await qwen.warmup()
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
        "model": qwen.MODEL,
        "qwen_ready": qwen.ready,
        "qwen_error": qwen.last_error,
        "qwen_runtime": qwen.status(),
        "retrieve": retrieve.status(),
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


@app.post("/v1/turn")
async def turn(body: TurnIn, background: BackgroundTasks):
    session = db.get_session(body.session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    db.add_message(session["id"], "user", body.text)
    result = await app.state.graph.ainvoke(
        {"session": session, "user_text": body.text, "traces": [{"_reset": True}]},
        {"configurable": {"thread_id": session["id"]}},
    )
    session = result["session"]
    db.save_session(session)
    db.add_message(session["id"], "assistant", result["reply_text"])
    zoho.drain()
    background.add_task(zoho.drain)
    return {
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
        "zoho": zoho.sync_status(session_id=session["id"], case_id=session.get("case_id"), opportunity_id=session.get("opportunity_id")),
    }


@app.get("/v1/cases")
def cases():
    return db.list_cases()


@app.get("/v1/cases/{case_id}")
def case_detail(case_id: str):
    row = db.get_case(case_id)
    if not row:
        raise HTTPException(404, "unknown case")
    row["files"] = db.list_case_files(case_id)
    row["blocking"] = db.blocking_files(case_id)
    row["entities"] = entities.resolve(case_id)
    row["packet"] = requirements.snapshot(case_id)
    row["zoho"] = zoho.sync_status(session_id=row.get("session_id"), case_id=case_id, opportunity_id=row.get("opportunity_id"))
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
    return db.acknowledge_case_files(case_id)


@app.post("/v1/cases/{case_id}/act")
def case_act(case_id: str, body: StaffAct):
    if body.act not in STAFF_ACTS:
        raise HTTPException(400, "unknown act")
    current = db.get_case(case_id)
    if not current:
        raise HTTPException(404, "unknown case")
    if body.act == "approve" and db.blocking_files(case_id):
        raise HTTPException(409, "Acknowledge flagged COI/lease issues before human approval. The worker cannot approve.")
    if body.act == "packet_sent":
        requirements.issue(case_id, current.get("task"))
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
