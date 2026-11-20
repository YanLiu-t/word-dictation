# -*- coding: utf-8 -*-
"""词表 → 音频。对应 SOP 第 6 节。"""
from __future__ import annotations

import time
from pathlib import Path

from . import normalize, tts, wordlist
from .batch import Batch


def _parts_for(rows, mapping, gaps, cfg: dict, rounds: int) -> list[Path]:
    """按「英文 → 中文」重复 rounds 遍，拼出片段序列。"""
    parts: list[Path] = []
    for row in rows:
        en = mapping[(tts.say(row.word, cfg), "en")]
        zh = mapping[(row.meaning, "zh")]
        parts += [en, gaps["en_zh"], zh]
        if rounds == 2:
            parts += [gaps["rounds"], en, gaps["en_zh"], zh]
        parts.append(gaps["word"])
    return parts


def run(batch: Batch, cfg: dict, name: str | None = None, quiet: bool = False) -> dict:
    rows = wordlist.read(batch.wordlist_path)
    audio_rows = [r for r in rows if r.in_audio]
    if not audio_rows:
        raise RuntimeError("没有可朗读的词条（status 全是 review/dup/skip，或释义为空）")

    started = time.time()
    pairs: list[tuple[str, str]] = []
    for row in audio_rows:
        pairs.append((tts.say(row.word, cfg), "en"))
        pairs.append((row.meaning, "zh"))

    def progress(done: int, total: int) -> None:
        if not quiet:
            print(f"  合成语音 {done}/{total}", end="\r", flush=True)

    mapping = tts.synth_pairs(pairs, batch.cache_dir, cfg, progress=progress)
    if not quiet:
        print(" " * 40, end="\r")
    gaps = tts.prepare_gaps(batch.cache_dir, cfg)

    batch_name = name or batch.name
    batch.out_dir.mkdir(parents=True, exist_ok=True)
    out_once = batch.out_dir / f"{batch_name}_读一遍.mp3"
    out_twice = batch.out_dir / f"{batch_name}_读两遍.mp3"
    script_file = batch.out_dir / f"{batch_name}_脚本.txt"

    size_once = tts.concat(_parts_for(audio_rows, mapping, gaps, cfg, 1), out_once)
    size_twice = tts.concat(_parts_for(audio_rows, mapping, gaps, cfg, 2), out_twice)

    lines = [f"{r.word} -> {r.meaning} -> {r.word} -> {r.meaning}" for r in audio_rows]
    script_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    pronounced = sorted(
        {
            f"{r.word} → {tts.say(r.word, cfg)}"
            for r in audio_rows
            if tts.say(r.word, cfg).lower() != r.word.lower()
        }
    )
    info = {
        "count": len(audio_rows),
        "once": f"{out_once.name}（{size_once / 1024 / 1024:.2f} MB，约 {size_once / 6000 / 60:.1f} 分钟）",
        "twice": f"{out_twice.name}（{size_twice / 1024 / 1024:.2f} MB，约 {size_twice / 6000 / 60:.1f} 分钟）",
        "seconds": time.time() - started,
        "skipped": len(rows) - len(audio_rows),
        "pronounced": pronounced,
    }
    normalize.append_audio_report(batch.report_path, info)
    return info
