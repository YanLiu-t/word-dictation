# -*- coding: utf-8 -*-
"""配置读取：config.json + .env（API Key）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 仓库根目录：src/dictation/config.py → 上三层
REPO_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """用户数据目录：打包后是 exe 所在目录，源码运行时是仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return REPO_ROOT

DEFAULTS = {
    "voices": {
        "en": {"voice": "en-US-AriaNeural", "rate": "-15%"},
        "zh": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "-10%"},
    },
    "gaps_ms": {"en_zh": 200, "between_rounds": 450, "word": 900},
    "pronounce": {
        "plough": "plow",
        "tyre": "tire",
        "odour": "odor",
        "splendour": "splendor",
    },
    "concurrency": 8,
}

# 各家识别服务对应的环境变量名
KEY_ENV = {"glm": "GLM_API_KEY", "gemini": "GEMINI_API_KEY", "qwen": "DASHSCOPE_API_KEY"}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env(*roots: Path) -> None:
    """把 .env 里的键值读进 os.environ，不覆盖已有环境变量。"""
    for root in roots:
        env_file = Path(root) / ".env"
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)


def load(root: Path | None = None) -> dict:
    """读取配置。查找顺序：指定目录的 config.json → 当前目录 → 仓库根。"""
    candidates = []
    if root:
        candidates.append(Path(root) / "config.json")
    candidates += [Path.cwd() / "config.json", REPO_ROOT / "config.json"]

    cfg = DEFAULTS
    for path in candidates:
        if path.is_file():
            cfg = _merge(DEFAULTS, json.loads(path.read_text(encoding="utf-8")))
            break

    load_env(*[c.parent for c in candidates], Path.cwd(), data_root(), REPO_ROOT)
    return cfg


def api_key(provider: str) -> str:
    env_name = KEY_ENV.get(provider)
    return os.environ.get(env_name, "").strip() if env_name else ""
