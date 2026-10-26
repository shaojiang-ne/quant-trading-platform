# 技术分析模块设计

## 概述

在 AI 分析助手中新增「技术分析」快捷场景，用户输入股票代码后，后端自动计算技术指标、K线形态、支撑阻力位和成交量分析，将结构化文本摘要注入 LLM system 提示词，由 LLM 做深度解读和操作建议。

## 方案

**方案 A：纯后端计算 + 场景按钮注入**

- 后端新增 `TechnicalAnalysisService`，复用 `strategies/base.py` 的 9 个指标函数 + 新增 K线形态识别、支撑阻力、成交量分析
- 结果以结构化文本注入 LLM system 提示词
- 前端在 `AIAssistant.tsx` 的 `quickScenarios` 数组中新增「技术分析」场景按钮
- 与现有 16 个场景的交互模式完全一致

## 后端设计

### 新增文件

`app/services/technical_analysis_service.py`

### 数据来源

复用 `data_bridge.load_bars_df()` 获取 K线数据（与现有 `analyze-stock` 一致），取近 120 日日线。

### 计算内容（4 大类）

#### 1. 趋势类指标

- **MA5/MA10/MA20/MA60**：复用 `sma()`，判断均线排列（多头/空头/纠缠）
- **MACD(12,26,9)**：复用 `macd()`，判断 DIF/DEA 金叉死叉、零轴位置
- **趋势判断**：综合均线排列 + MACD 方向

#### 2. 震荡类指标

- **RSI(6,14)**：复用 `rsi()`，判断超买超卖
- **KDJ(9,3,3)**：复用 `kdj()`，判断金叉死叉 + 超买超卖区
- **CCI(14)**：复用 `cci()`，判断异常偏离

#### 3. 波动/通道类指标

- **布林带(20,2)**：复用 `bollinger()`，判断价格位置（上轨外/上轨内/中轨/下轨内/下轨外）+ 带宽收窄/扩张
- **ATR(14)**：复用 `atr()`，判断波动率水平
- **唐奇安通道(20)**：复用 `donchian()`，判断突破

#### 4. K线形态识别 + 支撑阻力 + 成交量

**K线形态**（纯 pandas，6种基础形态，只扫描最近 5 根 K线）：

| 形态 | 判断条件 | 信号 |
|------|---------|------|
| 锤子线 | 下影线 > 实体*2, 上影线 < 实体*0.3, 出现在下跌后 | 看涨 |
| 倒锤子 | 上影线 > 实体*2, 下影线 < 实体*0.3, 出现在下跌后 | 看涨 |
| 十字星 | 实体 < (高-低)*0.1 | 中性/反转 |
| 看涨吞没 | 前阴后阳, 当日实体完全包住前日实体, 出现在下跌后 | 看涨 |
| 看跌吞没 | 前阳后阴, 当日实体完全包住前日实体, 出现在上涨后 | 看跌 |
| 刺透形态 | 前阴后阳, 开盘低于前日低点, 收盘在前日实体上半部 | 看涨 |

**支撑阻力位**：

- 近 60 日最高价、最低价
- MA20、MA60 当前值
- 布林带上轨、下轨当前值
- 密集成交区：近 60 日 K线按价格区间分 10 档，成交量最大的 2 个区间中值

**成交量分析**：

- 量比：当日成交量 / 近 5 日均量
  - >2.0: 明显放量
  - 1.5~2.0: 温和放量
  - 0.7~1.5: 正常
  - <0.7: 缩量
- 量价关系：近 5 日涨跌方向与成交量变化方向是否一致
- 量价背离：近 5 日价格创新高但成交量递减，或价格创新低但成交量递减

### 输出格式

**文本摘要**（注入 LLM system 提示词）：

```
## 技术指标分析
### 趋势指标
- MA5: 24.50, MA10: 24.20, MA20: 23.80, MA60: 22.90
- 均线排列: 多头排列(MA5>MA10>MA20>MA60)
- MACD: DIF=0.35, DEA=0.28, HIST=0.14, DIF>DEA金叉状态, DIF在零轴上方
- 趋势判断: 上升趋势

### 震荡指标
- RSI(6): 72.3 [超买], RSI(14): 65.1 [偏强]
- KDJ: K=68.5, D=62.3, J=80.9, K>D金叉状态
- CCI(14): 85.2 [偏强]

### 波动/通道
- 布林带: 上轨25.80, 中轨24.50, 下轨23.20, 价格在中轨上方, 带宽收窄
- ATR(14): 0.85, 近5日ATR均值0.78, 波动率偏低
- 唐奇安通道: 上轨25.50, 下轨22.80, 价格在通道内

### K线形态
- 最近5日形态: [十字星(3日前), 锤子线(1日前)]
- 支撑位: 23.80(MA20), 23.20(布林下轨)
- 阻力位: 25.80(布林上轨), 25.50(唐奇安上轨)

### 成交量
- 量比: 1.35 [温和放量]
- 近5日量价关系: 量价配合(上涨放量)
- 量价背离: 无
```

**结构化信号**（供未来扩展用）：

```json
{
  "trend": "上升",
  "ma_alignment": "多头排列",
  "macd_signal": "金叉",
  "rsi_status": "偏强",
  "kdj_signal": "金叉",
  "boll_position": "中轨上方",
  "volume_status": "温和放量",
  "patterns": ["锤子线(1日前)"],
  "support_levels": [23.80, 23.20],
  "resistance_levels": [25.80, 25.50]
}
```

## API 路由

在 `app/api/research.py` 中新增：

```
GET /research/technical-analysis?code=688017
```

响应：

```json
{
  "code": "688017",
  "stock_name": "绿盟科技",
  "latest_price": 24.50,
  "analysis": "上面的结构化文本摘要",
  "signals": { ... }
}
```

## 前端设计

### 新增场景

在 `AIAssistant.tsx` 的 `quickScenarios` 数组中新增：

```typescript
{
  icon: Activity,
  label: '技术分析',
  color: 'bg-pink-50 text-pink-600 border-pink-200',
  prompt: '帮我分析一下 688017 的技术面',
  fetchData: async (code) => {
    const d = await researchApi.technicalAnalysis(code);
    return { summary: d.analysis, detail: d.signals };
  },
}
```

### API 新增

`frontend/src/api/research.ts` 新增：

```typescript
technicalAnalysis: (code: string) => api.get<Record<string, any>>(`/research/technical-analysis?code=${code}`)
```

## 错误处理

- K线数据获取失败：返回 `analysis: "无法获取K线数据"` + `signals: null`，前端 fallback 让 LLM 基于一般性分析作答
- 数据不足（<60日）：降级计算，只算数据量允许的指标（如 MA5/MA10 但跳过 MA60），在文本中标注"数据不足，部分指标不可用"
- 指标计算异常：单个指标 try-catch，失败时该指标标注"计算失败"，不影响其他指标

## 测试

`tests/test_technical_analysis.py`：

- 用 mock K线数据测试各指标计算正确性
- 测试 K线形态识别（构造特定形态的 K线序列）
- 测试支撑阻力位计算
- 测试成交量分析
- 测试数据不足时的降级逻辑
- 测试 API 端点返回格式

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `app/services/technical_analysis_service.py` | 新增 | 技术分析服务 |
| `app/api/research.py` | 修改 | 新增 `/research/technical-analysis` 路由 |
| `frontend/src/api/research.ts` | 修改 | 新增 `technicalAnalysis` API |
| `frontend/src/pages/AIAssistant.tsx` | 修改 | 新增「技术分析」场景按钮 |
| `tests/test_technical_analysis.py` | 新增 | 单元测试 |
