"""Challenge-compatible API with authenticated, isolated user and operator access."""
from datetime import datetime
from time import perf_counter
from pathlib import Path
import asyncio
import sqlite3
from uuid import uuid4
import structlog
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Security
from fastapi.security import HTTPAuthorizationCredentials
from structlog.contextvars import bind_contextvars, clear_contextvars
from app.api.schemas import ChatRequest, ChatResponse, HandoffResolveRequest, FeedbackRequest
from app.core.auth import resolve_identity, authenticated_identity, assert_customer, _bearer_scheme
from app.core.config import get_settings
from app.core.metrics import metrics
from app.core.telemetry import TelemetryRepository
from app.core.usage import cost_usd
from app.core.security import operator_token_is_valid, user_ref
from app.core.session_lock import conversation_lock
from app.core.distributed_lock import postgres_conversation_lock
from app.core.upstream import UpstreamUnavailable
from app.handoff.repository import HandoffRepository
from app.memory.store import ConversationMemoryStore
from app.orchestration.graph import build_graph
from app.agents.guardrail import GuardrailAgent

router = APIRouter()
log = structlog.get_logger(__name__)
_graph = None
_memory = None
_handoffs = None
_telemetry = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def memory_store():
    global _memory
    if _memory is None:
        settings = get_settings()
        if getattr(settings, "state_backend", "sqlite") == "postgres":
            from app.core.postgres_state import PostgresConversationMemoryStore
            _memory = PostgresConversationMemoryStore(settings.state_database_url)
        else:
            _memory = ConversationMemoryStore()
    return _memory


def handoff_store():
    global _handoffs
    if _handoffs is None:
        settings = get_settings()
        if getattr(settings, "state_backend", "sqlite") == "postgres":
            from app.core.postgres_state import PostgresHandoffRepository
            _handoffs = PostgresHandoffRepository(settings.state_database_url)
        else:
            _handoffs = HandoffRepository()
    return _handoffs


def telemetry_store():
    global _telemetry
    if _telemetry is None:
        settings = get_settings()
        if getattr(settings, "state_backend", "sqlite") == "postgres":
            from app.core.postgres_state import PostgresTelemetryRepository
            _telemetry = PostgresTelemetryRepository(settings.state_database_url)
        else:
            _telemetry = TelemetryRepository()
    return _telemetry


def require_operator(
    x_operator_token: str = Header(default=""),
    credential: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> dict:
    """Authenticate operator from a configured bearer identity or local operator token.

    Audit identity is derived from the credential; never from the request JSON.
    The legacy operator token represents the configured local operator identity.
    """
    if credential is not None:
        identity = resolve_identity(authorization=f"Bearer {credential.credentials}")
        if identity["role"] != "operator":
            raise HTTPException(status_code=403, detail="Papel de operador obrigatório.")
        return identity
    if get_settings().auth_mode == "local" and get_settings().operator_token and operator_token_is_valid(x_operator_token):
        return {"user_id": "local-operator", "role": "operator"}
    raise HTTPException(status_code=403, detail="Acesso de operador negado.")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def readiness():
    from app.core.readiness import check_readiness
    if not check_readiness(get_settings()):
        raise HTTPException(status_code=503, detail="Persistência indisponível.")
    return {"status": "ready", "scope": (
        "central_state_only" if getattr(get_settings(), "state_backend", "sqlite") == "postgres"
        else "local_state_only")}


@router.get("/metrics", dependencies=[Depends(require_operator)])
def current_metrics():
    return telemetry_store().stats()


@router.get("/ops/slo", dependencies=[Depends(require_operator)])
def service_level_objectives(window_minutes: int = Query(default=60, ge=5, le=1440)):
    from app.core.observability import evaluate_slo
    return evaluate_slo(telemetry_store().recent_stats(window_minutes=window_minutes))


@router.get("/ops/alerts", dependencies=[Depends(require_operator)])
def operational_alerts(window_minutes: int = Query(default=60, ge=5, le=1440)):
    from app.core.observability import evaluate_operational_gates
    return evaluate_operational_gates(telemetry_store().recent_stats(window_minutes=window_minutes))


@router.get("/traces/{request_id}", dependencies=[Depends(require_operator)])
def request_traces(request_id: str):
    return {"request_id": request_id, "request": telemetry_store().request(request_id),
            "spans": telemetry_store().trace(request_id)}


@router.post("/feedback")
def submit_feedback(payload: FeedbackRequest, subject: dict = Depends(authenticated_identity)):
    if subject["role"] != "customer":
        raise HTTPException(status_code=403, detail="Apenas clientes podem avaliar.")
    if not telemetry_store().rate(payload.request_id, user_ref(subject["user_id"]), payload.rating):
        raise HTTPException(status_code=404, detail="Requisição não encontrada para este usuário.")
    return {"recorded": True}


@router.get("/conversations/{conversation_id}", dependencies=[Depends(require_operator)])
def conversation_history(conversation_id: str,
                         user_id: str = Query(min_length=1, max_length=100)):
    return {"conversation_id": conversation_id,
            "messages": memory_store().get_history(conversation_id, user_id)}


@router.get("/my-handoffs/{conversation_id}")
def my_handoffs(conversation_id: str, subject: dict = Depends(authenticated_identity)):
    if subject["role"] != "customer":
        raise HTTPException(status_code=403, detail="Apenas clientes podem consultar tickets.")
    return {"items": handoff_store().user_cases(conversation_id, subject["user_id"])}


@router.get("/handoffs", dependencies=[Depends(require_operator)])
def list_handoffs(status: str = Query(default="pending", pattern=r"^(pending|resolved)$"),
                  limit: int = Query(default=50, ge=1, le=100)):
    return {"items": handoff_store().list(status=status, limit=limit)}


@router.get("/handoffs/{handoff_id}", dependencies=[Depends(require_operator)])
def get_handoff(handoff_id: str):
    record = handoff_store().get(handoff_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Handoff não encontrado.")
    return record


@router.post("/handoffs/{handoff_id}/resolve")
async def resolve_handoff(handoff_id: str, payload: HandoffResolveRequest,
                    operator: dict = Depends(require_operator)):
    ticket = handoff_store().get(handoff_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Handoff não encontrado.")
    settings = get_settings()
    if getattr(settings, "state_backend", "sqlite") == "postgres":
        guard = postgres_conversation_lock(settings.state_database_url, ticket["user_id"],
                                           ticket["conversation_id"],
                                           timeout=settings.total_request_timeout_seconds)
    else:
        key = (str(memory_store().path.resolve()), ticket["user_id"], ticket["conversation_id"])
        guard = conversation_lock(key, timeout=getattr(settings, "total_request_timeout_seconds", 90))
    try:
        async with guard:
            return _resolve_handoff(handoff_id, payload, operator)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("handoff_resolution_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível persistir a resposta humana.") from exc


def _resolve_handoff(handoff_id, payload, operator):
    # All state shares one database by default. Atomic write means a resolved
    # ticket and the human reply cannot diverge on process interruption.
    memory, handoffs = memory_store(), handoff_store()
    if getattr(get_settings(), "state_backend", "sqlite") == "postgres":
        same_database = (getattr(memory, "dsn", None) == get_settings().state_database_url
                         and getattr(handoffs, "dsn", None) == get_settings().state_database_url)
    else:
        same_database = memory.path.resolve() == handoffs.path.resolve()
    if not same_database:
        # A completed ticket without an atomic human reply would break resume.
        # The service is configured for ONE local state database; fail closed.
        raise HTTPException(status_code=503, detail="Configuração de persistência inconsistente.")
    try:
        record = handoff_store().resolve(handoff_id, resolution=payload.resolution,
                                        resolved_by=operator["user_id"], append_memory=True)
    except sqlite3.Error as exc:
        log.error("handoff_resolution_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível persistir a resposta humana.") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Handoff não encontrado.")
    transitioned = record.pop("_transitioned", False)
    if transitioned:
        try:
            elapsed = (datetime.fromisoformat(record["resolved_at"]) -
                       datetime.fromisoformat(record["created_at"])).total_seconds()
            metrics.record_handoff_resolution(elapsed)
        except (ValueError, TypeError):
            metrics.record_handoff_resolution()
    return record


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, subject: dict = Depends(authenticated_identity)):
    assert_customer(subject, payload.user_id)
    started = perf_counter()
    request_id = str(uuid4())
    total_timeout = getattr(get_settings(), "total_request_timeout_seconds", 90)
    payload = payload.model_copy(update={"conversation_id": payload.conversation_id or str(uuid4())})
    settings = get_settings()
    if getattr(settings, "state_backend", "sqlite") == "postgres":
        guard = postgres_conversation_lock(settings.state_database_url, subject["user_id"],
                                           payload.conversation_id, timeout=total_timeout)
    else:
        path = _memory.path if _memory is not None else Path(settings.state_db_path)
        key = (str(path.resolve()), subject["user_id"], payload.conversation_id)
        guard = conversation_lock(key, timeout=total_timeout)
    try:
        async with guard:
            return await _chat(payload, subject, started, request_id, total_timeout)
    except UpstreamUnavailable as exc:
        _record_failure(request_id, subject["user_id"], payload.conversation_id, started, exc)
        raise HTTPException(status_code=503,
                            detail="Serviço de IA temporariamente indisponível. Tente novamente mais tarde.",
                            headers={"X-Request-ID": request_id}) from exc
    except TimeoutError as exc:
        _record_failure(request_id, subject["user_id"], payload.conversation_id, started, exc)
        raise HTTPException(status_code=503, detail="Não foi possível processar a solicitação.",
                            headers={"X-Request-ID": request_id}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Connection failures during advisory-lock acquisition happen before
        # _chat's error boundary. Classify them as unavailable persistence.
        _record_failure(request_id, subject["user_id"], payload.conversation_id, started, exc)
        raise HTTPException(status_code=503, detail="Persistência temporariamente indisponível.",
                            headers={"X-Request-ID": request_id}) from exc


def _record_failure(request_id, uid, conversation_id, started, exc):
    session_ref = user_ref(uid + ":" + conversation_id)
    log.error("chat_request_failed", error_type=type(exc).__name__, request_id=request_id,
              user_ref=user_ref(uid), session_ref=session_ref)
    metrics.record(route="error", agents=[], handoff=False, latency_ms=(perf_counter()-started)*1000,
                   error=True, degraded=True)
    try:
        telemetry_store().record(request_id=request_id, user_ref=user_ref(uid), session_ref=session_ref,
            route="error", latency_ms=(perf_counter()-started)*1000, escalated=False, degraded=True,
            spans=[], status_code=503, error_type=type(exc).__name__)
    except Exception as telemetry_error:
        log.error("telemetry_write_failure", error_type=type(telemetry_error).__name__)


async def _chat(payload, subject, started, request_id, total_timeout):
    assert_customer(subject, payload.user_id)
    conversation_id = payload.conversation_id or str(uuid4())
    uid = subject["user_id"]
    clear_contextvars()
    session_ref = user_ref(uid + ":" + conversation_id)
    bind_contextvars(request_id=request_id, session_ref=session_ref, user_ref=user_ref(uid))
    try:
        # Configured retention is enforced before reading any conversation.
        if get_settings().memory_retention_days:
            memory_store().purge_expired()
        # Memory is required for correct multi-turn semantics: fail closed if
        # persistence is unavailable instead of silently omitting earlier turns.
        history = memory_store().get_history(conversation_id, uid, current_message=payload.message)
        pending = handoff_store().pending(conversation_id, uid)
        pending_guard = None
        if pending:
            guard_started = perf_counter()
            pending_guard = GuardrailAgent().validate(payload.message)
            guard_span = {"agent":"guardrail","duration_ms":round((perf_counter()-guard_started)*1000,2),
                          "status":"ok" if pending_guard["allowed"] else "blocked"}
        if pending and not pending_guard["allowed"]:
            result = {"answer": "Não posso atender a essa solicitação.", "agent": "blocked",
                      "route": "blocked", "route_reason": "Guardrail em sessão aguardando humano",
                      "plan": [], "agents_used": ["blocked"], "confidence": 1.0,
                      "requires_human": False, "sources": [], "tools_used": [], "traces": [guard_span]}
        elif pending:
            answer = ("Sua solicitação permanece na fila de atendimento humano. "
                      f"Protocolo: {pending['handoff_id']}.")
            result = {"answer": answer, "agent": "human_escalation", "route": "human_escalation",
                      "route_reason": "Caso humano pendente", "plan": ["human_escalation"],
                      "agents_used": ["human_escalation"], "confidence": 0.0,
                      "requires_human": True, "sources": [], "tools_used": [],
                      "handoff_id": pending["handoff_id"], "handoff_status": pending["status"],
                      "routing_strategy": "pending_handoff", "routing_confidence": 1.0,
                      "traces": [guard_span, {"agent": "human_escalation", "duration_ms": 0.0, "status": "pending"}]}
        else:
            state = {"message": payload.message, "user_id": uid, "request_id": request_id,
                     "conversation_id": conversation_id, "history": history, "sources": [],
                     "tools_used": [], "errors": [], "agents_used": [], "agent_results": [], "traces": []}
            remaining = total_timeout - (perf_counter() - started)
            if remaining <= 0:
                raise TimeoutError("request deadline exceeded")
            result = await asyncio.wait_for(graph().ainvoke(state), timeout=remaining)
        response = ChatResponse(answer=result.get("answer", "Não foi possível concluir."),
            agent=result.get("agent", result.get("route", "human_escalation")),
            route_reason=result.get("route_reason", "Fluxo concluído."),
            tools_used=result.get("tools_used", []), sources=result.get("sources", []),
            confidence=float(result.get("confidence", 0)),
            requires_human=bool(result.get("requires_human", False)),
            request_id=request_id, conversation_id=conversation_id,
            plan=result.get("plan", []), agents_used=result.get("agents_used", []),
            routing_strategy=result.get("routing_strategy", ""),
            routing_confidence=float(result.get("routing_confidence", 0)),
            handoff_id=result.get("handoff_id") or None,
            handoff_status=result.get("handoff_status") or None)
        if response.agent != "blocked":
            memory_store().append_turn(conversation_id, uid, payload.message, response.answer, request_id)
        latency_ms = (perf_counter()-started)*1000
        metrics.record(route=result.get("route"),agents=response.agents_used,
                       handoff=response.requires_human, latency_ms=latency_ms,
                       degraded=bool(result.get("errors")),plan=response.plan,
                       routing_strategy=response.routing_strategy)
        try:
            telemetry_store().record(request_id=request_id, user_ref=user_ref(uid), session_ref=session_ref,
                route=result.get("route"), latency_ms=latency_ms,
                escalated=response.requires_human, degraded=bool(result.get("errors")),
                spans=result.get("traces", []), usage={**result.get("usage", {}),
                    "estimated_cost_usd": cost_usd(result.get("usage", {})) if result.get("usage_complete", True) else None},
                retrieval=result.get("retrieval"), plan=response.plan, routing_strategy=response.routing_strategy,
                agents=response.agents_used, usage_complete=result.get("usage_complete"))
        except Exception as exc:
            log.error("telemetry_write_failure",error_type=type(exc).__name__)
        log.info("chat_request_completed", agent=response.agent,
                 agents_used=response.agents_used, latency_ms=round(latency_ms,2))
        return response
    except (HTTPException, UpstreamUnavailable):
        # Let the outer /chat handler classify upstream outages, record the
        # incident once, and return the appropriate non-sensitive 503 message.
        raise
    except Exception as exc:
        _record_failure(request_id, uid, conversation_id, started, exc)
        raise HTTPException(status_code=503, detail="Não foi possível processar a solicitação.",
                            headers={"X-Request-ID": request_id}) from exc
    finally:
        clear_contextvars()
