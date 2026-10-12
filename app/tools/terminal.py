"""Terminal demonstration tool; user_id must come from authenticated API identity."""
from app.tools.common import ToolResult


def get_terminal_status(user_id, repository):
    customer = repository.get_by_user_id(user_id)
    if customer is None:
        return ToolResult(False, error="customer_not_found")
    terminal = customer.get("terminal")
    if not isinstance(terminal, dict) or any(key not in terminal for key in ("model", "connection", "last_sync")):
        return ToolResult(False, error="terminal_data_unavailable")
    return ToolResult(True, terminal)
