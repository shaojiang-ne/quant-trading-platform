import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Strategy
from app.schemas.strategy import StrategyCreate, StrategyUpdate, StrategyResponse, BatchDeleteRequest
from app.services.auth_service import get_current_user
from app.strategies.base import STRATEGY_MAP
from app.core.strategy_adapter import VNPY_STRATEGY_MAP

router = APIRouter(prefix="/strategies", tags=["策略"])


def _format_dt(dt: datetime | None, fallback: datetime | None = None) -> str | None:
    if dt is None:
        dt = fallback
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')

# 系统策略模板文件路径
TEMPLATES_PATH = Path(__file__).parent.parent / "strategies" / "templates.json"

# 策略类源代码缓存
_code_cache: dict[str, str] = {}


def _get_strategy_code(class_name: str) -> str:
    """从 base.py 获取策略类的源代码"""
    if class_name in _code_cache:
        return _code_cache[class_name]
    cls = STRATEGY_MAP.get(class_name)
    if cls:
        try:
            _code_cache[class_name] = inspect.getsource(cls)
        except (TypeError, OSError):
            _code_cache[class_name] = ""
    return _code_cache.get(class_name, "")


def to_response(s: Strategy) -> StrategyResponse:
    return StrategyResponse(
        id=s.id,
        name=s.name,
        description=s.description,
        tags=s.tags if isinstance(s.tags, list) else json.loads(s.tags or "[]"),
        difficulty=s.difficulty,
        class_name=s.class_name,
        code=_get_strategy_code(s.class_name) if s.is_system else s.code,
        algorithm=s.algorithm,
        advantages=s.advantages if isinstance(s.advantages, list) else json.loads(s.advantages or "[]"),
        disadvantages=s.disadvantages if isinstance(s.disadvantages, list) else json.loads(s.disadvantages or "[]"),
        parameters=s.parameters if isinstance(s.parameters, dict) else json.loads(s.parameters or "{}"),
        is_system=s.is_system,
        backtest_count=s.backtest_count,
        avg_return=float(s.avg_return),
        author=s.author,
        created_at=_format_dt(s.created_at),
        updated_at=_format_dt(s.updated_at, fallback=s.created_at),
    )


def load_system_strategies(db: Session):
    """确保系统策略已加载到数据库，增量添加新模板"""
    if not TEMPLATES_PATH.exists():
        return

    with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
        templates = json.load(f)

    # 获取已有系统策略的id集合
    existing_ids = {s.id for s in db.query(Strategy.id).filter(Strategy.is_system == True).all()}

    new_count = 0
    for t in templates:
        tid = t.get("id", f"sys-{t.get('class_name', '')}")
        if tid in existing_ids:
            # 系统策略已存在，更新参数定义（保持用户自定义策略不变）
            db.execute(
                text("UPDATE strategies SET parameters=:params, description=:desc, advantages=:adv, disadvantages=:disadv, tags=:tags, algorithm=:algo WHERE id=:id AND is_system=1"),
                {
                    "params": json.dumps(t.get("parameters", {}), ensure_ascii=False),
                    "desc": t.get("description", ""),
                    "adv": json.dumps(t.get("advantages", []), ensure_ascii=False),
                    "disadv": json.dumps(t.get("disadvantages", []), ensure_ascii=False),
                    "tags": json.dumps(t.get("tags", []), ensure_ascii=False),
                    "algo": t.get("algorithm", ""),
                    "id": tid,
                },
            )
            continue
        s = Strategy(
            id=tid,
            user_id="system",
            name=t["name"],
            description=t.get("description", ""),
            tags=t.get("tags", []),
            difficulty=t.get("difficulty", "beginner"),
            class_name=t.get("class_name", ""),
            code=t.get("code", ""),
            algorithm=t.get("algorithm", ""),
            advantages=t.get("advantages", []),
            disadvantages=t.get("disadvantages", []),
            parameters=t.get("parameters", {}),
            is_system=True,
            backtest_count=t.get("backtest_count", 0),
            avg_return=t.get("avg_return", 0),
            author=t.get("author", "系统"),
        )
        db.add(s)
        new_count += 1

    if new_count > 0:
        db.commit()


@router.get("", response_model=list[StrategyResponse])
def list_strategies(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    load_system_strategies(db)
    strategies = db.query(Strategy).filter(
        (Strategy.is_system == True) | (Strategy.user_id == current_user.id)
    ).order_by(Strategy.updated_at.desc()).all()
    return [to_response(s) for s in strategies]


@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    load_system_strategies(db)
    s = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        (Strategy.is_system == True) | (Strategy.user_id == current_user.id)
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="策略不存在")
    return to_response(s)


@router.post("", response_model=StrategyResponse)
def create_strategy(req: StrategyCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = Strategy(
        user_id=current_user.id,
        name=req.name,
        description=req.description,
        tags=req.tags,
        difficulty=req.difficulty,
        class_name=req.class_name,
        code=req.code,
        algorithm=req.algorithm,
        advantages=req.advantages,
        disadvantages=req.disadvantages,
        parameters=req.parameters,
        is_system=False,
        author=current_user.username,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return to_response(s)


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_strategy(strategy_id: str, req: StrategyUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id, Strategy.user_id == current_user.id, Strategy.is_system == False).first()
    if not s:
        raise HTTPException(status_code=404, detail="策略不存在或无权修改")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    # 更新后清除编译缓存，下次回测重新编译最新代码
    STRATEGY_MAP.pop(s.class_name, None)
    VNPY_STRATEGY_MAP.pop(s.class_name, None)
    return to_response(s)


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id, Strategy.user_id == current_user.id, Strategy.is_system == False).first()
    if not s:
        raise HTTPException(status_code=404, detail="策略不存在或无权删除")
    # 删除前清除编译缓存
    STRATEGY_MAP.pop(s.class_name, None)
    VNPY_STRATEGY_MAP.pop(s.class_name, None)
    db.delete(s)
    db.commit()
    return {"message": "删除成功"}


@router.post("/batch-delete")
def batch_delete_strategies(req: BatchDeleteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="未指定要删除的策略")
    strategies = db.query(Strategy).filter(
        Strategy.id.in_(req.ids),
        Strategy.user_id == current_user.id,
        Strategy.is_system == False,
    ).all()
    if not strategies:
        raise HTTPException(status_code=404, detail="未找到可删除的策略")
    count = len(strategies)
    for s in strategies:
        db.delete(s)
    db.commit()
    return {"message": f"成功删除 {count} 个策略", "deleted_count": count}
