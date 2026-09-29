"""Welfare blend: the need model that learns consumption, not the poverty gap.

Why not learn poverty_gap directly (as LGBMNeedModel does)? The gap is
max(0, line - consumption), so it is exactly 0 for every household above the
line: half the training signal says nothing about how far above the line a
household is. Learning z = -log(consumption_pc) keeps that information
(higher z = needier, so the same monotone directions apply), and the
prediction is turned back into the poverty gap in RWF for allocation.

Two models learn z and are averaged in z:
  - a small monotone LightGBM (more hardship can never lower need: see
    EXTRA_MONOTONE on top of model.MONOTONE_CONSTRAINTS);
  - a ridge regression on the same features (the proxy-means test).
On the realistic synthetic data (30% trees, 70% ridge) this blend ranked
the poor at 0.79 (Spearman, out of fold by district) against 0.77 for ridge
and 0.72 for the poverty-gap LightGBM, deferred fewer of the poorest decile
than either, and funded fewer non-poor households. The ceiling, with outcomes
for every household, was about 0.80.

Because both parts are additive in z (TreeSHAP for the trees, coefficient x
value for ridge), every prediction splits exactly into per-feature
contributions. That gives the need score: 0-100 on a fixed log scale
anchored to the poverty line (50 = at the line, 100 = a quarter of the line
or less, 0 = four times the line or more), with each factor's points adding
up to it. A narrower span saturated: many applicants live on a third of the
line, so decisions fell where every score read 100.
"""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .baselines import RidgePMTModel
from .model import (INTERVAL, MONOTONE_CONSTRAINTS, MONOTONE_PREFIXES, PRED_COLUMNS, LGBMNeedModel,
                    _top_contributions, welfare_weights)

SMALL_PARAMS = dict(num_leaves=7, min_child_samples=30, n_estimators=500, learning_rate=0.03,
                    colsample_bytree=0.7, reg_lambda=5.0)
BLEND_WEIGHT = 0.3              # share of the LightGBM part; the rest is ridge (0.3 beat 0.2, 0.5 and 0.7)
SCORE_SPAN = (4.0, 0.25)        # consumption (x poverty line) at score 0 and at score 100

# Directions added to model.MONOTONE_CONSTRAINTS for the tree part: bigger
# households, more dependants and illness or disability can only raise need;
# assets, livestock, land and earners can only lower it.
EXTRA_MONOTONE = {"household_size": 1, "children_under_5": 1, "members_over_65": 1, "dependency_ratio": 1,
                  "disability_in_household": 1, "chronic_illness": 1, "asset_index": -1,
                  "livestock_count": -1, "land_area": -1, "earners_count": -1}
EXTRA_MONOTONE_PREFIXES = {"asset_": -1}


def direction(col: str) -> int:
    """+1 if more of `col` can only raise need, -1 if only lower it, else 0."""
    if col in MONOTONE_CONSTRAINTS:
        return MONOTONE_CONSTRAINTS[col]
    if col in EXTRA_MONOTONE:
        return EXTRA_MONOTONE[col]
    prefixes = {**MONOTONE_PREFIXES, **EXTRA_MONOTONE_PREFIXES}
    return next((d for p, d in prefixes.items() if col.startswith(p)), 0)


class _MonotoneLGBM(LGBMNeedModel):
    def constraints(self) -> list[int]:
        return [direction(c) for c in self.feature_names]


class MonotoneRidge(BaseEstimator, RegressorMixin):
    """Ridge regression whose coefficients keep the sign in `signs`
    (+1: >= 0, -1: <= 0, 0: free), solved as bounded least squares on the
    ridge-augmented system. The intercept is free and not penalised."""

    def __init__(self, alpha: float = 1.0, signs=None):
        self.alpha = alpha
        self.signs = signs

    def fit(self, X, y, sample_weight=None):
        X = np.asarray(X.toarray() if hasattr(X, "toarray") else X, dtype=float)
        y = np.asarray(y, dtype=float)
        n, p = X.shape
        w = np.sqrt(np.ones(n) if sample_weight is None else np.asarray(sample_weight, dtype=float))
        A = np.vstack([np.hstack([X * w[:, None], w[:, None]]),
                       np.hstack([math.sqrt(self.alpha) * np.eye(p), np.zeros((p, 1))])])
        b = np.concatenate([y * w, np.zeros(p)])
        signs = np.zeros(p) if self.signs is None else np.asarray(self.signs)
        lower = np.where(signs > 0, 0.0, -np.inf)
        upper = np.where(signs < 0, 0.0, np.inf)
        sol = lsq_linear(A, b, bounds=(np.append(lower, -np.inf), np.append(upper, np.inf)))
        self.coef_, self.intercept_ = sol.x[:p], float(sol.x[p])
        return self

    def predict(self, X):
        X = X.toarray() if hasattr(X, "toarray") else X
        return np.asarray(X, dtype=float) @ self.coef_ + self.intercept_


class _MonotoneRidgePMT(RidgePMTModel):
    """The blend's linear half: the proxy-means test with the tree half's
    direction rules, so neither half can make more hardship lower need.
    Yes/no answers enter as 0/1 (not as categories) so they can be bound."""

    @staticmethod
    def _X(features: pd.DataFrame) -> pd.DataFrame:
        X = RidgePMTModel._X(features)
        for c in X.columns:
            if X[c].dtype == object and set(X[c].dropna().unique()) <= {"True", "False", "nan"}:
                X[c] = X[c].map({"True": 1.0, "False": 0.0})
        return X

    def fit(self, features: pd.DataFrame, y) -> "_MonotoneRidgePMT":
        X = self._X(features)
        y = np.asarray(y, dtype=float)
        num = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]
        cat = [c for c in X.columns if c not in num]
        prep = ColumnTransformer([
            ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), num),
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat),
        ])
        Z = prep.fit_transform(X)
        signs = [direction(n.partition("__")[2]) if n.startswith("num__") else 0 for n in prep.get_feature_names_out()]
        ridge = MonotoneRidge(self.alpha, signs).fit(Z, y, sample_weight=welfare_weights(y))
        self.pipeline = Pipeline([("prep", prep), ("ridge", ridge)])
        resid = y - self.pipeline.predict(X)
        self.resid_q = tuple(np.quantile(resid, INTERVAL))
        return self


class WelfareBlendModel:
    kind = "welfare_blend"
    in_target_units = True

    def __init__(self, params: dict | None = None, weight: float = BLEND_WEIGHT):
        self.gbm = _MonotoneLGBM({**SMALL_PARAMS, **(params or {})})
        self.ridge = _MonotoneRidgePMT()
        self.weight = weight
        self.line = float("nan")
        self.conformal = 0.0
        self.base_z = 0.0
        self.contrib_mean = np.zeros(0)
        self.score_span = SCORE_SPAN

    # ModelInputs and feature names are the tree part's (drift reports use them)
    @property
    def inputs(self):
        return self.gbm.inputs

    @property
    def feature_names(self) -> list[str]:
        return self.gbm.feature_names

    def fit(self, features: pd.DataFrame, y) -> "WelfareBlendModel":
        if "consumption_pc" not in features:
            raise ValueError("WelfareBlendModel learns consumption_pc; the training rows must include it")
        c = features["consumption_pc"].astype(float).clip(lower=1.0).values
        y = np.asarray(y, dtype=float)
        poor = y > 0
        # poverty_gap = line - consumption wherever it is positive, so the line is recoverable exactly
        self.line = float(np.median((y + c)[poor])) if poor.any() else float(np.median(c))
        z = -np.log(c)
        self.gbm.fit(features, z)
        self.ridge.fit(features, z)
        raw, base = self._raw_contributions(features)
        self.contrib_mean = raw.mean(axis=0)
        self.base_z = float(base + self.contrib_mean.sum())
        return self

    # --- predictions -----------------------------------------------------
    def predict_z(self, features: pd.DataFrame) -> pd.DataFrame:
        g, r = self.gbm.predict(features), self.ridge.predict(features)
        return self.weight * g[PRED_COLUMNS] + (1 - self.weight) * r[PRED_COLUMNS]

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        z = self.predict_z(features)
        need = self.line - np.exp(-z)
        # A negative value means "above the poverty line" (screens show it as
        # that). The estimate is a gap, so it is clipped at 0. The range is
        # not: a bound clipped at 0 would "cover" every non-poor household (true
        # gap exactly 0) at any width, and the conformal step could not
        # calibrate it. The three parts are separate models, so the range is
        # kept around the unclipped estimate: lo <= raw estimate <= hi (when
        # hi < 0 the whole range is above the line and the estimate reads 0).
        raw = need["need_mid"]
        lo = np.minimum(need["need_lo"] - self.conformal, raw)
        hi = np.maximum(need["need_hi"] + self.conformal, raw)
        return pd.DataFrame({"need_lo": lo, "need_mid": raw.clip(lower=0.0), "need_hi": hi}, index=features.index)

    # --- the need score ---------------------------------------------------
    @property
    def _score_z(self) -> tuple[float, float]:
        return -math.log(self.score_span[0] * self.line), -math.log(self.score_span[1] * self.line)

    def points_per_z(self) -> float:
        z0, z100 = self._score_z
        return 100.0 / (z100 - z0)

    def score_from_z(self, z) -> np.ndarray:
        z0, _ = self._score_z
        return np.clip((np.asarray(z, dtype=float) - z0) * self.points_per_z(), 0.0, 100.0)

    def score_from_need(self, need) -> np.ndarray:
        """Need score of a poverty gap in RWF (e.g. a cycle's cutoff)."""
        c = np.maximum(self.line - np.asarray(need, dtype=float), 1.0)
        return self.score_from_z(-np.log(c))

    def scorecard(self, features: pd.DataFrame) -> dict:
        """score (0-100, per row), base points (the average training
        applicant) and points per feature (rows x features), where
        base + sum(points) = score before clipping to 0-100."""
        z = self.predict_z(features)["need_mid"].values
        k = self.points_per_z()
        z0, _ = self._score_z
        return {"score": self.score_from_z(z), "base": (self.base_z - z0) * k,
                "points": self.contributions(features) * k, "features": self.feature_names}

    # --- explanations -------------------------------------------------------
    def _raw_contributions(self, features: pd.DataFrame) -> tuple[np.ndarray, float]:
        """Per-feature contributions to z_mid (uncentred) and the constant."""
        g = self.gbm.boosters["mid"].predict(self.gbm.inputs.transform(features), pred_contrib=True)
        prep, ridge = self.ridge.pipeline.named_steps["prep"], self.ridge.pipeline.named_steps["ridge"]
        Z = prep.transform(self.ridge._X(features))
        Z = Z.toarray() if hasattr(Z, "toarray") else np.asarray(Z)
        r = np.zeros((len(features), len(self.feature_names)))
        index = {name: i for i, name in enumerate(self.feature_names)}
        for j, name in enumerate(prep.get_feature_names_out()):
            i = index.get(_base_feature(name, index))
            if i is not None:
                r[:, i] += Z[:, j] * ridge.coef_[j]
        raw = self.weight * g[:, :-1] + (1 - self.weight) * r
        base = self.weight * float(g[0, -1]) + (1 - self.weight) * float(ridge.intercept_)
        return raw, base

    def contributions(self, features: pd.DataFrame) -> np.ndarray:
        """Contributions to z_mid relative to the average training applicant."""
        raw, _ = self._raw_contributions(features)
        return raw - self.contrib_mean

    def explain(self, features: pd.DataFrame, top_n: int = 5) -> list[list[tuple[str, float]]]:
        """Top drivers per row, in need-score points."""
        return _top_contributions(self.contributions(features) * self.points_per_z(), self.feature_names, top_n)

    # --- persistence --------------------------------------------------------
    def save(self, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        gbm_meta = self.gbm.save(directory / "gbm")
        joblib.dump(self.ridge.pipeline, directory / "ridge.joblib")
        return {"kind": self.kind, "weight": self.weight, "line": self.line, "conformal": self.conformal,
                "base_z": self.base_z, "contrib_mean": self.contrib_mean.tolist(),
                "ridge_resid_q": list(self.ridge.resid_q), "score_span": list(self.score_span),
                "params": gbm_meta["params"], "monotone_constraints": gbm_meta["monotone_constraints"],
                "feature_names": gbm_meta["feature_names"], "categories": gbm_meta["categories"],
                "asset_index": gbm_meta["asset_index"]}

    @classmethod
    def load(cls, directory: Path, metadata: dict) -> "WelfareBlendModel":
        m = cls(weight=float(metadata["weight"]))
        m.gbm = _MonotoneLGBM.load(directory / "gbm", metadata)
        m.gbm.conformal = 0.0          # the blend's widening is in RWF, applied in predict()
        m.ridge.pipeline = joblib.load(directory / "ridge.joblib")
        m.ridge.resid_q = tuple(metadata["ridge_resid_q"])
        m.line = float(metadata["line"])
        m.conformal = float(metadata.get("conformal", 0.0))
        m.base_z = float(metadata["base_z"])
        m.contrib_mean = np.asarray(metadata["contrib_mean"], dtype=float)
        m.score_span = tuple(metadata.get("score_span", SCORE_SPAN))
        return m


def _base_feature(transformed: str, known: dict) -> str | None:
    """Map a ridge column name ('num__monthly_income', 'cat__tenure_owned')
    back to the model feature it came from."""
    kind, _, rest = transformed.partition("__")
    if kind == "num":
        return rest
    matches = [f for f in known if rest.startswith(f + "_")]
    return max(matches, key=len) if matches else None
