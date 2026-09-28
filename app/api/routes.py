from uuid import uuid4
from fastapi import APIRouter, HTTPException
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from app.api.schemas import ChatRequest, ChatResponse
from app.orchestration.graph import build_graph

router = APIRouter()
_graph = None
log = structlog.get_logger(__name__)


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    request_id = str(uuid4())
    state = {
        "message": payload.message,
        "user_id": payload.user_id,
        "request_id": request_id,
        "sources": [],
        "tools_used": [],
        "errors": [],
    }
    clear_contextvars()
    bind_contextvars(request_id=request_id, user_id=payload.user_id)
    log.info("chat_request_started")
    try:
        result = await graph().ainvoke(state)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("chat_request_failed", error_type=type(exc).__name__)
        # Do not claim every internal exception is an external dependency outage.
        raise HTTPException(status_code=500, detail="Erro interno ao processar a solicitação.") from exc

    if result.get("errors"):
        log.warning("chat_request_degraded", errors=result["errors"])

    response = ChatResponse(
        answer=result.get("answer", "Não foi possível concluir."),
        agent=result.get("agent", result.get("route", "human_escalation")),
        route_reason=result.get("route_reason", "Fluxo concluído."),
        tools_used=result.get("tools_used", []),
        sources=result.get("sources", []),
        confidence=float(result.get("confidence", 0)),
        requires_human=bool(result.get("requires_human", False)),
        request_id=request_id,
    )
    log.info("chat_request_completed", agent=response.agent, requires_human=response.requires_human)
    clear_contextvars()
    return response
