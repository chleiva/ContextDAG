"""One `complete()` for every LLM call in F0.5, with two Bedrock backends:

- Anthropic model ids  -> anthropic.AnthropicBedrock streaming (identical to F0's llm.py)
- everything else      -> boto3 bedrock-runtime `converse` (DeepSeek, Kimi, Llama, MiniMax).
  Reasoning models return `reasoningContent` blocks first; only `text` blocks form the answer,
  but reasoning tokens are billed as output and are recorded as such.

Every call checks the F0.5 ledger before and records actual usage after.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import boto3
from anthropic import AnthropicBedrock, APIConnectionError, APIStatusError, RateLimitError
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

from f05_cost import ledger

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


@dataclass
class LLMResult:
    model: str
    model_reported: str
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    stop_reason: Optional[str]
    system: Optional[str]
    prompt: str
    temperature: float
    max_tokens: int
    backend: str = ""
    reasoning_chars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


_anthropic: Optional[AnthropicBedrock] = None
_converse = None
_lock = threading.Lock()


def _region() -> str:
    load_env()
    return os.environ.get("AWS_REGION", "us-east-1")


def anthropic_client() -> AnthropicBedrock:
    global _anthropic
    with _lock:
        if _anthropic is None:
            _anthropic = AnthropicBedrock(aws_region=_region(), max_retries=4, timeout=600)
    return _anthropic


def converse_client():
    global _converse
    with _lock:
        if _converse is None:
            _converse = boto3.client("bedrock-runtime", region_name=_region(),
                                     config=Config(read_timeout=600, connect_timeout=30, retries={"max_attempts": 2}))
    return _converse


def is_anthropic(model: str) -> bool:
    return ".anthropic." in model or model.startswith("anthropic.")


RETRYABLE = {"ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException", "InternalServerException",
             "ModelNotReadyException", "ModelTimeoutException", "ServiceQuotaExceededException", "RequestTimeout"}


def complete(model: str, prompt: str, *, system: Optional[str] = None, temperature: float = 0.0,
             max_tokens: int = 2048, retries: int = 6, purpose: str = "other", ref: str = "") -> LLMResult:
    ledger().check_budget()
    if is_anthropic(model):
        return _complete_anthropic(model, prompt, system=system, temperature=temperature, max_tokens=max_tokens,
                                   retries=retries, purpose=purpose, ref=ref)
    return _complete_converse(model, prompt, system=system, temperature=temperature, max_tokens=max_tokens,
                              retries=retries, purpose=purpose, ref=ref)


def _complete_anthropic(model, prompt, *, system, temperature, max_tokens, retries, purpose, ref) -> LLMResult:
    kwargs = dict(model=model, max_tokens=max_tokens, extra_body={"temperature": temperature},
                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with anthropic_client().messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            ledger().record(model, msg.usage.input_tokens, msg.usage.output_tokens, purpose, ref)
            return LLMResult(model=model, model_reported=msg.model, text=text, input_tokens=msg.usage.input_tokens,
                             output_tokens=msg.usage.output_tokens, latency_s=time.time() - t0, stop_reason=msg.stop_reason,
                             system=system, prompt=prompt, temperature=temperature, max_tokens=max_tokens, backend="anthropic")
        except RateLimitError as e:
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


def _complete_converse(model, prompt, *, system, temperature, max_tokens, retries, purpose, ref) -> LLMResult:
    kwargs = dict(modelId=model, messages=[{"role": "user", "content": [{"text": prompt}]}],
                  inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
    if system:
        kwargs["system"] = [{"text": system}]
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            r = converse_client().converse(**kwargs)
            blocks = r["output"]["message"]["content"]
            text = "".join(b["text"] for b in blocks if "text" in b)
            reasoning = sum(len(json.dumps(b["reasoningContent"])) for b in blocks if "reasoningContent" in b)
            u = r["usage"]
            ledger().record(model, u["inputTokens"], u["outputTokens"], purpose, ref)
            return LLMResult(model=model, model_reported=model, text=text, input_tokens=u["inputTokens"],
                             output_tokens=u["outputTokens"], latency_s=time.time() - t0, stop_reason=r.get("stopReason"),
                             system=system, prompt=prompt, temperature=temperature, max_tokens=max_tokens,
                             backend="converse", reasoning_chars=reasoning)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in RETRYABLE or e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) >= 500:
                last_err = e
                time.sleep(min(120, 5 * 2 ** attempt) + random.uniform(0, 3))
            else:
                raise
        except (ReadTimeoutError, EndpointConnectionError) as e:
            last_err = e
            time.sleep(min(60, 2 ** attempt * 3))
    raise RuntimeError(f"converse call failed after {retries + 1} attempts: {last_err}")


def extract_json(text: str):
    """Parse the first JSON object/array in a model response, tolerating code fences and <think> residue."""
    s = text.strip()
    if "</think>" in s:
        s = s.split("</think>", 1)[1].strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
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
