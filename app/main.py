from fastapi import FastAPI
from app.api.routes import router
from app.core.logging import configure_logging
configure_logging(); app=FastAPI(title="Multi-Agent Support System",version="1.0.0"); app.include_router(router)
