from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import router
from app.core.logging import configure_logging

configure_logging()
from app.core.config import get_settings
from app.core.observability import configure_tracing
from app.core.readiness import validate_deployment
validate_deployment(get_settings())
configure_tracing(get_settings())
@asynccontextmanager
async def lifespan(application):
    # Initialize state schemas before /ready starts receiving traffic. This
    # avoids the fresh-volume startup race caused by lazy repository creation.
    # No external LLM or embedding API is called on startup.
    from app.api import routes
    routes.memory_store()
    routes.handoff_store()
    routes.telemetry_store()
    yield


app = FastAPI(title="Multi-Agent Support System", version="2.3.0", lifespan=lifespan)
app.include_router(router)
