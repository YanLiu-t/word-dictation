# -*- coding: utf-8 -*-
"""词表 → 音频。对应 SOP 第 6 节。"""
from __future__ import annotations

import time
from pathlib import Path

from . import normalize, tts, wordlist
from .batch import Batch


LABELS = {1: "读一遍", 2: "读两遍", 3: "读三遍"}


def _parts_for(rows, mapping, gaps, cfg: dict, rounds: int) -> list[Path]:
    """按「英文 → 中文」重复 rounds 遍，拼出片段序列。"""
    parts: list[Path] = []
    for row in rows:
        en = mapping[(tts.say(row.word, cfg), "en")]
        zh = mapping[(row.meaning, "zh")]
        for turn in range(rounds):
            if turn:
                parts.append(gaps["rounds"])
            parts += [en, gaps["en_zh"], zh]
        parts.append(gaps["word"])
    return parts


def run(batch: Batch, cfg: dict, name: str | None = None, quiet: bool = False,
        rounds: int | None = None, speed: float = 1.0) -> dict:
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

    mapping = tts.synth_pairs(pairs, batch.cache_dir, cfg, progress=progress, speed=speed)
    if not quiet:
        print(" " * 40, end="\r")
    gaps = tts.prepare_gaps(batch.cache_dir, cfg)

    batch_name = name or batch.name
    batch.out_dir.mkdir(parents=True, exist_ok=True)
    targets = [rounds] if rounds in LABELS else [1, 2]

    outputs: list[tuple[str, str]] = []
    files: list[Path] = []
    for count in targets:
        out = batch.out_dir / f"{batch_name}_{LABELS[count]}.mp3"
        size = tts.concat(_parts_for(audio_rows, mapping, gaps, cfg, count), out)
        outputs.append((LABELS[count], f"{out.name}（{size / 1024 / 1024:.2f} MB，约 {size / 6000 / 60:.1f} 分钟）"))
        files.append(out)

    script_file = batch.out_dir / f"{batch_name}_脚本.txt"
    repeat = max(targets)
    lines = []
    for r in audio_rows:
        bits: list[str] = []
        for _ in range(repeat):
            bits += [r.word, r.meaning]
        lines.append(" -> ".join(bits))
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
        "outputs": outputs,
        "files": [str(p) for p in files],
        "script": str(script_file),
        "rounds": max(targets),
        "speed": speed,
        "seconds": time.time() - started,
        "skipped": len(rows) - len(audio_rows),
        "pronounced": pronounced,
    }
    normalize.append_audio_report(batch.report_path, info)
    return info
