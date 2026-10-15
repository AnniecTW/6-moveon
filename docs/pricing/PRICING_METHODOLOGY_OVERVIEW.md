# MoveOn Pricing Methodology — Team Overview

**Status:** Features 1 and 2 implemented; Feature 3 pricing proposed. Research parameters still require validation.

For current product behavior and evidence limits, use [implementation progress](IMPLEMENTATION_PROGRESS.md). The alternatives below describe the broader research plan, including methods not used in the live price guide.

## 1. What are we trying to solve?

MoveOn helps UIUC students sell used belongings before moving out, while helping other students assemble affordable bundles. Our pricing system recommends prices, but **sellers control final decisions**. The engine has three connected features:

1. **Initial listing:** What is a reasonable starting price for this specific item?
2. **Move-out markdown:** When should we recommend lowering it as the deadline approaches?
3. **Bundle discount:** What additional discount should *each seller* consider when their item joins a multi-seller bundle?

**Core idea:** Statistical evidence estimates a market benchmark; transparent rules produce deadline and bundle recommendations; mathematical optimization enforces fair allocation and seller constraints. AI helps interpret item information, **not** invent prices.

## 2. Methods at a glance

| Feature | Selected methods | Why these are appropriate / evidence | Next-best alternatives and why not the MVP default |
|---|---|---|---|
| **Initial listing price** | **Robust comparable-price medians** with condition matching/adjustment; **hedonic (attribute-based) regression** when data supports it | Comparable prices anchor values in observed market behavior. Hedonic theory models prices as a function of characteristics such as condition, brand and item type (Rosen, 1974). eBay Product Research is an industry example of using historical sold-price comparisons [1, 2]. | **Gradient boosting:** captures nonlinear effects, but more complex, less interpretable and harder to validate in sparse categories. **Flat depreciation tables:** simpler, but ignore differences across markets/items. We use the median as a reliable fallback and add regression only if it improves holdout results. |
| **Move-out price** | **Finite-horizon, bounded power-function markdown** with seller approval | A move-out deadline makes the remaining selling window economically important. Finite-horizon dynamic-pricing research studies this setting [3]. A power curve is an understandable **MVP heuristic**, not the formula proven optimal by that research. | **Linear price drops:** simpler, but cannot easily represent accelerating urgency. **Stochastic dynamic programming:** more adaptive but needs demand estimates MoveOn does not yet have. |
| **Per-item bundle proposal** | **Market-anchored, seller-authorized discount policy**, informed by benchmark position, urgency and seller flexibility | A seller can be invited to close a market-price gap or offer a separate multi-item incentive. eBay demonstrates real-world seller-controlled bundle incentives [4]; it does **not** establish optimal discounts for unrelated campus sellers. | **Flat 10% for everyone:** easy but ignores floor/consent, benchmark and urgency. **Response-model-driven discounts:** potentially stronger after MoveOn has bundle-offer outcomes, but not at launch. |
| **Final bundle allocation** | **Constrained linear programming (LP)** where needed | LP distributes a specified incentive across items under explicit seller floors/caps. This is a tractable, auditable optimization problem; SciPy implements LP solvers [5]. | **Equal allocation:** might violate seller-specific flexibility. **Mixed-integer/nonlinear optimization:** unnecessary unless eligibility or decision rules become discrete/nonlinear. |
| **AI & confidence** | **Gemini attribute extraction + human confirmation**; **evidence-quality labels** | AI can structure descriptions/photos, while deterministic code handles prices. Confidence should reflect comparable coverage, provenance and uncertainty, not an LLM-generated certainty score. | **LLM-only price guesses:** lack auditable comparable evidence and reproducibility. |

**Evidence boundary:** Publications support pricing *principles*; industry tools demonstrate *practice*. Neither gives a UIUC-specific optimal price, discount percentage or markdown exponent.

## 3. Feature 1 — Initial listing recommendation

### How it works

**Seller uploads photo and enters details → AI suggests attributes → seller confirms → comparable records matched → median benchmark computed → optional hedonic model evaluated → best validated method chosen → suggested price, range, and evidence label displayed.**

Start with **comparable-market median pricing**. If we have enough Good-condition desks of similar type/brand, use their median. Otherwise consider an evidence-supported adjustment to a broader desk median; otherwise report a broad, low-confidence benchmark rather than pretending to know the condition premium.

An illustrative adjustment (not a universal industry coefficient):

\[
P_{\mathrm{adjusted}}=P_{\mathrm{comparable}}\times F_{\mathrm{condition}}
\]

Suppose comparable Good-condition lamps have a median of **$40** and sufficiently comparable Fair-condition lamps have a median of **$30**. The estimated Fair/Good factor would be **0.75**, yielding **$30** from a $40 Good baseline. Brand, age, and item type can confound this comparison; matched comparisons are preferable.

**Hedonic regression** estimates characteristics *together*, avoiding simplistic independent multipliers:

\[
\log(P_i)=\beta_0+\beta_1\,\mathrm{Condition}_i+\beta_2\,\mathrm{Brand}_i+\beta_3\,\mathrm{ItemType}_i+\epsilon_i.
\]

Add age only after obtaining a reliable age field. When predicting back from log price, assess retransformation bias (e.g., smearing adjustment). Do **not** apply a second condition multiplier if regression already uses condition.

**Model decision:** Compare condition-adjusted median vs. a parsimonious hedonic model on the **same held-out records**, using MAE, median absolute error, bias by type/condition and stability. Use regression only where it performs adequately; otherwise keep the median fallback. Calling this "statistical valuation" is appropriate even though applying the model to a new listing is technically prediction.

### Dataset reality

The supplied `stable_pricing_items_v1.csv` contains **1,409 observations** from 2023, across **6 categories and 42 item types**. Condition counts: **New 968, Good 230, Like new 201, Fair 9, Poor 1**. Furniture has **15** observations. No age field is present. `price` and `observed_price_at_buy_comp` are identical in the inspected dataset, but their **meaning as completed-sale vs. asking price is not verified**. Until source semantics are confirmed, call the output an **observed-market asking/price benchmark**, not verified fair transaction value. Avoid strong claims for sparse furniture and Fair/Poor groups. This 2023 dataset is not a current UIUC sample.

### Confidence label

- **High:** Many recent, close, source-verified comparables and stable held-out error.
- **Medium:** Some close evidence, but limited local/condition coverage or wider uncertainty.
- **Low:** Sparse, old, broad, or unverified data; seller receives a qualified reference rather than false precision.

These are qualitative **evidence grades**, not probabilities that the price will sell. Thresholds must be defined after examining the data.

## 4. Feature 2 — Move-out markdown recommendation

The implemented rule is a **bounded power-function markdown**:

\[
P(t)=P_{\min}+(P_0-P_{\min})\left[1-\left(1-\frac{t}{T}\right)^{\gamma}\right],\qquad 0\le t\le T,\;\gamma>1.
\]

- \(P_0\): starting seller-approved listing price
- \(P_{\min}\): seller-approved floor
- \(T\): original selling-window length (fixed at setup)
- \(t\): days remaining
- \(\gamma\): configurable curve shape

**Example (illustrative, not fitted):** A $100 item with a $60 floor, 30-day window and \(\gamma=2\) has targets of **$100 at day 30**, **$90 at day 15**, and **$60 at day 0**. The complementary power curve deliberately saves larger reductions for later. The previous written \((t/T)^\gamma\) form contradicted that behavior for \(\gamma>1\). It is a **power** function, *not an exponential function*.

**Workflow:** Seller provides date and normal minimum; selecting `sell_no_matter_what` also requires a seller-chosen urgent minimum no higher than the normal one. The markdown base is filled from the original listing price and remains fixed unless the seller edits it directly. Normal and urgent pilot exponents are 2 and 1.2 respectively; neither is fitted to MoveOn demand. The scheduled service checks unsold/eligible listings, proposes only a target below the current asking price, and logs the seller's accept, decline, or modify decision. Edits to the asking price, base, minimum prices, urgency, or move-out date recalculate suggestions; ordinary edits do not change the base. The normal curve uses the normal minimum; Sell no matter what uses the urgent minimum. Each below-normal-minimum change requires separate explicit approval, and no change can pass the urgent minimum. Discounts are never applied automatically.

MoveOn inbox reminders are sent only when 30, 21, 14, 7, or 3 days remain and a lower curve price exists. These milestones do not restrict the seller's on-demand Markdown suggestion button on My Listings. A reminder links to the current proposal; approval still happens on My Listings.

**Why this method:** Research by Gallego and van Ryzin [3] establishes the finite-selling-window pricing problem, **not** a universal quadratic curve or specific percentage discount. Test different curve parameters as actual MoveOn sales accumulate.

## 5. Feature 3 — Per-item bundle discounts, then optimization

**Two decisions must be separated:**

1. **What discount is defensible to *propose* for this item?** Use a transparent market-anchored and seller-authorized rule.
2. **How should a chosen total bundle incentive be allocated?** Use constrained LP where useful.

For item \(i\): \(L_i\) = current listing price, \(M_i\) = evidence-backed market benchmark, \(F_i\) = seller floor, and \(C_i\) = any additional seller-specific bundle discount cap.

\[
\text{Discount capacity}_i=\min\big(\max(0,L_i-F_i),C_i\big)
\]

If no distinct cap is configured, use the allowable floor-based capacity **only if bundle consent exists**. Use the benchmark to calculate a **market-alignment opportunity**:

\[
A_i=\max(0,L_i-M_i).
\]

Market-alignment is **not** a buyer-incentive optimum. If an item is already below benchmark, a further incentive must be **separately opted into** by its seller; urgency can help *suggest* that option, not authorize it. Never double-count a previously accepted move-out markdown.

**Example (illustrative):**

| Item | Listing | Benchmark | Seller floor | Market-alignment opportunity | Allowed reduction |
|---|---:|---:|---:|---:|---:|
| Desk | $100 | $90 | $80 | $10 | $20 |
| Chair | $40 | $42 | $35 | $0 | $5 |
| Lamp | $30 | $25 | $20 | $5 | $10 |

The initial market-alignment proposals might be **$10 / $0 / $5** subject to confidence and seller approval. The chair seller may separately offer up to $3 as an explicit bundling incentive. Note that eBay's bundle discounts are controlled by sellers of their own inventory [4], whereas MoveOn bundles **different sellers' items**, so MoveOn needs per-seller consent.

For an approved target total discount \(D\), set \(d_i\) as the discount on each item:

\[
\sum_i d_i=D,\qquad 0\le d_i\le \text{Discount capacity}_i.
\]

A possible LP minimizes \(\sum_i w_i d_i\), where \(w_i\) is an **explicit, documented seller-preference cost**. Another option is to minimize deviation from each item's approved proposed discount. If \(D\) exceeds total authorized capacity, reduce \(D\); **never violate constraints**. Round monetary allocations carefully and verify sums.

**Workflow:** Buyer selects 3+ eligible items → existing bundle builder chooses listings → policy proposes individual discounts → sellers authorize discounts → LP allocates feasible approved total → buyer sees itemized savings → revalidate listings and seller permissions before checkout.

## 6. Statistical and operational checks

Regression requires **assumption and validation diagnostics**, not just a good R². Check:

- **Independence:** Identify duplicates, repeated product/seller records and dependence between errors. *Predictors need not be independent of each other.* Use group-aware splits when identifiers exist.
- **Multicollinearity:** Check design-matrix rank, correlations and VIF; simplify or regularize when needed.
- **Functional form:** Inspect residual plots and examine log-price fit and category interactions.
- **Heteroscedasticity:** Inspect residual spread and use the Breusch–Pagan test for appropriate OLS fits; use robust errors if making inferences.
- **Influence/outliers:** Investigate leverage/Cook's distance rather than blindly deleting expensive items.
- **Normality:** Q–Q plots matter mainly for certain parametric inference, not as an absolute requirement for useful predictions.
- **Leakage:** Fit preprocessing on training data only; use meaningful time/group-aware holdouts, where feasible.
- **Sparse categories:** Count records per condition/type and parameters. Revert to broad qualified benchmarks when necessary.

The median method needs source-quality, similarity and sparse-group checks; the power curve needs boundary/monotonicity and seller-floor tests; LP needs feasibility, authorization and total-consistency tests. **Do not apply OLS-specific assumptions to deterministic pricing rules or LP.** See [6, 7].

## 7. Practical MVP requirements and rollout

| Order | Deliverable | Definition of done |
|---|---|---|
| 1 | Source audit and cleaning | Provenance/price meaning checked, exclusions logged, record counts reported |
| 2 | Median price baseline | Item-type and condition matching, documented sparse-data fallback |
| 3 | Regression benchmark | Parsimonious model, diagnostic report, out-of-sample comparison; use only where justified |
| 4 | Seller listing UI | Suggested price/range/confidence and editable seller decision |
| 5 | Move-out pricing | Bounded curve, seller approval, history and scheduled reassessment |
| 6 | Bundle policy + LP | Distinct proposed vs. allocated discount, per-seller consent/floor, audit trail |
| 7 | Outcomes collection | Sale vs. unsold, listing exposure, markdown approvals, bundle completions for future calibration |

**Architecture:** Keep monetary calculations in Python/Django with Decimal; use Gemini for attribute extraction/explanations and existing Chart.js for visualizations. Reuse existing `Listing`, `PriceRecommendation`, `Transaction`, `BundleItem`, and bundle-selection functionality; inspect branch state before editing.

## 8. Supporting references

1. Rosen, S. (1974), *Hedonic Prices and Implicit Markets*, *Journal of Political Economy*. https://doi.org/10.1086/260169
2. eBay, *Product Research* (market research using historical transaction prices). https://www.ebay.com/help/selling/selling-tools/research?id=4853
3. Gallego, G., and van Ryzin, G. (1994), *Optimal Dynamic Pricing of Inventories with Stochastic Demand over Finite Horizons*, *Management Science*. https://doi.org/10.1287/mnsc.40.8.999
4. eBay Seller Center, *Bundle Discounts*. https://www.ebay.com/sellercenter/growth/seller-hub-discounts/bundle-discounts
5. SciPy, `scipy.optimize.linprog` documentation. https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
6. statsmodels, *Regression Diagnostics*. https://www.statsmodels.org/stable/examples/notebooks/generated/regression_diagnostics.html
7. scikit-learn, *Common Pitfalls and Recommended Practices* (notably leakage). https://scikit-learn.org/stable/common_pitfalls.html

**Interpretation:** These are sources for methodological rationale or actual industry practice. They do **not** validate MoveOn-specific condition factors, discount amounts, demand uplift or UIUC market prices. Those require data and testing.
