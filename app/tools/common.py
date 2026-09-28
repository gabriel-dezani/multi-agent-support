from dataclasses import dataclass,field
from typing import Any
@dataclass(frozen=True)
class ToolResult:
 ok:bool; data:dict[str,Any]=field(default_factory=dict); error:str|None=None
