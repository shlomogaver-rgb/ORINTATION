"""Page image -> structured page JSON, using Claude vision with structured outputs."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import anthropic

from .prompts import SYSTEM_PROMPT, USER_PROMPT
from .schema import PAGE_SCHEMA
from .source import Page

MODEL = "claude-opus-5-5"


def _png_b64(page: Page) -> str:
    buf = io.BytesIO()
    page.image.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode()


def transcribe_page(client: anthropic.Anthropic, page: Page, page_count: int,
                    cache_dir: Path | None = None, model: str = MODEL, effort: str = "high") -> dict:
    data = _png_b64(page)
    cache_file = None
    if cache_dir:
        key = hashlib.sha256((model + effort + SYSTEM_PROMPT + data).encode()).hexdigest()[:24]
        cache_file = Path(cache_dir) / f"page-{page.index + 1:03d}-{key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": PAGE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                {"type": "text", "text": USER_PROMPT.format(page_no=page.index + 1, page_count=page_count)},
            ],
        }],
        extra_body={"fallbacks": "default"},
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError(f"page {page.index + 1}: request declined ({message.stop_details})")
    if message.stop_reason == "max_tokens":
        raise RuntimeError(f"page {page.index + 1}: output truncated (max_tokens)")
    text = next(b.text for b in message.content if b.type == "text")
    result = json.loads(text)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
