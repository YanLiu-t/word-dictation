# -*- coding: utf-8 -*-
"""识别结果 → 词表：顺序、去重、可疑标记。对应 SOP 第 5 节 R1–R8。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import wordlist
from .batch import page_no
from .wordlist import DUP, OK, REVIEW, Row

LOW_CONFIDENCE = 0.9
_SPACES = re.compile(r"\s+")
_BAD_HYPHEN = re.compile(r"\s*[-‐‑–—]\s*")


def clean_word(raw: str) -> str:
    """统一小写、收拢空格、规范连字符。"""
    word = (raw or "").strip().lower()
    word = word.replace("’", "'")
    word = _BAD_HYPHEN.sub("-", _SPACES.sub(" ", word))
    return word.strip(" .,;:")


_COMMAS = re.compile(r"\s*[,，、;；]\s*")
# 释义里不该出现阿拉伯数字，出现了基本是识别串行
_ODD_MEANING = re.compile(r"[0-9]")


def clean_meaning(raw: str) -> str:
    """统一用中文全角逗号分隔义项，去掉多余空格。"""
    text = _SPACES.sub(" ", (raw or "").strip())
    text = _COMMAS.sub("，", text)
    return text.strip("，。;；")


def _chars(text: str) -> set[str]:
    return {c for c in (text or "") if "\u4e00" <= c <= "\u9fff"}


def meaning_drift(raw: str, suggest: str) -> bool:
    """手写释义与补全释义差异过大的粗判：汉字重合比例低于 30%。"""
    a, b = _chars(raw), _chars(suggest)
    if not a or not b:
        return False
    return len(a & b) / len(a) < 0.3


@dataclass
class Stats:
    pages: int = 0
    total: int = 0
    review: int = 0
    dup: int = 0
    ok: int = 0
    empty_meaning: int = 0
    drift: int = 0
    review_items: list[Row] = field(default_factory=list)
    dup_items: list[Row] = field(default_factory=list)
    drift_items: list[Row] = field(default_factory=list)


def from_ocr(files: list[Path]) -> tuple[list[Row], Stats]:
    rows: list[Row] = []
    stats = Stats(pages=len(files))
    seen: dict[str, int] = {}

    for path in files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        source = f"p{page_no(path):02d}" if page_no(path) != 9999 else path.stem
        items = data.get("items") or []
        for item in items:
            word_raw = item.get("word", "") or ""
            variant = ""
            if "/" in word_raw:  # 模型常写 tyre/tire、utilize/-ise 这类异体
                head, _, tail = word_raw.partition("/")
                variant = tail.strip().lstrip("-(").rstrip(")")
                word_raw = head
            word = clean_word(word_raw)
            raw = clean_meaning(item.get("meaning_raw") or item.get("meaning") or "")
            suggest = clean_meaning(item.get("meaning_suggest") or item.get("suggest") or "")
            note_bits: list[str] = []
            if variant:
                note_bits.append(f"异体拼写：{variant}")

            if not word:
                note_bits.append("整行无法辨认，需人工补录")
                meaning = raw or suggest
                status = REVIEW
            else:
                try:
                    conf = float(item.get("word_confidence", item.get("confidence", 1)))
                except (TypeError, ValueError):
                    conf = 1.0
                candidates = [c for c in (item.get("candidates") or []) if c]
                if conf < LOW_CONFIDENCE:
                    note_bits.append(f"拼写置信度低（{conf:.2f}）")
                if candidates:
                    note_bits.append("候选：" + " / ".join(candidates))
                status = REVIEW if (conf < LOW_CONFIDENCE or candidates) else OK

                if raw:
                    meaning = raw
                    if _ODD_MEANING.search(raw):
                        note_bits.append("释义含数字等异常字符，疑识别错误")
                        status = REVIEW
                    if suggest and meaning_drift(raw, suggest):
                        note_bits.append(f"手写释义与高频义差异较大，补全建议：{suggest}")
                        stats.drift += 1
                        if status == OK:
                            status = REVIEW
                elif suggest:
                    meaning = suggest
                    note_bits.append("释义未识别，已用补全释义")
                    stats.empty_meaning += 1
                else:
                    meaning = ""
                    note_bits.append("缺释义，需人工补录")
                    status = REVIEW

            if word and word in seen:
                note_bits.append(f"与第 {seen[word]} 条重复")
                status = DUP

            model_note = (item.get("note", "") or "").strip()
            cc = item.get("cross_check")
            # 只有「第二遍多看到的词」才算不一致：第二遍模型较弱，
            # 它漏读第一遍已识别的词（primary_only）属于正常现象，不拦
            if cc == "secondary_only" or (cc == "diff" and "仅第二遍识别到" in model_note):
                note_bits.append("两遍识别不一致，需人工确认")
                if status == OK:
                    status = REVIEW
            pieces = note_bits + ([model_note] if model_note else [])
            pieces = list(dict.fromkeys(p for p in pieces if p))
            # 去掉被其他说明包含的冗余片段
            pieces = [p for p in pieces if not any(p != q and p in q for q in pieces)]
            note = "；".join(pieces)

            row = Row(
                seq=len(rows) + 1,
                word=word,
                meaning=meaning,
                note=note,
                status=status,
                source=source,
            )
            rows.append(row)

            if status == DUP:
                stats.dup += 1
                stats.dup_items.append(row)
            elif status == REVIEW:
                stats.review += 1
                stats.review_items.append(row)
            else:
                stats.ok += 1
            # 不管当前状态如何都记下单词，后面的重复项才能被识别出来
            if word:
                seen.setdefault(word, row.seq)

    stats.total = len(rows)
    return rows, stats


def write_report(path: Path, rows: list[Row], stats: Stats, batch_name: str) -> None:
    lines = [
        f"# 处理报告 · {batch_name}",
        "",
        "## 概况",
        "",
        "| 项目 | 数量 |",
        "|---|---|",
        f"| 识别页数 | {stats.pages} |",
        f"| 词条总数 | {stats.total} |",
        f"| 可直接进音频（ok） | {stats.ok} |",
        f"| 待核对（review） | {stats.review} |",
        f"| 重复（dup） | {stats.dup} |",
        f"| 释义未识别 | {stats.empty_meaning} |",
        f"| 释义疑似偏差 | {stats.drift} |",
        "",
    ]

    if stats.review_items:
        lines += [
            "## 待核对（这些不进音频）",
            "",
            "| 序号 | 单词 | 释义 | 说明 |",
            "|---|---|---|---|",
        ]
        for r in stats.review_items:
            lines.append(f"| {r.seq} | {r.word} | {r.meaning} | {r.note} |")
        lines.append("")
        lines.append("核对完成后，把对应行的 status 改为 ok 再重新 build。")
        lines.append("")

    if stats.dup_items:
        lines += ["## 重复项（不进音频）", "", "| 序号 | 单词 | 位置 |", "|---|---|---|"]
        for r in stats.dup_items:
            lines.append(f"| {r.seq} | {r.word} | {r.source} |")
        lines.append("")

    drift = [r for r in rows if "差异较大" in r.note]
    if drift:
        lines += ["## 释义偏差提示（已转人工核对）", "", "| 序号 | 单词 | 手写释义 | 建议 |", "|---|---|---|---|"]
        for r in drift:
            lines.append(f"| {r.seq} | {r.word} | {r.meaning} | {r.note.split('补全建议：')[-1]} |")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def append_audio_report(path: Path, info: dict) -> None:
    lines = [
        "## 音频",
        "",
        f"- 朗读词数：{info['count']}",
        f"- 语速：{info.get('speed', 1.0):g}×",
    ]
    for label, detail in info.get("outputs", []):
        lines.append(f"- {label}：{detail}")
    lines += [
        f"- 合成耗时：{info['seconds']:.1f} 秒",
    ]
    if info.get("skipped"):
        lines.append(f"- 跳过（非 ok 状态）：{info['skipped']} 条")
    if info.get("pronounced"):
        lines.append("- 读音修正：" + "，".join(info["pronounced"]))

    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "\n## 音频\n"
    if marker in text:
        text = text.split(marker)[0]
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
