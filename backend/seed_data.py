"""
种子数据初始化脚本

创建演示用户、账户、系统策略模板等初始数据。
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal, engine, Base
from app.models import User, Account, Strategy
from app.services.auth_service import hash_password
import json
from datetime import datetime


def seed_all():
    db = SessionLocal()

    try:
        # 1. 创建演示用户
        demo_user = db.query(User).filter(User.username == "demo").first()
        if not demo_user:
            demo_user = User(
                id="user-demo",
                username="demo",
                email="demo@example.com",
                hashed_password=hash_password("demo123"),
                is_active=True,
                created_at=datetime(2024, 1, 1),
            )
            db.add(demo_user)
            db.commit()
            print("✓ 演示用户创建成功 (demo / demo123)")
        else:
            print("- 演示用户已存在，跳过")

        # 2. 创建演示账户
        if db.query(Account).filter(Account.user_id == demo_user.id).count() == 0:
            accounts = [
                Account(
                    id="acc-real-ht", user_id=demo_user.id, name="实盘账户-华泰",
                    type="real", broker="华泰证券", balance=1000000, available=350000,
                    frozen=50000, market_value=600000, profit=85000, profit_rate=0.093,
                    commission_rate=0.0003, stamp_tax_rate=0.001, status="active",
                    created_at=datetime(2023, 1, 15),
                ),
                Account(
                    id="acc-real-zx", user_id=demo_user.id, name="实盘账户-中信",
                    type="real", broker="中信证券", balance=500000, available=200000,
                    frozen=30000, market_value=270000, profit=-15000, profit_rate=-0.029,
                    commission_rate=0.0003, stamp_tax_rate=0.001, status="active",
                    created_at=datetime(2023, 3, 20),
                ),
                Account(
                    id="acc-virtual-1", user_id=demo_user.id, name="虚拟账户-练习",
                    type="virtual", balance=100000, available=45000,
                    frozen=5000, market_value=50000, profit=12000, profit_rate=0.136,
                    commission_rate=0.0003, stamp_tax_rate=0.001, status="active",
                    created_at=datetime(2024, 1, 1),
                ),
                Account(
                    id="acc-virtual-2", user_id=demo_user.id, name="虚拟账户-策略测试",
                    type="virtual", balance=1000000, available=800000,
                    frozen=0, market_value=200000, profit=35000, profit_rate=0.0365,
                    commission_rate=0.0001, stamp_tax_rate=0.001, status="active",
                    created_at=datetime(2024, 2, 15),
                ),
            ]
            db.add_all(accounts)
            db.commit()
            print(f"✓ 创建 {len(accounts)} 个演示账户")
        else:
            print("- 演示账户已存在，跳过")

        # 3. 加载系统策略模板
        templates_path = Path(__file__).parent / "app" / "strategies" / "templates.json"
        if templates_path.exists():
            existing_count = db.query(Strategy).filter(Strategy.is_system == True).count()
            if existing_count == 0:
                with open(templates_path, "r", encoding="utf-8") as f:
                    templates = json.load(f)

                for t in templates:
                    s = Strategy(
                        id=t.get("id", f"sys-{t.get('class_name', '')}"),
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
                db.commit()
                print(f"✓ 加载 {len(templates)} 个系统策略模板")
            else:
                print(f"- 系统策略已存在 ({existing_count}个)，跳过")
        else:
            print("! 策略模板文件不存在，跳过")

        print("\n种子数据初始化完成!")

    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    # 确保表已创建
    Base.metadata.create_all(bind=engine)
    seed_all()
