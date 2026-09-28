import logging
import sys
import structlog
from app.core.config import get_settings


def configure_logging():
    logging.basicConfig(
        stream=sys.stdout,
        level=get_settings().log_level,
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def logger():
    return structlog.get_logger()
