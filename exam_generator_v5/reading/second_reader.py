"""The SECOND, independent reading of a photographed question.

Reader A (PASS 1) sees the whole question with its context and may silently "correct" what it reads.
Reader B sees each printed line ALONE, zoomed, with no question context, no instructions to solve, and no knowledge of
A's answer - it can only copy what is printed. Disagreements between A and B are exactly the places where one of them
misread the photo.

Two interchangeable back-ends:
  GeminiLineReader - the same Gemini service (different input and task: literal line transcription);
  ClaudeLineReader - a different model family (errors are less correlated with Gemini's); enabled when the secret
                     SECOND_READER = "claude" and ANTHROPIC_API_KEY are set.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Protocol

from pydantic import BaseModel, Field

LINE_BATCH = 18              # line crops per request

LINE_SYSTEM_PROMPT = r"""
You are a literal transcriber. Each image is ONE printed line cut out of a photographed mathematics exam (Hebrew, right to
left, with mathematics). Copy exactly what is printed - nothing more, nothing less.
- Hebrew: exact spelling as printed (e.g. keep "הפונקצייה" if it is printed with two yods), exact punctuation.
- Mathematics: LaTeX between $...$ (variables, point names, numbers that belong to formulas, equations, intervals).
- A line label at the start (א. / ב. / (1) / 3.) is copied as printed.
- Do not complete, fix, translate or explain anything. If a character cannot be read with certainty, write [?] in its
  place and set unreadable=true. Never guess a digit.
Return one item per image, with the image's index.
""".strip()

LABEL_SYSTEM_PROMPT = r"""
You receive ONE cropped figure (graph, geometric drawing, chart, 3-D drawing) from a photographed mathematics exam.
List every piece of text printed INSIDE the figure, each as printed: point names (A, B, O), axis names (x, y, f(x)),
numbers on axes or sides, angle values, percentages, words. One entry per separate label. Do not interpret the figure.
If a label cannot be read with certainty write [?] for the unreadable characters.
""".strip()


class LineReading(BaseModel):
    index: int
    text: str
    unreadable: bool = False


class LineReadingsAI(BaseModel):
    lines: list[LineReading] = Field(default_factory=list)


class FigureLabelsAI(BaseModel):
    labels: list[str] = Field(default_factory=list)


class LineReader(Protocol):
    name: str

    def read_lines(self, crops: list[bytes]) -> list[LineReading]: ...

    def read_figure_labels(self, crop: bytes) -> list[str]: ...


def _batches(items: list, n: int):
    for i in range(0, len(items), n):
        yield i, items[i:i + n]


def _collect(batch_start: int, got: list[LineReading], n: int) -> list[LineReading]:
    by_idx = {r.index: r for r in got}
    return [by_idx.get(i, LineReading(index=i, text="", unreadable=True)) for i in range(batch_start, batch_start + n)]


class GeminiLineReader:
    """Uses the existing GeminiService (rate limiting, retries, model fallback)."""

    name = "gemini-lines"

    def __init__(self, service: Any):
        self.service = service

    def read_lines(self, crops: list[bytes]) -> list[LineReading]:
        from google.genai import types
        out: list[LineReading] = []
        for start, batch in _batches(crops, LINE_BATCH):
            parts = []
            for k, png in enumerate(batch):
                parts.append(types.Part.from_text(text=f"Image index {start + k}:"))
                parts.append(types.Part.from_bytes(data=png, mime_type="image/png"))
            res = self.service.generate(parts, LineReadingsAI, LINE_SYSTEM_PROMPT, max_output_tokens=16384)
            out += _collect(start, res.lines, len(batch))
        return out

    def read_figure_labels(self, crop: bytes) -> list[str]:
        from google.genai import types
        parts = [types.Part.from_bytes(data=crop, mime_type="image/png")]
        return self.service.generate(parts, FigureLabelsAI, LABEL_SYSTEM_PROMPT, max_output_tokens=4096).labels


def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema -> the strict JSON schema structured outputs expect (every property required, no extras)."""
    schema = model.model_json_schema()

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            node.pop("default", None)
            node.pop("title", None)
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    fix(schema)
    return schema


class ClaudeLineReader:
    """A different model family as reader B (Anthropic SDK, structured outputs)."""

    name = "claude-lines"
    MODEL = "claude-opus-5-5"

    def __init__(self, api_key: str | None = None, model: str | None = None, client: Any = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.model = model or self.MODEL

    def _ask(self, content: list[dict], system: str, schema_model: type[BaseModel]) -> Any:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _strict_schema(schema_model)}},
            messages=[{"role": "user", "content": content}],
            extra_body={"fallbacks": "default"},
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"second reader declined: {getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("second reader output truncated")
        text = next(b.text for b in resp.content if b.type == "text")
        return schema_model.model_validate(json.loads(text))

    @staticmethod
    def _img(png: bytes) -> dict:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.standard_b64encode(png).decode()}}

    def read_lines(self, crops: list[bytes]) -> list[LineReading]:
        out: list[LineReading] = []
        for start, batch in _batches(crops, LINE_BATCH):
            content: list[dict] = []
            for k, png in enumerate(batch):
                content += [{"type": "text", "text": f"Image index {start + k}:"}, self._img(png)]
            content.append({"type": "text", "text": "Transcribe every image."})
            out += _collect(start, self._ask(content, LINE_SYSTEM_PROMPT, LineReadingsAI).lines, len(batch))
        return out

    def read_figure_labels(self, crop: bytes) -> list[str]:
        content = [self._img(crop), {"type": "text", "text": "List the labels."}]
        return self._ask(content, LABEL_SYSTEM_PROMPT, FigureLabelsAI).labels


def make_reader(service: Any, secrets: dict | None = None) -> LineReader:
    """SECOND_READER = "claude" (+ ANTHROPIC_API_KEY) -> Claude; anything else -> Gemini (same service)."""
    secrets = secrets or {}
    if str(secrets.get("SECOND_READER", "")).lower() == "claude" and secrets.get("ANTHROPIC_API_KEY"):
        return ClaudeLineReader(api_key=secrets["ANTHROPIC_API_KEY"], model=secrets.get("SECOND_READER_MODEL"))
    return GeminiLineReader(service)
