# -*- coding: utf-8 -*-
"""打包入口：双击 exe 后启动本地网页版并自动打开浏览器。"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 8501


def _resource_dir() -> Path:
    """打包后资源在 _MEIPASS（onedir 模式为 _internal）；源码运行时在仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def main() -> int:
    base = _resource_dir()
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

    script = base / "ui" / "web.py"
    if not script.is_file():
        script = base / "src" / "dictation" / "web.py"

    url = f"http://localhost:{PORT}"
    threading.Timer(3.0, lambda: webbrowser.open(url)).start()
    print(f"网页版已启动：{url}")
    print("关闭这个窗口即停止服务。")

    # 显式导入，保证 PyInstaller 把这些模块打进包里
    import dictation  # noqa: F401
    import dictation.web  # noqa: F401

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", str(script),
        "--server.address", "localhost",
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
