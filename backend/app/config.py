from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "量化交易平台 API"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Database
    # 默认使用本地 SQLite；生产环境请通过 .env / 环境变量覆盖为 MySQL 等外部数据库，
    # 例如：mysql+pymysql://user:password@host:3306/stock_quant?charset=utf8mb4
    DATABASE_URL: str = "sqlite:///./stock_quant.db"

    # JWT
    # 生产环境务必通过环境变量 JWT_SECRET_KEY 覆盖为随机字符串
    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # 数据源: auto / mootdx / akshare / baostock / xtquant / tencent / sina / efinance
    DATA_SOURCE: str = "auto"

    # stock_data 行情服务
    STOCK_DATA_URL: str = "http://localhost:8000"
    STOCK_DATA_API_KEY: str = ""

    # stock_trade 交易服务
    STOCK_TRADE_URL: str = "http://localhost:8800"
    STOCK_TRADE_API_KEY: str = ""

    # 数据后端选择: akshare / stock_data
    MARKET_BACKEND: str = "akshare"
    # 交易后端选择: sim / stock_trade
    TRADE_BACKEND: str = "sim"

    # 交易网关自动连接
    TRADE_AUTO_CONNECT: bool = False

    # 券商选择: qmt / xtp_cjzq / xtp_ztzq / ht / ths / gtja / hundsun
    BROKER: str = "qmt"

    # XTP 通用配置（长江/中泰/东方/财通/华鑫/国盛/粤开等 XTP 券商共用）
    XTP_TD_ADDRESS: str = ""
    XTP_MD_ADDRESS: str = ""
    XTP_BROKER_ID: str = ""
    XTP_APP_ID: str = ""
    XTP_SOFTWARE_KEY: str = ""

    # 华泰证券 htquant 配置
    HT_USERID: str = ""
    HT_PASSWORD: str = ""

    # 同花顺 iFinD 配置
    THS_USERID: str = ""
    THS_PASSWORD: str = ""

    # 国泰君安 tquant2 配置
    GTJA_USERID: str = ""
    GTJA_PASSWORD: str = ""
    GTJA_TD_ADDRESS: str = ""

    # 恒生 PTrade 配置
    HUNDSUN_USERID: str = ""
    HUNDSUN_PASSWORD: str = ""
    HUNDSUN_TD_ADDRESS: str = ""

    # LLM 配置（外部 LLM 网关，对应 .env 中的 LLM_* 变量）
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
