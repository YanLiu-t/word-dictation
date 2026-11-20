# -*- coding: utf-8 -*-
"""网页版界面。启动方式：dictation web"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dictation import __version__, config, normalize, ocr, verify, wordlist  # noqa: E402
from dictation import build as builder  # noqa: E402
from dictation.batch import Batch  # noqa: E402
from dictation.cli import load_prompt  # noqa: E402

PROVIDERS = {
    "glm": {
        "name": "智谱 GLM-4V-Flash",
        "free": "有免费额度，中文手写认得比较准",
        "apply": "https://open.bigmodel.cn/",
    },
    "gemini": {
        "name": "Google Gemini Flash",
        "free": "每天有免费次数，英文认得好",
        "apply": "https://aistudio.google.com/apikey",
    },
    "qwen": {
        "name": "通义 Qwen-VL",
        "free": "新用户有免费额度",
        "apply": "https://bailian.console.aliyun.com/",
    },
}

STATUS_LABEL = {"ok": "ok（进音频）", "review": "review（待核对）", "dup": "dup（重复）", "skip": "skip（不要）"}

st.set_page_config(page_title="单词听写音频", page_icon="🎧", layout="wide")


def save_key(provider: str, value: str) -> Path:
    """把 Key 写入本机 .env，同时立即生效。"""
    env_name = config.KEY_ENV[provider]
    env_path = config.data_root() / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith(f"{env_name}="):
            out.append(f"{env_name}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{env_name}={value}")
    env_path.write_text("\n".join(out).strip() + "\n", encoding="utf-8")
    os.environ[env_name] = value
    return env_path


def render_sidebar() -> str:
    with st.sidebar:
        st.header("识别服务")
        provider = st.selectbox(
            "选择服务商",
            options=list(PROVIDERS),
            format_func=lambda k: PROVIDERS[k]["name"],
            index=0,
        )
        info = PROVIDERS[provider]
        st.caption(f"免费额度：{info['free']}")
        st.caption(f"申请地址：{info['apply']}")

        current = config.api_key(provider)
        if current:
            st.success(f"已经填过了（{current[:4]}…）")
        else:
            st.warning("还没填 Key")

        key = st.text_input("粘贴 API Key", type="password", placeholder="只存在本机 .env")
        col1, col2 = st.columns(2)
        if col1.button("保存"):
            if key.strip():
                save_key(provider, key.strip())
                st.success("存好了")
                st.rerun()
            else:
                st.error("Key 是空的")
        if col2.button("测试连接"):
            with st.spinner("试一下能不能连上…"):
                try:
                    ocr.test_provider(provider, key.strip() or current)
                    st.success("能连上")
                except Exception as exc:
                    st.error(f"没连上：{exc}")

        st.divider()
        st.caption(
            "Key 只写在本机 .env 里，.gitignore 已经排除，不会传到别处。"
            "十页差不多十几次请求，免费额度够用一阵。"
        )
        st.divider()
        st.caption(f"word-dictation v{__version__}")
    return provider


def save_uploads(batch: Batch, files) -> int:
    batch.ensure()
    for old in batch.input_dir.iterdir():
        if old.is_file():
            old.unlink()
    for index, uploaded in enumerate(files, 1):
        suffix = Path(uploaded.name).suffix.lower() or ".jpg"
        (batch.input_dir / f"{index:02d}{suffix}").write_bytes(uploaded.getbuffer())
    return len(files)


def list_batches(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir() and (p / "wordlist.tsv").is_file()])


def main() -> None:
    st.title("手写单词本 → 听写音频")
    st.caption("拍照片，认词，改表，最后出 mp3。拿不准的词默认不读。")

    provider = render_sidebar()
    config.load()  # 载入 .env，保证后续 api_key 可用

    work_root = Path.cwd() / "批次"
    work_root.mkdir(parents=True, exist_ok=True)

    with st.expander("① 传照片认词", expanded=True):
        batch_name = st.text_input("批次名称", value="10页", help="音频文件名会用这个")
        files = st.file_uploader(
            "选择照片（一次 3–10 张，多点也行）",
            type=["jpg", "jpeg", "png", "webp", "bmp"],
            accept_multiple_files=True,
        )
        st.caption("顺序按你选文件的顺序来。想严格按页排，先把文件改成 01、02、03 再传。")
        st.caption("每张照片是单独认的，传多少张都不影响单张的准确率，只是等得久一点。")

        start = st.button("开始识别", type="primary", disabled=not files)
        if start and files:
            batch = Batch(work_root / batch_name)
            status = st.status("正在认，别急…", expanded=True)
            try:
                status.write(f"保存 {len(files)} 张照片")
                save_uploads(batch, files)

                if provider != "manual":
                    status.write(f"交给 {PROVIDERS[provider]['name']} 认字")
                    ocr.extract(batch, provider, load_prompt(), config.load(batch.root),
                                only_missing=False)
                else:
                    status.write("手动模式：跳过识别，直接读 ocr/ 里已有的 JSON")

                pages = batch.ocr_files()
                if not pages:
                    raise RuntimeError(f"{batch.ocr_dir} 里没有识别结果")
                status.write(f"整理了 {len(pages)} 页")
                rows, stats = normalize.from_ocr(pages)
                wordlist.write(batch.wordlist_path, rows)
                normalize.write_report(batch.report_path, rows, stats, batch.name)

                st.session_state["batch"] = str(batch.root)
                status.update(label=f"认完了，{stats.total} 条，其中 {stats.review} 条要你看一眼",
                              state="complete")
            except Exception as exc:
                status.update(label="失败", state="error")
                st.error(str(exc))

    batch_dir = st.session_state.get("batch")
    existing = list_batches(work_root)
    if existing:
        picked = st.selectbox("或者接着上次的批次", options=["（不打开）"] + existing, index=0)
        if picked != "（不打开）":
            batch_dir = str(work_root / picked)

    if not batch_dir or not Path(batch_dir).is_dir():
        st.info("还没选照片。可以现在传，也可以从上面挑一个以前的批次。")
        return

    batch = Batch(batch_dir)
    if not batch.wordlist_path.is_file():
        st.info(f"{batch.root} 里还没有词表")
        return

    rows = wordlist.read(batch.wordlist_path)
    st.subheader("② 看一眼词表")
    st.caption("只有 ok 会读出来。改完先点保存，再去合成。")

    df = pd.DataFrame(
        [
            {
                "序号": r.seq,
                "单词": r.word,
                "释义": r.meaning,
                "状态": r.status,
                "备注": r.note,
                "来源": r.source,
            }
            for r in rows
        ]
    )
    edited = st.data_editor(
        df,
        hide_index=True,
        disabled=["序号", "备注", "来源"],
        column_config={
            "状态": st.column_config.SelectboxColumn(
                "状态", options=["ok", "review", "dup", "skip"], required=True
            ),
            "单词": st.column_config.TextColumn("单词", width="medium"),
            "释义": st.column_config.TextColumn("释义", width="large"),
        },
        key=f"editor_{batch.name}_{len(rows)}",
    )

    col1, col2, col3 = st.columns([1, 1, 3])
    if col1.button("保存修改"):
        new_rows = [
            wordlist.Row(
                seq=int(rec["序号"]),
                word=str(rec["单词"]).strip(),
                meaning=str(rec["释义"]).strip(),
                note=str(rec["备注"] or ""),
                status=str(rec["状态"]),
                source=str(rec["来源"] or ""),
            )
            for rec in edited.to_dict("records")
        ]
        wordlist.write(batch.wordlist_path, new_rows)
        st.success(f"存好了，{len(new_rows)} 条")

    if col2.button("释义反查"):
        if provider == "manual":
            st.warning("手动模式没配识别服务，反查用不了")
        else:
            try:
                info = verify.run(batch.root, provider)
                st.success(f"查了 {info['checked']} 条，改了 {info['fixed']} 条。刷新一下就能看到")
                st.rerun()
            except Exception as exc:
                st.error(f"反查失败：{exc}")

    ok_count = sum(1 for r in rows if r.in_audio)
    st.caption(f"这次会读 {ok_count} 个词。文件夹：{batch.root}")

    st.subheader("③ 出音频")
    c1, c2 = st.columns(2)
    rounds = c1.selectbox(
        "读几遍",
        options=[1, 2, 3],
        index=1,
        format_func=lambda n: {1: "一遍（词 → 义）", 2: "两遍（词 → 义 → 词 → 义）",
                               3: "三遍（词义重复三次）"}[n],
    )
    speed = c2.selectbox(
        "语速",
        options=[1.0, 1.5, 0.5],
        index=0,
        format_func=lambda v: {1.0: "正常 1.0×", 1.5: "快 1.5×", 0.5: "慢 0.5×"}[v],
    )
    if st.button("开始合成", type="primary"):
        with st.spinner("第一次会慢一点，之后就快了"):
            try:
                info = builder.run(batch, config.load(batch.root), name=batch.name,
                                   quiet=True, rounds=rounds, speed=speed)
                st.session_state["built"] = info
                st.session_state["batch"] = str(batch.root)
            except Exception as exc:
                st.error(str(exc))

    info = st.session_state.get("built")
    if info:
        st.success(f"好了，读了 {info['count']} 个词，{info['speed']:g}× 语速，用了 {info['seconds']:.1f} 秒")
        downloads = []
        for (label, _), path in zip(info.get("outputs", []), info.get("files", [])):
            downloads.append((label, Path(path)))
        if info.get("script"):
            downloads.append(("朗读脚本", Path(info["script"])))
        for label, path in downloads:
            if path.is_file():
                mime = "audio/mpeg" if path.suffix == ".mp3" else "text/plain"
                st.download_button(
                    f"下载 {label}（{path.stat().st_size / 1024 / 1024:.1f} MB）",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    key=f"dl_{path.name}",
                )
        if batch.report_path.is_file():
            with st.expander("看处理记录"):
                st.markdown(batch.report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
