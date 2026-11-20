# -*- coding: utf-8 -*-
"""拍照预处理：摆正、提对比度、轻锐化、放大，提升视觉模型识别率。"""
from __future__ import annotations

from pathlib import Path

# 长边目标像素：低于这个值模型容易看不清连笔
TARGET_LONG_EDGE = 1800
MAX_SCALE = 3.0


def prepare(image: Path, out_dir: Path, target_long_edge: int = TARGET_LONG_EDGE) -> Path:
    """生成一张更适合识别的图，返回新路径；失败时返回原图。"""
    from PIL import Image, ImageEnhance, ImageOps

    try:
        img = Image.open(image)
        img = ImageOps.exif_transpose(img)  # 手机照片按 EXIF 摆正
        img = img.convert("RGB")

        long_edge = max(img.size)
        if long_edge < target_long_edge:
            scale = min(target_long_edge / long_edge, MAX_SCALE)
            img = img.resize(
                (round(img.width * scale), round(img.height * scale)),
                Image.LANCZOS,
            )

        # 手写稿常见问题是发灰、阴影，autocontrast 比固定亮度更稳
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = ImageEnhance.Sharpness(img).enhance(1.5)

        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{image.stem}.png"
        img.save(out)
        return out
    except Exception:
        # 预处理只是加分项，不能因为它让整批失败
        return image
