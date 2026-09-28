from typing import Literal
from pydantic import BaseModel,Field
AgentName=Literal["knowledge","customer_support","web_search","human_escalation","blocked"]
class ChatRequest(BaseModel):
 message:str=Field(min_length=1,max_length=4000)
 user_id:str=Field(min_length=1,max_length=100)
class ChatResponse(BaseModel):
 answer:str; agent:AgentName; route_reason:str
 tools_used:list[str]=Field(default_factory=list)
 sources:list[str]=Field(default_factory=list)
 confidence:float=Field(ge=0,le=1)
 requires_human:bool=False
 request_id:str
