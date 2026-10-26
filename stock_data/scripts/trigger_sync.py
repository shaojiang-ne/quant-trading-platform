"""手动触发 QMT 数据同步任务。

用法:
  python scripts/trigger_sync.py              # 通过 API 触发（默认）
  python scripts/trigger_sync.py --local       # 本地直接执行
  python scripts/trigger_sync.py --host 192.168.1.10 --port 8000
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def trigger_via_api(host: str, port: int, api_key: str = ""):
    import urllib.request
    import urllib.error
    import json

    url = f"http://{host}:{port}/api/v1/sync/trigger"
    req = urllib.request.Request(url, method="POST")
    if api_key:
        req.add_header("X-API-Key", api_key)

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            print(f"OK: {data}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 409:
            print(f"Conflict: download task is already running")
        else:
            print(f"Error {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"Connection error: {e}")
        sys.exit(1)


def trigger_local():
    import logging
    from data.sync import trigger_download, is_sync_running

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if is_sync_running():
        print("Conflict: download task is already running")
        sys.exit(1)

    ok = trigger_download()
    if not ok:
        print("Conflict: download task is already running")
        sys.exit(1)

    print("OK: download task triggered locally")
    print("Press Ctrl+C to exit (task runs in background thread)")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting (background task continues)")


def main():
    parser = argparse.ArgumentParser(description="Trigger QMT data sync")
    parser.add_argument("--local", action="store_true", help="Run locally instead of via API")
    parser.add_argument("--host", default="127.0.0.1", help="API host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument("--api-key", default="", help="API key for authentication")
    args = parser.parse_args()

    if args.local:
        trigger_local()
    else:
        trigger_via_api(args.host, args.port, args.api_key)


if __name__ == "__main__":
    main()
