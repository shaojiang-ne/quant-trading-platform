import pytest
from scheduler import StockScheduler


@pytest.fixture
def scheduler():
    config = {
        "schedule": {
            "pool_update": "0 9 * * 1",
            "strategy_scan": "*/10 9-11,13-14 * * 1-5",
            "trading_hours": {
                "morning": ["09:30", "11:30"],
                "afternoon": ["13:00", "15:00"],
            },
        },
        "screener": {
            "min_market_cap": 50,
            "min_daily_amount": 1,
            "exclude_st": True,
            "exclude_new_stock_days": 60,
            "exclude_code_prefix": ["688", "30"],
            "industries": [],
        },
        "strategies": {
            "six_sword": {"enabled": True, "params": {}},
            "four_dimension": {"enabled": True, "params": {}},
        },
        "dingtalk": {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "secret": "",
        },
    }
    return StockScheduler(config)


def test_scheduler_creates_with_config(scheduler):
    assert scheduler.config is not None


def test_scheduler_has_jobs(scheduler):
    scheduler.setup_jobs()
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 2
    job_ids = {j.id for j in jobs}
    assert "screener" in job_ids
    assert "strategy_1428" in job_ids
    
