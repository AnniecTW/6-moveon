# Phase 1 holdout and regression decision

**Historical comparison:** This report and `phase1_evaluation.json` were
generated with the original 12-record type-only fallback. Production policy
`initial-v1.3` shows a warned reference from sparse same-type observations;
its current holdout coverage and errors are summarized in
`../IMPLEMENTATION_PROGRESS.md`. The regression comparison here has not been
rerun for the additional covered items.

Run `python experiments/merrec-pricing/analysis/run_phase1.py` for the current
policy; it will replace the archived outputs with new results. Historical
figures below are in `phase1_evaluation.json`; the residual and Q–Q plots are
in `regression_diagnostics.png`. All errors below measure prediction of the
**2023 observed `buy_comp` price**, not completed sale price or current UIUC
value.

## Evaluation design

After excluding two price-risk observations, 1,407 rows remain. The last 20%
by `(stime, item_id)` are held out: 282 records. One training row sharing an
exact normalized name with a held-out row is removed, leaving 1,124 training
comparables. Fair/Poor records are excluded from the regression fit because
their support is inadequate; model training has 1,115 rows. Item IDs do not
overlap across partitions. All median matching, factor estimation, rare-level
pooling, one-hot levels, OLS coefficients, and smearing are fit from training
data only. An exact name is only a crude proxy for duplicate products; seller
identifiers are unavailable.

The baseline first uses brand + type + condition when it has at least 8
observations, then an observed same-type condition factor applied to a
same-brand New reference when both ratio groups and the brand reference have
at least 8, then type + condition, and finally a type-only unadjusted median
for New/Like new/Good if at least 12 observations exist. Fair/Poor abstain
when not directly supported. The observed Q1–Q3 is a description of matched
prices, **not a predictive interval**. Thresholds are provisional product
policy. In the holdout, method counts were 37 brand-condition, 4 supported
brand-condition factor, 185 type-condition, 42 type-only unadjusted, and 14
abstentions.

The candidate model is OLS on log(price) with pooled item type, condition and
pooled brand indicators; no age term is included. Category is omitted because
it is strongly determined by item type. Item types with fewer than 15 training
records and brands with fewer than 20 are pooled. Dollar predictions use a
training-only Duan smearing factor of 1.436087. The model is associational,
not a causal condition-depreciation estimate.

## Same-row held-out results

Both methods are compared on the 268 rows where the baseline provides a
recommendation (95.04% coverage; 14 abstentions).

| Method | MAE | Median absolute error | Signed bias (prediction minus observed) |
|---|---:|---:|---:|
| Comparable median/condition baseline | $21.72 | $10.36 | −$7.32 |
| Hedonic OLS with smearing | $25.68 | $16.73 | +$2.24 |

| Category | Holdout / covered | Median MAE | Regression MAE |
|---|---:|---:|---:|
| Appliances | 10 / 8 | $82.29 | $80.75 |
| Bedding & Bath | 38 / 35 | $19.31 | $24.13 |
| Home Decor | 96 / 92 | $26.93 | $29.90 |
| Kitchen & Dining | 133 / 133 | $15.11 | $19.85 |
| Storage & Organization | 5 / 0 | unavailable | unavailable |
| Furniture | 0 / 0 | unavailable | unavailable |

Fair has one held-out observation and no baseline coverage; Poor has none.
For covered Good, Like new, and New observations, the median MAEs are $19.46,
$10.64, and $24.27 respectively; regression MAEs are $18.87, $15.85, and
$29.03. These small or imbalanced slices cannot establish reliable
condition-specific error bounds.

## Assumptions and diagnostics

- **Independence: unverified.** Item IDs and exact rows are unique. There are
  14 repeated names in the source and one train/holdout name overlap was
  removed. No seller ID, stable product ID, or market cluster ID is available;
  shard dependence and repeated sellers cannot be ruled out.
- **Collinearity: acceptable for the fitted design.** Rank is 28 of 28,
  condition number 18.98, maximum VIF excluding intercept 2.83 after
  train-only pooling. This does not establish predictor exogeneity.
- **Heteroscedasticity: violated for homoscedastic OLS inference.** The
  Breusch–Pagan LM p-value is 0.00194. Standard OLS standard errors would be
  inappropriate for inference without robust treatment. The model is not
  promoted for prediction regardless.
- **Functional form: limited.** Residuals vs fitted show broad spread and
  distinct fitted-value stripes from categorical predictors. The correlation
  of absolute residual with fitted log price is 0.0303, which alone cannot
  certify correct functional form. Train log-price R² is 0.1963.
- **Normality: imperfect.** The Q–Q plot bends away from the reference line,
  especially in the upper half. Normality is not required for a point
  prediction, but parametric intervals/inference need more care.
- **Influential observations: present.** 63 records exceed Cook's 4/n
  screening threshold; maximum Cook's distance is 0.02635. Examples include
  high-priced bakeware and food storage. They were retained because premium
  products and mismatched quality may be genuine; no arbitrary trimming was
  used. Sparse Fair/Poor conditions were omitted from OLS to avoid a singleton
  with leverage 1.
- **Leakage: controlled for known fields.** Source price is never an input,
  and seller asking price is absent from the benchmark service. All learned
  transformations use training rows. Unknown repeated sellers/products may
  still leak similar examples across time.
- **Exogeneity and transfer: unverified.** Brand, product quality, seller
  selection, shipping, and local demand are incompletely measured. The
  historical US-wide prices may not transfer to today's UIUC market.

**Decision:** The regression is fitted and evaluated, but fails the held-out
accuracy comparison and source-transfer standard. It is not used for live
recommendations. The deterministic comparable service is deployed with LOW
evidence grade for every covered result and abstention for unsupported
matches. Neither method is validated as a completed-sale estimator.
