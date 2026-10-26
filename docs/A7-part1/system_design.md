# A7 — System Design

> Scope: Part 2 cost and capacity estimates, followed by the Part 3 routing strategy. The estimates use the 15 models and completed Part 1 benchmark.

## Estimation Basis

- Each DAU sends **5 requests per day**. Requests are split evenly across the five task types. The 15 models are alternatives; each row assumes one model serves the traffic.
- Token averages and latency come from each model's 25 Part 1 responses. Mean latency is used for capacity; median latency is shown as a typical-request reference.
- The benchmark timer covers `model.generate()` (prompt prefill and decoding). It excludes tokenization, model loading, warm-up, network, and queue time, so it is not full request latency.
- AWS requests are spread evenly over 24 hours, with a 70% target utilization. Replicas = `ceil(DAU × 5 × mean latency ÷ (86,400 × 0.70))`, with at least one replica. This simple estimate treats a replica as handling one request at a time; it is not a production load test.
- AWS self-hosting uses one `g4dn.4xlarge` T4 at $1.204/hour. Benchmark latency is treated as a proxy for one AWS replica; actual capacity may differ.
- HF API costs use public input and output prices per million tokens. The workload uses local benchmark token counts, though another model or tokenizer may use different counts. HF provider machines are managed by the provider and are not publicly disclosed.

## Part 1 Evaluation Data

The benchmark contains **375 responses** (15 models × 25 prompts), with saved scores for all 375. Scores are an AI-assisted first pass with targeted review, not an independent ground-truth evaluation. Latency and tokens/sec describe speed; they do not measure answer quality. `token_limit_hits` flags possible truncation.

## 2.1–2.2 Token Usage Per Request

The table shows per-model means from the 25 responses. Daily request count is `DAU × 5`; daily input and output tokens equal requests multiplied by the corresponding per-request mean.

| Model | Model size | Input tokens/request | Output tokens/request | Total tokens/request | Mean latency (s) | Median latency (s) | Output tokens/s |
|---|---|---:|---:|---:|---:|---:|---:|
| `Qwen/Qwen3-0.6B` | Ultra-Light (<1B) | 276.44 | 68.16 | 344.60 | 3.052 | 2.284 | 23.09 |
| `HuggingFaceTB/SmolLM2-360M-Instruct` | Ultra-Light (<1B) | 310.24 | 107.08 | 417.32 | 4.124 | 2.341 | 25.86 |
| `Qwen/Qwen3-1.7B` | Small (1-3B) | 276.44 | 97.28 | 373.72 | 4.242 | 2.897 | 22.58 |
| `HuggingFaceTB/SmolLM2-1.7B-Instruct` | Small (1-3B) | 310.24 | 70.72 | 380.96 | 1.749 | 1.468 | 39.51 |
| `microsoft/Phi-4-mini-instruct` | Medium (3-5B) | 263.28 | 88.00 | 351.28 | 4.307 | 2.980 | 20.68 |
| `Qwen/Qwen3-4B` | Medium (3-5B) | 276.44 | 78.36 | 354.80 | 4.671 | 3.944 | 16.51 |
| `Qwen/Qwen2.5-7B-Instruct` | Large (6-9B) | 293.44 | 69.68 | 363.12 | 4.207 | 2.805 | 15.73 |
| `mistralai/Mistral-7B-Instruct-v0.3` | Large (6-9B) | 303.04 | 98.04 | 401.08 | 6.122 | 5.617 | 15.17 |
| `Qwen/Qwen2.5-14B-Instruct` | X-Large (10-15B) | 293.44 | 73.24 | 366.68 | 8.376 | 6.399 | 8.43 |
| `microsoft/phi-4` | X-Large (10-15B) | 269.56 | 97.72 | 367.28 | 10.440 | 8.257 | 9.26 |
| `mistralai/Mistral-Nemo-Instruct-2407` | X-Large (10-15B) | 278.48 | 95.80 | 374.28 | 8.867 | 5.669 | 10.33 |
| `google/gemma-3-270m-it` | Ultra-Light (<1B) | 277.16 | 115.80 | 392.96 | 3.933 | 1.433 | 29.59 |
| `meta-llama/Llama-3.2-1B-Instruct` | Small (1-3B) | 297.56 | 172.48 | 470.04 | 4.037 | 1.783 | 42.04 |
| `meta-llama/Llama-3.2-3B-Instruct` | Medium (3-5B) | 297.56 | 134.16 | 431.72 | 5.859 | 3.444 | 22.55 |
| `meta-llama/Llama-3.1-8B-Instruct` | Large (6-9B) | 297.56 | 77.16 | 374.72 | 5.416 | 3.915 | 13.32 |

## 2.3 Self-Hosting and 2.4 HF API Cost

The notebook generates both required 90-row tables (six DAU tiers × 15 models), including daily token load, AWS replica count and cost, HF input/output rates and costs, provider machine-count disclosure, and total cost. For HF API cost, input and output are billed separately:

`daily API cost = daily input tokens × input price / 1,000,000 + daily output tokens × output price / 1,000,000`

HF provider machine count is shown as **Provider-managed; not disclosed**. The API table's total cost is the token usage estimate; it is not an infrastructure replica estimate.

Matching is model-level and family-first: prefer the same model or family, then a similar-scale general instruction model with public token rates. The 15 local models now map to 7 distinct HF API models. A shared API alternative is used only when the local models have a related family or a similar size and role. Rows label larger or different-family alternatives so the approximate comparisons are clear.

| Local LLM | HF API model | Provider | Input ($/1M) | Output ($/1M) | Matching rationale |
|---|---|---|---:|---:|---|
| `Qwen/Qwen3-0.6B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same Qwen3 family; **Larger-model alternative** (4B) |
| `HuggingFaceTB/SmolLM2-360M-Instruct` | `ibm-granite/granite-4.2-3b` | DeepInfra | $0.03 | $0.12 | Different family; **Larger-model alternative** (3B) |
| `google/gemma-3-270m-it` | `google/gemma-3-4b-it` | DeepInfra | $0.05 | $0.10 | Same Gemma 3 family; **Larger-model alternative** (4B) |
| `meta-llama/Llama-3.2-1B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Same Llama family; **Larger-model alternative** (8B) |
| `Qwen/Qwen3-1.7B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same Qwen3 family; larger 4B alternative |
| `HuggingFaceTB/SmolLM2-1.7B-Instruct` | `ibm-granite/granite-4.2-3b` | DeepInfra | $0.03 | $0.12 | Different family; larger 3B general instruction model |
| `microsoft/Phi-4-mini-instruct` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Similar size and instruction use; different family |
| `Qwen/Qwen3-4B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same family and size; updated instruct variant |
| `Qwen/Qwen2.5-7B-Instruct` | `Qwen/Qwen3.5-9B` | DeepInfra | $0.10 | $0.15 | Related Qwen family; similar scale and newer generation |
| `mistralai/Mistral-7B-Instruct-v0.3` | `Qwen/Qwen3.5-9B` | DeepInfra | $0.10 | $0.15 | Similar scale and instruction use; different family |
| `Qwen/Qwen2.5-14B-Instruct` | `Qwen/Qwen3-14B` | Nscale | $0.07 | $0.20 | Related Qwen family and similar size; newer generation |
| `microsoft/phi-4` | `microsoft/phi-4` | DeepInfra | $0.07 | $0.14 | Exact model match |
| `mistralai/Mistral-Nemo-Instruct-2407` | `Qwen/Qwen3-14B` | Nscale | $0.07 | $0.20 | Similar scale and instruction use; different family |
| `meta-llama/Llama-3.2-3B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Same Llama family; **Larger-model alternative** (8B) |
| `meta-llama/Llama-3.1-8B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Exact model match |

The official [HF Inference Providers model and price list](https://huggingface.co/inference/models) currently lists these models, providers, and input/output token prices; the HF [pricing and billing page](https://huggingface.co/docs/inference-providers/main/pricing) describes pay-as-you-go usage. Model cards: [Qwen3 4B Instruct](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [Granite 4.2 3B](https://huggingface.co/ibm-granite/granite-4.2-3b), [Gemma 3 4B](https://huggingface.co/google/gemma-3-4b-it), [Llama 3.1 8B](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct), [Qwen3.5 9B](https://huggingface.co/Qwen/Qwen3.5-9B), [Qwen3 14B](https://huggingface.co/Qwen/Qwen3-14B), and [Phi-4](https://huggingface.co/microsoft/phi-4). Prices were checked on 2026-10-26; credits, taxes, and discounts are excluded.

No priced, provider-listed option close to SmolLM2's 0.36B–1.7B scale was verified, so Granite 3B is a **Larger-model alternative**. Qwen3 4B, Gemma 4B, and Llama 8B are also larger alternatives for smaller local models. Qwen3.5 9B and Qwen3 14B are newer generations than the local Qwen2.5 models. Model size and family differences may change quality, latency, and tokenization; all API estimates reuse the local model's token counts.

## 2.5 Daily Cost Range Across Model Alternatives

Each range shows the lowest and highest cost among the 15 separate model options at that DAU. It does not add all models together.

| DAU tier | AWS self-host cost/day | HF API usage cost/day |
|---|---:|---:|
| Prototype (1,000) | $28.90–$28.90 | $0.02–$0.23 |
| Early Startup (10,000) | $57.79–$260.06 | $0.24–$2.25 |
| Growing Product (100,000) | $433.44–$2513.95 | $2.40–$22.50 |
| Large Platform (1,000,000) | $4189.92–$24966.14 | $24.05–$225.05 |
| Mass Consumer App (10,000,000) | $41812.51–$249430.27 | $240.46–$2250.50 |
| Global Platform (100,000,000) | $417922.85–$2494100.45 | $2404.60–$22505.00 |

## Part 3 — Multi-Model Routing Strategy

MoveOn is a secondhand marketplace, so requests include listing classification, price estimates, listing text, structured detail extraction, and purchase advice. The router first identifies the task, then chooses the smallest suitable model. It escalates only when a response fails a check or the request needs more detailed reasoning. Price suggestions must be grounded in comparable listings or another trusted data source; a language model can explain the evidence, but it should not invent the market data.

The choices below use Part 1 as an initial guide. For example, `microsoft/Phi-4-mini-instruct` scored 10.0 on classification with 0.35-second median latency, and `Qwen/Qwen3-0.6B` scored 10.0 on text generation with 0.42-second median latency. `Qwen/Qwen2.5-7B-Instruct` scored 8.61 on structured extraction, while the 14B Qwen scored 9.91. For purchase considerations, `Qwen/Qwen3-4B` scored 8.60 at 10.21 seconds; `Mistral-Nemo-Instruct-2407` scored 8.65 but took 25.28 seconds. These are small benchmark samples and the scores are an initial signal, not a production quality guarantee. See the `ALL` and task rows in `docs/A7-part1/output/summary.csv`.

| Scenario and trigger | Routing strategy | Local model | Hugging Face hosted model | Expected benefit |
|---|---|---|---|---|
| **Normal operation:** traffic and queue time stay within the capacity established by a load test. | Route by task. Use a compact model for short, low-risk work; validate structured output before returning it. Send only failed validation or requests that need more detail to the hosted fallback. | Classification: `microsoft/Phi-4-mini-instruct`; short listing text: `Qwen/Qwen3-0.6B`; extraction: `Qwen/Qwen2.5-7B-Instruct`; purchase advice: `Qwen/Qwen3-4B`. Use listing data and deterministic calculations for price suggestions. | Match the task to the same model family when local inference is unavailable or a validated retry is needed; use `Qwen/Qwen2.5-14B-Instruct` for difficult extraction and `Mistral-Nemo-Instruct-2407` for detailed purchase advice when its latency is acceptable. | Keeps the common path on models that were fast in the benchmark, while retaining a higher-capacity fallback for harder requests. |
| **Peak usage:** request rate, GPU utilization, or queue delay crosses a threshold set by production load tests. | Keep classification and short text generation on the local compact models. Spill eligible, latency-tolerant complex requests to a separately provisioned HF API, with bounded concurrency and a request budget. If the endpoint is at its own limit, queue or return a brief fallback rather than retrying repeatedly. | `microsoft/Phi-4-mini-instruct` for classification and `Qwen/Qwen3-0.6B` for short text; `Qwen/Qwen3-4B` for purchase advice when local capacity is available. | `Qwen/Qwen2.5-7B-Instruct` for extraction overflow; `Qwen/Qwen3-4B` for purchase advice overflow. Reserve 14B or Mistral Nemo for cases whose quality need justifies their measured latency. | Uses the hosted API as burst capacity and protects the local queue. This can improve peak response time if the endpoint has spare capacity, but it adds hosted cost and must be tested under concurrent traffic. |
| **High-complexity request:** the user asks for comparisons across several listings, missing-field recovery, or a detailed purchase trade-off. | Start with a task-specific local model and run schema, evidence, and completeness checks. Escalate a failed or incomplete answer once to a larger hosted model. Do not use model confidence alone as the escalation signal; the benchmark did not calibrate confidence. | `Qwen/Qwen2.5-7B-Instruct` for extraction; `Qwen/Qwen3-4B` for purchase considerations. Use a deterministic price-comparison step for numeric recommendations. | `Qwen/Qwen2.5-14B-Instruct` for difficult extraction; `Mistral-Nemo-Instruct-2407` for detailed purchase considerations when a roughly 25-second benchmark median is acceptable. | Gives complex cases access to the strongest task-level benchmark results without making every request pay the latency cost of a large model. |
| **Cost optimization:** hosted inference usage or the monthly budget approaches its target. | Prefer deterministic code for category rules and numeric price calculations, reuse cached listing facts, and keep routine requests on local models when that GPU capacity is already paid for. Escalate to HF only after validation failure or for a quality-critical request. Scale hosted replicas down or to zero only if the service's cold-start delay is acceptable. | Compact local models for classification and short text; `Qwen/Qwen2.5-7B-Instruct` or `Qwen/Qwen3-4B` for routine extraction and purchase advice. | Keep `Qwen/Qwen2.5-14B-Instruct` and `Mistral-Nemo-Instruct-2407` for justified escalations; use a smaller hosted model for routine overflow if its quality checks pass. | Reduces avoidable large-model calls and may reduce endpoint hours when autoscaling or scale-to-zero is available. Part 2 compares token-priced API usage with always-on AWS machines; actual production bills depend on traffic, model choice, and provider pricing. |
| **System overload or local GPU failure:** the local service is unhealthy, its queue exceeds the response-time target, or its measured capacity is exhausted. | Open a circuit breaker for the unhealthy local worker and send a limited amount of traffic to a healthy HF API. Keep only essential tasks enabled, cap retries, and use a queue or clear temporary-unavailable response if both paths are saturated. | If the GPU is healthy but busy, keep only compact classification and short-text work on `microsoft/Phi-4-mini-instruct` and `Qwen/Qwen3-0.6B`; otherwise do not send traffic to the failed worker. | Use a healthy `Qwen/Qwen2.5-7B-Instruct` endpoint for extraction and `Qwen/Qwen3-4B` for purchase advice, subject to health checks and rate limits. Avoid sending every request to the largest model. | Prevents retry storms and contains failures. A hosted fallback can preserve service when local infrastructure fails, but it is not a guarantee if the endpoint is also throttled or unavailable. |

### How the routing trade-offs are evaluated

- **Latency:** task-based routing keeps common classification and short-text requests on the fastest suitable benchmark candidates. Escalation adds another model call, and the larger models were slower on some tasks. The Part 1 measurements are single-request generation latencies, not end-to-end service times; set queue and utilization thresholds only after a concurrent load test and track P50/P95/P99 latency in production.
- **Cost:** avoid sending easy requests to large models and avoid repeated retries. Local models can reduce marginal hosted usage when local GPU capacity is already provisioned, while a hosted API can be less expensive when traffic is low or irregular. The Part 2 table compares one always-on model at a time and does not calculate a blended router bill; record hosted requests, replica hours, and cost per successfully validated response before choosing a policy.
- **Quality:** validate JSON against a schema, verify extracted values against the listing, and keep price calculations tied to comparable-item data. Escalate invalid or incomplete outputs rather than trusting a model's self-reported confidence. Review a sample of routed answers by task and monitor correction, fallback, and user-report rates; the five prompts per task in Part 1 are not enough to establish production reliability.


## Limitations and Interpretation Notes

- Five requests per DAU per day, an even task mix, uniform traffic, and 70% utilization are planning assumptions, not observed product traffic.
- Only 25 prompts per model were benchmarked, with one run per prompt. No concurrent or production load test was performed; the replica estimate does not guarantee a service-level target.
- API token use reuses local model counts. Actual hosted models can tokenize prompts and generate answers differently.
- The AWS replica estimate uses T4 benchmark latency as a proxy. HF hardware and throughput are unknown, so this is a usage-cost comparison, not a matched-throughput comparison.
- Prices and available models can change. Some API alternatives are larger or from a different family and may have different quality, latency, and token use.
- AWS cost excludes storage, network, monitoring, taxes, and discounts. HF costs are token-usage estimates and exclude credits, taxes, discounts, and any API pricing changes.
- The notebook contains the Part 1 benchmark and the Part 2 scaling calculations. This document contains the Part 3 routing plan; it does not simulate concurrent routing.

## Official and Pricing References

- [AWS EC2 G4 instance specifications](https://aws.amazon.com/ec2/instance-types/g4/) and [On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/).
- [HF Inference Providers model and price list](https://huggingface.co/inference/models).
- [IBM Granite 4.2 3B](https://huggingface.co/ibm-granite/granite-4.2-3b), [Qwen3 4B Instruct](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [Gemma 3 4B](https://huggingface.co/google/gemma-3-4b-it), [Llama 3.1 8B](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct), [Qwen3.5 9B](https://huggingface.co/Qwen/Qwen3.5-9B), [Qwen3 14B](https://huggingface.co/Qwen/Qwen3-14B), [Phi-4](https://huggingface.co/microsoft/phi-4), and [HF Inference Providers pricing and billing](https://huggingface.co/docs/inference-providers/main/pricing).
