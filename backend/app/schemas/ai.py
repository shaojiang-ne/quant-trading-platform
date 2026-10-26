from typing import Literal, Optional
from pydantic import BaseModel


class AIChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage]
    strategy_id: Optional[str] = None
    context: Optional[dict] = None
