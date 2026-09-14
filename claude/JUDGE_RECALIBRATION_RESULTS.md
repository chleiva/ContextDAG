# Judge Recalibration Extension — Results

Run date: 2026-09-14  
Manifest: `f05-candidate-realism/manifest.yaml` (`judge_recalibration` section) at commit 880213e  
Instances: 160 (reused from F0.5 `results/raw/calibration_sample.json`, no resampling); reference verdicts: Claude Opus 4.6, reused from F0.5 (zero new Opus calls)  
New candidates scored: gpt-oss-120b (Bedrock) (`openai.gpt-oss-120b-1:0`, route openai.gpt-oss-120b-1:0@us-east-1, temperature 0.0); GPT-5 Mini (OpenAI API) (`gpt-5-mini`, route gpt-5-mini@api.openai.com, temperature default/1, reasoning model); GPT-5 Nano (OpenAI API) (`gpt-5-nano`, route gpt-5-nano@api.openai.com, temperature default/1, reasoning model); GPT-5.4 Mini (OpenAI API) (`gpt-5.4-mini`, route gpt-5.4-mini@api.openai.com, temperature 0.0); GPT-5.4 Nano (OpenAI API) (`gpt-5.4-nano`, route gpt-5.4-nano@api.openai.com, temperature 0.0)  
Bar applied: `judge_adoption_bar_v2` (frozen in the manifest before any new scoring): item κ ≥ 0.6, method ranking preserved (tie band 0.03), and |candidate contrast − Opus contrast| ≤ 0.02 on every one of dag−full, dag−tree, dag−sliding, dag−semantic. Cheapest passer wins.

**Decision: no candidate passed bar v2.**

## Reference contrasts (Opus 4.6 on the 160-instance sample)

| dag_minus_full | dag_minus_tree | dag_minus_sliding | dag_minus_semantic |
|---|---|---|---|
| -0.0845 | 0.0423 | 0.1528 | -0.0897 |

The handoff quoted dag−full = −0.084 from an earlier rounding of the same data; the frozen value is the one computed here.

## Per-candidate results

| candidate | n | item_kappa | ranking_preserved | err_dag_minus_full | err_dag_minus_tree | err_dag_minus_sliding | err_dag_minus_semantic | max_abs_contrast_err | mean |Δ| (old bar, info) | $/call | PASS_v2 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Llama 4 Maverick | 160 | 0.7860 | True | -0.0075 | 0.0105 | 0.0273 | -0.0101 | 0.0273 | 0.0752 | 0.0007 | False |
| GPT-5.4 Nano (OpenAI API) | 160 | 0.6393 | True | -0.0541 | 0.0072 | 0.0229 | -0.0671 | 0.0671 | 0.1256 | 0.0007 | False |
| gpt-oss-120b (Bedrock) | 160 | 0.7074 | True | -0.0121 | 0.0084 | 0.0185 | 0.0426 | 0.0426 | 0.0978 | 0.0007 | False |
| GPT-5 Nano (OpenAI API) | 159 | 0.6952 | True | -0.0071 | 0.0133 | 0.0347 | 0.0788 | 0.0788 | 0.1044 | 0.0008 | False |
| Mistral Large 3 | 160 | 0.6999 | True | -0.0342 | -0.0134 | -0.0046 | 0.0256 | 0.0342 | 0.1132 | 0.0014 | False |
| DeepSeek V3.2 | 160 | 0.7724 | True | -0.0043 | 0.0373 | 0.0243 | 0.0036 | 0.0373 | 0.0835 | 0.0017 | False |
| Kimi K2.5 | 160 | 0.7788 | True | -0.0301 | 0.0332 | 0.0512 | -0.0040 | 0.0512 | 0.0786 | 0.0021 | False |
| GPT-5.4 Mini (OpenAI API) | 160 | 0.6328 | True | 0.0361 | 0.0327 | 0.0327 | 0.0725 | 0.0725 | 0.1386 | 0.0023 | False |
| GPT-5 Mini (OpenAI API) | 160 | 0.7578 | True | -0.0301 | -0.0256 | 0.0138 | 0.0585 | 0.0585 | 0.0875 | 0.0023 | False |

Errors are candidate contrast minus Opus contrast (signed); a candidate fails if any |error| > 0.02. Sorted by $/call. Item agreement, Spearman ρ of the method ranking, fallback-prompt uses and routes are in `f05-candidate-realism/results/tables/recalibration_summary.csv`.

### Sampling noise of the contrast errors (information, not part of the bar)

Each contrast error was bootstrapped over the 160 instances (2,000 resamples). The table gives the standard error of each error and how many of the four errors have a 95% CI excluding zero. With ~32 instances per method on this sample, an error's standard error is roughly 0.03–0.04, so the 0.02 bound sits below the resolution of the sample: a candidate whose true error is zero would still fail it about half the time on one of four contrasts. This is reported so the next decision is made with the noise floor in view; the bar itself was not changed.

| candidate | se_dag_minus_full | se_dag_minus_tree | se_dag_minus_sliding | se_dag_minus_semantic | mean_err_se | errors whose 95% CI excludes 0 (of 4) |
|---|---|---|---|---|---|---|
| Llama 4 Maverick | 0.040 | 0.030 | 0.037 | 0.032 | 0.035 | 0 |
| GPT-5.4 Nano (OpenAI API) | 0.049 | 0.051 | 0.055 | 0.046 | 0.050 | 0 |
| gpt-oss-120b (Bedrock) | 0.041 | 0.040 | 0.042 | 0.040 | 0.041 | 0 |
| GPT-5 Nano (OpenAI API) | 0.035 | 0.039 | 0.044 | 0.044 | 0.041 | 0 |
| Mistral Large 3 | 0.046 | 0.043 | 0.049 | 0.051 | 0.047 | 0 |
| DeepSeek V3.2 | 0.041 | 0.042 | 0.045 | 0.032 | 0.040 | 0 |
| Kimi K2.5 | 0.035 | 0.037 | 0.047 | 0.034 | 0.038 | 0 |
| GPT-5.4 Mini (OpenAI API) | 0.055 | 0.058 | 0.052 | 0.050 | 0.054 | 0 |
| GPT-5 Mini (OpenAI API) | 0.034 | 0.034 | 0.042 | 0.035 | 0.036 | 0 |

## Method means on the sample, per judge

| method | Opus 4.6 (reference) | DeepSeek V3.2 | Kimi K2.5 | Llama 4 Maverick | Mistral Large 3 | gpt-oss-120b (Bedrock) | GPT-5 Mini (OpenAI API) | GPT-5 Nano (OpenAI API) | GPT-5.4 Mini (OpenAI API) | GPT-5.4 Nano (OpenAI API) |
|---|---|---|---|---|---|---|---|---|---|---|
| semantic_retrieval@1024 | 0.878 | 0.844 | 0.844 | 0.878 | 0.781 | 0.805 | 0.781 | 0.776 | 0.734 | 0.841 |
| full_history | 0.872 | 0.846 | 0.865 | 0.870 | 0.836 | 0.854 | 0.865 | 0.857 | 0.766 | 0.823 |
| oracle_dag | 0.788 | 0.758 | 0.750 | 0.778 | 0.717 | 0.758 | 0.750 | 0.765 | 0.717 | 0.684 |
| oracle_tree | 0.746 | 0.678 | 0.674 | 0.725 | 0.688 | 0.707 | 0.733 | 0.710 | 0.642 | 0.635 |
| sliding_window@1024 | 0.635 | 0.581 | 0.546 | 0.598 | 0.569 | 0.586 | 0.583 | 0.578 | 0.532 | 0.509 |

## Decision

No candidate passed. Closest: **Llama 4 Maverick** with max contrast error 0.0273 (bound 0.02), κ = 0.786. Per the handoff, the bar is not adjusted here; widening the tolerance is a pre-registered-threshold change that needs explicit sign-off, and Opus is not the default fallback.

## Cost

Actual spend for this extension: **$1.09** across 806 calls (1,416,761 input / 661,889 output tokens), against the handoff's under-$1 estimate and the $5 ledger hard limit. Zero new Opus calls.

| model | usd |
|---|---|
| gpt-5-mini | 0.367 |
| gpt-5.4-mini | 0.362 |
| gpt-5-nano | 0.143 |
| openai.gpt-oss-120b-1:0 | 0.112 |
| gpt-5.4-nano | 0.110 |

## Deferred, as instructed

An Opus 4.6 self test–retest floor (~40 instances, ~$3) would show how well Opus agrees with itself on this rubric; candidates are being asked to agree with a single Opus pass. Not run under the no-new-Opus policy; available as future work with explicit sign-off.

## What this unblocks

Benchmark 1.2 and check 3 still need a judge decision: either sign off on a wider contrast tolerance (with the table above as evidence) or add candidates.

