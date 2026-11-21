"""python -m src.web → 启动报告归档 Web 服务(uvicorn)"""

import uvicorn

from src.config import load_config


def main() -> int:
    config = load_config()
    web_cfg = config.get("web", {})
    host = web_cfg.get("host", "127.0.0.1")
    port = int(web_cfg.get("port", 8000))
    print(f"🌐 报告归档 Web 服务启动: http://{host}:{port}")
    uvicorn.run("src.web.app:create_app", factory=True, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
