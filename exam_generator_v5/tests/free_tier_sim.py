"""Simulates Google's Gemini free tier: N requests / minute / model, answering with the real SDK ClientError(429)."""
from __future__ import annotations

import threading

from google.genai import errors

import mock_gemini


def quota_error(model: str, limit: int = 5, per_day: bool = False, retry: float = 6.2) -> errors.ClientError:
    quota_id = ("GenerateRequestsPerDayPerProjectPerModel-FreeTier" if per_day
                else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
    body = {"error": {
        "code": 429,
        "message": f"You exceeded your current quota, please check your plan and billing details. "
                   f"* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                   f"limit: {limit}, model: {model}\nPlease retry in {retry}s.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.Help", "links": [{"description": "Learn more", "url": "https://ai.google.dev/gemini-api/docs/rate-limits"}]},
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                "quotaId": quota_id, "quotaDimensions": {"model": model, "location": "global"}, "quotaValue": str(limit)}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{int(retry)}s"},
        ],
    }}
    return errors.ClientError(429, body)


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.lock = threading.Lock()

    def monotonic(self):
        with self.lock:
            return self.t

    def sleep(self, s):
        with self.lock:
            self.t += max(0.01, s)


class FreeTierClient(mock_gemini.FakeClient):
    """Enforces `rpm` per model with a sliding 60 s window; optional daily cap per model."""

    def __init__(self, clock: FakeClock, rpm: int = 5, daily: dict[str, int] | None = None):
        super().__init__()
        self.clock, self.rpm, self.daily = clock, rpm, daily or {}
        self.hits: dict[str, list[float]] = {}
        self.used: dict[str, int] = {}
        self.rejected = 0
        self.accepted = 0
        inner = self.models.generate_content

        def generate_content(model, contents, config):
            now = clock.monotonic()
            with clock.lock:
                if model in self.daily and self.used.get(model, 0) >= self.daily[model]:
                    self.rejected += 1
                    raise quota_error(model, self.daily[model], per_day=True)
                recent = [t for t in self.hits.get(model, []) if now - t < 60]
                if len(recent) >= self.rpm:
                    self.rejected += 1
                    raise quota_error(model, self.rpm, retry=60 - (now - recent[0]))
                self.hits[model] = recent + [now]
                self.used[model] = self.used.get(model, 0) + 1
                self.accepted += 1
            return inner(model, contents, config)

        self.models.generate_content = generate_content
