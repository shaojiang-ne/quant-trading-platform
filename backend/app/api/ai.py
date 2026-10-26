import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings

from app.database import get_db
from app.models import User, Strategy
from app.schemas.ai import AIChatRequest
from app.services.auth_service import get_current_user
from app.services.ai_service import ai_service
from app.services.agent_service import plan_and_fetch_data

router = APIRouter(prefix="/ai", tags=["AI助手"])

# ── 研究助手系统提示词 ──────────────────────────────────────────────────────────
RESEARCH_SYSTEM_PROMPT = """你是一位专业的 A 股研究助手，精通个股估值、题材归因、资金流向、龙虎榜、北向资金、融资融券、大宗交易、行业轮动、限售解禁等全维度分析。

## 你的数据来源
系统已根据用户问题自动获取相关实时数据，并以"【数据：xxx】"数据段的形式注入在下方系统提示中。
- 若注入了数据：请基于这些数据进行分析和解读，引用时标注来源（如"据注入的实时数据"）。
- 若未注入数据或数据段为 error：说明数据获取受限，基于一般性分析作答，并标注"以上基于一般性分析，建议查看最新数据"，不要臆造具体数字。

## 回复规范
- 用中文回复，专业但易懂
- 结构化输出：使用标题、列表、表格让信息一目了然
- 估值分析时给出 PE / PB / PEG / 消化时间等关键指标及你的解读
- 题材/行业归因时说明逻辑链和核心标的
- 资金分析时区分主力/散户/北向
- 始终给出风险提示
- 引用数据时标注来源（如"据腾讯财经实时行情"）
"""

RESEARCH_CHAT_REQUEST_ADDED = False


@router.post("/research-chat")
async def ai_research_chat(
    req: AIChatRequest,
    current_user: User = Depends(get_current_user),
):
    """AI 研究助手聊天（SSE 流式）

    采用"先取数再分析"：根据最后一条用户提问，先用一次纯文本 LLM 调用选定数据集并取数，
    再把数据注入 system 提示，发单轮流式聊天让 LLM 分析。全程纯文本（无 tools），
    规避讯飞多轮 tool-call 1105。前端注入的 system 消息仍合并进系统提示。
    """
    system_parts = [RESEARCH_SYSTEM_PROMPT]
    chat_messages = []

    last_user_question = ""
    for m in req.messages:
        if m.role == "system":
            # 前端传入的 system 消息（数据注入），合并到系统提示词
            system_parts.append(m.content)
        else:
            chat_messages.append({"role": m.role, "content": m.content})
            if m.role == "user" and m.content:
                last_user_question = m.content

    # 先取数：让 LLM 理解自由提问后选定数据集，再取数注入 system
    if last_user_question:
        data_blocks = await plan_and_fetch_data(last_user_question)
        if data_blocks:
            data_text = "\n\n".join(
                f"【数据：{b['name']}】（参数：{b['args']}）\n{b['data']}"
                for b in data_blocks
            )
            system_parts.append(f"以下是系统已自动获取的实时数据，请基于其作答：\n\n{data_text}")

    merged_system_prompt = "\n\n".join(system_parts)

    return StreamingResponse(
        ai_service.chat_stream_with_system(chat_messages, merged_system_prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat")
async def ai_chat(
    req: AIChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI chat endpoint with SSE streaming"""
    strategy = None

    if req.strategy_id:
        s = db.query(Strategy).filter(
            Strategy.id == req.strategy_id,
            (Strategy.is_system == True) | (Strategy.user_id == current_user.id),
        ).first()
        if s:
            tags = s.tags if isinstance(s.tags, list) else json.loads(s.tags or "[]")
            params = s.parameters if isinstance(s.parameters, dict) else json.loads(s.parameters or "{}")
            strategy = {
                "name": s.name,
                "description": s.description,
                "difficulty": s.difficulty,
                "tags": tags,
                "parameters": params,
                "code": s.code,
            }

    # Override with context if provided (for unsaved strategies)
    if req.context:
        strategy = {**strategy, **req.context} if strategy else req.context

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    return StreamingResponse(
        ai_service.chat_stream(messages, strategy),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class TestCodeRequest(BaseModel):
    code: str
    parameters: dict = {}


@router.post("/test-code")
async def test_code(
    req: TestCodeRequest,
    current_user: User = Depends(get_current_user),
):
    """在模拟数据上测试策略代码（模拟回测引擎的完整执行路径）"""
    from app.services.strategy_test_service import test_strategy_code
    result = test_strategy_code(req.code, req.parameters)
    # 剔除仅供测试断言的内部字段
    result.pop("_signals", None)
    return result


class AnalyzeStockRequest(BaseModel):
    symbol: str
    stock_name: str = ""


@router.post("/analyze-stock")
async def analyze_stock(
    req: AnalyzeStockRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 分析股票并推荐策略"""
    from app.core.data_bridge import data_bridge
    from datetime import datetime, timedelta

    # 获取近60日K线（使用与交易数据模块一致的 DataSourceProvider 体系）
    kline_summary = ""
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

        df = data_bridge.load_bars_df(req.symbol, start_date, end_date, period="1d")
        if df is not None and not df.empty:
            # 只取最后60条
            df = df.tail(60)

            close = df["close"]
            high = df["high"]
            low = df["low"]
            volume = df["volume"]

            latest_price = float(close.iloc[-1])
            high_60 = float(high.max())
            low_60 = float(low.min())
            avg_vol = float(volume.mean())

            # 简单技术指标
            ma5 = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else latest_price
            ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else latest_price
            ma60_val = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else latest_price

            # 波动率
            returns = close.pct_change().dropna()
            volatility = float(returns.std() * (252 ** 0.5)) if len(returns) > 1 else 0

            # 趋势判断
            if latest_price > ma20 > ma60_val:
                trend = "上升趋势"
            elif latest_price < ma20 < ma60_val:
                trend = "下降趋势"
            else:
                trend = "震荡"

            kline_summary = f"""当前价: {latest_price:.2f}
60日最高: {high_60:.2f}, 最低: {low_60:.2f}
MA5: {ma5:.2f}, MA20: {ma20:.2f}, MA60: {ma60_val:.2f}
年化波动率: {volatility:.2%}
日均成交量: {avg_vol:.0f}
趋势判断: {trend}
近5日收盘价: {', '.join(f'{float(v):.2f}' for v in close.tail(5))}"""
        else:
            kline_summary = "无法获取K线数据"
    except Exception as e:
        kline_summary = f"获取行情数据失败: {e}"

    # 获取可用策略列表
    all_strategies = db.query(Strategy).filter(
        (Strategy.is_system == True) | (Strategy.user_id == current_user.id)
    ).all()

    strategy_list = []
    for s in all_strategies:
        params = s.parameters if isinstance(s.parameters, dict) else json.loads(s.parameters or "{}")
        param_desc = []
        if isinstance(params, dict):
            for k, v in params.items():
                if isinstance(v, dict):
                    param_desc.append(f"{k}(默认{v.get('value', '?')}, 范围{v.get('min', '?')}~{v.get('max', '?')})")
        strategy_list.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "difficulty": s.difficulty,
            "parameters": param_desc,
        })

    # 调用 LLM
    ai_service._ensure_client()
    if not ai_service.client:
        return {"success": False, "error": "AI服务未配置"}

    prompt = f"""请分析以下股票数据，并推荐最适合的交易策略。

## 股票信息
代码: {req.symbol}
名称: {req.stock_name or req.symbol}

## 近期行情数据
{kline_summary}

## 可用策略列表
{json.dumps(strategy_list, ensure_ascii=False, indent=2)}

## 要求
1. 分析该股票的特征（趋势、波动、成交量等）
2. 从可用策略列表中选择最适合的策略，说明选择理由
3. 推荐该策略的参数设置
4. 用以下JSON格式回复（不要包含其他内容）:
```json
{{
  "analysis": "股票特征分析（1-2句话）",
  "strategy_id": "推荐的策略ID",
  "reason": "选择理由（2-3句话）",
  "params": {{"参数key": 推荐值}},
  "risk_tip": "风险提示（1句话）"
}}
```"""

    try:
        from openai import AsyncOpenAI
        response = await ai_service.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的量化交易策略顾问。请根据股票数据推荐最适合的策略。回复必须包含JSON代码块。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""

        # 提取JSON
        import re
        m = re.search(r'```json\n([\s\S]*?)```', content)
        if not m:
            return {"success": False, "error": "AI返回格式无法解析", "raw": content}

        result = json.loads(m.group(1).strip())

        # 验证 strategy_id 存在
        strategy_id = result.get("strategy_id", "")
        strategy_exists = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy_exists:
            # 尝试按名称模糊匹配
            name_match = db.query(Strategy).filter(Strategy.name.contains(result.get("strategy_id", ""))).first()
            if name_match:
                result["strategy_id"] = name_match.id
            else:
                result["strategy_id"] = ""

        return {"success": True, **result}

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"AI分析失败: {e}",
            "traceback": traceback.format_exc(),
        }


class GenerateStreamRequest(BaseModel):
    messages: list[dict] = []
    phase: str = "understand"  # understand | generate | fix


@router.post("/generate-stream")
async def generate_stream(
    req: GenerateStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """三步策略生成流式端点

    phase=understand: AI 输出对策略的理解和计划
    phase=generate: AI 输出完整策略代码
    phase=fix: AI 根据测试错误修复代码
    """
    messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in req.messages]

    return StreamingResponse(
        ai_service.generate_stream(messages, req.phase),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class GenerateStrategyRequest(BaseModel):
    idea: str


@router.post("/generate-strategy")
async def generate_strategy(
    req: GenerateStrategyRequest,
    current_user: User = Depends(get_current_user),
):
    """根据用户的策略想法生成代码和参数"""
    ai_service._ensure_client()
    if not ai_service.client:
        return {"success": False, "error": "AI服务未配置，请在系统设置中配置 LLM_API_KEY"}

    # 普通字符串 + .replace 占位符：避免 f-string 解析示例代码里未转义的 {fast_window} 等
    prompt = """请根据用户的策略想法生成一个完整的量化交易策略。

## 用户策略想法
{idea}

## 策略框架规范
你的 Python 代码必须实现以下函数：
```python
def generate_signals(df, setting) -> pd.Series:
    # df: DataFrame，包含列 date, open, high, low, close, volume, turnover
    # setting: dict，策略参数，通过 setting.get("key", default) 读取
    # 返回值: pandas Series，1=买入, -1=卖出, 0=持有
```

### 关键约束（必须遵守）
- generate_signals 必须返回 pd.Series，值为**整数** 1（买入）、-1（卖出）、0（持有）
- **不要返回布尔值（True/False）**，必须用整数 1、-1、0
- 信号赋值示例：`signals[cross_over] = 1`（正确） `signals[cross_over] = True`（错误！）
- 不要在函数外使用 import 语句，所有需要的模块已在沙箱中预加载
- 可以直接使用 sma/ema/rsi/macd/bollinger/atr/donchian/kdj/cci/math，无需 import

### 日志输出要求（必须遵守）
代码中必须直接使用沙箱预置的 `logger` 对象记录关键操作过程，让回测时能在日志中看到策略的运行细节。**不要自己创建 logger**，沙箱已预配置好：
```python
# logger 已在沙箱中预置，直接使用即可，不要 import logging 或 getLogger
```
必须在以下位置输出日志：
- **策略参数**：函数开始时记录读取到的参数值
- **指标计算结果**：记录关键指标的当前值（如均线值、RSI值等）
- **信号触发**：当产生买入/卖出信号时，记录触发原因和当时的指标值
- **信号汇总**：函数结束前记录信号统计（买入/卖出/持有各多少次）

日志示例：
```python
logger.info(f"策略参数: fast_window={fast_window}, slow_window={slow_window}")
logger.info(f"指标计算: fast_ma={fast_ma.iloc[-1]:.2f}, slow_ma={slow_ma.iloc[-1]:.2f}")
logger.info(f"买入信号触发: fast_ma={fast_ma.iloc[-1]:.2f} 上穿 slow_ma={slow_ma.iloc[-1]:.2f}")
logger.info(f"信号汇总: 买入={buy_count}次, 卖出={sell_count}次, 持有={hold_count}次")
```

### 内置技术指标函数（可以直接使用，无需 import）：
- sma(series, window) - 简单移动平均
- ema(series, window) - 指数移动平均
- rsi(series, window=14) - RSI 指标
- macd(series, fast, slow, signal) - MACD，返回 (dif, dea, hist)
- bollinger(series, window, num_std) - 布林带，返回 (mid, upper, lower)
- atr(high, low, close, window) - 平均真实波幅
- donchian(high, low, window) - 唐奇安通道，返回 (upper, lower)
- kdj(high, low, close, n, m1, m2) - KDJ，返回 (k, d, j)
- cci(high, low, close, window) - CCI 指标

### 常用信号模式示例：
- 金叉买入: (fast > slow) & (fast.shift(1) <= slow.shift(1))
- 死叉卖出: (fast < slow) & (fast.shift(1) >= slow.shift(1))
- 首次触发: signal & ~signal.shift(1).fillna(False)

## 输出格式要求
你必须以严格的 JSON 格式回复，不要包含任何 markdown 之外的多余文本。格式如下：
```json
{{
  "name": "策略中文名称",
  "description": "策略的中文详细描述说明（100字以内）",
  "code": "完整的 Python 代码，包含 generate_signals 函数和详细的行注释，单双引号请注意正确转义",
  "parameters": {{
    "参数Key": {{
      "value": 默认值（数字或布尔值）,
      "type": "int/float/boolean",
      "label": "参数显示名称",
      "min": 最小值（可选）,
      "max": 最大值（可选）
    }}
  }}
}}
```
"""
    prompt = prompt.replace("{idea}", req.idea)

    try:
        response = await ai_service.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个量化交易策略代码生成专家。你只输出符合格式要求的 JSON 块。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""

        # 提取 JSON 块
        import re
        m = re.search(r'```json\n([\s\S]*?)```', content)
        if not m:
            # 尝试直接解析全部内容
            try:
                result = json.loads(content.strip())
                return {"success": True, **result}
            except Exception:
                return {"success": False, "error": "AI 返回格式无法解析", "raw": content}

        result = json.loads(m.group(1).strip())
        return {"success": True, **result}
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"生成失败: {str(e)}",
            "traceback": traceback.format_exc(),
        }

