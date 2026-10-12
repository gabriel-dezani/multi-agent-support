"""Sales demonstration tool; user_id must come from authenticated API identity."""
from app.tools.common import ToolResult


def get_sales_data(user_id, repository):
    customer = repository.get_by_user_id(user_id)
    if customer is None:
        return ToolResult(False, error="customer_not_found")
    sales = customer.get("sales")
    if not isinstance(sales, dict) or any(key not in sales for key in ("status", "amount", "settlement_date")):
        return ToolResult(False, error="sales_data_unavailable")
    if not isinstance(sales["amount"], (int, float)) or isinstance(sales["amount"], bool):
        return ToolResult(False, error="invalid_sales_amount")
    return ToolResult(True, sales)
