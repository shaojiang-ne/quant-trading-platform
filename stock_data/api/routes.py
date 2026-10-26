from fastapi import FastAPI
from api.v1_routes import router as v1_router

app = FastAPI(title="A股数据库", version="1.0.0")
app.include_router(v1_router, prefix="/api/v1")
