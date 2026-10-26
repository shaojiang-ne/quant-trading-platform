from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

# MySQL 不需要 check_same_thread（仅 SQLite 需要）
connect_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_kwargs["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_kwargs,
    echo=False,
    pool_recycle=3600,       # MySQL 连接回收时间（秒）
    pool_pre_ping=True,      # 连接池预检，防止 MySQL 断连
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
