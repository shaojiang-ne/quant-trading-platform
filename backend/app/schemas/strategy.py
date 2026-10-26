from pydantic import BaseModel


class BatchDeleteRequest(BaseModel):
    ids: list[str]


class StrategyCreate(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    difficulty: str = "beginner"
    class_name: str = ""
    code: str = ""
    algorithm: str = ""
    advantages: list[str] = []
    disadvantages: list[str] = []
    parameters: dict = {}


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    code: str | None = None
    parameters: dict | None = None


class StrategyResponse(BaseModel):
    id: str
    name: str
    description: str
    tags: list
    difficulty: str
    class_name: str
    code: str
    algorithm: str
    advantages: list
    disadvantages: list
    parameters: dict
    is_system: bool
    backtest_count: int
    avg_return: float
    author: str
    created_at: str
    updated_at: str = ""

    model_config = {"from_attributes": True}
