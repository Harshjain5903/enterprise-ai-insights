import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from importlib import resources

from pydantic import ValidationError

from .config import Settings
from .evidence import Packet
from .schema import Report

log = logging.getLogger(__name__)

PROMPT_NAME = "weekly_v1.txt"
RETRYABLE = {429, 500, 502, 503, 504}


def load_prompt(name: str = PROMPT_NAME) -> str:
    return resources.files("insights.prompts").joinpath(name).read_text()


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class Narration:
    report: Report | None
    raw_text: str | None = None
    attempts: int = 0
    calls: int = 0
    model_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    errors: list[str] = field(default_factory=list)


class TransientError(Exception):
    pass


def _status_code(exc) -> int | None:
    return getattr(exc, "code", None) or getattr(exc, "status_code", None)


class GeminiNarrator:
    def __init__(self, settings: Settings, client=None, sleep=time.sleep,
                 max_generations: int = 2, max_retries: int = 3, timeout_s: int = 30):
        self.settings = settings
        self.prompt = load_prompt()
        self.prompt_hash = prompt_hash(self.prompt)
        self.max_generations = max_generations
        self.max_retries = max_retries
        self._sleep = sleep
        if client is None:
            from google import genai
            from google.genai import types
            client = genai.Client(
                vertexai=True, project=settings.project, location=settings.location,
                http_options=types.HttpOptions(timeout=timeout_s * 1000),
            )
        self.client = client

    def _config(self):
        from google.genai import types
        return types.GenerateContentConfig(
            system_instruction=self.prompt,
            temperature=self.settings.temperature,
            response_mime_type="application/json",
            response_schema=Report,
            max_output_tokens=2048,
            # 2.5 flash thinks by default; the token budget is better spent on output here
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

    def _call(self, contents: str, out: Narration):
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            out.calls += 1
            try:
                return self.client.models.generate_content(
                    model=self.settings.model, contents=contents, config=self._config())
            except Exception as e:  # noqa: BLE001 - sdk raises a few different types
                code = _status_code(e)
                transient = code in RETRYABLE or isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower()
                if not transient or attempt == self.max_retries:
                    raise
                wait = delay + random.uniform(0, delay / 2)
                log.warning("gemini call failed (%s), retrying in %.1fs", code or type(e).__name__, wait)
                self._sleep(wait)
                delay *= 2

    def generate(self, packet: Packet) -> Narration:
        out = Narration(report=None)
        evidence = packet.model_dump_json(exclude={"query_hashes"})
        contents = f"Evidence packet:\n{evidence}"

        for gen in range(1, self.max_generations + 1):
            out.attempts = gen
            resp = self._call(contents, out)
            out.raw_text = resp.text
            out.model_version = getattr(resp, "model_version", None) or self.settings.model
            usage = getattr(resp, "usage_metadata", None)
            if usage is not None:
                out.input_tokens = getattr(usage, "prompt_token_count", None)
                out.output_tokens = getattr(usage, "candidates_token_count", None)
            try:
                out.report = Report.model_validate_json(resp.text or "")
                return out
            except (ValidationError, ValueError) as e:
                msg = str(e).splitlines()[0][:300]
                out.errors.append(f"schema: {msg}")
                log.warning("gemini returned invalid json (attempt %d): %s", gen, msg)
                contents = (
                    f"Evidence packet:\n{evidence}\n\n"
                    f"Your previous answer did not match the schema ({msg}). "
                    "Return only valid JSON for the schema."
                )
        return out
