import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, desc, select

from app.agent.service import support_agent
from app.audit import list_audit_events
from app.config import settings
from app.database import get_session, init_db
from app.models import Customer, RefundCase
from app.schemas import ChatRequest, ChatResponse, CustomerRead, RefundCaseRead


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict:
    return support_agent.run(request.message, request.session_id)


@app.get("/api/customers", response_model=list[CustomerRead])
def customers(session: Session = Depends(get_session)) -> list[Customer]:
    statement = select(Customer).order_by(Customer.name)
    return list(session.exec(statement).all())


@app.get("/api/admin/logs")
def admin_logs(limit: int = 100) -> list[dict]:
    return list_audit_events(limit=limit)


@app.get("/api/admin/sessions/{session_id}/logs")
def admin_session_logs(session_id: str, limit: int = 100) -> list[dict]:
    return list_audit_events(session_id=session_id, limit=limit)


@app.get("/api/admin/refund-cases", response_model=list[RefundCaseRead])
def refund_cases(session: Session = Depends(get_session), limit: int = 100) -> list[dict]:
    statement = select(RefundCase).order_by(desc(RefundCase.created_at)).limit(limit)
    cases = session.exec(statement).all()
    return [
        {
            "id": case.id,
            "session_id": case.session_id,
            "customer_id": case.customer_id,
            "order_id": case.order_id,
            "request_signature": case.request_signature,
            "decision": case.decision,
            "status": case.status,
            "amount": case.amount,
            "requested_item_ids": json.loads(case.requested_item_ids_json),
            "selected_item_ids": json.loads(case.selected_item_ids_json),
            "reason_codes": json.loads(case.reason_codes_json),
            "policy_citations": json.loads(case.policy_citations_json),
            "customer_message": case.customer_message,
            "created_at": case.created_at.isoformat(),
        }
        for case in cases
    ]


@app.get("/api/policy")
def policy() -> dict:
    policy_path = Path(__file__).resolve().parent / "data" / "refund_policy.md"
    return {"policy": policy_path.read_text(encoding="utf-8")}


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
