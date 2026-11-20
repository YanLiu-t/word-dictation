# -*- coding: utf-8 -*-
"""图片识别：多服务商可选，结果落盘到 ocr/*.json。"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config, imageprep
from .batch import Batch, page_no

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".bmp": "image/bmp"}

DEFAULT_MODELS = {
    # 智谱免费视觉模型的代号会随版本变化，按顺序尝试直到有一个可用
    "glm": ["glm-4.6v-flash", "glm-4v-flash", "glm-4v-plus"],
    "gemini": ["gemini-2.5-flash", "gemini-2.0-flash"],
    "qwen": ["qwen-vl-plus", "qwen-vl-max"],
}

USER_HINT = "请按要求处理这张图片，只输出 JSON。"

# 智谱等平台对 max_tokens 有上限（2048），超过会直接报错
MAX_TOKENS = 2048

# 部分模型的 max_tokens 上限更低，单独登记
MODEL_MAX_TOKENS = {"glm-4v-flash": 1024, "glm-4v-plus": 1024}


def _max_tokens(model: str) -> int:
    return MODEL_MAX_TOKENS.get(model, MAX_TOKENS)


def _data_url(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络错误：{exc.reason}") from exc


def _call_glm(image: Path, prompt: str, key: str, model: str) -> str:
    data = _post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(image)}},
                        {"type": "text", "text": USER_HINT},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": _max_tokens(model),
        },
        {"Authorization": f"Bearer {key}"},
    )
    return data["choices"][0]["message"]["content"]


def _call_qwen(image: Path, prompt: str, key: str, model: str) -> str:
    data = _post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(image)}},
                        {"type": "text", "text": USER_HINT},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": _max_tokens(model),
        },
        {"Authorization": f"Bearer {key}"},
    )
    return data["choices"][0]["message"]["content"]


def _call_gemini(image: Path, prompt: str, key: str, model: str) -> str:
    mime = MIME.get(image.suffix.lower(), "image/jpeg")
    data = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {
            "system_instruction": {"parts": [{"text": prompt}]},
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": _b64(image)}},
                        {"text": USER_HINT},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": _max_tokens(model)},
        },
        {},
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


CALLERS = {"glm": _call_glm, "gemini": _call_gemini, "qwen": _call_qwen}

# 验证 Key 用的纯文本模型，不消耗图像额度；按顺序尝试
# glm-4.7/4.5-flash 是推理型，接口常返回空 content，放在后面兜底
TEXT_MODEL = {
    "glm": ["glm-4-flash", "glm-4.5-flash", "glm-4.7-flash"],
    "gemini": ["gemini-2.5-flash", "gemini-2.0-flash"],
    "qwen": ["qwen-turbo", "qwen-plus"],
}


def _text_call(provider: str, key: str, model: str) -> str:
    if provider in ("glm", "qwen"):
        url = ("https://open.bigmodel.cn/api/paas/v4/chat/completions"
               if provider == "glm"
               else "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        data = _post(
            url,
            {"model": model,
             "messages": [{"role": "user", "content": "回复 ok"}],
             "max_tokens": 8},
            {"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        return data["choices"][0]["message"]["content"]

    data = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {"contents": [{"parts": [{"text": "回复 ok"}]}]},
        {},
        timeout=60,
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


def text_completion(provider: str, key: str, system: str, user: str,
                    model: str | None = None, max_tokens: int = 2048) -> str:
    """纯文本对话，用于释义反查校正，不消耗图像额度。"""
    if provider not in CALLERS:
        raise RuntimeError(f"不支持的识别服务：{provider}")
    models = [model] if model else TEXT_MODEL[provider]
    last_err = ""
    for name in models:
        try:
            if provider in ("glm", "qwen"):
                url = ("https://open.bigmodel.cn/api/paas/v4/chat/completions"
                       if provider == "glm"
                       else "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
                data = _post(
                    url,
                    {"model": name,
                     "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}],
                     "temperature": 0.1,
                     "max_tokens": min(max_tokens, _max_tokens(name))},
                    {"Authorization": f"Bearer {key}"},
                    timeout=120,
                )
                reply = data["choices"][0]["message"]["content"]
                if reply.strip():
                    return reply
                last_err = f"{name} 返回空内容"
                continue

            data = _post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent?key={key}",
                {"system_instruction": {"parts": [{"text": system}]},
                 "contents": [{"parts": [{"text": user}]}],
                 "generationConfig": {"temperature": 0.1,
                                      "maxOutputTokens": min(max_tokens, _max_tokens(name))}},
                {},
                timeout=120,
            )
            reply = data["candidates"][0]["content"]["parts"][0]["text"]
            if reply.strip():
                return reply
            last_err = f"{name} 返回空内容"
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(last_err)


def test_provider(provider: str, key: str) -> str:
    """用一次极小的文本请求验证 Key 是否可用，返回模型回复。"""
    if provider not in CALLERS:
        raise RuntimeError(f"不支持的识别服务：{provider}")
    if not key:
        raise RuntimeError("Key 为空")

    last_err = ""
    for model in TEXT_MODEL[provider]:
        try:
            return _text_call(provider, key, model)
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(last_err)


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned


def _salvage_objects(text: str) -> list[dict]:
    """输出被截断时，抢救出所有完整的词条对象。"""
    found: list[dict] = []
    stack: list[int] = []
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            try:
                obj = json.loads(text[start:i + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "word" in obj:
                found.append(obj)
    return found


def parse_json(text: str) -> dict:
    """从模型回复里取出 JSON，容忍代码块包裹、前后废话与输出截断。"""
    cleaned = _strip_fence(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0:
        raise RuntimeError(f"模型未返回 JSON：{text[:300]}")

    if end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass

    items = _salvage_objects(cleaned[start:])
    if items:
        print(f"    ⚠ 输出被截断，已抢救 {len(items)} 条，建议检查该页是否漏词")
        return {"item_count": len(items), "items": items, "truncated": True}

    raise RuntimeError(f"模型返回的 JSON 无法解析：{cleaned[start:start + 300]}")


def _slice_tiles(image: Path, count: int, overlap: float, out_dir: Path) -> list[Path]:
    """把一页按水平方向切成 count 条，相邻条重叠 overlap 比例，避免切断词条。"""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(image)
    width, height = img.size
    band = height / count
    pad = int(band * overlap)
    tiles: list[Path] = []
    for i in range(count):
        top = max(0, int(i * band) - pad)
        bottom = min(height, int((i + 1) * band) + pad)
        tile = out_dir / f"{image.stem}_t{i + 1}.png"
        img.crop((0, top, width, bottom)).save(tile)
        tiles.append(tile)
    return tiles


def _dedupe_items(items: list[dict]) -> list[dict]:
    """分块拼接处会重复，按单词去重并重新编号。"""
    seen: set[str] = set()
    merged: list[dict] = []
    for item in items:
        word = (item.get("word") or "").strip().lower()
        if word:
            if word in seen:
                continue
            seen.add(word)
        merged.append(item)
    for index, item in enumerate(merged, 1):
        item["seq"] = index
    return merged


def _recognize(image: Path, prompt: str, provider: str, key: str,
               models: list[str], depth: int = 0) -> list[dict]:
    """对一张图（或一个分块）调用模型；输出被截断时二分该块再识别。"""
    last_err = ""
    for model in models:
        for attempt in range(3):
            try:
                reply = CALLERS[provider](image, prompt, key, model)
                data = parse_json(reply)
                if data.get("truncated") and depth < 2:
                    print(f"      超出长度限制，二分该块…", flush=True)
                    halves = _slice_tiles(image, 2, 0.05, image.parent / "split")
                    items: list[dict] = []
                    for half in halves:
                        items += _recognize(half, prompt, provider, key, models, depth + 1)
                    return _dedupe_items(items)
                return data.get("items") or []
            except Exception as exc:
                last_err = str(exc)
                # 模型代号不存在时直接换下一个，不必重试
                if "model" in last_err.lower() and ("not" in last_err.lower() or "exist" in last_err.lower()):
                    break
                time.sleep(2 + attempt * 3)
        else:
            continue
        break
    raise RuntimeError(f"{image.name} 识别失败（已尝试 {', '.join(models)}）：{last_err}")


def _cross_check(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """两遍识别比对：两边都有的词视为一致。

    第二遍用的是较弱模型，它漏读第一遍已识别的词很常见，属于弱信号，
    不拦截；只有「第二遍多看到的词」才标记 secondary_only，交人工核对。
    """
    by_word: dict[str, dict] = {}
    for item in secondary:
        word = (item.get("word") or "").strip().lower()
        if word:
            by_word.setdefault(word, item)

    seen: set[str] = set()
    for item in primary:
        word = (item.get("word") or "").strip().lower()
        if not word:
            item["cross_check"] = "primary_only"
            continue
        seen.add(word)
        item["cross_check"] = "agree" if word in by_word else "primary_only"

    for word, item in by_word.items():
        if word in seen:
            continue
        note = (item.get("note") or "").strip()
        item["note"] = "；".join(filter(None, [note, "仅第二遍识别到"]))
        item["cross_check"] = "secondary_only"
        primary.append(item)

    return primary


def extract(batch: Batch, provider: str, prompt: str, cfg: dict,
            only_missing: bool = True, model: str | None = None,
            cross: bool | None = None) -> list[Path]:
    if provider not in CALLERS:
        raise RuntimeError(f"不支持的识别服务：{provider}（可选 {' / '.join(CALLERS)}）")
    key = config.api_key(provider)
    if not key:
        raise RuntimeError(
            f"没有配置 {config.KEY_ENV[provider]}，请复制 .env.example 为 .env 并填入，"
            "或改用 --provider manual 手动放 ocr/*.json"
        )

    images = batch.images()
    if not images:
        raise RuntimeError(f"{batch.input_dir} 里没有图片")

    ocr_cfg = cfg.get("ocr", {})
    override = model or ocr_cfg.get(f"{provider}_model")
    models = [override] if override else list(DEFAULT_MODELS[provider])
    tiles = max(1, int(ocr_cfg.get("tiles", 2)))
    overlap = float(ocr_cfg.get("tile_overlap", 0.08))
    if cross is None:
        cross = bool(ocr_cfg.get("cross_check", True))
    # 第二遍换一个模型，才是独立的第二意见
    if override:
        secondary = next((m for m in DEFAULT_MODELS[provider] if m != override), None)
    else:
        secondary = DEFAULT_MODELS[provider][1] if len(DEFAULT_MODELS[provider]) > 1 else None

    batch.ocr_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    print("  模型：" + " → ".join(models)
          + (f"　复核：{secondary}" if cross and secondary else ""), flush=True)

    for image in images:
        page = page_no(image)
        target = batch.ocr_dir / f"p{page:02d}.json"
        if only_missing and target.is_file():
            print(f"  跳过 p{page:02d}（已存在）")
            saved.append(target)
            continue

        print(f"  识别 {image.name} → {target.name}" + (f"（分 {tiles} 块）" if tiles > 1 else ""), flush=True)
        source = image
        if ocr_cfg.get("preprocess", True):
            source = imageprep.prepare(image, batch.cache_dir / "prepared")
        if tiles > 1:
            parts = _slice_tiles(source, tiles, overlap, batch.cache_dir / "tiles")
            collected: list[dict] = []
            for index, tile in enumerate(parts, 1):
                hint = prompt + (
                    f"\n\n补充要求：这张图是同一页的第 {index}/{tiles} 部分（从上到下切分）。"
                    "只转录本图中完整出现的词条，按从上到下顺序排列，seq 从 1 开始编号。"
                    "被切断的半个词条不要输出。"
                )
                items = _recognize(tile, hint, provider, key, models)
                print(f"    第 {index}/{tiles} 块：{len(items)} 条", flush=True)
                collected += items
            items = _dedupe_items(collected)
        else:
            items = _recognize(source, prompt, provider, key, models)

        if cross and secondary:
            print(f"    第二遍复核（{secondary}）…", flush=True)
            try:
                second = _recognize(source, prompt, provider, key, [secondary])
                items = _dedupe_items(_cross_check(items, second))
                extra = sum(1 for it in items if it.get("cross_check") == "secondary_only")
                print(f"    两遍比对：{len(items)} 条，其中 {extra} 条仅第二遍识别到（待核对）", flush=True)
            except Exception as exc:
                print(f"    复核失败，已跳过：{exc}", flush=True)

        data = {"page": page, "tiles": tiles, "item_count": len(items), "items": items}
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(target)

    return saved
