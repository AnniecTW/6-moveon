"""Reproduce Phase 1 cleaning, comparable evaluation, and hedonic diagnostics.

Run from the repository root: python experiments/merrec-pricing/analysis/run_phase1.py
No learned statistic is fit on the chronological holdout before evaluation.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm
from sklearn.metrics import mean_absolute_error, median_absolute_error
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from marketplace.pricing.initial import load_source, recommend  # noqa: E402

VALIDATION = ROOT / "docs/pricing/validation"
DERIVED = ROOT / "experiments/merrec-pricing/data/pricing_clean_v1.csv"
SEED = 42


def metrics(actual, predicted):
    return {
        "n": len(actual),
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "median_absolute_error": round(float(median_absolute_error(actual, predicted)), 4),
        "signed_bias": round(float(np.mean(np.asarray(predicted) - np.asarray(actual))), 4),
    }


def frame(records):
    return pd.DataFrame([{
        "item_id": r.item_id, "observed_at": r.observed_at.isoformat(),
        "price": float(r.price), "category": r.category, "item_type": r.item_type,
        "condition": r.condition, "brand": r.brand, "name": r.name,
        "source_shard": r.source_shard,
    } for r in records])


def encode(train, test):
    """Pool sparse levels using training counts, then one-hot encode with a base level."""
    train = train.copy()
    test = test.copy()
    for field, minimum in (("item_type", 15), ("brand", 20)):
        counts = train[field].value_counts()
        known = set(counts[counts >= minimum].index) - {""}
        train[field] = train[field].map(lambda x: x if x in known else "OTHER")
        test[field] = test[field].map(lambda x: x if x in known else "OTHER")
    # Category is omitted: it is determined by item type for most records,
    # which would create redundant dummy variables in an OLS design.
    fields = ["item_type", "condition", "brand"]
    train_x = pd.get_dummies(train[fields], drop_first=True, dtype=float)
    test_x = pd.get_dummies(test[fields], drop_first=True, dtype=float)
    test_x = test_x.reindex(columns=train_x.columns, fill_value=0.0)
    return sm.add_constant(train_x, has_constant="add"), sm.add_constant(test_x, has_constant="add"), train


def main():
    VALIDATION.mkdir(parents=True, exist_ok=True)
    records, profile = load_source()
    data = frame(records)
    # Titles are needed in memory for duplicate-name leakage checks, but are
    # unnecessary in the persisted derived pricing table.
    data.drop(columns=["name"]).to_csv(DERIVED, index=False, quoting=csv.QUOTE_MINIMAL)
    raw = pd.read_csv(ROOT / "experiments/merrec-pricing/data/stable_pricing_items_v1.csv")
    profile.update({
        "date_min": data.observed_at.min(), "date_max": data.observed_at.max(),
        "unique_names": int(raw.name.nunique()),
        "duplicate_full_rows": int(raw.duplicated().sum()),
        "unique_shards": int(raw.source_shard.nunique()),
        "category_counts": raw.moveon_category.value_counts().to_dict(),
        "condition_counts": raw.item_condition_name.value_counts().to_dict(),
        "type_counts": raw.moveon_item_type.value_counts().to_dict(),
        "missing_by_column": {column: int(raw[column].isna().sum()) for column in raw},
        "human_verified_counts": raw.human_verified.value_counts().to_dict(),
        "risk_flags": raw.price_risk_flags.dropna().value_counts().to_dict(),
        "shipping_counts": raw.shipper_name.value_counts().to_dict(),
        "min_price": float(raw.price.min()), "max_price": float(raw.price.max()),
        "duplicate_price_column_matches": int((raw.price == raw.observed_price_at_buy_comp).sum()),
        "same_name_multiple_rows": int((raw.name.value_counts() > 1).sum()),
    })
    (VALIDATION / "data_profile.json").write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")

    cut = int(len(records) * 0.8)
    chronological_training, heldout = records[:cut], records[cut:]
    holdout_names = {r.name for r in heldout if r.name}
    training = [r for r in chronological_training if r.name not in holdout_names]
    excluded_matching_names = len(chronological_training) - len(training)
    train_frame, hold_frame = frame(training), frame(heldout)
    baseline = [recommend(training, category=r.category, item_type=r.item_type,
                          condition=r.condition, brand=r.brand) for r in heldout]
    # Simulate the listing form before the seller chooses a condition.
    type_only = [recommend(training, category=r.category, item_type=r.item_type,
                           condition="") for r in heldout]
    type_only_supported = np.array([item["benchmark_price"] is not None for item in type_only])
    type_only_sparse = np.array([item["evidence_grade"] == "VERY_LOW" for item in type_only])
    type_only_actual = hold_frame.price.to_numpy()[type_only_supported]
    type_only_predicted = np.array([
        float(item["benchmark_price"]) for item, covered in zip(type_only, type_only_supported)
        if covered
    ])
    supported = np.array([result["benchmark_price"] is not None for result in baseline])
    baseline_sparse = np.array([result["evidence_grade"] == "VERY_LOW" for result in baseline])
    base_price = np.array([float(result["benchmark_price"]) if result["benchmark_price"] is not None
                           else np.nan for result in baseline])
    # Fair/Poor have 9/1 records overall; the singleton creates leverage 1.
    # Model only conditions with meaningful training support. The comparable
    # baseline retains explicit abstention for unsupported conditions.
    model_train = train_frame[train_frame.condition.isin(["NEW", "LIKE_NEW", "GOOD"])].copy()
    train_x, test_x, pooled = encode(model_train, hold_frame)
    y_train = np.log(model_train.price.to_numpy())
    ols = sm.OLS(y_train, train_x.to_numpy()).fit()
    smearing = float(np.mean(np.exp(ols.resid)))
    regression_price = np.exp(ols.predict(test_x.to_numpy())) * smearing
    same_actual = hold_frame.price.to_numpy()[supported]
    same_baseline = base_price[supported]
    same_regression = regression_price[supported]
    comparable_metrics = metrics(same_actual, same_baseline) if supported.any() else None
    regression_metrics = metrics(same_actual, same_regression) if supported.any() else None
    by_category = {}
    for category in sorted(hold_frame.category.unique()):
        mask = (hold_frame.category.to_numpy() == category) & supported
        by_category[category] = {
            "holdout_n": int((hold_frame.category == category).sum()),
            "covered_n": int(mask.sum()),
            "baseline": metrics(hold_frame.price.to_numpy()[mask], base_price[mask]) if mask.any() else None,
            "regression": metrics(hold_frame.price.to_numpy()[mask], regression_price[mask]) if mask.any() else None,
        }
    by_condition = {}
    for condition in sorted(hold_frame.condition.unique()):
        mask = (hold_frame.condition.to_numpy() == condition) & supported
        by_condition[condition] = {
            "holdout_n": int((hold_frame.condition == condition).sum()),
            "covered_n": int(mask.sum()),
            "baseline": metrics(hold_frame.price.to_numpy()[mask], base_price[mask]) if mask.any() else None,
            "regression": metrics(hold_frame.price.to_numpy()[mask], regression_price[mask]) if mask.any() else None,
        }
    matrix = train_x.to_numpy()
    influence = ols.get_influence()
    cooks = influence.cooks_distance[0]
    bp = het_breuschpagan(ols.resid, matrix)
    vif = {name: round(float(variance_inflation_factor(matrix, index)), 4)
           for index, name in enumerate(train_x.columns) if index > 0}
    residual_correlation = float(np.corrcoef(ols.fittedvalues, np.abs(ols.resid))[0, 1])
    # A deployment gate is intentionally strict: one split from an old,
    # nonlocal, unverified-price sample is insufficient for promotion.
    regression_improves_mae = bool(
        comparable_metrics and regression_metrics and
        regression_metrics["mae"] < comparable_metrics["mae"] * 0.95
    )
    finite_cooks = cooks[np.isfinite(cooks)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].scatter(ols.fittedvalues, ols.resid, s=9, alpha=0.35)
    axes[0].axhline(0, color="black", linewidth=1)
    axes[0].set(xlabel="Fitted log price", ylabel="Log-price residual",
                title="Training residuals vs fitted")
    sm.qqplot(ols.resid, line="45", ax=axes[1], markerfacecolor="tab:blue",
              markeredgecolor="tab:blue", alpha=0.35)
    axes[1].set_title("Training residual Q–Q")
    fig.tight_layout()
    fig.savefig(VALIDATION / "regression_diagnostics.png", dpi=140)
    plt.close(fig)

    influential = np.argsort(cooks)[-5:][::-1]
    top_influential = [
        {"item_id": model_train.iloc[int(index)].item_id,
         "price": float(model_train.iloc[int(index)].price),
         "item_type": model_train.iloc[int(index)].item_type,
         "cook_distance": round(float(cooks[index]), 6)}
        for index in influential
    ]
    result = {
        "source_sha256": profile["sha256"], "seed": SEED,
        "split": "chronological 80/20 by stime, then item_id",
        "train_n": len(training), "model_train_n": len(model_train), "holdout_n": len(heldout),
        "matching_name_train_rows_removed": excluded_matching_names,
        "cutoff_first_holdout": heldout[0].observed_at.isoformat(),
        "overlap_item_ids": len({r.item_id for r in training} & {r.item_id for r in heldout}),
        "median_coverage_n": int(supported.sum()),
        "median_abstention_n": int((~supported).sum()),
        "median_coverage_fraction": round(float(supported.mean()), 4),
        "baseline_method_counts": dict(Counter(result["method"] for result in baseline)),
        "baseline_same_rows": comparable_metrics,
        "baseline_sparse_references": {
            "n": int(baseline_sparse.sum()),
            "metrics": metrics(hold_frame.price.to_numpy()[baseline_sparse],
                               base_price[baseline_sparse]) if baseline_sparse.any() else None,
        },
        "type_only_before_condition": {
            "covered_n": int(type_only_supported.sum()),
            "abstained_n": int((~type_only_supported).sum()),
            "metrics_on_covered": metrics(type_only_actual, type_only_predicted)
            if type_only_supported.any() else None,
            "sparse_reference_n": int(type_only_sparse.sum()),
            "policy": "same category and item type; 10 records for standard guide, 1-9 for warned sparse reference",
        },
        "regression_same_rows": regression_metrics,
        "category_errors": by_category, "condition_errors": by_condition,
        "model": {
            "specification": "OLS log(price) ~ pooled item type + condition + pooled brand; Duan smearing",
            "n_parameters": int(matrix.shape[1]), "design_rank": int(np.linalg.matrix_rank(matrix)),
            "condition_number": round(float(np.linalg.cond(matrix)), 4),
            "max_vif_excluding_intercept": round(max(vif.values()), 4),
            "high_vif_terms": {k: v for k, v in vif.items() if v > 10},
            "breusch_pagan_lm_p": float(bp[1]), "breusch_pagan_f_p": float(bp[3]),
            "absolute_residual_fitted_correlation": round(residual_correlation, 4),
            "cook_threshold": round(4 / len(model_train), 6),
            "cooks_above_4_over_n": int((cooks > 4 / len(model_train)).sum()),
            "max_cooks_distance": round(float(finite_cooks.max()), 6) if len(finite_cooks) else None,
            "nonfinite_cooks_distance": int((~np.isfinite(cooks)).sum()),
            "top_influential": top_influential,
            "shapiro_not_used": "Large-sample residual normality is not a point-prediction gate",
            "smearing_factor": round(smearing, 6),
            "r_squared_log_train": round(float(ols.rsquared), 4),
        },
        "regression_improves_mae_by_5_percent": regression_improves_mae,
        "production_method": "COMPARABLE_MEDIAN",
        "production_regression_gate": "NOT_PROMOTED: historical nonlocal unverified price source and no external validation",
    }
    (VALIDATION / "phase1_evaluation.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
