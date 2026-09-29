"""The welfare blend need model (backend/ml/welfare.py) and its scorecard."""
import numpy as np
import pandas as pd
import pytest

from backend.ml.registry import load, save
from backend.ml.scorecard import FACTOR_OF, factor_points
from backend.ml.welfare import MonotoneRidge, WelfareBlendModel

LINE = 16_000.0


def _toy(n=900, seed=0):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({
        "monthly_income": rng.uniform(3_000, 120_000, n),
        "essential_costs": rng.uniform(20_000, 90_000, n),
        "household_size": rng.integers(1, 9, n),
        "children_under_5": rng.integers(0, 3, n),
        "food_security_score": rng.integers(0, 9, n),
        "shock_job_loss_12m": rng.random(n) < 0.2,
        "asset_tv": rng.random(n) < 0.3,
        "asset_car": rng.random(n) < 0.08,
        "need_category": rng.choice(["food", "medical", "education"], n),
    })
    f["monthly_deficit"] = f["essential_costs"] - f["monthly_income"]
    f["deficit_ratio"] = f["monthly_deficit"] / f["essential_costs"]
    resources = 0.8 * f["monthly_income"] + 4_000 + 6_000 * f["asset_car"] + 2_000 * f["asset_tv"]
    c = resources * np.where(f["shock_job_loss_12m"], 0.8, 1.0) / (1 + 0.7 * (f["household_size"] - 1))
    f["consumption_pc"] = (c * np.exp(rng.normal(0, 0.15, n))).clip(lower=1_500)
    y = (LINE - f["consumption_pc"]).clip(lower=0)
    return f, y


@pytest.fixture(scope="module")
def fitted():
    f, y = _toy()
    return f, y, WelfareBlendModel(params={"n_estimators": 150}).fit(f, y)


def test_recovers_the_poverty_line_and_keeps_estimates_inside_their_range(fitted):
    f, y, m = fitted
    assert m.line == pytest.approx(LINE, rel=1e-6)
    p = m.predict(f)
    assert (p["need_mid"] >= 0).all()
    poor_or_unsure = p["need_hi"] >= 0          # when the whole range is above the line the estimate reads 0
    assert (p["need_lo"] <= p["need_mid"])[poor_or_unsure].all() and (p["need_mid"] <= p["need_hi"])[poor_or_unsure].all()


def test_score_points_add_up_exactly(fitted):
    f, _, m = fitted
    card = m.scorecard(f.iloc[:50])
    z = m.predict_z(f.iloc[:50])["need_mid"].values
    unclipped = (z + np.log(m.score_span[0] * m.line)) * m.points_per_z()
    np.testing.assert_allclose(card["base"] + card["points"].sum(axis=1), unclipped, atol=1e-8)
    assert ((card["score"] >= 0) & (card["score"] <= 100)).all()


def test_score_is_anchored_to_the_poverty_line(fitted):
    _, _, m = fitted
    assert m.score_from_z(-np.log(m.line)) == pytest.approx(50)
    assert m.score_from_z(-np.log(m.line * m.score_span[1])) == pytest.approx(100)
    assert m.score_from_need(m.line * 0.5) > m.score_from_need(0)


@pytest.mark.parametrize("col,change,sign", [
    ("monthly_income", 20_000, -1), ("shock_job_loss_12m", True, +1), ("asset_car", True, -1),
    ("asset_tv", True, -1), ("household_size", 2, +1), ("children_under_5", 1, +1),
])
def test_more_hardship_never_lowers_the_score(fitted, col, change, sign):
    f, _, m = fitted
    nudged = f.copy()
    nudged[col] = True if isinstance(change, bool) else nudged[col] + change
    nudged["monthly_deficit"] = nudged["essential_costs"] - nudged["monthly_income"]
    nudged["deficit_ratio"] = nudged["monthly_deficit"] / nudged["essential_costs"]
    before = m.predict_z(f)["need_mid"].values
    after = m.predict_z(nudged)["need_mid"].values
    assert (sign * (after - before) >= -1e-9).all()


def test_round_trips_through_its_artifact(tmp_path, fitted):
    f, _, m = fitted
    m.conformal = -150.0
    save(m, "welfare-test", {"target": "poverty_gap"}, {"gates": {"passed": True}}, models_dir=tmp_path)
    loaded = load("welfare_blend", tmp_path / "welfare-test")
    pd.testing.assert_frame_equal(m.predict(f), loaded.predict(f))
    np.testing.assert_allclose(m.scorecard(f.iloc[:5])["points"], loaded.scorecard(f.iloc[:5])["points"])
    assert loaded.gbm.conformal == 0.0 and loaded.conformal == -150.0
    m.conformal = 0.0


def test_monotone_ridge_keeps_the_signs_it_is_given():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(300, 3))
    y = -2.0 * X[:, 0] + 1.0 * X[:, 1] + rng.normal(0, 0.1, 300)   # truth: feature 0 lowers y
    free = MonotoneRidge(alpha=1.0).fit(X, y)
    bound = MonotoneRidge(alpha=1.0, signs=[+1, 0, -1]).fit(X, y)
    assert free.coef_[0] < 0
    assert bound.coef_[0] >= 0 and bound.coef_[2] <= 0
    assert bound.coef_[1] == pytest.approx(free.coef_[1], abs=0.2)


def test_every_feature_has_a_factor_and_factors_sum_their_points():
    names = ["monthly_income", "shock_job_loss_12m", "shock_count_12m", "asset_car", "household_size"]
    assert all(n in FACTOR_OF for n in names)
    factors = factor_points(names, np.array([3.0, 1.0, 2.0, -4.0, 0.5]))
    by = {f["factor"]: f["points"] for f in factors}
    assert by == {"income": 3.0, "shocks": 3.0, "assets": -4.0, "household": 0.5}
    assert abs(factors[0]["points"]) >= abs(factors[-1]["points"])   # biggest effect first
