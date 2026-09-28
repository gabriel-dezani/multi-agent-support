from app.tools.common import ToolResult
def get_sales_data(user_id,repository):
 c=repository.get_by_user_id(user_id)
 return ToolResult(False,error="customer_not_found") if c is None else ToolResult(True,c.get("sales",{}))
