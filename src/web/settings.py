"""设置页:读取/写回 config.json(目前仅 llm.model)

写回采用原子替换(临时文件 + os.replace),保持 4 空格缩进与原文件一致。
"""

import json
import os
from pathlib import Path
from typing import Dict

DEFAULT_MODEL = "deepseek-v4-flash"

_CONFIG_ENV = "DNEWS_CONFIG"


def _config_path() -> Path:
    return Path(os.environ.get(_CONFIG_ENV, "config.json"))


class SettingsError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def read_settings() -> Dict:
    """读取当前设置;config 缺失字段回退默认值"""
    path = _config_path()
    model = DEFAULT_MODEL
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            model = cfg.get("llm", {}).get("model") or DEFAULT_MODEL
        except (json.JSONDecodeError, OSError):
            pass
    return {"model": model, "defaultModel": DEFAULT_MODEL}


def update_settings(model: str) -> Dict:
    """写回 llm.model 到 config.json"""
    model = (model or "").strip()
    if not model or len(model) > 100:
        raise SettingsError("模型名不能为空且不超过 100 字符")
    if any(c in model for c in '\n\r\t'):
        raise SettingsError("模型名包含非法字符")

    path = _config_path()
    if not path.is_file():
        raise SettingsError(f"配置文件不存在: {path}", status_code=500)

    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SettingsError(f"配置文件解析失败: {e}", status_code=500)

    cfg.setdefault("llm", {})["model"] = model

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    return read_settings()
