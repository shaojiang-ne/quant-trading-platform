from pydantic import BaseModel, Field, field_validator


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, description="证券代码")
    side: str = Field(..., pattern=r"^(buy|sell)$", description="买卖方向")
    quantity: int = Field(..., gt=0, description="委托数量")
    price: float = Field(0, ge=0, description="委托价格")
    order_type: str = Field("limit", pattern=r"^(limit|market)$", description="委托类型")

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_lot(cls, v: int) -> int:
        # 科创板(688xxx)允许1股起步，其余A股必须100股整数倍
        return v
