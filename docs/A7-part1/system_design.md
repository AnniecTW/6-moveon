# A7 — System Design

## Estimation Basis

- Each DAU sends **5 requests daily**, evenly split across five tasks; models are alternatives.
- Means use 25 answers per model. Mean latency estimates AWS capacity; median is a typical-request reference.
- Part 1 times `model.generate()` (prefill and decoding), excluding tokenization, loading, warm-up, network, and queue time.
- Assume even traffic over 24 hours at **70% utilization**. Replicas = `ceil(DAU × 5 × mean latency ÷ (86,400 × 0.70))`, with at least one replica and one request at a time.
- AWS uses a **`g4dn.4xlarge` in `us-east-1`** (16 vCPUs, 64 GiB, Tesla T4) at **$1.204/hour**. Price checked 2026-10-26; T4 latency is a capacity proxy.
- HF uses public token rates and local counts; serverless machine count and throughput are not public.

## Part 1 Evaluation Data

The benchmark has **375 responses** (15 models × 25 prompts), scored with AI assistance and targeted review—not independent ground truth. Latency and tokens/sec measure speed; `token_limit_hits` flags possible truncation.

## 2.1–2.2 Token Usage Per Request

Per-request values are means across 25 answers; daily requests = `DAU × 5`.

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

The two **90-row tables** cover six DAU tiers and 15 local models. HF input and output costs are calculated separately:

`daily API cost = daily input tokens × input price / 1,000,000 + daily output tokens × output price / 1,000,000`

HF machine count is **Provider-managed; not disclosed**; total cost is token usage.

### Methodology

We matched local models to paid HF APIs, preferring exact or same-family matches. Otherwise, we chose by size and use. The 15 locals map to seven APIs.

| Local LLM | HF API model | Provider | Input ($/1M) | Output ($/1M) | Matching rationale |
|---|---|---|---:|---:|---|
| `Qwen/Qwen3-0.6B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same family; 4B alternative |
| `HuggingFaceTB/SmolLM2-360M-Instruct` | `ibm-granite/granite-4.2-3b` | DeepInfra | $0.03 | $0.12 | Different family; 3B alternative |
| `google/gemma-3-270m-it` | `google/gemma-3-4b-it` | DeepInfra | $0.05 | $0.10 | Same family; 4B alternative |
| `meta-llama/Llama-3.2-1B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Same family; 8B alternative |
| `Qwen/Qwen3-1.7B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same family; 4B alternative |
| `HuggingFaceTB/SmolLM2-1.7B-Instruct` | `ibm-granite/granite-4.2-3b` | DeepInfra | $0.03 | $0.12 | Different family; similar small use |
| `microsoft/Phi-4-mini-instruct` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Similar size/use; different family |
| `Qwen/Qwen3-4B` | `Qwen/Qwen3-4B-Instruct-2507` | Nscale | $0.01 | $0.03 | Same family and size |
| `Qwen/Qwen2.5-7B-Instruct` | `Qwen/Qwen3.5-9B` | DeepInfra | $0.10 | $0.15 | Related family; similar scale |
| `mistralai/Mistral-7B-Instruct-v0.3` | `Qwen/Qwen3.5-9B` | DeepInfra | $0.10 | $0.15 | Similar scale; different family |
| `Qwen/Qwen2.5-14B-Instruct` | `Qwen/Qwen3-14B` | Nscale | $0.07 | $0.20 | Related family; similar size |
| `microsoft/phi-4` | `microsoft/phi-4` | DeepInfra | $0.07 | $0.14 | Exact model match |
| `mistralai/Mistral-Nemo-Instruct-2407` | `Qwen/Qwen3-14B` | Nscale | $0.07 | $0.20 | Similar scale; different family |
| `meta-llama/Llama-3.2-3B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Same family; 8B alternative |
| `meta-llama/Llama-3.1-8B-Instruct` | `meta-llama/Llama-3.1-8B-Instruct` | Novita | $0.02 | $0.05 | Exact model match |

Prices and availability were checked on **2026-10-26** using the official [HF price list](https://huggingface.co/inference/models). Alternatives and token counts differ; credits, taxes, and discounts are excluded.

No priced API close to SmolLM2's 0.36B–1.7B range was verified; Granite 3B is a larger, different-family alternative.

## 2.5 Cost Analysis

Ranges show the lowest and highest daily cost among the 15 alternatives; they are not summed.

| DAU tier | AWS self-host cost/day | HF API usage cost/day |
|---|---:|---:|
| Prototype (1,000) | $28.90–$28.90 | $0.02–$0.23 |
| Early Startup (10,000) | $57.79–$260.06 | $0.24–$2.25 |
| Growing Product (100,000) | $433.44–$2,513.95 | $2.40–$22.50 |
| Large Platform (1,000,000) | $4,189.92–$24,966.14 | $24.05–$225.05 |
| Mass Consumer App (10,000,000) | $41,812.51–$249,430.27 | $240.46–$2,250.50 |
| Global Platform (100,000,000) | $417,922.85–$2,494,100.45 | $2,404.60–$22,505.00 |

1. **When is local hosting cheaper?** At none; the highest HF estimate is below the lowest AWS estimate in every tier.
2. **When is API cheaper?** At all six DAU levels.
3. **When should the architecture change?** Reconsider self-hosting if measured steady traffic lowers full cost and the team can operate it. Use APIs for low or bursty traffic; consider hybrid if cost, reliability, or privacy warrants it.

## Part 3 — Multi-Model Routing Strategy

Route routine requests to task-specific local models; escalate complex or incomplete answers, peak overflow, or local failures to one of seven priced HF models. This compares local quality and latency with hosted flexibility and fallback coverage. Part 2 estimates lower API cost at all six scales. Use comparable listings for price recommendations and code for arithmetic.

Examples: `microsoft/Phi-4-mini-instruct` scored 10.00 on classification (0.35 s); `Qwen/Qwen3-0.6B` scored 10.00 on text generation (0.42 s). `Qwen/Qwen2.5-7B-Instruct` and `Qwen/Qwen2.5-14B-Instruct` scored 8.61 and 9.91 on extraction. For purchase advice, `Qwen/Qwen3-4B` scored 8.60 (10.21 s) and `mistralai/Mistral-Nemo-Instruct-2407` scored 8.65 (25.28 s). Each pair has five responses in [summary.csv](output/summary.csv).

| Scenario | Routing strategy | Local model | HF hosted model | Expected benefit |
|---|---|---|---|---|
| **Normal operation** | Run routine tasks locally; send invalid or incomplete answers to HF. | Phi-4-mini for classification; Qwen3-0.6B for text; Qwen2.5-7B for extraction; Qwen3-4B for advice. | `Qwen/Qwen3-4B-Instruct-2507` for retries; `Qwen/Qwen3.5-9B` for extraction; `Qwen/Qwen3-14B` for harder advice. | Keeps routine work local. |
| **Peak usage** | Send selected overflow to HF, subject to provider limits. | Phi-4-mini for classification; Qwen3-0.6B for text; Qwen2.5-7B or Qwen3-4B for harder tasks. | `Qwen/Qwen3-4B-Instruct-2507` for short requests; `Qwen/Qwen3.5-9B` or `Qwen/Qwen3-14B` for complex requests. | Eases queues at added cost. |
| **High-complexity request** | Validate local output; escalate one incomplete answer. | Qwen2.5-14B for extraction; Mistral-Nemo or Phi-4 for purchase advice. | `Qwen/Qwen3-14B` for extraction; `microsoft/phi-4` or `Qwen/Qwen3.5-9B` for advice. | Reserves larger models for hard requests. |
| **Cost optimization** | Use code for rules; shorten prompts and answers; limit calls and retries. | Use compact local models for routine tasks when available. | Use `Qwen/Qwen3-4B-Instruct-2507` or `ibm-granite/granite-4.2-3b` for simple tasks; reserve larger APIs for harder cases. | Reduces token use. |
| **Local overload or GPU failure** | Route essential requests to HF; limit retries if rejected. | Use local models only while healthy. | `Qwen/Qwen3-4B-Instruct-2507` for routine tasks; `Qwen/Qwen3.5-9B` or `Qwen/Qwen3-14B` for harder requests. | Provides a local-failure fallback. |

### Routing Trade-offs

- **Latency:** Small local models were fast on some tasks; API network and queue time were not measured.
- **Cost:** Part 2 favors API at all six scales. Limit calls and tokens; compare with real traffic.
- **Quality:** Check outputs and listing facts; escalate incomplete answers.

## Limitations

- Each model answered 25 prompts once; no concurrent test was run. AWS capacity uses T4 latency as a proxy.
- AWS excludes storage, network, and monitoring. Both estimates exclude taxes and discounts; HF rates may change.

## References

- AWS [On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/).
- Checked **2026-10-26**: [Economize](https://www.economize.cloud/resources/aws/pricing/ec2/g4dn.4xlarge/) (updated 2026-10-24) lists $1.204/hour in `us-east-1`; [EC2Info](https://ec2info.app/g4dn.4xlarge) reports the same AWS Pricing API rate. [AWS G4 specs](https://aws.amazon.com/ec2/instance-types/g4/) confirm the T4.
- HF [Inference Providers model and price list](https://huggingface.co/inference/models) and [pricing and billing](https://huggingface.co/docs/inference-providers/main/pricing).
