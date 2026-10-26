"""
数据库迁移脚本：从 SQLite 迁移数据到 MySQL

用法：
    在 .env / 环境变量中配置目标 MySQL 连接串：
        MYSQL_URL=mysql+pymysql://user:password@host:3306/stock_quant?charset=utf8mb4
    然后执行：python migrate_to_mysql.py
"""

import os
import sys
from pathlib import Path

# 将当前目录加入系统路径
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, make_transient
from app.database import Base
from app.models import (
    User, Account, Strategy, StrategyState, BacktestResult,
    Order, Position, TradingInstance, AutoTradeConfig, Signal, StrategyLog
)

# 目标 MySQL 连接串（来自环境变量，不在代码中保留任何密码）
MYSQL_URL = os.environ.get("MYSQL_URL", "")
if not MYSQL_URL:
    print("✗ 请先设置环境变量 MYSQL_URL，例如：")
    print("  export MYSQL_URL='mysql+pymysql://user:password@host:3306/stock_quant?charset=utf8mb4'")
    sys.exit(1)

# 1. 临时连接 MySQL 服务器（不指定数据库）以创建目标数据库
mysql_root_url = MYSQL_URL.rsplit("/", 1)[0] + "/"
print("正在连接 MySQL 服务器以检查/创建数据库...")
temp_engine = create_engine(mysql_root_url)
with temp_engine.connect() as conn:
    conn.execute(text("CREATE DATABASE IF NOT EXISTS stock_quant CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"))
temp_engine.dispose()
print("✓ MySQL 数据库 stock_quant 检查/创建成功！")

# 2. 创建 SQLite 和 MySQL 的连接引擎
sqlite_engine = create_engine("sqlite:///./stock_quant.db")
mysql_engine = create_engine(MYSQL_URL)

# 3. 创建 MySQL 表结构
print("正在 MySQL 中创建表结构...")
Base.metadata.create_all(mysql_engine)
print("✓ MySQL 表结构创建成功！")

# 4. 数据同步
# 使用单一 MySQL 连接以确保 SET FOREIGN_KEY_CHECKS = 0 持续生效
with mysql_engine.connect() as mysql_conn:
    # 开启事务
    with mysql_conn.begin():
        print("禁用 MySQL 外键约束...")
        mysql_conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        # 绑定 Session
        SqliteSession = sessionmaker(bind=sqlite_engine)
        sqlite_session = SqliteSession()
        
        MysqlSession = sessionmaker(bind=mysql_conn)
        mysql_session = MysqlSession()
        
        # 定义要迁移的模型列表（保持推荐的依赖顺序）
        models = [
            User,
            Account,
            Strategy,
            StrategyState,
            BacktestResult,
            Order,
            Position,
            TradingInstance,
            AutoTradeConfig,
            Signal,
            StrategyLog
        ]
        
        try:
            for model in models:
                table_name = model.__tablename__
                print(f"正在迁移表 {table_name}...")
                
                # 清空 MySQL 表中已有的数据以防冲突
                mysql_conn.execute(text(f"TRUNCATE TABLE {table_name};"))
                
                # 查询 SQLite 数据
                records = sqlite_session.query(model).all()
                count = 0
                
                for record in records:
                    # 剥离旧 of SQLite Session 状态
                    sqlite_session.expunge(record)
                    # 将其标记为 Transient（全新记录），同时保留其 id
                    make_transient(record)
                    # 添加到 MySQL Session
                    mysql_session.add(record)
                    count += 1
                    
                mysql_session.flush()
                print(f"✓ 成功迁移 {count} 条记录到 {table_name}。")
                
            mysql_session.commit()
            print("\n恭喜！所有数据迁移成功！")
            
        except Exception as e:
            mysql_session.rollback()
            print(f"\n✗ 迁移过程中发生错误: {e}")
            raise
        finally:
            print("恢复 MySQL 外键约束...")
            mysql_conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            sqlite_session.close()
            mysql_session.close()
