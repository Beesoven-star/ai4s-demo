"""Serve local discovery and the original archive without automatic LLM jobs."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    config_path = runtime / "preview-config.json"
    if not config_path.exists():
        config = json.loads((ROOT / "config.json.example").read_text(encoding="utf-8"))
        for platform in config.get("push", {}).values():
            platform["enabled"] = False
        config["site_sync"]["enabled"] = False
        config["search"]["enabled"] = False
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    os.environ["DNEWS_CONFIG"] = str(config_path)
    os.environ["DNEWS_DATA_DIR"] = str(ROOT / "AI4S-Daily-HTML" / "public" / "reports")
    os.environ["DNEWS_WORK_DIR"] = str(ROOT / "ongoing_work")
    os.environ["DNEWS_WEB_DIST"] = str(ROOT / "web" / "dist")
    os.environ.setdefault("DNEWS_DISCOVERY_DB", str(ROOT / "news-data" / "discovery.sqlite"))
    os.environ.setdefault("DNEWS_DISCOVERY_AUTO", "1")
    pid_file = runtime / "preview.pid"

    import uvicorn

    pid_file.write_text(str(os.getpid()), encoding="ascii")
    print("AI4S molecular discovery: http://127.0.0.1:8000/discover", flush=True)
    print("Daily public-source collection enabled (settings in the web UI); no LLM or push jobs.", flush=True)
    try:
        uvicorn.run("src.web.app:create_app", factory=True, host="127.0.0.1", port=8000)
    finally:
        if pid_file.exists() and pid_file.read_text(encoding="ascii").strip() == str(os.getpid()):
            pid_file.unlink()


if __name__ == "__main__":
    main()
