from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Position, Order
from app.schemas.order import PositionResponse, OrderResponse
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/positions", tags=["持仓与委托"])


def _position_to_response(p: Position) -> PositionResponse:
    return PositionResponse(
        id=p.id,
        account_id=p.account_id,
        symbol=p.symbol,
        name=p.name,
        quantity=float(p.quantity),
        avg_cost=float(p.avg_cost),
        current_price=float(p.current_price),
        market_value=float(p.market_value),
        profit=float(p.profit),
        profit_rate=float(p.profit_rate),
        update_time=p.update_time.isoformat(),
    )


def _order_to_response(o: Order) -> OrderResponse:
    return OrderResponse(
        id=o.id,
        account_id=o.account_id,
        symbol=o.symbol,
        name=o.name,
        side=o.side,
        type=o.type,
        quantity=float(o.quantity),
        price=float(o.price) if o.price else None,
        status=o.status,
        filled_quantity=float(o.filled_quantity),
        filled_price=float(o.filled_price) if o.filled_price else None,
        created_at=o.created_at.isoformat(),
        updated_at=o.updated_at.isoformat(),
    )


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import TradingInstance
    account_ids = [i.account_id for i in db.query(TradingInstance).filter(TradingInstance.user_id == current_user.id).all()]
    positions = db.query(Position).filter(Position.account_id.in_(account_ids)).all()
    return [_position_to_response(p) for p in positions]


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc()).all()
    return [_order_to_response(o) for o in orders]
