# -*- coding: utf-8 -*-
"""语音合成 + 片段缓存。"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import edge_tts
import lameenc

SAMPLE_RATE = 24000
BITRATE = 48


def cache_path(cache_dir: Path, text: str, voice: str, rate: str) -> Path:
    digest = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:20]
    return Path(cache_dir) / f"{digest}.mp3"


def _valid(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 1000


async def _one(text: str, voice: str, rate: str, path: Path, sem: asyncio.Semaphore,
               tick=None, retries: int = 3) -> None:
    if _valid(path):
        if tick:
            tick()
        return
    last_err = ""
    for attempt in range(retries):
        try:
            async with sem:
                await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
            if _valid(path):
                if tick:
                    tick()
                return
        except Exception as exc:  # 网络抖动重试
            last_err = str(exc)
            if path.exists():
                path.unlink(missing_ok=True)
        await asyncio.sleep(1 + attempt)
    raise RuntimeError(f"合成失败：{text!r}（{last_err}）")


def synth_pairs(pairs: list[tuple[str, str]], cache_dir: Path, cfg: dict,
                progress=None) -> dict[tuple[str, str], Path]:
    """pairs 为 (文本, 语言) 列表，返回 {(文本, 语言): mp3 路径}，已去重。"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    voices = cfg["voices"]
    sem = asyncio.Semaphore(int(cfg.get("concurrency", 8)))
    uniq = list(dict.fromkeys(pairs))
    total = len(uniq)
    state = {"done": 0, "step": max(1, total // 10)}

    def tick() -> None:
        state["done"] += 1
        if progress and (state["done"] % state["step"] == 0 or state["done"] == total):
            progress(state["done"], total)

    mapping: dict[tuple[str, str], Path] = {}
    jobs = []
    for text, lang in uniq:
        spec = voices[lang]
        path = cache_path(cache_dir, text, spec["voice"], spec["rate"])
        mapping[(text, lang)] = path
        jobs.append(_one(text, spec["voice"], spec["rate"], path, sem, tick))

    async def run() -> None:
        results = await asyncio.gather(*jobs, return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise RuntimeError(str(errors[0]))

    asyncio.run(run())
    return mapping


def make_silence(ms: int, path: Path) -> Path:
    """生成指定时长的静音 mp3（24kHz 单声道）。"""
    path = Path(path)
    if _valid(path):
        return path
    enc = lameenc.Encoder()
    enc.set_bit_rate(BITRATE)
    enc.set_in_sample_rate(SAMPLE_RATE)
    enc.set_channels(1)
    enc.set_quality(5)
    frames = int(SAMPLE_RATE * ms / 1000)
    data = enc.encode(b"\x00\x00" * frames) + enc.flush()
    path.write_bytes(data)
    return path


def prepare_gaps(cache_dir: Path, cfg: dict) -> dict[str, Path]:
    gaps = cfg["gaps_ms"]
    return {
        "en_zh": make_silence(int(gaps["en_zh"]), Path(cache_dir) / f"gap_{gaps['en_zh']}ms.mp3"),
        "rounds": make_silence(int(gaps["between_rounds"]), Path(cache_dir) / f"gap_{gaps['between_rounds']}ms.mp3"),
        "word": make_silence(int(gaps["word"]), Path(cache_dir) / f"gap_{gaps['word']}ms.mp3"),
    }


def concat(paths: list[Path], out: Path) -> int:
    total = 0
    with out.open("wb") as fh:
        for p in paths:
            data = Path(p).read_bytes()
            fh.write(data)
            total += len(data)
    return total


def say(word: str, cfg: dict) -> str:
    """按读音修正表处理，连字符词拆成两个词读。"""
    lowered = word.lower()
    spoken = cfg.get("pronounce", {}).get(lowered, word)
    return spoken.replace("-", " ")
