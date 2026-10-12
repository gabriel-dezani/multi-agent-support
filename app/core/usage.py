"""Provider-reported token accounting. Never invent missing usage values."""
from app.core.config import get_settings


def read_usage(response) -> dict:
    data = getattr(response, "usage_metadata", None) or {}
    if not isinstance(data, dict):
        return {}
    try:
        return {"input_tokens": max(0, int(data["input_tokens"])),
                "output_tokens": max(0, int(data["output_tokens"]))}
    except (KeyError, TypeError, ValueError):
        return {}


def add_usage(*usages: dict) -> dict:
    valid = [v for v in usages if isinstance(v, dict) and {"input_tokens", "output_tokens"} <= v.keys()]
    if not valid:
        return {}
    return {"input_tokens": sum(int(v["input_tokens"]) for v in valid),
            "output_tokens": sum(int(v["output_tokens"]) for v in valid)}


def cost_usd(usage: dict) -> float | None:
    cfg = get_settings()
    if not usage or cfg.input_price_per_million_usd <= 0 or cfg.output_price_per_million_usd <= 0:
        return None
    return round((usage["input_tokens"] * cfg.input_price_per_million_usd +
                  usage["output_tokens"] * cfg.output_price_per_million_usd) / 1_000_000, 8)
