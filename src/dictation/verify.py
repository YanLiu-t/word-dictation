# -*- coding: utf-8 -*-
"""释义反查校正：用纯文本模型检查「单词 ↔ 释义」是否匹配。

只处理语义，不重新看图。手写释义读对、单词拼错（bark/bank）时最有效；
修正后仍保持原有 status 语义，改不动的转 review。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, ocr, wordlist
from .wordlist import DUP, OK, Row

SYSTEM = """你是英语词表校对助手。用户给你若干「序号 单词 释义」，这些来自手写笔记的识别结果。
任务：判断每个单词与释义是否匹配；不匹配时，根据释义反推最可能的正确单词。

规则：
- 正确单词必须与给出单词拼写相近（编辑距离不超过 2），且是高中/四六级常用词
- 无法确定时不要猜，fix 留空
- 释义本身也可能读错；释义与单词都不合理时，fix 留空
- 只输出有问题的条目，正常的不要输出

输出 JSON（不要代码块、不要解释）：
{"items":[{"seq":12,"word":"bank","fix":"bark","reason":"释义树皮对应bark"}]}
"""

_BATCH = 40
_WORD_RE = re.compile(r"^[a-z][a-z'-]*$")


def _distance(a: str, b: str) -> int:
    """编辑距离，只用于小词长，直接 DP。"""
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _stem(word: str) -> str:
    """粗略词干：去掉常见词尾，用于识别同一个词的不同词形。"""
    for suffix in ("ly", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _same_lemma(a: str, b: str) -> bool:
    """relentlessly / relentless 这类只是词形变化，不是形近误读。"""
    def forms(word: str) -> set[str]:
        out = {word}
        for _ in range(2):
            add = {_stem(w) for w in list(out)}
            out |= add
        return out

    return bool(forms(a) & forms(b))


def _chunks(rows: list[Row], size: int) -> list[list[Row]]:
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _ask(rows: list[Row], provider: str, key: str) -> list[dict]:
    lines = "\n".join(f"{r.seq}\t{r.word}\t{r.meaning}" for r in rows)
    reply = ocr.text_completion(provider, key, SYSTEM, lines)
    data = ocr.parse_json(reply)
    items = data.get("items") or []
    return [it for it in items if isinstance(it, dict)]


def run(batch_root: Path, provider: str, only: str = "all") -> dict:
    """校正 wordlist.tsv，返回统计。only=ok 时只查状态为 ok 的行。"""
    root = Path(batch_root).expanduser().resolve()
    path = root / "wordlist.tsv"
    rows = wordlist.read(path)
    key = config.api_key(provider)
    if not key:
        raise RuntimeError(f"没有配置 {config.KEY_ENV[provider]}，无法做释义反查")

    target = [r for r in rows if r.status != DUP and r.word and r.meaning]
    if only == "ok":
        target = [r for r in target if r.status == OK]

    by_seq = {r.seq: r for r in rows}
    fixed = 0
    for chunk in _chunks(target, _BATCH):
        for item in _ask(chunk, provider, key):
            try:
                row = by_seq.get(int(item.get("seq")))
            except (TypeError, ValueError):
                continue
            if row is None:
                continue
            fix = (item.get("fix") or "").strip().lower()
            reason = (item.get("reason") or "").strip()
            if not fix or not _WORD_RE.match(fix):
                # 没有可信候选：不改词，也不写噪音备注
                continue
            gap = _distance(fix, row.word)
            if gap > 2:
                # 差异太大，不像形近误读：静默跳过
                continue
            if _same_lemma(fix, row.word):
                # 同一个词的不同词形，不算误读
                continue
            if gap == 2:
                # 差两个字母不自动改，交人工确认（如 comb / amb）
                if row.status == OK:
                    row.status = REVIEW
                    row.note = _join(row.note, f"释义疑对应 {fix}，请确认")
                continue
            row.note = _join(row.note, f"按释义由 {row.word} 纠正为 {fix}" + (f"（{reason}）" if reason else ""))
            row.word = fix
            fixed += 1

    wordlist.write(path, rows)
    return {"total": len(rows), "checked": len(target), "fixed": fixed}


def _join(note: str, extra: str) -> str:
    return "；".join(p for p in [note.strip(), extra.strip()] if p)
