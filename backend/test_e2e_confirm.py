"""TestClient 端到端测试:真实 HTTP 端点覆盖 confirm→execute 链路与错误码。

用 dependency_overrides 绕过 JWT 鉴权,直接打真实路由。
依赖:DB 可连(远程 MySQL)、LLM 可达(讯飞)、auto 数据源(可能不可达→execute 返回 503,属预期)。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app
from app.services.auth_service import get_current_user
from app.database import SessionLocal
from app.models import User, PickStrategy, PickResult


# ── 找一个真实用户(或造一个测试用户)作为鉴权主体 ──
db = SessionLocal()
try:
    user = db.query(User).first()
    if not user:
        user = User(id="test-e2e-user", username="test-e2e", hashed_password="x", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    TEST_USER = user
    print(f"[setup] 测试用户: id={TEST_USER.id} username={TEST_USER.username}")
finally:
    db.close()


def fake_current_user():
    return TEST_USER


app.dependency_overrides[get_current_user] = fake_current_user

client = TestClient(app)

SEP = "=" * 70


def step(title):
    print(f"\n{SEP}\n{title}\n{SEP}")


def cleanup(strategy_ids):
    db = SessionLocal()
    try:
        for sid in strategy_ids:
            db.query(PickResult).filter(PickResult.strategy_id == sid).delete()
            db.query(PickStrategy).filter(PickStrategy.id == sid).delete()
        db.commit()
    finally:
        db.close()


def main():
    created = []

    # ── 1. create:多轮思考生成 draft ──
    step("1. POST /pick/strategy (多轮思考 → draft)")
    r = client.post("/api/agent/pick/strategy", json={"description": "低估值蓝筹，PE低于30，量比大于1.5，换手率大于2"})
    print("status:", r.status_code)
    assert r.status_code == 200, r.text
    body = r.json()
    strategy = body["strategy"]
    sid = strategy["id"]
    created.append(sid)
    print(f"  id={sid}")
    print(f"  status={strategy['status']} (期望 draft)")
    print(f"  rules={strategy['rules']} (期望 空)")
    print(f"  optimized_description 前80字: {(body.get('optimized') or '')[:80]}")
    assert strategy["status"] == "draft", "create 后应为 draft"
    assert strategy["rules"] in ([], None), "draft 时 rules 应为空"

    # ── 2. execute(draft)应 422 ──
    step("2. POST /pick/execute/{id} (draft 未确认 → 422)")
    r = client.post(f"/api/agent/pick/execute/{sid}")
    print("status:", r.status_code, "(期望 422)")
    print("  detail:", r.json().get("detail"))
    assert r.status_code == 422, "draft 执行应被拒绝"

    # ── 3. confirm:编译规则 → confirmed ──
    step("3. POST /pick/strategy/{id}/confirm (编译规则 → confirmed)")
    r = client.post(f"/api/agent/pick/strategy/{sid}/confirm")
    print("status:", r.status_code, "(期望 200;LLM 撞1105 可能 503)")
    if r.status_code == 200:
        s2 = r.json()["strategy"]
        print(f"  status={s2['status']} (期望 confirmed)")
        print(f"  rules={s2['rules']}")
        assert s2["status"] == "confirmed", "confirm 后应为 confirmed"
        rules = s2["rules"]
        assert isinstance(rules, dict), "rules 应为 dict"
        assert rules.get("pool") in ("hs300", "sse50", "star50"), f"pool 非法: {rules.get('pool')}"
        print("  [OK] 规则程序合法")

        # ── 4. execute(confirmed):跑解释器 ──
        step("4. POST /pick/execute/{id} (confirmed → 跑解释器)")
        r = client.post(f"/api/agent/pick/execute/{sid}")
        print("status:", r.status_code, "(期望 200 出结果;行情不通则 503 保留旧结果)")
        if r.status_code == 200:
            results = r.json()
            print(f"  选股结果数: {len(results)}")
            for x in results[:3]:
                print(f"    {x['code']} {x['name']}: 分{x.get('match_score')} | {x.get('match_reason','')[:40]}")
            # 校验落库
            db = SessionLocal()
            try:
                cnt = db.query(PickResult).filter(PickResult.strategy_id == sid).count()
                print(f"  落库 PickResult 数: {cnt}")
                assert cnt == len(results), "落库数应与返回一致"
            finally:
                db.close()
        elif r.status_code == 503:
            print("  [WARN] 行情数据源不可达(503),旧结果保留 — 属环境问题,非代码问题")
        else:
            print("  ❌ 意外状态码:", r.text[:200])
            raise AssertionError(f"execute 意外 {r.status_code}")

        # ── 5. 编辑描述 → 清空 rules + draft + 停调度 ──
        step("5. PUT /pick/strategy/{id} (编辑 → 清空 rules + draft)")
        # 先开调度,验证编辑会停掉
        r = client.post("/api/agent/pick/schedule",
                        json={"strategy_id": sid, "schedule_time": "09:35", "enabled": True})
        print("  先开调度:", r.status_code)
        r = client.put(f"/api/agent/pick/strategy/{sid}",
                       json={"description": "改成高成长股，营收增速大于20%"})
        print("  编辑 status:", r.status_code)
        assert r.status_code == 200, r.text
        s3 = r.json()
        print(f"  status={s3['status']} (期望 draft)")
        print(f"  rules={s3['rules']} (期望 空)")
        print(f"  scheduleEnabled={s3.get('scheduleEnabled')} (期望 False)")
        assert s3["status"] == "draft", "编辑后应退回 draft"
        assert s3["rules"] in ([], None), "编辑后 rules 应清空"
        assert s3.get("scheduleEnabled") is False, "编辑后应停调度"

        # ── 6. 编辑后再 execute 应再次 422 ──
        step("6. 编辑后再 execute (draft → 422)")
        r = client.post(f"/api/agent/pick/execute/{sid}")
        print("status:", r.status_code, "(期望 422)")
        assert r.status_code == 422

    elif r.status_code == 503:
        print("  [WARN] confirm 因 LLM 1105 失败(503),策略保持 draft — 属 LLM 不稳定,非代码问题")
        print("  跳过 4/5/6 步(依赖 confirm 成功)")
    else:
        print("  ❌ confirm 意外:", r.text[:200])
        raise AssertionError(f"confirm 意外 {r.status_code}")

    cleanup(created)
    step("测试完成")


if __name__ == "__main__":
    main()
