#!/usr/bin/env python3
"""一次性 AI 端点探针；用 Python 直接打避开 bash 引号坑"""
import json
import time
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def _post_json(path, body, timeout=10):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


_, login = _post_json("/api/auth/login", {"username": "demo", "password": "demo123"})
TOKEN = login["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def post(path: str, body: dict, stream: bool = False, timeout: int = 40):
    url = f"{BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HDR, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            if stream:
                chunks = []
                total = 0
                # 流式：读前 12 秒的内容（足够判首字节 + 速度 + 断流）
                deadline = t0 + min(12, timeout)
                while time.time() < deadline:
                    raw = r.read(2048)
                    if not raw:
                        break
                    chunks.append(raw)
                    total += len(raw)
                    if total > 4000:
                        break
                body_bytes = b"".join(chunks)
                elapsed = (time.time() - t0) * 1000
                print(f"  status={status} ctype={ctype} bytes={total} elapsed={elapsed:.0f}ms")
                try:
                    print("  preview:", body_bytes.decode("utf-8", errors="replace")[:600])
                except Exception:
                    print("  preview: <binary>")
                return status, body_bytes
            else:
                body_bytes = r.read()
                elapsed = (time.time() - t0) * 1000
                print(f"  status={status} ctype={ctype} bytes={len(body_bytes)} elapsed={elapsed:.0f}ms")
                try:
                    txt = body_bytes.decode("utf-8")
                    if len(txt) < 1500:
                        print("  body:", txt)
                    else:
                        print("  body[:700]:", txt[:700])
                        print("  body[-300:]:", txt[-300:])
                except Exception:
                    print("  body: <binary>")
                return status, body_bytes
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - t0) * 1000
        body_bytes = e.read()
        print(f"  HTTPError status={e.code} elapsed={elapsed:.0f}ms body={body_bytes[:600]!r}")
        return e.code, body_bytes
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        print(f"  Exception {type(e).__name__} elapsed={elapsed:.0f}ms: {e}")
        return None, b""


cases = [
    ("/api/ai/chat (stream, retry)", "/api/ai/chat",
     {"messages": [{"role": "user", "content": "一句话回答：今天是周几?"}]}, True, 25),
    ("/api/ai/test-code (no LLM)", "/api/ai/test-code",
     {"code": "def generate_signals(df, setting):\n    import pandas as pd\n    return pd.Series(0, index=df.index)", "parameters": {}}, False, 15),
    ("/api/ai/analyze-stock (sync) raw", "/api/ai/analyze-stock",
     {"symbol": "000001", "stock_name": "平安银行"}, False, 60),
    ("/api/agent/pick/strategy (sync)", "/api/agent/pick/strategy",
     {"description": "高换手 + 放量突破"}, False, 90),
    ("/api/agent/pick/optimize-stream", "/api/agent/pick/optimize-stream",
     {"description": "MA 金叉策略"}, True, 40),
]

for label, path, body, stream, t in cases:
    print(f"===== {label} =====")
    post(path, body, stream=stream, timeout=t)
    print()

print("DONE")