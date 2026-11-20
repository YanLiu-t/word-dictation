# -*- coding: utf-8 -*-
"""命令行入口：extract / check / build / doctor。"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

from . import __version__, build, config, normalize, ocr, tts, verify, wordlist
from .batch import Batch


def load_prompt() -> str:
    """从 prompts/extract.md 里取出 Prompt 正文。"""
    md = config.REPO_ROOT / "prompts" / "extract.md"
    if not md.is_file():
        raise RuntimeError(f"找不到识别 Prompt：{md}")
    text = md.read_text(encoding="utf-8")
    marker = "```text"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError("prompts/extract.md 里没有 ```text 代码块")
    start += len(marker)
    end = text.find("```", start)
    return text[start:end].strip()


def cmd_extract(args) -> int:
    batch = Batch(args.batch)
    batch.ensure()
    cfg = config.load(batch.root)
    if args.provider == "manual":
        print("手动模式：请把图片交给任意支持读图的 AI，使用 prompts/extract.md 取得 JSON，")
        print(f"存成 {batch.ocr_dir}\\p01.json、p02.json … 然后运行 dictation check")
        return 0
    prompt = load_prompt()
    print(f"使用 {args.provider} 识别 {batch.describe()}")
    saved = ocr.extract(batch, args.provider, prompt, cfg,
                        only_missing=not args.overwrite, model=args.model,
                        cross=False if args.no_cross else None)
    print(f"完成，共 {len(saved)} 页写入 {batch.ocr_dir}")
    print("下一步：dictation check " + str(batch.root))
    return 0


def cmd_check(args) -> int:
    batch = Batch(args.batch)
    files = batch.ocr_files()
    if not files:
        raise RuntimeError(f"{batch.ocr_dir} 里没有 JSON，先运行 dictation extract（或用 --provider manual 手动放入）")

    if batch.wordlist_path.is_file() and not args.force:
        newest_ocr = max(f.stat().st_mtime for f in files)
        if batch.wordlist_path.stat().st_mtime > newest_ocr:
            print("检测到 wordlist.tsv 比识别结果更新，可能已人工修改。")
            print("继续会覆盖这些修改；确认要重算请加 --force")
            return 2

    rows, stats = normalize.from_ocr(files)
    wordlist.write(batch.wordlist_path, rows)
    normalize.write_report(batch.report_path, rows, stats, batch.name)

    print(f"页数 {stats.pages}，词条 {stats.total}")
    print(f"  可进音频 {stats.ok}　待核对 {stats.review}　重复 {stats.dup}")
    if stats.review:
        print("待核对条目（不会进音频）：")
        for r in stats.review_items[:10]:
            print(f"  {r.seq:>3} {r.word or '(空)':<18} {r.meaning or '(无释义)':<16} {r.note}")
        if len(stats.review_items) > 10:
            print(f"  … 其余 {len(stats.review_items) - 10} 条见 report.md")
    print(f"词表：{batch.wordlist_path}")
    print(f"报告：{batch.report_path}")
    print("核对完成后运行：dictation build " + str(batch.root))
    return 0


def cmd_verify(args) -> int:
    batch = Batch(args.batch)
    if not batch.wordlist_path.is_file():
        raise RuntimeError(f"找不到 {batch.wordlist_path}，先运行 dictation check")
    config.load(batch.root)
    info = verify.run(batch.root, args.provider, only=args.only)
    print(f"检查 {info['checked']} 条：修正 {info['fixed']} 条")
    print(f"词表：{batch.wordlist_path}")
    print("确认无误后运行：dictation build " + str(batch.root))
    return 0


def cmd_build(args) -> int:
    batch = Batch(args.batch)
    if not batch.wordlist_path.is_file():
        raise RuntimeError(f"找不到 {batch.wordlist_path}，先运行 dictation check")
    cfg = config.load(batch.root)
    if args.backend != "edge":
        raise RuntimeError("当前版本仅支持 edge 后端；离线 piper 后端在后续版本提供")
    info = build.run(batch, cfg, name=args.name)
    print(f"完成，朗读 {info['count']} 个词，耗时 {info['seconds']:.1f} 秒")
    print(f"  读一遍：{info['once']}")
    print(f"  读两遍：{info['twice']}")
    if info["skipped"]:
        print(f"  跳过 {info['skipped']} 条（非 ok 状态）")
    print(f"输出目录：{batch.out_dir}")
    return 0


def cmd_doctor(args) -> int:
    print(f"cet6-dictation {__version__}")
    print(f"Python {sys.version.split()[0]}（需要 >= 3.10）")
    ok = True
    for mod in ("edge_tts", "lameenc"):
        try:
            __import__(mod)
            print(f"  依赖 {mod}：正常")
        except ImportError:
            print(f"  依赖 {mod}：缺失，执行 pip install -r requirements.txt")
            ok = False
    for provider, env in config.KEY_ENV.items():
        key = config.api_key(provider)
        print(f"  {env}：{'已配置（' + key[:4] + '…）' if key else '未配置'}")
    cache = Path(args.batch).expanduser() / ".cache"
    if cache.is_dir():
        count = len(list(cache.glob("*.mp3")))
        size = sum(p.stat().st_size for p in cache.glob("*.mp3")) / 1024 / 1024
        print(f"  语音缓存：{count} 个片段，{size:.1f} MB")
    return 0 if ok else 1


def _lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def cmd_web(args) -> int:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise RuntimeError('未安装网页依赖，执行：pip install -e ".[web]"')

    script = Path(__file__).with_name("web.py")
    address = "0.0.0.0" if args.lan else "localhost"
    env = dict(
        os.environ,
        STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
        STREAMLIT_SERVER_HEADLESS="true",
    )
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.address", address,
        "--server.port", str(args.port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    print(f"网页版：http://localhost:{args.port}")
    if args.lan:
        print(f"手机（同一 WiFi）：http://{_lan_ip()}:{args.port}")
    print("按 Ctrl+C 停止")
    return subprocess.call(cmd, env=env)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dictation",
        description="手写单词笔记照片 → 词表 → 中英交替听写音频",
    )
    parser.add_argument("--version", action="version", version=f"cet6-dictation {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="调用识别服务，把图片转成 ocr/*.json")
    p.add_argument("batch", help="批次目录，如 批次/10页")
    p.add_argument("--provider", default="glm", choices=["glm", "gemini", "qwen", "manual"],
                   help="识别服务，默认 glm；manual 表示自己把 JSON 放进 ocr/")
    p.add_argument("--model", default=None,
                   help="指定模型，如 glm-4v-plus（付费）；默认用免费链")
    p.add_argument("--no-cross", action="store_true", help="关闭第二遍交叉校验")
    p.add_argument("--overwrite", action="store_true", help="已有 JSON 也重新识别")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("check", help="校验识别结果并生成 wordlist.tsv")
    p.add_argument("batch", help="批次目录")
    p.add_argument("--force", action="store_true", help="即使 wordlist.tsv 更新过也覆盖")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("verify", help="用文本模型做释义反查，校正形近误读")
    p.add_argument("batch", help="批次目录")
    p.add_argument("--provider", default="glm", choices=["glm", "gemini", "qwen"])
    p.add_argument("--only", default="all", choices=["all", "ok"],
                   help="只检查 ok 行（ok），或连同 review 一起查（all）")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("build", help="按词表合成读一遍 / 读两遍音频")
    p.add_argument("batch", help="批次目录")
    p.add_argument("--name", default=None, help="输出文件名前缀，默认取批次目录名")
    p.add_argument("--backend", default="edge", choices=["edge"], help="语音后端")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("doctor", help="检查环境与配置")
    p.add_argument("batch", nargs="?", default=".", help="批次目录（用于统计缓存）")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("web", help="启动网页版界面")
    p.add_argument("--port", type=int, default=8501, help="端口，默认 8501")
    p.add_argument("--lan", action="store_true", help="允许同一 WiFi 的手机访问")
    p.set_defaults(func=cmd_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
