# MoveOn — Pricing Engine Technical Strategy and Implementation Specification

**Audience:** Coding agents, developers, data analysts, course reviewers  
**Status:** Features 1 and 2 implemented; Feature 3 pricing proposed. This document also records earlier implementation guidance.
**Companion:** `PRICING_METHODOLOGY_OVERVIEW.md`  
**Target:** Existing `6-moveon` Django application; confirm current checkout branch before implementation.

## 1. Product objectives and non-negotiable constraints

MoveOn serves UIUC students selling belongings before moving out and buyers furnishing rooms using individual items or customized bundles. Implement three interlocking pricing capabilities:

1. **Suggested initial listing price:** statistical, evidence-aware valuation benchmark.
2. **Deadline markdown recommendations:** bounded nonlinear seller-approved price adjustments.
3. **Bundle price recommendations:** evidence-informed item proposals plus seller-constrained allocation.

**MVP architecture:** robust comparable medians and condition matching; conditional hedonic regression; deterministic markdown/discount rules; linear programming where allocation warrants it; Gemini as an attribute/explanation assistant, **not** the sole numeric price estimator.

Required properties:

- Price calculations are auditable, reproducible, versioned and precision-safe (use `Decimal` at all monetary boundaries).
- Every recommendation distinguishes **benchmark**, **suggested offer**, and **seller-approved listed price**.
- Sellers retain approval control, including separate approval for below-floor offers.
- Never bypass bundle eligibility, seller caps or price floors without specific authorization.
- Source data provenance, verification status, observation date, comparable eligibility and confidence are retained.
- Reuse current Django models, migrations, services, existing Gemini/bundle logic, templates, Chart.js assets and tests. Don't create a parallel app unless warranted after inspection.
- Do not invent observed completed sales, age or model information, uncertainty bounds, optimal discount percentages or measured conversion uplift.

## 2. Existing codebase: inspection checklist

At the time of a prior review of GitHub branch `week3`, relevant files and fields included:

| Location | Previously observed structures | Implementation guidance |
|---|---|---|
| `marketplace/models.py` | `Listing.listing_price`, `retail_price`, `benchmark_price`, `move_out_date`, `minimum_price`, `bundle_eligible`, `sell_no_matter_what` | Reuse; inspect constraints, field types, and actual available `benchmark_low/high` fields |
| `marketplace/models.py` | `PriceRecommendation.previous_price`, `recommended_price`, `applied_price`, status/history | Extend minimally for method/policy versions, rationale, approval evidence when missing |
| `marketplace/models.py` | `Transaction.agreed_price`, completed status, benchmark snapshot | Future local completed-sale comparables; distinguish from incomplete transactions |
| `marketplace/forms.py`, `marketplace/views.py` | Listing price, floor and move-out inputs | Keep validation and seller-controlled workflow |
| `bundles/models.py` | `BundleItem.listing_price_snapshot`, `proposed_bundle_price`, `final_price` | Reuse price snapshots; add only missing per-seller approval/quote lifecycle data |
| `bundles/services.py` | Gemini-based Budget / Best Value / Premium *selection*, without calculating discounts | Keep selection separate from deterministic bundle pricing |
| Templates, static JS | Seller listing and bundle-builder interfaces | Enhance existing design; reuse Chart.js rather than duplicate chart frameworks |

**These are prior observations, not a fresh code audit.** Agent must inspect the currently checked-out branch first and document differences. Avoid migrations unless required by a demonstrated missing persistence invariant.

## 3. Methods, rationale, evidence and alternatives

| Capability | Selected method | Evidence-based rationale and limitation | Best alternative / selection justification |
|---|---|---|---|
| Initial price | **Comparable median + condition-adjusted matching**, with **parsimonious hedonic regression** when validated | Comparable observations represent market price evidence; hedonic attribute-price analysis is established by Rosen (1974) [R1]. eBay Product Research uses comparable sold-price histories [R2]. These do **not** certify our CSV as completed sales. | Gradient boosting can learn complex nonlinearities but is harder to justify for sparse groups; fixed depreciation percentages are less market-specific. Median fallback is stable and interpretable. |
| Move-out | **Bounded power-function markdown**, configurable parameters and approval | Deadline-aware pricing is supported by finite-horizon stochastic-demand pricing research [R3]. Exact power curve is an engineered MVP heuristic, *not* the research's universal optimum. | Linear markdown less flexible for accelerating urgency; demand optimization requires sale probability modeling and more outcomes. |
| Item bundle proposal | **Market-anchored + seller-authorized discount opportunity**, with explicit urgency and voluntary incentive | eBay offers opt-in multi-item discounts [R4]; comparing current price to an evidence-backed benchmark and respecting willingness makes proposed changes transparent. No external source establishes optimal cross-seller UIUC discount rates. | Flat % ignores seller floors and market competitiveness; demand/causal discount optimization requires bundle outcome data. |
| Bundle allocation | **Constrained linear programming (LP)** for a chosen total discount | LP is the right formal tool when objectives/constraints are linear and item decisions are continuous [R5]. It proves *feasibility and objective optimality conditional on inputs*, not market-level optimal discount size. | Even/proportional allocation is easier but can ignore preferences/caps; MILP only needed if binary selection or tiers are added. |
| AI | Gemini multimodal attribute identification, explanations; seller verification | Structured interpretation can assist data entry; deterministic pricing ensures traceability. | LLM-only valuations risk fabrication and non-repeatable estimates. |
| Confidence | Source, match, sample and uncertainty rubric; calibration later | A qualitative evidence-grade avoids fake probability claims; evaluation and leakage controls follow statistical software guidance [R6, R7]. | LLM self-confidence is uncalibrated; conformal intervals might be considered with suitable holdout coverage. |

## 4. Dataset contract and audit

**Provided source:** `stable_pricing_items_v1.csv`; inspect actual location on disk, do not hardcode an unverified path. An inspection of the uploaded version found **1,409 rows, 21 columns, 6 broad categories, 42 item types**.

Exact columns observed:

```text
item_id, stime, price, name, c0_name, c1_name, c2_name,
brand_name, item_condition_id, item_condition_name, shipper_name,
observed_price_at_buy_comp, source_shard, moveon_category,
moveon_item_type, classification_source, classification_evidence,
human_verified, price_risk_flags, training_eligibility, exclusion_reason
```

Observed distribution:

| Category | Count |
|---|---:|
| Kitchen & Dining | 670 |
| Home Decor | 407 |
| Bedding & Bath | 207 |
| Appliances | 92 |
| Storage & Organization | 18 |
| Furniture | 15 |

Condition distribution: New **968**, Good **230**, Like new **201**, Fair **9**, Poor **1**. Records are dated 2023. No age attribute. `price` and `observed_price_at_buy_comp` contain matching values in the inspected file; that does **not** resolve whether either means verified sale, asking price, or price-at-purchase snapshot. `human_verified` concerns classification metadata unless provenance demonstrates otherwise; never reinterpret it as transaction verification.

### Audit deliverables (must precede fitting)

1. Profile schema, types, nulls, category/type/condition/brand frequencies and sample rows; summarize data dictionary and source semantics.
2. Investigate item IDs, duplicated rows, repeated products/sellers (where detectable), duplicated source shards, timestamp format/timezone and impossible prices.
3. Inspect `training_eligibility`, `price_risk_flags`, `exclusion_reason` and `classification_evidence`; respect exclusions and record counts at each filter. Do **not** assume flagged records can be silently discarded without documenting selection bias.
4. Check source and temporal coverage. Split observational asking benchmarks vs. confirmed completed transactions; never mix them without explicit policy or calibration.
5. Normalize conditions, item names and brands conservatively. Handle rare levels (e.g., sparse brands) without creating huge parameter counts.
6. Distinguish retail, sale price, listing price and total delivered price. Normalize shipping/pickup when credible metadata exists, otherwise note comparability limits.
7. Create `docs/pricing/validation/data_profile.md`, schema and quality summary; preserve cleaned data as a reproducible derived artifact with no unnecessary personal information.
8. Do not infer age from `stime` (observation timestamp is not item age). Do not report 2023 out-of-campus prices as current UIUC market value.

## 5. Initial listing feature — statistical valuation

### 5.1 Data inputs and output contract

Input: item type, broad category, seller-confirmed condition, brand/model if known, age if reliably captured later, retail reference if sourced, listing context/pickup and optional move-out date. Pricing benchmark **must not** depend on the seller's own ask in a way that leaks it into the market estimate.

Example typed output (illustrative values, not verified observed results):

```json
{
  "benchmark_price": "72.00",
  "suggested_listing_price": "72.00",
  "range_low": "65.00",
  "range_high": "85.00",
  "evidence_grade": "MEDIUM",
  "comparable_count": 12,
  "source_price_kind": "UNVERIFIED_OBSERVED_PRICE",
  "method": "CONDITION_MEDIAN",
  "model_version": "v1",
  "data_version": "2023-source-v1",
  "notes": ["Illustrative output; not a verified sale prediction"]
}
```

Range type must be declared: observed IQR, bootstrapped benchmark interval, or validated predictive interval are **not interchangeable**. The seller's chosen price is stored distinctly from estimated benchmark.

### 5.2 Robust comparable medians — default baseline

- Match exact type/brand/model/condition when possible; relax brand, condition, or geography only under documented hierarchy.
- Require a configurable minimum number of qualified comparables for each match tier; example threshold (such as eight) is **provisional**, never presented as a statistical law.
- Calculate median, Q1/Q3, support count and date coverage; weigh recency only after demonstrating appropriate rationale.
- Use broader condition/type/category medians as **qualified fallbacks**, with downgraded confidence. Avoid nonsensical cross-category matches.
- Avoid blind outlier deletion. Investigate product quality/brand differences.
- When there are few Fair/Poor records, report that a reliable condition-specific price is unavailable rather than manufacturing a discount.

### 5.3 Condition-aware adjustments — if supported

Where matching quality is adequate:

\[
F_{c\mid g}=\frac{\operatorname{median}(P\mid c,g)}{\operatorname{median}(P\mid c_{\mathrm{reference}},g)}
\]

Here \(g\) is a tightly matched comparable group and \(c\) the condition. Then \(P_{\mathrm{target}}=P_{\mathrm{reference}}F_{c\mid g}\), **only** if reference median is not already condition-matched. Estimate group-specific uncertainty; address confounding by age/brand/quality; use a conservative fallback if samples are inadequate. A factor observed on mugs should not automatically be applied to sofas.

### 5.4 Hedonic regression — complementary candidate, not mandatory output

Reference formulation (adjust to available predictors):

\[
\log(P_i)=\beta_0+\beta_{\mathrm{type}}+\beta_{\mathrm{condition}}+\beta_{\mathrm{brand}}+\epsilon_i.
\]

Age and select interactions are **future features only when reliable and sufficiently populated**. Category and type have a hierarchical relationship; avoid singular design matrices caused by redundant indicators. Treat model as conditional price association, not a causal measurement of condition damage. For log predictions, assess retransformation bias before reporting prices in dollars.

- Start with a simple OLS specification for diagnostics/interpretation; consider Ridge regularization for sparse features and production inference.
- Encode categories within a training-only preprocessing pipeline; manage rare brands with grouped tiers or appropriate regularization, not arbitrary 40+ dummy variables when unsupported.
- Document complete-case or imputation policy, parameters to observation ratio and effective support within segments.
- Avoid training separate models on tiny categories (e.g., Furniture n=15); consider controlled pooling and clearly labeled uncertainty instead.
- If input features cannot be trusted or validation fails, fall back to robust median with explanation.

### 5.5 Model diagnostics and independence

| Issue | Test/review | Treatment |
|---|---|---|
| Independent observations/errors | Duplicate IDs/shards, possible repeated seller/product, grouping structure, residual patterns | Deduplicate; grouped validation and possibly cluster-robust SE when clusters known; don't claim proven independence without identifiers |
| Functional form | Residuals vs fitted, component plots, log-vs-level fit | Transform, simplify, selected interactions, re-evaluate |
| Multicollinearity | Design rank, category encoding, correlation, VIF, condition number | Remove redundant indicators, group levels, regularize |
| Heteroscedasticity | Residual spread; Breusch–Pagan for appropriate OLS | Robust covariance for inference or alternative model; reassess predictive intervals |
| Residual normality | Q–Q inspection where inferential methods need it | Investigate extreme deviations; normality not mandatory for point prediction |
| Influential values | Leverage, Cook's distance, high residuals | Audit real premium products vs errors; sensitivity report |
| Leakage | Pipeline inspection; time/group split; remove post-listing information | Fit encoders, imputation, thresholds and learned factors on training only |
| Sparse segments | Counts by item type × condition/brand; feature count | Pool cautiously, penalize complexity, median fallback |
| Endogeneity/confounding | Seller asks and age/brand/condition correlation; unobserved quality | Avoid causal language; prioritize matched comparable groups and interpret association only |

**Important:** predictors (age, brand, condition) do not have to be statistically independent. Independently drawn errors/observations, lack of perfect multicollinearity and appropriate exogeneity are different concepts. Breusch–Pagan p-values and Q–Q plots do not certify model validity; penalized regression does not inherit OLS standard-error formulas automatically.

### 5.6 Evaluation and model gating

1. Freeze a held-out evaluation set before feature-selection/calibration. Prefer chronological holdout when record timestamps are meaningful; apply group-aware splits when repeated product/seller identifiers exist.
2. Fit median baseline and condition-factor estimates on training data *only*.
3. Fit an interpretable hedonic specification and any penalized variant on the same training partition.
4. Compare all methods on exactly the same eligible held-out records: MAE, median absolute error, bias, per-type/condition error, coverage and failure rate; be careful with MAPE for low-priced goods.
5. Report performance separately for common vs. sparse categories and verified sold vs. unverified observed price, if distinguishable.
6. Promotion rule: select regression only if it improves stability and relevant holdout metrics and produces credible outputs; otherwise choose condition-adjusted median; if that fails, plain comparable median or no recommendation.
7. Store model/data/policy version, coverage and explanations. Never present held-out observed-price error as verified transaction-price error.

### 5.7 Qualitative evidence confidence

Use at least: verified source type, comparable count, similarity score, recency, segment density, benchmark spread, model holdout error. Create configurable HIGH/MEDIUM/LOW rubric; no fixed numerical probability without calibration. For a low-evidence listing, present a qualified broad range or manual price entry and explicitly describe missing evidence. Markdown effectiveness and bundle-response uncertainty **must not** inherit valuation confidence by default.

### 5.8 AI involvement

Gemini may parse title/photo into candidate type, brand, visible wear, size, model; return structured provenance and missing fields; seller confirms them. Never assume unseen functionality/age. Use AI to generate an *explanation grounded in actual engine outputs*, not to select price or fabricate comparables. Fail gracefully when AI unavailable.

### 5.9 UI integration / acceptance

Connect pricing to current listing form only after service tests. Display benchmark, suggested amount, range *with range type*, confidence grade and factors; allow edit/accept/reject. Persist exact seller decision and avoid anchoring valuation to seller entered asking price. Ensure seller price can differ from benchmark.

## 6. Feature 2 — move-out markdown policy

### 6.1 Definition and research boundary

For fixed initial selling window \(T\), time remaining \(0\le t\le T\), seller-approved markdown base \(P_0\) (filled from the original listing price until the seller edits it), approved normal floor \(P_{\min}\):

\[
P(t)=P_{\min}+(P_0-P_{\min})\left[1-\left(1-\frac{t}{T}\right)^{\gamma}\right],\qquad \gamma>1.
\]

This is a **bounded complementary power curve**, not exponential decay. Designed so \(P(T)=P_0\), \(P(0)=P_{\min}\), and markdowns accelerate near deadline when time flows forward. Example: \(P_0=100\), floor 60, \(T=30\), exponent 2 => day 30 $100; day 15 $90; day 0 $60. These values are illustrations. The earlier written form \((t/T)^\gamma\) with \(\gamma>1\) decreased faster *early*, contrary to the stated product objective; this correction is required for acceleration. Gallego & van Ryzin [R3] motivate finite-horizon dynamic pricing; they do **not** validate \(\gamma=2\) or this exact interpolation rule.

For **Sell no matter what**, retain the same seller-approved \(P_0\) and use a separately
approved urgent minimum \(P_u\le P_{\min}\) with a smaller exponent
\(1<\gamma_u<\gamma_n\). Pilot defaults are \(\gamma_n=2\) and
\(\gamma_u=1.2\); neither is an empirically optimal setting. The seller
chooses \(P_u\), and each proposal below the normal minimum needs separate
approval. Apply only a target below the current listing price; accepting an
earlier markdown or toggling urgency never replaces \(P_0\); only a seller edit to the markdown base does.

### 6.2 Policy rules and timeline

- Capture `initial_window_start`, original `T`, seller-editable markdown base, floor, exponent/policy version and approval mode.
- When a seller starts a schedule with fewer than 30 days left, use the 30-day date before move-out as the reference start while snapshotting the seller's current price and approved floor. This gives an immediate proposal based on remaining time; it is a policy reference date, not a claim that the item was listed earlier. For longer windows, use the actual schedule start date.
- Do not reset selling-window duration each day. Fill the markdown base from the original listing price and preserve it through accepted markdowns and ordinary listing edits. Sellers may edit the base directly; recalculate suggestions from that value and the current minimum, urgency, and move-out date. Applying a suggested price still requires seller approval.
- Clamp time input into [0,T] and guard against zero-length window and invalid price/floor/exponent.
- Run scheduled management command to evaluate ACTIVE/available listings; avoid repeated suggestions for unchanged parameters/day; exclude sold/reserved where not appropriate.
- Create seller-only MoveOn inbox reminders at exactly 30, 21, 14, 7, and 3 days remaining when the curve yields a lower proposal. These days control notifications only; on-demand My Listings suggestions remain available on other days. A schedule started exactly 30 days before move-out has no day-zero markdown, so its 30-day reminder has no price-drop proposal to send.
- Recommendation is a **proposal** until accepted. Respect listing price and seller floor. Record previous/recommended/applied, timestamp, accepted/declined/pending, policy version and rationale.
- `sell_no_matter_what`: require a seller-entered urgent minimum no higher than the normal minimum, and record explicit approval for each below-normal-minimum application. Never automatically apply a proposal or cross the urgent minimum.
- Detect existing bundle negotiations/reservations to avoid incompatible edits; revalidate on apply.
- Initially use views/inquiries for **review triggers**, not statistically established sale elasticity; treat future use as measured and calibrated.

### 6.3 Testing and monitoring

Test endpoints and monotonicity, zero/negative deadlines, floor, rounding and approval flows, duplicate scheduler runs, concurrency, unavailable status, and `sell_no_matter_what`. Track accepted markdowns, sale outcomes, time-to-sale and proceeds. Compare experimental curve policies later; don't claim causal lift from uncontrolled correlations.

## 7. Feature 3 — bundle pricing in two distinct stages

### 7.1 Economic objective, constraints, and consent

Different MoveOn items may have **different sellers**, unlike a conventional merchant's all-owned bundle. Preserve per-seller consent. Current bundle item price must reflect already-approved markdowns: **do not double-discount a move-out markdown**.

Variable definitions:

- \(L_i\) = current listed price (snapshot when bundle proposed).
- \(M_i\) = evidence-backed market benchmark (if sufficiently supported).
- \(F_i\) = seller-approved minimum (default regular price floor).
- \(C_i\) = seller-approved bundle-specific max discount (may be absent).
- \(d_i\) = newly proposed incremental bundle discount.

**Eligible cap:** If seller opted in and approved terms, \(U_i=\max(0,L_i-F_i)\), then cap at \(C_i\) if explicitly specified. Otherwise \(U_i=0\) when consent/floor policy is missing or ambiguous; request seller choice. `sell_no_matter_what` is not automatically bundle consent for below-floor pricing.

### 7.2 Stage A — evidence-informed proposed item discount

**Market gap:** \(A_i=\max(0,L_i-M_i)\) only if \(M_i\) has appropriate confidence; this suggests how far item price is above benchmark, **not** the optimal rebate. A conservative alignment proposal can be \(d_{i,\mathrm{market}}=\min(A_i,U_i)\) after approval. If below/near benchmark, don't create market gap artificially. Offer a *separate*, explicitly seller-authorized bundle incentive \(d_{i,\mathrm{incentive}}\); the total must share the same cap:

\[
0\le d_{i,\mathrm{market}}+d_{i,\mathrm{incentive}}\le U_i.
\]

Use remaining move-out days to **suggest** seller incentives, not to compute an unvalidated universal percentage. For provisional tier rules, document what is a product policy vs. estimated from market data; collect offer/acceptance outcomes to calibrate later.

**Example (illustrative, not empirical):** Desk L=$100, M=$90, F=$80 → market opportunity $10, total allowed $20. Chair L=$40, M=$42, F=$35 → market opportunity $0, max $5; seller may separately approve a $3 bundle incentive. Lamp L=$30, M=$25, F=$20 → market opportunity $5, allowed $10. Candidate proposals $10/$3/$5 if all approve. eBay's seller-controlled mix-and-match discounts [R4] establish an industry precedent for incentives, **not** an optimal cross-seller rate.

### 7.3 Stage B — LP allocation of chosen bundle discount

If product policy targets a total discount \(D\) and sellers authorize per-item capacities, solve:

\[
\sum_i d_i=D,\quad 0\le d_i\le U_i.
\]

A linear objective can be \(\min\sum_i w_i d_i\), where weights encode **documented seller preference costs**. Without meaningful weights, use transparent deterministic allocation or minimize deviation from approved proposed values (possibly an LP with extra positive/negative deviation variables). Require feasibility \(D\le\sum_i U_i\); if not, reduce D and disclose achievable discount, **not** breach floors. LP allocates a chosen discount; it does not prove that D maximizes conversion or total welfare. Use `scipy.optimize.linprog` if needed; a simple greedy capped allocator may be preferable for trivial constraints.

Avoid price-padding: do not permit a seller to raise the ask merely to advertise a bigger fake discount. Display savings relative to the actual captured listing-price snapshot and maintain discount provenance.

### 7.4 Bundle transaction workflow

1. Buyer chooses 3+ eligible items/categories; preserve existing tier/bundle selection service.
2. Snapshot availability, listed prices, sellers and benchmark metadata.
3. For each item compute `U_i`, `A_i`, and proposed market-alignment/incentive components with evidence label.
4. Obtain necessary per-seller approval for actual discounted amount and duration; unapproved items have zero authorized discount.
5. Set feasible target D; allocate with LP/transparent fallback; if approved proposed amounts are fixed, do not change them silently during allocation.
6. Show itemized `listing_price_snapshot`, approved discount, `proposed_bundle_price` and final total; record version and approvals.
7. Recheck seller floor, eligibility, price, availability and active transactions atomically before checkout/reservation. Expired or changed offers need reconfirmation.
8. Persist final agreed item prices and bundle totals; ensure rounding residuals are allocated deterministically and sums match to cent.

### 7.5 Bundle validation

Unit tests: seller consent, no missing floor bypass, cap/floor, infeasible D, simultaneous buyers, changed listing, seller withdrawal, no markdown double-count, split penny rounding, fixed approvals, consistent totals and pricing snapshots. Future analytics: buyer view → accepted offer → completed bundle, item-level take rate, seller proceeds and time-to-sale. Distinguish correlation from causal discount effects; controlled experiments are best for identifying uplift.

## 8. Statistical assumptions, diagnostic reports and method-specific checks

**Do not claim any test passed without executing it.** Report assumptions alongside sample sizes and observed problems.

### 8.1 Hedonic OLS / conditional regression checks

- **Observation/error independence:** inspect duplicates, repeated items/sellers/source shards, time dependence. Cannot confirm full independence without identifying clusters; group-aware split/cluster-robust inference when feasible. Predictors need *not* be independent of one another.
- **Exogeneity and omitted-variable bias:** seller selection, quality, retail value and model identity may affect coefficients. Report association rather than causal depreciation effects.
- **Functional form:** residual vs fitted, log transform diagnostics and sensible interactions; consider retransformation bias.
- **Collinearity:** VIF, rank and condition number, especially category/type dummy relationships and brand sparsity.
- **Heteroscedasticity:** plot residual spreads; Breusch–Pagan/White tests where appropriate; robust SE if making inference.
- **Normality:** inspect Q–Q, useful for small-sample formal inference but not absolute prerequisite for price-point estimation.
- **High leverage/influence:** Cook's distance, leverage, standardized residuals; investigate rather than delete all expensive items.
- **Enough data per term:** usable n after exclusions, actual encoded parameter count, group counts and model complexity; penalize or simplify when unstable.
- **Data leakage:** pipeline train-only transforms, proper holdout and source metadata; exclude final transaction information unavailable when the initial price is generated.

Produce plots and tables under `docs/pricing/validation/` plus a written decision for model use. Use `statsmodels` for OLS diagnostic/inference where applicable and scikit-learn for pipelines/regularized predictive models. Do not report OLS p-values as if they directly tested Ridge coefficients.

### 8.2 Comparable and adjustment checks

Within-group similarity, provenance, sample counts, observed spread, recency, duplicate suppression, bootstrap stability if resampling assumptions defensible, condition-adjustment confounding. Sparse groups should fall back or abstain. Never equate observed IQR with a validated predictive interval.

### 8.3 Pricing rules and optimization checks

Power curve: no OLS residual assumptions; test endpoints, shape, dates, floor, approval and sensitivity. LP: no residual normality assumptions; check feasibility, objective appropriateness, constraint satisfaction, degeneracy/non-unique solutions, rounding and auditability. If seller weights or discount effects become statistically estimated, validate the estimation models separately.

## 9. Evidence grades and explanatory UI

Design shared output fields: `method`, `benchmark`, `suggested`, `range_kind`, `range_low/high`, `evidence_grade`, `comparable_count`, `source_type`, `data_age`, `limitations`, `policy_version`, `model_version`. Build a rubric using count, match closeness, verified sale provenance, recency, price spread and held-out error; thresholds calibrated from dataset and documented. Differentiate **valuation evidence grade**, **markdown-effect evidence**, and **bundle-response evidence**. No unsupported "87% confident" display.

Suggested UX:

- Listing editor: recommended starting price, market range, evidence grade, factors and accept/edit action.
- Seller pricing panel: current and proposed deadline curve, days remaining, floor, explanation, explicit approval.
- Buyer bundle builder: line-item original/discount/final, total savings and pending seller approvals; do not represent proposals as locked prices.

## 10. AI boundary and implementation

Use existing Gemini service when possible for structured attribute extraction and natural language explanation only. Define schema + confidence/unknown state + human review. Avoid inventing product model, functional condition, age or sourcing. When AI fails, collect manual inputs. LLM explanations must quote actual numeric outputs from pricing service; no separate LLM-generated price. Never send unnecessary personal information to external model service.

## 11. Suggested code organization (adapt to actual repository)

```text
marketplace/
  pricing/
    comparables.py      # source-aware matching and robust baseline
    valuation.py        # hedonic fit/inference and model selection
    confidence.py       # evidence grade (not sale probability)
    deadline.py         # power curve, approvals/policy logic
    ai_attributes.py    # structured AI-assisted item metadata
    schemas.py          # dataclasses/typed service contracts
  management/commands/
    evaluate_pricing.py # scheduled recommendations
bundles/
  pricing.py            # market-anchor proposals, LP allocation, approvals
reports/ or docs/pricing/validation/
  data_profile.md
  regression_diagnostics.md
  comparison_metrics.md
  pricing_policy_tests.md
```

If equivalent modules exist, extend them instead. Create a service API which functions independently of HTTP views; test statistical functions offline first and integrate via existing Django views. Persist only fields needed for reproducibility, lifecycle, provenance and consent. Document any schema changes before migrating.

## 12. Implementation plan and acceptance criteria

**Phase 0 — baseline / source audit**

- [ ] Inspect branch, code and all existing pricing logic; document reuse map.
- [ ] Inspect CSV data dictionary, source price meaning, flags and quality; summarize eligibility counts.
- [ ] Establish deterministic reproducibility (dataset hash, Python environment, dependencies, random seed for splits, model version).

**Phase 1 — initial listing valuation**

- [ ] Comparable matcher + medians + IQR and sparse fallback.
- [ ] Condition matching and support-tested factor (not arbitrary blanket multipliers).
- [ ] Parsimonious hedonic OLS candidate, optional regularized version.
- [ ] Independence/diagnostic report, leakage-aware held-out comparison; method gate/fallback.
- [ ] Evidence grades and traceable source references.
- [ ] Seller listing UI: preview, accept/edit, exact price persisted; complete tests.

**Phase 2 — deadline pricing**

- [ ] Validate fixed T / `gamma` / floor policy; generate deterministic schedule.
- [ ] Schedule recommendation without automatic unauthorized change.
- [ ] Explicit below-floor opt-in plus per-change approval; history recording.
- [ ] Unit and integration tests for statuses, concurrency and price revisions.

**Phase 3 — bundles**

- [ ] Preserve existing bundle selection service and models.
- [ ] Evidence-informed `A_i`, eligibility, capacity and separately approved incentives.
- [ ] Choose explicit target D policy; verify feasible aggregate capacity.
- [ ] Allocate via LP (or simpler verified algorithm); no unauthorized allocations.
- [ ] Buyer itemized and seller approval UX; atomic revalidation and exact cent totals.

**Phase 4 — measure and later ML**

- [ ] Log exposures, price recommendations and decisions, inquiries, offers, completed/unsold outcomes, time-to-sale, bundle status and realized price.
- [ ] After enough quality data, evaluate ML valuation / sale-probability models and causal discount tests; adopt only with out-of-sample evidence.

## 13. Agent operational instructions

1. Read this document and overview, then audit the current branch. Do not infer that prior `week3` findings remain up to date.
2. Perform data audit and baseline first; show results and missing-data limitations. Do **not** claim dataset represents verified completed sales until established.
3. Implement incremental, testable services using existing architecture and DRY. Restrict initial work to Phase 1 until reviewed; do not silently implement all three features in one unvalidated change.
4. Document data provenance, model specification, diagnostics, holdout error, selected model, policy coefficients and price constraints. Don't hardcode a universal "industry-standard" discount.
5. Use `Decimal` at price boundaries, migrations only when needed, seller approvals and safe transaction state checks; verify relevant Django tests.
6. Save clear implementation notes and evidence in `docs/pricing/` and report exact files changed, tests run, remaining uncertainty and recommendations.

## 14. Research and technical references

- **[R1]** Rosen, S. (1974), *Hedonic Prices and Implicit Markets: Product Differentiation in Pure Competition*. https://doi.org/10.1086/260169
- **[R2]** eBay, *Product Research*, marketplace comparable analysis. https://www.ebay.com/help/selling/selling-tools/research?id=4853
- **[R3]** Gallego, G., & van Ryzin, G. (1994), *Optimal Dynamic Pricing of Inventories with Stochastic Demand over Finite Horizons*. https://doi.org/10.1287/mnsc.40.8.999
- **[R4]** eBay Seller Center, *Bundle Discounts* (opt-in discounts on multiple items). https://www.ebay.com/sellercenter/growth/seller-hub-discounts/bundle-discounts
- **[R5]** SciPy, `linprog`, linear optimization method. https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
- **[R6]** statsmodels, regression diagnostics. https://www.statsmodels.org/stable/examples/notebooks/generated/regression_diagnostics.html
- **[R7]** scikit-learn, common pitfalls including data leakage. https://scikit-learn.org/stable/common_pitfalls.html
- **[R8]** Bakos, Y., & Brynjolfsson, E. (1999), *Bundling Information Goods: Pricing, Profits, and Efficiency*. https://doi.org/10.1287/mnsc.45.12.1613 (background on bundling; digital-goods assumptions are not evidence of MoveOn's optimal discount)

**Citation boundary:** Theory and commercial mechanisms are credible motivation, not demonstrations that MoveOn's provisional percentages, fitted coefficients, or conversion improvements have been validated on UIUC transactions.
