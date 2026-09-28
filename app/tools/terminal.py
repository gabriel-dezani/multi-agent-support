from app.tools.common import ToolResult
def get_terminal_status(user_id,repository):
 c=repository.get_by_user_id(user_id)
 if c is None:return ToolResult(False,error="customer_not_found")
 return ToolResult(True,c["terminal"]) if c.get("terminal") else ToolResult(False,error="terminal_not_found")
