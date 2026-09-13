"""One thin Bedrock client wrapper so every LLM call in F0 is logged identically."""
from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import yaml
from anthropic import AnthropicBedrock, APIStatusError, APIConnectionError, RateLimitError

from cost import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Load KEY=VALUE lines from the repo-root .env without overriding real env vars."""
    for cand in (ROOT.parent / ".env", ROOT / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def load_manifest() -> dict:
    return yaml.safe_load((ROOT / "manifest.yaml").read_text())


@dataclass
class LLMResult:
    model: str            # requested id
    model_reported: str   # id the API reported back
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    stop_reason: Optional[str]
    system: Optional[str]
    prompt: str
    temperature: float
    max_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


_client: Optional[AnthropicBedrock] = None


def client() -> AnthropicBedrock:
    global _client
    if _client is None:
        load_env()
        region = os.environ.get("AWS_REGION", "us-east-1")
        _client = AnthropicBedrock(aws_region=region, max_retries=4, timeout=600)
    return _client


def complete(model: str, prompt: str, *, system: Optional[str] = None, temperature: float = 0.0,
             max_tokens: int = 2048, retries: int = 6, purpose: str = "other", ref: str = "") -> LLMResult:
    """Single-turn call. Streams so long generations don't hit HTTP timeouts.

    Refuses to start if the spend ledger has hit the hard limit; records actual usage after.
    """
    ledger().check_budget()
    # SDK 1.x dropped `temperature` from the typed params (the newest models reject it);
    # the Claude 4.6 / Haiku 4.5 models used here still accept it, so pass it in the body.
    kwargs = dict(model=model, max_tokens=max_tokens, extra_body={"temperature": temperature},
                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with client().messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            ledger().record(model, msg.usage.input_tokens, msg.usage.output_tokens, purpose, ref)
            return LLMResult(
                model=model, model_reported=msg.model, text=text,
                input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
                latency_s=time.time() - t0, stop_reason=msg.stop_reason, system=system,
                prompt=prompt, temperature=temperature, max_tokens=max_tokens,
            )
        except RateLimitError as e:
            # Bedrock's Opus quota on this account is low; back off patiently rather than fail.
            last_err = e
            time.sleep(min(120, 10 * 2 ** attempt) + random.uniform(0, 5))
        except APIConnectionError as e:
            last_err = e
            time.sleep(min(60, 2 ** attempt * 3))
        except APIStatusError as e:
            if e.status_code >= 500:
                last_err = e
                time.sleep(min(60, 2 ** attempt * 3))
            else:
                raise
    raise RuntimeError(f"LLM call failed after {retries + 1} attempts: {last_err}")


def extract_json(text: str):
    """Parse the first JSON object/array in a model response, tolerating code fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # fall back to the outermost bracket pair
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = s.find(open_c), s.rfind(close_c)
        if i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model response")


_jsonl_lock = threading.Lock()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _jsonl_lock, path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
