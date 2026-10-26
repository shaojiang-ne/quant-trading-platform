import logging
import os
import uvicorn
from api.routes import app
from config import HTTP_HOST, HTTP_PORT, DATA_DIR
from scheduler.jobs import start_scheduler


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[stock_data] %(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # 降噪：uvicorn access log 使用自定义格式
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    os.makedirs(DATA_DIR, exist_ok=True)

    start_scheduler()

    cert_file = os.path.join(DATA_DIR, "server.crt")
    key_file = os.path.join(DATA_DIR, "server.key")
    use_ssl = os.path.exists(cert_file) and os.path.exists(key_file)

    if use_ssl:
        logging.getLogger(__name__).info(f"HTTPS enabled, listening on https://{HTTP_HOST}:{HTTP_PORT}")
        uvicorn.run(app, host=HTTP_HOST, port=HTTP_PORT, ssl_certfile=cert_file, ssl_keyfile=key_file)
    else:
        logging.getLogger(__name__).info(f"HTTP mode, listening on http://{HTTP_HOST}:{HTTP_PORT}")
        uvicorn.run(app, host=HTTP_HOST, port=HTTP_PORT)


if __name__ == "__main__":
    main()
