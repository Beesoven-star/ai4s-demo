"""Serve the independent IC example and the existing workbench on localhost."""
import os
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def configure_environment(root=ROOT):
    report_dir = root / 'news-data' / 'ic-reports'
    work_dir = root / 'ongoing_work_ic'
    report_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = root / '.runtime' / 'ic-preview-config.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(json.dumps({'llm':{'model':'deepseek-v4-flash'},
            'sections':{'relevance':{'work_dir':str(work_dir)}}}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.environ["DNEWS_CONFIG"] = str(config_path)
    os.environ["DNEWS_DATA_DIR"] = str(report_dir)
    os.environ["DNEWS_WORK_DIR"] = str(work_dir)
    os.environ['DNEWS_RESEARCH_DOMAIN'] = 'ic'
    os.environ["DNEWS_WEB_DIST"] = str(root / "web" / "dist")
    os.environ["DNEWS_DISCOVERY_DB"] = str(root / "news-data" / "discovery-ic.sqlite")
    os.environ["DNEWS_DISCOVERY_SOURCES"] = str(root / "resources" / "discovery_sources_ic.json")
    os.environ.setdefault("DNEWS_DISCOVERY_AUTO", "1")


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    configure_environment()
    pid_file = ROOT / ".runtime" / "ic-preview.pid"
    pid_file.parent.mkdir(exist_ok=True)
    import uvicorn
    pid_file.write_text(str(os.getpid()), encoding="ascii")
    print("IC briefing: http://127.0.0.1:8001/", flush=True)
    print("Independent IC database; scheduled collection and automatic observations.", flush=True)
    try:
        uvicorn.run("src.web.app:create_app", factory=True, host="127.0.0.1", port=8001)
    finally:
        if pid_file.exists() and pid_file.read_text(encoding="ascii").strip() == str(os.getpid()):
            pid_file.unlink()


if __name__ == "__main__":
    main()
