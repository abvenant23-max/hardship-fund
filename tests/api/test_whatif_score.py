"""'Try the model' with the welfare blend: the need score, its cut-off and
the points per factor, end to end through the API, and that each input
moves the score the way a caseworker would expect."""
import numpy as np
import pytest

from backend.ml import db, registry
from backend.ml.__main__ import TARGET, load_dataset, main as ml_main
from backend.ml.welfare import WelfareBlendModel

BASE = {"area_code": "AR017", "need_category": "food", "amount_requested": 30000, "household_size": 7,
        "children_under_5": 2, "members_over_65": 1, "monthly_income": 12000, "essential_costs": 95000,
        "food_security_score": 7, "employment_type": "informal", "shocks": ["job_loss"], "assets": ["phone"],
        "female_headed": True}


@pytest.fixture(scope="module")
def welfare_active(client, auth, test_dsn, tmp_path_factory):
    ds = load_dataset(test_dsn)
    full, lab = ds["full"], ds["labelled"]
    model = WelfareBlendModel(params={"n_estimators": 120}).fit(full[lab], full.loc[lab, TARGET].values)
    path = registry.save(model, "welfare-api-test", {"target": TARGET}, {"gates": {"passed": True}},
                         models_dir=tmp_path_factory.mktemp("models"))
    db.register_model_version(test_dsn, "welfare-api-test", model.kind, str(path), int(lab.sum()), None,
                              {"gates": {"passed": True}})
    assert client.post("/models/welfare-api-test/activate", headers=auth, json={}).status_code == 200
    ml_main(["--dsn", test_dsn, "score", "--cycle", "24"])       # gives the latest cycle a cutoff
    yield
    client.post("/models/rules-v0/activate", headers=auth, json={})


def score(client, auth, **changes):
    r = client.post("/models/what-if", headers=auth, json={**BASE, **changes})
    assert r.status_code == 200, r.text
    return r.json()


def test_score_cutoff_and_factors(client, auth, welfare_active):
    d = score(client, auth)
    s = d["score"]
    assert 0 <= s["score"] <= 100
    assert s["low"] - 1e-6 <= s["score"] <= s["high"] + 1e-6      # the score sits inside its likely range
    assert d["context"]["cutoff_score"] is not None and d["context"]["likely_band"] in {"auto_approve", "human_review", "defer"}
    total = s["base"] + sum(f["points"] for f in s["factors"])
    assert s["score"] == pytest.approx(float(np.clip(total, 0, 100)), abs=0.05)
    assert {f["factor"] for f in s["factors"]} >= {"income", "shocks", "assets", "household"}


@pytest.mark.parametrize("changes,direction", [
    ({"monthly_income": 60000}, -1),
    ({"shocks": []}, -1),
    ({"shocks": ["job_loss", "serious_illness", "disaster"]}, +1),
    ({"assets": ["phone", "car", "fridge", "tv"]}, -1),
    ({"disability_in_household": True}, +1),
    ({"food_security_score": 1}, -1),
    ({"livestock_count": 6, "land_area": 1.5}, -1),
])
def test_inputs_move_the_score_the_expected_way(client, auth, welfare_active, changes, direction):
    base = score(client, auth, monthly_income=40000)["score"]["score"]   # mid-range, away from the 0/100 caps
    moved = score(client, auth, **{"monthly_income": 40000, **changes})["score"]["score"]
    assert direction * (moved - base) >= 0, (changes, base, moved)
