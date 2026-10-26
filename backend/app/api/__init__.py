from fastapi import APIRouter

from app.api import auth, strategies, backtest, simulation, trading, positions, market, stocks, dashboard, simulation_test, ai, research, agent

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(strategies.router)
api_router.include_router(backtest.router)
api_router.include_router(simulation.router)
api_router.include_router(trading.router)
api_router.include_router(positions.router)
api_router.include_router(market.router)
api_router.include_router(stocks.router)
api_router.include_router(dashboard.router)
api_router.include_router(simulation_test.router)
api_router.include_router(ai.router)
api_router.include_router(research.router)
api_router.include_router(agent.router)
