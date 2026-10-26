"""端到端测试：对话框输入策略 → 取数 → AI分析 → 生成策略选股 的完整链路。

直接调用 agent_service 的真实函数（不走 HTTP），分阶段打印结果。
依赖：LLM 已在 .env 配置（讯飞 astron-code）；MySQL 可连；auto 数据源可用。
"""
import asyncio
import json
import os
import sys

# 确保用 backend 目录的包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import agent_service
from app.database import SessionLocal
from app.models import PickStrategy, PickResult


SEP = "=" * 70


def stage(title):
    print(f"\n{SEP}\n{title}\n{SEP}")


async def main():
    user_strategy = "低估值蓝筹股，PE低于20，量比大于1.5，流通市值大于500亿"
    print(f"用户输入策略：{user_strategy}")

    # ── 阶段1：取候选池 + 实时快照 ──────────────────────────────────────────
    stage("阶段1：沪深300候选池 + 实时快照 (_fetch_pool_quotes)")
    quotes = agent_service._fetch_pool_quotes()
    print(f"候选股数量：{len(quotes)}")
    if quotes:
        for q in quotes[:3]:
            print(f"  {q['code']} {q['name']}: 价{q['price']} 涨{q['change_pct']}% "
                  f"PE{q['pe_ttm']} PB{q['pb']} 量比{q['vol_ratio']} 市值{q['float_mcap_yi']}亿")
    if not quotes:
        print("!! 候选池为空，后续无法选股。检查数据源。")
        return

    # ── 阶段2：先取数（plan_and_fetch_data） ────────────────────────────────
    stage("阶段2：AI 选数据集并取数 (plan_and_fetch_data)")
    blocks = await agent_service.plan_and_fetch_data(user_strategy)
    print(f"LLM 选取的数据集数：{len(blocks)}")
    for b in blocks:
        preview = b["data"][:200].replace("\n", " ")
        print(f"  [{b['name']}] 参数={b['args']} → {preview}...")

    # ── 阶段3：AI 流式分析（system 注入数据后单轮流式） ──────────────────────
    stage("阶段3：AI 流式分析 (chat_stream_with_system)")
    from app.services.ai_service import ai_service
    system_parts = [agent_service.__dict__.get("RESEARCH_SYSTEM_PROMPT", "")]
    # 复刻 ai.py 的数据注入逻辑
    if blocks:
        data_text = "\n\n".join(
            f"【数据：{b['name']}】（参数：{b['args']}）\n{b['data']}" for b in blocks
        )
        system_parts.append(f"以下是系统已自动获取的实时数据，请基于其作答：\n\n{data_text}")
    # 用 ai.py 的真实 system prompt
    from app.api.ai import RESEARCH_SYSTEM_PROMPT
    sys_prompt = RESEARCH_SYSTEM_PROMPT + ("\n\n" + data_text if blocks else "")
    full = ""
    async for chunk in ai_service.chat_stream_with_system(
        [{"role": "user", "content": user_strategy}], sys_prompt
    ):
        # chunk 形如 'data: {"type":"text","content":"..."}\n\n'
        try:
            payload = json.loads(chunk[len("data: "):].strip())
            if payload.get("type") == "text":
                full += payload["content"]
            elif payload.get("type") == "error":
                print(f"!! 流式错误：{payload.get('error')}")
                break
        except Exception:
            pass
    print(f"AI 分析输出（前500字）：\n{full[:500]}")

    # ── 阶段4：真正选股 (execute_pick_strategy) ──────────────────────────────
    stage("阶段4：执行选股 (execute_pick_strategy)")
    db = SessionLocal()
    try:
        # 造一条临时策略（不落库到真实用户，用 test 标记便于清理）
        strategy = PickStrategy(
            user_id="test-pipeline-user",
            name="测试策略",
            description=user_strategy,
            optimized_description=user_strategy,
            rules={
                "pool": "hs300",
                "filters": [
                    {"field": "pe_ttm", "op": "<=", "value": 20},
                    {"field": "pe_ttm", "op": ">", "value": 0},
                ],
                "scoring": [
                    {"field": "vol_ratio", "weight": 12, "direction": "high"},
                    {"field": "turnover_pct", "weight": 6, "direction": "high"},
                ],
                "top_n": 6,
            },
            status="confirmed",
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        print(f"临时策略 id={strategy.id}")

        results = await agent_service.execute_pick_strategy(db, strategy, strategy.user_id)
        print(f"选股结果数：{len(results)}（Top 6）")
        for r in results:
            print(f"  {r.code} {r.name}: 分{r.match_score} 价{r.price} 涨{r.change_pct}% "
                  f"| {r.match_reason}")

        # 校验 PickResult 是否落库
        cnt = db.query(PickResult).filter(PickResult.strategy_id == strategy.id).count()
        print(f"落库 PickResult 数：{cnt}")

        # 清理测试数据
        db.query(PickResult).filter(PickResult.strategy_id == strategy.id).delete()
        db.delete(strategy)
        db.commit()
        print("已清理测试策略与结果。")
    finally:
        db.close()

    stage("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
