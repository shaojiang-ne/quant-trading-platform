import asyncio
import json
import logging
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def _is_transient_llm_error(exc: Exception) -> bool:
    """判断是否为 LLM 网关偶发性错误（值得重试）。
    讯飞 MaaS 偶发 EngineInternalError:1105 "system is busy"，HTTP 500/502/503。
    """
    msg = str(exc)
    if any(k in msg for k in ("EngineInternalError", "10012", "system is busy", "please try again later")):
        return True
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status in (500, 502, 503, 429)

GENERATE_UNDERSTAND_PROMPT = """你是一位专业的量化交易策略顾问。用户会描述一个策略想法，你需要：

1. 用通俗的语言解释你理解的策略逻辑
2. 列出你计划使用的技术指标/因子及其参数
3. 明确说明买入和卖出条件
4. 指出可能的风险或注意事项

**重要：此阶段只输出你的理解和计划，不要生成任何代码。**
**用中文回复，结构化输出，让用户可以确认你的理解是否正确。**

## 策略框架规范

### 可用技术指标（无需 import）：
- sma(series, window) - 简单移动平均
- ema(series, window) - 指数移动平均
- rsi(series, window=14) - RSI 指标
- macd(series, fast, slow, signal) - MACD，返回 (dif, dea, hist)
- bollinger(series, window, num_std) - 布林带，返回 (mid, upper, lower)
- atr(high, low, close, window) - 平均真实波幅
- donchian(high, low, window) - 唐奇安通道，返回 (upper, lower)
- kdj(high, low, close, n, m1, m2) - KDJ，返回 (k, d, j)
- cci(high, low, close, window) - CCI 指标

### 常用信号模式
- 金叉买入: (fast > slow) & (fast.shift(1) <= slow.shift(1))
- 死叉卖出: (fast < slow) & (fast.shift(1) >= slow.shift(1))
- 首次触发: signal & ~signal.shift(1).fillna(False)
"""

GENERATE_CODE_PROMPT = """你是一位量化交易策略代码生成专家。用户已经确认了策略理解，请生成完整的策略代码。

## 策略框架规范

策略代码必须包含以下函数：
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
代码中必须直接使用沙箱中预置的 `logger` 对象记录关键操作过程，让回测时能在日志中看到策略的运行细节。**不要自己创建 logger**，沙箱已预配置好：
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

### 可用技术指标（无需 import）：
- sma(series, window) - 简单移动平均
- ema(series, window) - 指数移动平均
- rsi(series, window=14) - RSI 指标
- macd(series, fast, slow, signal) - MACD，返回 (dif, dea, hist)
- bollinger(series, window, num_std) - 布林带，返回 (mid, upper, lower)
- atr(high, low, close, window) - 平均真实波幅
- donchian(high, low, window) - 唐奇安通道，返回 (upper, lower)
- kdj(high, low, close, n, m1, m2) - KDJ，返回 (k, d, j)
- cci(high, low, close, window) - CCI 指标

### 常用信号模式
- 金叉买入: (fast > slow) & (fast.shift(1) <= slow.shift(1))
- 死叉卖出: (fast < slow) & (fast.shift(1) >= slow.shift(1))
- 首次触发: signal & ~signal.shift(1).fillna(False)

## 输出格式要求
1. 先用 ```desc ... ``` 包裹策略描述（100字以内）
2. 再用 ```python ... ``` 包裹完整代码（含详细中文注释）
3. 最后用 ```json ... ``` 包裹参数定义，格式为 {{"key": {{"value": 默认值, "type": "int|float|boolean", "label": "显示名", "min": 最小值, "max": 最大值}}}}
"""

GENERATE_FIX_PROMPT = """你是一位量化交易策略代码修复专家。用户生成的策略代码在测试时出错了，请根据错误信息修复代码。

## 修复要求
1. 仔细分析错误信息和堆栈跟踪
2. 找出代码中的 BUG（语法错误、逻辑错误、类型错误等）
3. 输出修复后的完整代码，不要只输出修改的部分

## 策略框架规范

策略代码必须包含以下函数：
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
代码中必须直接使用沙箱中预置的 `logger` 对象记录关键操作过程，让回测时能在日志中看到策略的运行细节。**不要自己创建 logger**，沙箱已预配置好：
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

### 可用技术指标（无需 import）：
- sma(series, window) - 简单移动平均
- ema(series, window) - 指数移动平均
- rsi(series, window=14) - RSI 指标
- macd(series, fast, slow, signal) - MACD，返回 (dif, dea, hist)
- bollinger(series, window, num_std) - 布林带，返回 (mid, upper, lower)
- atr(high, low, close, window) - 平均真实波幅
- donchian(high, low, window) - 唐奇安通道，返回 (upper, lower)
- kdj(high, low, close, n, m1, m2) - KDJ，返回 (k, d, j)
- cci(high, low, close, window) - CCI 指标

## 输出格式
用 ```python ... ``` 包裹修复后的完整代码
"""


SYSTEM_PROMPT = """你是一个专业的量化交易策略助手，帮助用户编写、分析和优化交易策略。

## 策略框架说明

### 函数签名
策略代码必须包含以下函数：
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
代码中必须直接使用沙箱中预置的 `logger` 对象记录关键操作过程，让回测时能在日志中看到策略的运行细节。**不要自己创建 logger**，沙箱已预配置好：
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

### 可用技术指标（无需 import）
- sma(series, window) - 简单移动平均
- ema(series, window) - 指数移动平均
- rsi(series, window=14) - RSI 指标
- macd(series, fast, slow, signal) - MACD，返回 (dif, dea, hist)
- bollinger(series, window, num_std) - 布林带，返回 (mid, upper, lower)
- atr(high, low, close, window) - 平均真实波幅
- donchian(high, low, window) - 唐奇安通道，返回 (upper, lower)
- kdj(high, low, close, n, m1, m2) - KDJ，返回 (k, d, j)
- cci(high, low, close, window) - CCI 指标

### 常用信号模式
- 金叉买入: (fast > slow) & (fast.shift(1) <= slow.shift(1))
- 死叉卖出: (fast < slow) & (fast.shift(1) >= slow.shift(1))
- 首次触发: signal & ~signal.shift(1).fillna(False)

## 当前策略信息
{strategy_context}

## 回复规范
- 用中文回复，代码注释也用中文
- 当建议修改策略代码时，在回复中用 ```python ... ``` 包裹完整的新代码
- 当建议修改参数时，用 ```json ... ``` 包裹参数 JSON，格式为 {{"key": {{"value": 默认值, "type": "int|float", "label": "显示名", "min": 最小值, "max": 最大值}}}}
- 当建议修改描述时，用 ```desc ... ``` 包裹新描述文本
- 分析策略时，从逻辑合理性、参数敏感性、风险控制、适用市场环境等角度给出建议
"""


class AIService:
    def __init__(self):
        self.client: AsyncOpenAI | None = None
        self._initialized = False

    def _ensure_client(self):
        if self._initialized:
            return
        if settings.LLM_API_KEY:
            self.client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        self._initialized = True

    def _build_strategy_context(self, strategy: dict | None) -> str:
        if not strategy:
            return "暂无当前策略（用户正在创建新策略）"

        params = strategy.get("parameters", {})
        if isinstance(params, dict):
            params_str = json.dumps(params, ensure_ascii=False, indent=2)
        else:
            params_str = str(params)

        return f"""策略名称: {strategy.get('name', '未命名')}
策略描述: {strategy.get('description', '无')}
分类: {strategy.get('category', '未分类')}
难度: {strategy.get('difficulty', 'beginner')}
标签: {strategy.get('tags', [])}
当前参数:
{params_str}
当前代码:
```python
{strategy.get('code', '# 暂无代码')}
```"""

    async def chat_stream(
        self,
        messages: list[dict],
        strategy: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        self._ensure_client()

        if not self.client:
            yield 'data: {"type": "error", "error": "AI服务未配置，请在设置中配置LLM_API_KEY"}\n\n'
            return

        # 用 .replace 不用 .format：SYSTEM_PROMPT 里有示例代码 f-string 的未转义花括号
        # （{fast_window} 等），.format 会 KeyError。{strategy_context} 是字符串里唯一真正的占位符。
        system_prompt = SYSTEM_PROMPT.replace(
            "{strategy_context}", self._build_strategy_context(strategy)
        )

        full_messages = [{"role": "system", "content": system_prompt}, *messages]

        # 讯飞 MaaS 偶发 503 / code 10310 "The system is busy" 过载，
        # 在尚未向客户端输出任何内容时退避重试，避免一次过载直接失败。
        MAX_LLM_RETRIES = 3
        try:
            response = None
            yielded = False
            for attempt in range(MAX_LLM_RETRIES + 1):
                try:
                    response = await self.client.chat.completions.create(
                        model=settings.LLM_MODEL,
                        messages=full_messages,
                        stream=True,
                        temperature=0.7,
                    )
                    async for chunk in response:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yielded = True
                            yield f'data: {json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False)}\n\n'
                    break  # 流式成功完成
                except Exception as e:
                    if _is_transient_llm_error(e) and not yielded and attempt < MAX_LLM_RETRIES:
                        wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
                        logger.warning(f"[AI聊天] LLM 偶发错误，{wait:.1f}s 后重试({attempt+1}/{MAX_LLM_RETRIES}): {str(e)[:160]}")
                        await asyncio.sleep(wait)
                        continue
                    raise

            yield 'data: {"type": "done"}\n\n'

        except Exception as e:
            logger.error(f"AI chat error: {e}")
            yield f'data: {json.dumps({"type": "error", "error": f"AI服务调用失败: {e}"}, ensure_ascii=False)}\n\n'


    async def chat_stream_with_system(
        self,
        messages: list[dict],
        system_prompt: str,
    ) -> AsyncGenerator[str, None]:
        """使用自定义系统提示词的流式聊天"""
        self._ensure_client()

        if not self.client:
            yield 'data: {"type": "error", "error": "AI服务未配置，请在设置中配置LLM_API_KEY"}\n\n'
            return

        full_messages = [{"role": "system", "content": system_prompt}, *messages]

        # 讯飞 MaaS 偶发 503 / code 10310 "The system is busy" 过载，
        # 在尚未向客户端输出任何内容时退避重试，避免一次过载直接失败。
        MAX_LLM_RETRIES = 3
        try:
            response = None
            yielded = False
            for attempt in range(MAX_LLM_RETRIES + 1):
                try:
                    response = await self.client.chat.completions.create(
                        model=settings.LLM_MODEL,
                        messages=full_messages,
                        stream=True,
                        temperature=0.7,
                    )
                    async for chunk in response:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yielded = True
                            yield f'data: {json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False)}\n\n'
                    break  # 流式成功完成
                except Exception as e:
                    if _is_transient_llm_error(e) and not yielded and attempt < MAX_LLM_RETRIES:
                        wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
                        logger.warning(f"[研究助手] LLM 偶发错误，{wait:.1f}s 后重试({attempt+1}/{MAX_LLM_RETRIES}): {str(e)[:160]}")
                        await asyncio.sleep(wait)
                        continue
                    raise

            yield 'data: {"type": "done"}\n\n'

        except Exception as e:
            logger.error(f"AI research chat error: {e}")
            yield f'data: {json.dumps({"type": "error", "error": f"AI服务调用失败: {e}"}, ensure_ascii=False)}\n\n'

    async def chat_stream_with_tools(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
    ) -> AsyncGenerator[str, None]:
        """带工具调用的流式聊天（function calling）。

        循环：流式生成 → 若模型请求 tool_calls → 执行工具 → 把结果作为 tool 消息回灌
        → 再次流式，直到产出最终纯文本。tools 为空时退化为 chat_stream_with_system。
        """
        # 无工具时走原纯文本路径，保持兼容
        if not tools:
            async for chunk in self.chat_stream_with_system(messages, system_prompt):
                yield chunk
            return

        self._ensure_client()
        if not self.client:
            yield 'data: {"type": "error", "error": "AI服务未配置，请在设置中配置LLM_API_KEY"}\n\n'
            return

        # 延迟导入避免与 agent_service 的循环依赖
        from app.services.agent_service import execute_pick_tool

        full_messages: list[dict] = [{"role": "system", "content": system_prompt}, *messages]
        MAX_TOOL_ROUNDS = 5
        MAX_LLM_RETRIES = 3  # 讯飞偶发 EngineInternalError:1105 过载，重试

        try:
            for _ in range(MAX_TOOL_ROUNDS + 1):
                # 流式请求 + 偶发错误重试：仅在本轮尚未向客户端输出任何内容时重试，
                # 避免半流式输出后重试导致内容重复。
                response = None
                content_buf = ""
                tool_calls_buf: dict[int, dict] = {}
                finish_reason = None
                yielded_this_round = False
                last_err: Exception | None = None

                for attempt in range(MAX_LLM_RETRIES + 1):
                    try:
                        response = await self.client.chat.completions.create(
                            model=settings.LLM_MODEL,
                            messages=full_messages,
                            tools=tools,
                            stream=True,
                            temperature=0.7,
                        )
                        async for chunk in response:
                            choice = chunk.choices[0]
                            delta = choice.delta
                            if delta.content:
                                content_buf += delta.content
                                yielded_this_round = True
                                yield f'data: {json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False)}\n\n'
                            if getattr(delta, "tool_calls", None):
                                for tc in delta.tool_calls:
                                    idx = tc.index if tc.index is not None else 0
                                    slot = tool_calls_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                    if tc.id:
                                        slot["id"] = tc.id
                                    if tc.function and tc.function.name:
                                        slot["name"] = tc.function.name
                                    if tc.function and tc.function.arguments:
                                        slot["arguments"] += tc.function.arguments
                            if choice.finish_reason:
                                finish_reason = choice.finish_reason
                        last_err = None
                        break  # 本轮流式成功完成
                    except Exception as e:
                        last_err = e
                        if _is_transient_llm_error(e) and not yielded_this_round and attempt < MAX_LLM_RETRIES:
                            wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
                            logger.warning(f"[选股工具] LLM 偶发错误，{wait:.1f}s 后重试({attempt+1}/{MAX_LLM_RETRIES}): {str(e)[:160]}")
                            await asyncio.sleep(wait)
                            # 重置本轮缓冲，重新发起
                            content_buf = ""
                            tool_calls_buf = {}
                            finish_reason = None
                            continue
                        raise

                # 无工具调用：文本已流式输出，结束
                if not tool_calls_buf:
                    yield 'data: {"type": "done"}\n\n'
                    return

                # 有工具调用：构造 assistant 消息（含 tool_calls）并执行
                ordered = [tool_calls_buf[i] for i in sorted(tool_calls_buf)]
                assistant_tool_calls = []
                for slot in ordered:
                    assistant_tool_calls.append({
                        "id": slot["id"],
                        "type": "function",
                        "function": {"name": slot["name"], "arguments": slot["arguments"]},
                    })
                full_messages.append({"role": "assistant", "content": content_buf or None, "tool_calls": assistant_tool_calls})

                for slot in ordered:
                    tool_name = slot["name"]
                    try:
                        tool_args = json.loads(slot["arguments"]) if slot["arguments"] else {}
                    except Exception:
                        tool_args = {}
                    logger.info(f"[选股工具] 调用 {tool_name}({tool_args})")
                    result = execute_pick_tool(tool_name, tool_args)
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": slot["id"],
                        "content": result,
                    })
                # 继续下一轮流式，让模型基于工具结果作答

            # 超过最大轮数仍未结束
            yield 'data: {"type": "done"}\n\n'

        except Exception as e:
            logger.error(f"AI tool chat error: {e}")
            yield f'data: {json.dumps({"type": "error", "error": f"AI服务调用失败: {e}"}, ensure_ascii=False)}\n\n'


    async def generate_stream(
        self,
        messages: list[dict],
        phase: str = "understand",
    ) -> AsyncGenerator[str, None]:
        """三步策略生成流式端点"""
        self._ensure_client()

        if not self.client:
            yield 'data: {"type": "error", "error": "AI服务未配置，请在设置中配置LLM_API_KEY"}\n\n'
            return

        # 根据阶段选择系统提示词
        if phase == "understand":
            system_prompt = GENERATE_UNDERSTAND_PROMPT
        elif phase == "generate":
            system_prompt = GENERATE_CODE_PROMPT
        elif phase == "fix":
            system_prompt = GENERATE_FIX_PROMPT
        else:
            system_prompt = GENERATE_UNDERSTAND_PROMPT

        full_messages = [{"role": "system", "content": system_prompt}, *messages]

        # 讯飞 MaaS 偶发 503 / code 10310 "The system is busy" 过载，
        # 在尚未向客户端输出任何内容时退避重试，避免一次过载直接失败。
        MAX_LLM_RETRIES = 3
        try:
            response = None
            yielded = False
            for attempt in range(MAX_LLM_RETRIES + 1):
                try:
                    response = await self.client.chat.completions.create(
                        model=settings.LLM_MODEL,
                        messages=full_messages,
                        stream=True,
                        temperature=0.3 if phase in ("generate", "fix") else 0.7,
                    )
                    async for chunk in response:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yielded = True
                            yield f'data: {json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False)}\n\n'
                    break  # 流式成功完成
                except Exception as e:
                    if _is_transient_llm_error(e) and not yielded and attempt < MAX_LLM_RETRIES:
                        wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
                        logger.warning(f"[策略生成] LLM 偶发错误，{wait:.1f}s 后重试({attempt+1}/{MAX_LLM_RETRIES}): {str(e)[:160]}")
                        await asyncio.sleep(wait)
                        continue
                    raise

            yield 'data: {"type": "done"}\n\n'

        except Exception as e:
            logger.error(f"AI generate stream error: {e}")
            yield f'data: {json.dumps({"type": "error", "error": f"AI服务调用失败: {e}"}, ensure_ascii=False)}\n\n'


ai_service = AIService()
