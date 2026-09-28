import httpx
from app.core.config import get_settings
class WebSearchTool:
 async def execute(self,query,max_results=5):
  s=get_settings()
  if not s.tavily_api_key: raise RuntimeError("TAVILY_API_KEY não configurada")
  payload={"api_key":s.tavily_api_key,"query":query,"max_results":max_results,"search_depth":"basic","include_answer":False}
  async with httpx.AsyncClient(timeout=s.request_timeout_seconds) as c:
   r=await c.post("https://api.tavily.com/search",json=payload); r.raise_for_status()
  return [{"title":x.get("title",""),"url":x.get("url",""),"content":x.get("content","")} for x in r.json().get("results",[])]
