# -*- coding: utf-8 -*-
"""批次目录结构：input / ocr / wordlist.tsv / report.md / out。"""
from __future__ import annotations

import re
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_DIGITS = re.compile(r"(\d+)")


def page_no(path: Path) -> int:
    """从文件名里取页码，取不到时排到最后。"""
    m = _DIGITS.search(path.stem)
    return int(m.group(1)) if m else 9999


class Batch:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.name = self.root.name
        self.input_dir = self.root / "input"
        self.ocr_dir = self.root / "ocr"
        self.out_dir = self.root / "out"
        self.cache_dir = self.root / ".cache"
        self.wordlist_path = self.root / "wordlist.tsv"
        self.report_path = self.root / "report.md"

    def ensure(self) -> None:
        for d in (self.input_dir, self.ocr_dir, self.out_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)

    def images(self) -> list[Path]:
        if not self.input_dir.is_dir():
            return []
        files = [p for p in self.input_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
        return sorted(files, key=lambda p: (page_no(p), p.name))

    def ocr_files(self) -> list[Path]:
        if not self.ocr_dir.is_dir():
            return []
        return sorted(self.ocr_dir.glob("*.json"), key=lambda p: (page_no(p), p.name))

    def describe(self) -> str:
        return f"批次 {self.name}（{self.root}）"
