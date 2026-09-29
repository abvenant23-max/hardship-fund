"""The need score as a scorecard: the model's per-feature points (exact, see
welfare.WelfareBlendModel.scorecard) summed into a handful of factors a
caseworker recognises. Points are relative to the average applicant the
model was trained on, so a factor at +12 made this household look 12 points
needier than average, and base + the factors' points = the score (before it
is clipped to 0-100).
"""
from __future__ import annotations

import numpy as np

# (key, label, features). Every model feature belongs to exactly one factor;
# anything not listed falls into "other".
FACTORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("income", "Income and costs", (
        "monthly_income", "essential_costs", "monthly_deficit", "deficit_ratio", "income_std_12m",
        "income_seasonality", "income_volatility", "employment_type", "earners_count", "hours_worked")),
    ("household", "Household and dependants", (
        "household_size", "children_under_5", "members_over_65", "dependency_ratio", "female_headed",
        "single_caregiver", "dependents_requiring_care", "education_head", "literacy_head", "crowding", "rooms")),
    ("health", "Illness and disability", ("chronic_illness", "disability_in_household")),
    ("shocks", "Shocks this year", (
        "shock_bereavement_12m", "shock_serious_illness_12m", "shock_job_loss_12m", "shock_eviction_12m",
        "shock_displacement_12m", "shock_disaster_12m", "shock_crop_failure_12m", "shock_count_12m",
        "days_since_hardship_onset")),
    ("food", "Food insecurity", ("food_security_score",)),
    ("assets", "Assets, land and housing", (
        "asset_phone", "asset_radio", "asset_tv", "asset_fridge", "asset_washing_machine", "asset_bicycle",
        "asset_motorcycle", "asset_car", "asset_index", "livestock_count", "land_area", "roof_material",
        "wall_material", "floor_material", "tenure", "water_source", "sanitation_type", "electricity",
        "cooking_fuel")),
    ("district", "District", (
        "area_deprivation_index", "area_poverty_rate", "distance_to_services_km", "local_unemployment_rate",
        "local_housing_cost_index")),
    ("application", "The application", (
        "amount_requested", "stated_need_amount", "request_closes_gap", "need_category",
        "prior_applications_count", "days_since_last_application", "referral_source", "application_channel",
        "application_completeness", "documentation_provided")),
]
FACTOR_OF = {f: key for key, _, feats in FACTORS for f in feats}
LABEL = {key: label for key, label, _ in FACTORS} | {"other": "Other"}


def factor_points(features: list[str], points: np.ndarray, top: int = 3) -> list[dict]:
    """One row's per-feature points -> factors, biggest effect first, each
    with its largest contributing features."""
    by: dict[str, list[tuple[str, float]]] = {}
    for name, p in zip(features, points):
        by.setdefault(FACTOR_OF.get(name, "other"), []).append((name, float(p)))
    out = []
    for key, items in by.items():
        items.sort(key=lambda kv: -abs(kv[1]))
        out.append({"factor": key, "label": LABEL[key], "points": round(sum(p for _, p in items), 2),
                    "drivers": [{"feature": n, "points": round(p, 2)} for n, p in items[:top] if abs(p) >= 0.05]})
    return sorted(out, key=lambda f: -abs(f["points"]))
