# -*- coding: utf-8 -*-
"""wordlist.tsv 读写。列定义见 docs/SOP.md 第 4 节。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = ["seq", "word", "meaning", "note", "status", "source"]

OK = "ok"
REVIEW = "review"
DUP = "dup"
SKIP = "skip"

AUDIO_STATUSES = {OK}


@dataclass
class Row:
    seq: int
    word: str
    meaning: str
    note: str = ""
    status: str = OK
    source: str = ""

    def to_line(self) -> str:
        cells = [str(self.seq), self.word, self.meaning, self.note, self.status, self.source]
        return "\t".join(c.replace("\t", " ").replace("\n", " ") for c in cells)

    @property
    def in_audio(self) -> bool:
        return self.status in AUDIO_STATUSES and bool(self.word) and bool(self.meaning)


def write(path: Path, rows: list[Row]) -> None:
    path = Path(path)
    lines = ["\t".join(COLUMNS)] + [r.to_line() for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read(path: Path) -> list[Row]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到词表：{path}")
    rows: list[Row] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        cells = line.split("\t")
        if i == 0 and cells and cells[0].strip().lower() == "seq":
            continue
        cells += [""] * (len(COLUMNS) - len(cells))
        try:
            seq = int(cells[0])
        except ValueError:
            seq = len(rows) + 1
        rows.append(
            Row(
                seq=seq,
                word=cells[1].strip(),
                meaning=cells[2].strip(),
                note=cells[3].strip(),
                status=(cells[4].strip() or OK),
                source=cells[5].strip(),
            )
        )
    return rows
