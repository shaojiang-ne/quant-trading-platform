import os
from pathlib import Path
from pydantic_settings import BaseSettings
import yaml


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8800
    ssl_cert: str = ""
    ssl_key: str = ""


class AuthSettings(BaseSettings):
    api_key: str = ""

    def get_effective_api_key(self) -> str:
        return os.environ.get("STOCK_TRADE_API_KEY", self.api_key)


class GatewaySettings(BaseSettings):
    type: str = "xtquant"
    qmt_path: str = ""
    session_id: int = 0

    def get_effective_qmt_path(self) -> str:
        """QMT 客户端路径：优先取环境变量 QMT_PATH，其次取配置文件。"""
        return os.environ.get("QMT_PATH", self.qmt_path)


class Settings(BaseSettings):
    server: ServerSettings = ServerSettings()
    auth: AuthSettings = AuthSettings()
    gateway: GatewaySettings = GatewaySettings()


def load_settings(config_path: str = "config.yaml") -> Settings:
    p = Path(config_path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return Settings(**data)
    return Settings()


settings = load_settings()
