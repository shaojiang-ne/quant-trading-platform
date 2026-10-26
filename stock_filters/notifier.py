import base64
import datetime
import hashlib
import hmac
import logging
import os
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)


class DingTalkNotifier:
    """钉钉机器人通知"""

    def __init__(self, config: dict, test_config: dict | None = None):
        self.webhook = os.environ.get("DINGTALK_WEBHOOK", config.get("webhook", ""))
        self.secret = os.environ.get("DINGTALK_SECRET", config.get("secret", ""))
        # 测试机器人配置（手动执行时使用）
        self.test_webhook = os.environ.get("DINGTALK_TEST_WEBHOOK", (test_config or {}).get("webhook", ""))
        self.test_secret = os.environ.get("DINGTALK_TEST_SECRET", (test_config or {}).get("secret", ""))

    def format_messages(self, results: dict[str, list[dict]], elapsed: float = 0) -> list[str]:
        """按策略拆分消息，适合移动端查看"""
        now = datetime.datetime.now().strftime("%H:%M")

        if not results:
            return [f"📊 选股提醒 {now}\n未筛选出符合条件的股票"]

        messages = []
        total = sum(len(hits) for hits in results.values())
        # 摘要消息：所有策略都列出，未命中的标注0只
        summary_parts = [f"{name}:{len(hits)}只" for name, hits in results.items()]
        messages.append(f"📊 选股提醒 {now} | {' '.join(summary_parts)} | 耗时{elapsed:.0f}s")

        for strategy_name, hits in results.items():
            if not hits:
                messages.append(f"【{strategy_name}】未命中")
                continue
            lines = [f"【{strategy_name}】{len(hits)}只"]
            for hit in hits:
                code = hit['code'].replace("sh", "").replace("sz", "").replace("bj", "")
                parts = [code, hit.get('name', '')]
                industry = hit.get('industry', '')
                if industry:
                    parts.append(industry)
                price = hit.get("price")
                change_pct = hit.get("change_pct")
                if price and price > 0:
                    change_str = f" {change_pct:+.2f}%" if change_pct is not None else ""
                    parts.append(f"{price:.2f}{change_str}")
                lines.append(" ".join(parts))
            messages.append("\n".join(lines))

        # 重点股票：被2个以上策略同时命中
        code_strategies: dict[str, list[str]] = {}
        code_info: dict[str, dict] = {}
        for strategy_name, hits in results.items():
            for hit in hits:
                code = hit["code"]
                code_strategies.setdefault(code, []).append(strategy_name)
                code_info.setdefault(code, {"name": hit.get("name", ""), "industry": hit.get("industry", ""), "price": hit.get("price", 0), "change_pct": hit.get("change_pct")})
        focus = [(code, info, strategies) for code, info, strategies in
                 [(c, code_info[c], s) for c, s in code_strategies.items() if len(s) >= 2]]
        if focus:
            focus.sort(key=lambda x: len(x[2]), reverse=True)
            lines = [f"⭐ 重点股票（多策略共振）"]
            for code, info, strategies in focus:
                code = code.replace("sh", "").replace("sz", "").replace("bj", "")
                parts = [code, info['name']]
                industry = info.get('industry', '')
                if industry:
                    parts.append(industry)
                price = info["price"]
                change_pct = info["change_pct"]
                if price and price > 0:
                    change_str = f" {change_pct:+.2f}%" if change_pct is not None else ""
                    parts.append(f"{price:.2f}{change_str}")
                parts.append(f"({'+'.join(strategies)})")
                lines.append(" ".join(parts))
            messages.append("\n".join(lines))

        return messages

    def format_message(self, results: dict[str, list[dict]], elapsed: float = 0) -> str:
        """格式化单条通知消息（兼容旧接口）"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if not results:
            return f"📊 选股提醒\n\n时间: {now}\n耗时: {elapsed:.1f}秒\n\n未筛选出符合条件的股票"

        lines = [f"📊 选股提醒", f"时间: {now}", f"耗时: {elapsed:.1f}秒"]
        total = 0
        for strategy_name, hits in results.items():
            if not hits:
                continue
            lines.append(f"\n【{strategy_name}】")
            for hit in hits:
                reason = hit.get("reason") or "+".join(hit.get("conditions", []))
                code = hit['code'].replace("sh", "").replace("sz", "").replace("bj", "")
                price = hit.get("price")
                change_pct = hit.get("change_pct")
                if price and price > 0:
                    change_str = f" {change_pct:+.2f}%" if change_pct is not None else ""
                    lines.append(f"• {code} {hit.get('name', '')} {price:.2f}{change_str} - {reason}")
                else:
                    lines.append(f"• {code} {hit.get('name', '')} - {reason}")
                total += 1

        lines.append(f"\n共筛选出 {total} 只股票")
        return "\n".join(lines)

    def send(self, message: str, test: bool = False) -> bool:
        """发送钉钉消息，失败重试3次。test=True时使用测试机器人"""
        webhook = self.test_webhook if test else self.webhook
        secret = self.test_secret if test else self.secret
        if not webhook:
            logger.warning("钉钉Webhook未配置，跳过发送")
            return False

        # 钉钉文本消息body限制约20000字节
        MAX_BYTES = 18000
        msg_bytes = message.encode("utf-8")
        if len(msg_bytes) > MAX_BYTES:
            # 按行截断，保留前面的行
            lines = message.split("\n")
            truncated = []
            current_len = 0
            for line in lines:
                line_len = len(line.encode("utf-8")) + 1  # +1 for \n
                if current_len + line_len > MAX_BYTES - 50:  # 留空间给截断提示
                    break
                truncated.append(line)
                current_len += line_len
            truncated.append(f"... (已截断，共{len(lines)}行)")
            message = "\n".join(truncated)

        url = self._build_url(webhook, secret)
        payload = {
            "msgtype": "text",
            "text": {"content": message},
        }
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                data = resp.json()
                if data.get("errcode") == 0:
                    return True
                logger.warning(f"钉钉发送失败: {data}")
            except Exception as e:
                logger.warning(f"钉钉发送异常(第{attempt + 1}次): {e}")
            if attempt < 2:
                time.sleep(5)
        return False

    @staticmethod
    def _build_url(webhook: str, secret: str) -> str:
        """构建带签名的webhook URL"""
        if not secret:
            return webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{webhook}&timestamp={timestamp}&sign={sign}"
