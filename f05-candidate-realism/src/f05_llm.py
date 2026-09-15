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

ROOT = Path(os.environ["F05_ROOT"]).resolve() if os.environ.get("F05_ROOT") else Path(__file__).resolve().parents[1]


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
    route: str = ""        # "<model id actually used>@<region>"

    def to_dict(self) -> dict:
        return asdict(self)


_anthropic: dict[str, AnthropicBedrock] = {}
_converse: dict[str, object] = {}
_lock = threading.Lock()


def _region() -> str:
    load_env()
    return os.environ.get("AWS_REGION", "us-east-1")


def _fallback_regions() -> list[str]:
    import yaml
    prov = yaml.safe_load((ROOT / "manifest.yaml").read_text())["provider"]
    regs = [prov.get("region", _region())] + list(prov.get("fallback_regions", []))
    out: list[str] = []
    for r in regs:
        if r not in out:
            out.append(r)
    return out


def anthropic_client(region: Optional[str] = None) -> AnthropicBedrock:
    region = region or _region()
    with _lock:
        if region not in _anthropic:
            _anthropic[region] = AnthropicBedrock(aws_region=region, max_retries=2, timeout=600)
    return _anthropic[region]


def converse_client(region: Optional[str] = None):
    region = region or _region()
    with _lock:
        if region not in _converse:
            _converse[region] = boto3.client("bedrock-runtime", region_name=region,
                                             config=Config(read_timeout=600, connect_timeout=30, retries={"max_attempts": 2}))
    return _converse[region]


def is_anthropic(model: str) -> bool:
    return ".anthropic." in model or model.startswith("anthropic.")


def _alt_profile(model: str) -> Optional[str]:
    """global.<id> <-> us.<id>: same model, different inference-profile quota bucket."""
    if model.startswith("global."):
        return "us." + model[len("global."):]
    if model.startswith("us."):
        return "global." + model[len("us."):]
    return None


def routes(model: str) -> list[tuple[str, str]]:
    """(model_id, region) pairs to try in order: the requested id in the primary region, then the
    requested id and its alternate profile across the fallback regions. Region-bound `us.` profiles
    are only tried in US regions; `global.` works from any region."""
    forced = os.environ.get("F05_FORCE_ROUTE")          # "model_id@region": single route, no fallback (used for audited re-judging)
    if forced and "@" in forced:
        m, r = forced.split("@", 1)
        if m == model or _alt_profile(m) == model:
            return [(m, r)]
    regs = _fallback_regions()
    out = [(model, regs[0])]
    alt = _alt_profile(model)
    for r in regs:
        for m in (model, alt):
            if m and (m, r) not in out:
                out.append((m, r))
    return out


RETRYABLE = {"ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException", "InternalServerException",
             "ModelNotReadyException", "ModelTimeoutException", "ServiceQuotaExceededException", "RequestTimeout"}


def is_openai_api(model: str) -> bool:
    """OpenAI models called directly through api.openai.com (not Bedrock's `openai.` ids)."""
    return model.startswith(("gpt-", "o1", "o3", "o4"))


def complete(model: str, prompt: str, *, system: Optional[str] = None, temperature: Optional[float] = 0.0,
             max_tokens: int = 2048, retries: int = 6, purpose: str = "other", ref: str = "") -> LLMResult:
    ledger().check_budget()
    if is_anthropic(model):
        return _complete_anthropic(model, prompt, system=system, temperature=temperature, max_tokens=max_tokens,
                                   retries=retries, purpose=purpose, ref=ref)
    if is_openai_api(model):
        return _complete_openai(model, prompt, system=system, temperature=temperature, max_tokens=max_tokens,
                                retries=retries, purpose=purpose, ref=ref)
    return _complete_converse(model, prompt, system=system, temperature=temperature, max_tokens=max_tokens,
                              retries=retries, purpose=purpose, ref=ref)


def _complete_openai(model, prompt, *, system, temperature, max_tokens, retries, purpose, ref) -> LLMResult:
    """OpenAI chat completions over plain HTTPS (no SDK dependency). `temperature=None` omits the
    parameter (GPT-5 mini/nano reasoning models accept only the default). Reasoning tokens are part
    of completion_tokens and are billed as output."""
    import urllib.error
    import urllib.request
    load_env()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set (repo-root .env)")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                r = json.load(resp)
            u = r["usage"]
            choice = r["choices"][0]
            text = choice["message"].get("content") or ""
            reasoning_tok = u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            ledger().record(model, u["prompt_tokens"], u["completion_tokens"], purpose, ref)
            return LLMResult(model=model, model_reported=r.get("model", model), text=text, input_tokens=u["prompt_tokens"],
                             output_tokens=u["completion_tokens"], latency_s=time.time() - t0, stop_reason=choice.get("finish_reason"),
                             system=system, prompt=prompt, temperature=(-1.0 if temperature is None else temperature),
                             max_tokens=max_tokens, backend="openai", reasoning_chars=int(reasoning_tok), route=f"{model}@api.openai.com")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:300]
            if e.code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {e.code}: {msg}")
                time.sleep(min(120, 5 * 2 ** attempt) + random.uniform(0, 3))
            else:
                raise RuntimeError(f"OpenAI HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(min(60, 2 ** attempt * 3))
    raise RuntimeError(f"OpenAI call failed after {retries + 1} attempts: {last_err}")


def _complete_anthropic(model, prompt, *, system, temperature, max_tokens, retries, purpose, ref) -> LLMResult:
    """Throttling (429, incl. the per-region daily token quota) rotates through routes() before
    backing off; the id actually used is what gets ledgered and returned."""
    base = dict(max_tokens=max_tokens, extra_body={"temperature": temperature}, messages=[{"role": "user", "content": prompt}])
    if system:
        base["system"] = system
    rts = routes(model)
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        for mid, region in rts:
            t0 = time.time()
            try:
                with anthropic_client(region).messages.stream(model=mid, **base) as stream:
                    msg = stream.get_final_message()
                text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
                ledger().record(mid, msg.usage.input_tokens, msg.usage.output_tokens, purpose, ref)
                return LLMResult(model=mid, model_reported=msg.model, text=text, input_tokens=msg.usage.input_tokens,
                                 output_tokens=msg.usage.output_tokens, latency_s=time.time() - t0, stop_reason=msg.stop_reason,
                                 system=system, prompt=prompt, temperature=temperature, max_tokens=max_tokens,
                                 backend="anthropic", route=f"{mid}@{region}")
            except RateLimitError as e:
                last_err = e                      # try the next route right away
            except APIConnectionError as e:
                last_err = e
            except APIStatusError as e:
                if e.status_code >= 500:
                    last_err = e
                elif e.status_code in (403, 404):
                    continue                      # this profile is not usable here; try the next route
                else:
                    raise
        time.sleep(min(120, 10 * 2 ** attempt) + random.uniform(0, 5))
    raise RuntimeError(f"LLM call failed after {retries + 1} attempts over {len(rts)} routes: {last_err}")


def _complete_converse(model, prompt, *, system, temperature, max_tokens, retries, purpose, ref) -> LLMResult:
    kwargs = dict(modelId=model, messages=[{"role": "user", "content": [{"text": prompt}]}],
                  inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
    if system:
        kwargs["system"] = [{"text": system}]
    last_err: Optional[Exception] = None
    regs = _fallback_regions()
    for attempt in range(retries + 1):
        for region in regs:
            t0 = time.time()
            try:
                r = converse_client(region).converse(**kwargs)
                blocks = r["output"]["message"]["content"]
                text = "".join(b["text"] for b in blocks if "text" in b)
                reasoning = sum(len(json.dumps(b["reasoningContent"])) for b in blocks if "reasoningContent" in b)
                u = r["usage"]
                ledger().record(model, u["inputTokens"], u["outputTokens"], purpose, ref)
                return LLMResult(model=model, model_reported=model, text=text, input_tokens=u["inputTokens"],
                                 output_tokens=u["outputTokens"], latency_s=time.time() - t0, stop_reason=r.get("stopReason"),
                                 system=system, prompt=prompt, temperature=temperature, max_tokens=max_tokens,
                                 backend="converse", reasoning_chars=reasoning, route=f"{model}@{region}")
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in RETRYABLE or e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) >= 500:
                    last_err = e                  # next region
                elif code in ("ValidationException", "ResourceNotFoundException"):
                    last_err = e; continue        # model not served in this region; next region
                else:
                    raise
            except (ReadTimeoutError, EndpointConnectionError) as e:
                last_err = e
        time.sleep(min(120, 5 * 2 ** attempt) + random.uniform(0, 3))
    raise RuntimeError(f"converse call failed after {retries + 1} attempts over {len(regs)} regions: {last_err}")


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
