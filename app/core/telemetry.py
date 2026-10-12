"""Durable low-cardinality observability & customer feedback (no raw text/PII)."""
import sqlite3
import json
import math
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from app.core.config import get_settings


class TelemetryRepository:
    def __init__(self, path=None):
        self.path = Path(path or get_settings().state_db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS request_spans (
                request_id TEXT NOT NULL, seq INTEGER NOT NULL, agent TEXT NOT NULL,
                duration_ms REAL NOT NULL, status TEXT NOT NULL, PRIMARY KEY(request_id, seq))""")
            db.execute("""CREATE TABLE IF NOT EXISTS request_stats (
                request_id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, route TEXT NOT NULL, latency_ms REAL NOT NULL,
                escalated INTEGER NOT NULL, degraded INTEGER NOT NULL, agents_count INTEGER NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd REAL,
                retrieval_hits INTEGER, retrieval_best_score REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""CREATE TABLE IF NOT EXISTS user_feedback (
                request_id TEXT NOT NULL, user_ref TEXT NOT NULL, rating INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(request_id,user_ref))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(request_stats)")}
            for name, definition in {
                "session_ref": "TEXT", "plan_json": "TEXT", "routing_strategy": "TEXT",
                "status_code": "INTEGER DEFAULT 200", "error_type": "TEXT", "usage_complete": "INTEGER",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE request_stats ADD COLUMN {name} {definition}")
            if "details_json" not in {row[1] for row in db.execute("PRAGMA table_info(request_spans)")}:
                db.execute("ALTER TABLE request_spans ADD COLUMN details_json TEXT")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def safe_details(details):
        """Persist only known structural/numeric fields, never prompts or reasons."""
        safe = {}
        if not isinstance(details, dict):
            return safe
        for key in ("results_reviewed", "input_tokens", "output_tokens", "hits", "max_score", "mean_score", "hnsw_recovered"):
            value = details.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                safe[key] = value
        nodes = {"knowledge", "customer_support", "web_search", "human_escalation", "synthesis"}
        if details.get("next_node") in nodes:
            safe["next_node"] = details["next_node"]
        if isinstance(details.get("unresolved_agents"), list):
            safe["unresolved_agents"] = [name for name in details["unresolved_agents"] if name in nodes]
        components = nodes | {"router_llm", "knowledge_llm", "knowledge_retrieval", "synthesis_llm",
                              "handoff_repository", "get_sales_data", "get_terminal_status"}
        codes = {"TimeoutError", "ValueError", "TypeError", "RuntimeError", "KeyError", "AttributeError",
                 "ValidationError", "HTTPStatusError", "ReadTimeout", "ConnectError", "OSError",
                 "OperationalError", "IntegrityError", "PermissionError", "JSONDecodeError",
                 "APITimeoutError", "APIConnectionError", "AuthenticationError", "RateLimitError",
                 "customer_not_found", "sales_data_unavailable", "terminal_data_unavailable", "invalid_sales_amount"}
        if isinstance(details.get("error_codes"), list):
            safe["error_codes"] = []
            for error in details["error_codes"][:16]:
                if isinstance(error, str):
                    component, _, code = error.partition(":")
                    if component in components and code.strip() in codes:
                        safe["error_codes"].append(component + ":" + code.strip())
        for key in ("usage", "retrieval"):
            if isinstance(details.get(key), dict):
                safe[key] = TelemetryRepository.safe_details(details[key])
        return safe

    def record(self, *, request_id, user_ref, route, latency_ms, escalated, degraded, spans,
               usage=None, retrieval=None, session_ref=None, plan=None, routing_strategy=None,
               agents=None, status_code=200, error_type=None, usage_complete=None):
        usage = usage or {}
        retrieval = retrieval or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cost = usage.get("estimated_cost_usd")
        with self.connect() as db:
            db.execute("INSERT INTO request_stats(request_id,user_ref,route,latency_ms,escalated,degraded,agents_count,input_tokens,output_tokens,estimated_cost_usd,retrieval_hits,retrieval_best_score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (request_id, user_ref, route or "unknown", max(0,latency_ms), int(escalated), int(degraded),
                        len(agents) if agents is not None else sum(span.get("agent") in {
                            "knowledge", "customer_support", "web_search", "synthesis", "human_escalation", "blocked"
                        } for span in spans),input_tokens,output_tokens,cost,retrieval.get("hits"),retrieval.get("max_score")))
            db.execute("UPDATE request_stats SET session_ref=?,plan_json=?,routing_strategy=?,status_code=?,error_type=?,usage_complete=? WHERE request_id=?",
                       (session_ref,json.dumps(plan or []),routing_strategy,status_code,error_type,
                        int(usage_complete) if usage_complete is not None else None,request_id))
            db.executemany("INSERT INTO request_spans(request_id,seq,agent,duration_ms,status,details_json) VALUES (?,?,?,?,?,?)", [
                (request_id, index, str(x.get("agent", "unknown"))[:64],
                 float(x.get("duration_ms",0)),str(x.get("status","unknown"))[:32],
                 json.dumps(self.safe_details(x.get("details"))))
                for index,x in enumerate(spans)
            ])

    def trace(self, request_id):
        with self.connect() as db:
            rows = db.execute("SELECT agent,duration_ms,status,details_json FROM request_spans WHERE request_id=? ORDER BY seq",(request_id,)).fetchall()
        return [dict(agent=a,duration_ms=ms,status=status,details=json.loads(details or "{}")) for a,ms,status,details in rows]

    def request(self, request_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT request_id,user_ref,session_ref,route,plan_json,routing_strategy,status_code,error_type,latency_ms,escalated,degraded,agents_count,input_tokens,output_tokens,estimated_cost_usd,retrieval_hits,retrieval_best_score,usage_complete FROM request_stats WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["plan"] = json.loads(result.pop("plan_json") or "[]")
        result["usage_complete"] = bool(result["usage_complete"]) if result["usage_complete"] is not None else None
        return result

    def rate(self,request_id,user_ref,rating):
        with self.connect() as db:
            exists=db.execute("SELECT 1 FROM request_stats WHERE request_id=? AND user_ref=?",(request_id,user_ref)).fetchone()
            if not exists:
                return False
            db.execute("INSERT INTO user_feedback(request_id,user_ref,rating) VALUES(?,?,?) ON CONFLICT(request_id,user_ref) DO UPDATE SET rating=excluded.rating",(request_id,user_ref,rating))
        return True

    def stats(self):
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*),SUM(escalated),SUM(degraded),AVG(latency_ms),SUM(input_tokens),SUM(output_tokens),SUM(estimated_cost_usd),AVG(retrieval_hits),AVG(retrieval_best_score) FROM request_stats").fetchone()
            ag = db.execute("SELECT agent,COUNT(*) FROM request_spans GROUP BY agent").fetchall()
            fb = db.execute("SELECT COUNT(*), AVG(rating) FROM user_feedback").fetchone()
            latencies=[r[0] for r in db.execute("SELECT latency_ms FROM request_stats ORDER BY latency_ms").fetchall()]
            errors = db.execute("SELECT COUNT(*) FROM request_stats WHERE status_code>=400").fetchone()[0]
            completeness = db.execute("SELECT COUNT(*),SUM(usage_complete) FROM request_stats WHERE usage_complete IS NOT NULL").fetchone()
            component_rows = db.execute("SELECT agent,duration_ms FROM request_spans ORDER BY duration_ms").fetchall()
            queue_exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='handoffs'").fetchone()
            queue_counts = dict(db.execute("SELECT status,COUNT(*) FROM handoffs GROUP BY status")) if queue_exists else None
            resolution_rows = db.execute("SELECT created_at,resolved_at FROM handoffs WHERE status='resolved'").fetchall() if queue_exists else []
        def percentile(p):
            if not latencies:
                return None
            return round(latencies[round((len(latencies)-1)*p)],2)
        components = {}
        for name, duration in component_rows:
            components.setdefault(name, []).append(duration)
        component_latency = {name: {"count":len(values),"p50_ms":round(values[round((len(values)-1)*.5)],2),
                                   "p95_ms":round(values[round((len(values)-1)*.95)],2)}
                             for name, values in components.items()}
        resolution_seconds = []
        for created, resolved in resolution_rows:
            try:
                seconds = (datetime.fromisoformat(resolved)-datetime.fromisoformat(created)).total_seconds()
                if seconds >= 0:
                    resolution_seconds.append(seconds)
            except (ValueError, TypeError):
                pass
        resolution_seconds.sort()
        resolution_latency = {"samples":len(resolution_seconds),
            "p50":round(resolution_seconds[round((len(resolution_seconds)-1)*.5)],3) if resolution_seconds else None,
            "p95":round(resolution_seconds[round((len(resolution_seconds)-1)*.95)],3) if resolution_seconds else None}
        return {"requests":row[0],"human_escalations":row[1] or 0,"degraded":row[2] or 0,
                "errors":errors,"error_rate":round(errors/row[0],4) if row[0] else 0,
                "usage_complete_requests":completeness[1] or 0,"usage_evaluated_requests":completeness[0],
                "component_latency_ms":component_latency,
                "tickets_pending":queue_counts.get("pending",0) if queue_counts is not None else None,
                "tickets_resolved":queue_counts.get("resolved",0) if queue_counts is not None else None,
                "handoff_resolution_seconds":resolution_latency,
                "avg_latency_ms":round(row[3] or 0,2),"latency_p50_ms":percentile(.5),
                "latency_p95_ms":percentile(.95),"agent_calls":dict(ag),
                "input_tokens_reported":row[4],"output_tokens_reported":row[5],
                "estimated_cost_usd_reported":row[6],
                "avg_retrieval_hits_reported":round(row[7],2) if row[7] is not None else None,
                "avg_retrieval_best_score_reported":round(row[8],4) if row[8] is not None else None,
                "feedback_count":fb[0],
                "avg_feedback_rating":round(fb[1],2) if fb[1] is not None else None}
