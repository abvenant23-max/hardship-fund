// "Try the model": describe an imagined household and watch its need score,
// the decision it would get in the latest cycle, and how the score adds up.
// Re-scores as you type; nothing is saved.

import { useEffect, useRef, useState } from "react";
import { useApi, useApiMutation } from "../../api/hooks";
import type { Area, ModelVersion, WhatIfResult } from "../../api/types";
import { DriverBars, RangeChart } from "../../components/charts";
import { Button, Card, Check, ErrorBox, Field, Input, Pill, Select } from "../../components/ui";
import { BAND, featureLabel, monthLabel, need, NEED_LABEL, pct } from "../../lib/format";

const SHOCKS = ["bereavement", "serious_illness", "job_loss", "eviction", "displacement", "disaster", "crop_failure"];
const ASSETS = ["phone", "radio", "tv", "fridge", "washing_machine", "bicycle", "motorcycle", "car"];
const label = (s: string) => (s === "bereavement" ? "Death in the family" : s === "tv" ? "TV" : s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()));

type Form = {
  version: string; area_code: string; need_category: string; amount_requested: number; household_size: number; children_under_5: number;
  members_over_65: number; monthly_income: number; essential_costs: number; food_security_score: number; employment_type: string;
  shocks: string[]; assets: string[]; prior_applications_count: number; female_headed: boolean; disability_in_household: boolean; chronic_illness: boolean;
  // "More details": "" = the district's typical value
  livestock_count: string; land_area: string; earners_count: string; rooms: string; electricity: string; floor_material: string;
};

const TYPICAL = { livestock_count: "", land_area: "", earners_count: "", rooms: "", electricity: "", floor_material: "" };
const PRESETS: Record<string, Partial<Form>> = {
  "Struggling family": { area_code: "AR017", need_category: "food", amount_requested: 30000, household_size: 7, children_under_5: 2, members_over_65: 1,
    monthly_income: 12000, essential_costs: 95000, food_security_score: 7, employment_type: "informal", shocks: ["job_loss", "serious_illness"], assets: ["phone"],
    female_headed: true, disability_in_household: false, chronic_illness: false, ...TYPICAL },
  "Recent shock": { area_code: "AR002", need_category: "funeral", amount_requested: 45000, household_size: 4, children_under_5: 1, members_over_65: 0,
    monthly_income: 45000, essential_costs: 80000, food_security_score: 4, employment_type: "self_employed", shocks: ["bereavement"], assets: ["phone", "radio", "bicycle"],
    female_headed: false, disability_in_household: false, chronic_illness: false, ...TYPICAL },
  "Stable household": { area_code: "AR001", need_category: "utilities", amount_requested: 20000, household_size: 3, children_under_5: 0, members_over_65: 0,
    monthly_income: 220000, essential_costs: 70000, food_security_score: 1, employment_type: "formal", shocks: [], assets: ["phone", "tv", "fridge", "motorcycle"],
    female_headed: false, disability_in_household: false, chronic_illness: false, ...TYPICAL, electricity: "yes", floor_material: "tile" },
};

function body(f: Form): Record<string, unknown> {
  const opt = (v: string) => (v === "" ? null : Number(v));
  const { version, livestock_count, land_area, earners_count, rooms, electricity, floor_material, ...rest } = f;
  return {
    ...rest, version: version || null, livestock_count: opt(livestock_count), land_area: opt(land_area), earners_count: opt(earners_count),
    rooms: opt(rooms), electricity: electricity === "" ? null : electricity === "yes", floor_material: floor_material || null,
  };
}

export default function WhatIf() {
  const areas = useApi<Area[]>("/areas").data;
  const versions = useApi<ModelVersion[]>("/models").data;
  const [f, setF] = useState<Form>(() => ({ ...(PRESETS["Struggling family"] as Form), version: "", prior_applications_count: 0 }));
  const run = useApiMutation<Record<string, unknown>, WhatIfResult>("POST", () => "/models/what-if");
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [delta, setDelta] = useState<{ points: number; what: string } | null>(null);
  const lastChange = useRef("");
  const set = <K extends keyof Form>(k: K, v: Form[K], what?: string) => { lastChange.current = what ?? String(k); setF((p) => ({ ...p, [k]: v })); };
  const toggle = (k: "shocks" | "assets", v: string) => set(k, f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v], label(v));

  // Re-score shortly after the last change.
  const payload = JSON.stringify(body(f));
  useEffect(() => {
    if (!f.area_code) return;
    const t = setTimeout(() => run.mutate(JSON.parse(payload), {
      onSuccess: (r) => {
        setResult((prev) => {
          const was = prev?.score?.score, now = r.score?.score;
          setDelta(was !== undefined && now !== undefined && lastChange.current && Math.abs(now - was) >= 0.05
            ? { points: now - was, what: lastChange.current } : null);
          return r;
        });
      },
    }), 350);
    return () => clearTimeout(t);
  }, [payload]); // eslint-disable-line react-hooks/exhaustive-deps

  const num = (k: keyof Form, text: string, step = 1) => (
    <Field label={text}><Input type="number" min={0} step={step} value={String(f[k])} onChange={(e) => set(k, Number(e.target.value) as never, text)} /></Field>
  );
  const optNum = (k: "livestock_count" | "land_area" | "earners_count" | "rooms", text: string, step = 1) => (
    <Field label={text}><Input type="number" min={0} step={step} placeholder="typical" value={f[k]} onChange={(e) => set(k, e.target.value, text)} /></Field>
  );

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", alignItems: "start" }}>
      <Card title="An imagined household" actions={<div className="row">{Object.keys(PRESETS).map((p) => (
        <Button key={p} small onClick={() => { lastChange.current = ""; setF((x) => ({ ...x, ...PRESETS[p] })); }}>{p}</Button>
      ))}</div>}>
        <form className="stack" style={{ gap: 12 }} onSubmit={(e) => e.preventDefault()}>
          <div className="grid cols-3">
            <Field label="District"><Select value={f.area_code} onChange={(e) => set("area_code", e.target.value, "District")} options={(areas ?? []).map((a) => [a.area_code, `${a.area_name} · ${a.urban_rural}`])} /></Field>
            <Field label="Need"><Select value={f.need_category} onChange={(e) => set("need_category", e.target.value, "Need")} options={Object.entries(NEED_LABEL)} /></Field>
            {num("amount_requested", "Amount requested (RWF)", 1000)}
            {num("household_size", "People")}
            {num("children_under_5", "Under five")}
            {num("members_over_65", "Over 65")}
            {num("monthly_income", "Monthly income (RWF)", 1000)}
            {num("essential_costs", "Essential costs (RWF)", 1000)}
            <Field label="Main employment"><Select value={f.employment_type} onChange={(e) => set("employment_type", e.target.value, "Employment")}
              options={["formal", "informal", "self_employed", "unemployed", "unable_to_work"].map((x) => [x, label(x)])} /></Field>
          </div>
          {f.monthly_income < f.essential_costs && (
            <span className="small muted">Income covers {pct(f.monthly_income, f.essential_costs)} of essential costs: a gap of {need(f.essential_costs - f.monthly_income)} RWF a month.</span>
          )}
          <Field label={`Food insecurity: ${f.food_security_score} of 8`}>
            <input type="range" min={0} max={8} value={f.food_security_score} onChange={(e) => set("food_security_score", Number(e.target.value), "Food insecurity")} style={{ accentColor: "var(--teal)" }} />
          </Field>
          <fieldset className="group"><legend>Shocks this year</legend>
            <div className="grid cols-3" style={{ gap: 4 }}>{SHOCKS.map((s) => <Check key={s} label={label(s)} checked={f.shocks.includes(s)} onChange={() => toggle("shocks", s)} />)}</div></fieldset>
          <fieldset className="group"><legend>Assets owned</legend>
            <div className="grid cols-4" style={{ gap: 4 }}>{ASSETS.map((s) => <Check key={s} label={label(s)} checked={f.assets.includes(s)} onChange={() => toggle("assets", s)} />)}</div></fieldset>
          <div className="row wrap" style={{ gap: 18 }}>
            <Check label="Female-headed" checked={f.female_headed} onChange={(e) => set("female_headed", e.target.checked, "Female-headed")} />
            <Check label="Disability in household" checked={f.disability_in_household} onChange={(e) => set("disability_in_household", e.target.checked, "Disability")} />
            <Check label="Chronic illness" checked={f.chronic_illness} onChange={(e) => set("chronic_illness", e.target.checked, "Chronic illness")} />
          </div>
          <details className="group" style={{ padding: "8px 12px" }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>More details <span className="small muted">(blank = typical for the district)</span></summary>
            <div className="grid cols-3" style={{ marginTop: 10 }}>
              {optNum("livestock_count", "Livestock (head)")}
              {optNum("land_area", "Land (hectares)", 0.1)}
              {optNum("earners_count", "People earning")}
              {optNum("rooms", "Rooms")}
              <Field label="Electricity"><Select value={f.electricity} onChange={(e) => set("electricity", e.target.value, "Electricity")} options={[["", "Typical"], ["yes", "Yes"], ["no", "No"]]} /></Field>
              <Field label="Floor"><Select value={f.floor_material} onChange={(e) => set("floor_material", e.target.value, "Floor")} options={[["", "Typical"], ["earth", "Earth"], ["cement", "Cement"], ["tile", "Tile"]]} /></Field>
            </div>
          </details>
          <Field label="Model" quiet><Select value={f.version} onChange={(e) => set("version", e.target.value, "Model")} placeholder="The active need model"
            options={(versions ?? []).filter((v) => v.purpose === "need" && v.kind !== "rules").map((v) => [v.model_version, v.model_version])} /></Field>
        </form>
      </Card>

      <div className="stack" style={{ gap: 14 }}>
        {run.error && <ErrorBox error={run.error} />}
        {!result ? (
          <Card title="The model's view"><p className="muted" style={{ margin: 0 }}>Scoring…</p></Card>
        ) : result.score ? (
          <>
            <ScoreCard r={result} delta={delta} busy={run.isPending} />
            <AddsUp r={result} />
          </>
        ) : <LegacyView r={result} />}
      </div>
    </div>
  );
}

const DECISION: Record<string, { tone: "teal" | "amber" | "neutral"; why: string }> = {
  auto_approve: { tone: "teal", why: "The score and its whole likely range are above the cut-off, so it would be approved automatically." },
  human_review: { tone: "amber", why: "Its likely range crosses the cut-off, so the model is not sure: a caseworker would decide." },
  defer: { tone: "neutral", why: "Even the top of its likely range is below the cut-off, so it would be deferred. The household can appeal." },
};

function ScoreCard({ r, delta, busy }: { r: WhatIfResult; delta: { points: number; what: string } | null; busy: boolean }) {
  const s = r.score!, c = r.context;
  const d = c ? DECISION[c.likely_band] : null;
  return (
    <Card title="Need score" note={busy ? "updating…" : r.model_version}>
      <div className="row" style={{ gap: 24, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div className="stack" style={{ gap: 0 }}>
          <span><b className="serif" style={{ fontSize: 48, lineHeight: 1 }}>{Math.round(s.score)}</b><span className="muted"> / 100</span></span>
          {delta && (
            <span className="small" style={{ color: delta.points > 0 ? "var(--teal)" : "var(--amber-text)", fontWeight: 600 }}>
              {delta.points > 0 ? "+" : "−"}{Math.abs(delta.points).toFixed(1)} points · {delta.what}
            </span>
          )}
        </div>
        {c && d && (
          <div className="stack" style={{ gap: 4 }}>
            <span className="small muted">In {monthLabel(c.period_start)} it would be</span>
            <Pill tone={d.tone}>{BAND[c.likely_band]?.label}</Pill>
          </div>
        )}
      </div>
      <ScoreBar score={s.score} low={s.low} high={s.high} cutoff={c?.cutoff_score ?? null} />
      {d && <p style={{ margin: 0 }}>{d.why}</p>}
      <span className="small muted">
        50 = at the poverty line · 100 = living on a quarter of it or less · 0 = four times it or more.
        {c && ` The cut-off (${Math.round(c.cutoff_score ?? 0)}) is where ${monthLabel(c.period_start)}'s budget ran out.`}
        {` Need: ${need(r.need_mid)}${r.need_mid > 0 ? " RWF per person a month below the line" : ""}.`}
      </span>
    </Card>
  );
}

function ScoreBar({ score, low, high, cutoff }: { score: number; low: number; high: number; cutoff: number | null }) {
  const x = (v: number) => `${Math.max(0, Math.min(100, v))}%`;
  return (
    <div style={{ position: "relative", height: 58, margin: "8px 4px 0" }}>
      <div style={{ position: "absolute", top: 22, left: 0, right: 0, height: 10, borderRadius: 5,
        background: "linear-gradient(90deg, var(--teal-soft), var(--amber-soft))" }} />
      <div title="Likely range" style={{ position: "absolute", top: 18, height: 18, left: x(low), width: `${Math.max(0.8, Math.min(100, high) - Math.max(0, low))}%`,
        background: "var(--teal-mid)", opacity: 0.35, borderRadius: 9 }} />
      {cutoff !== null && (
        <div style={{ position: "absolute", top: 4, bottom: 16, left: x(cutoff), borderLeft: "2px solid var(--amber)" }}>
          <span className="small" style={{ position: "absolute", top: -4, left: 4, whiteSpace: "nowrap", color: "var(--amber-text)", fontWeight: 600 }}>cut-off {Math.round(cutoff)}</span>
        </div>
      )}
      <div title="Score" style={{ position: "absolute", top: 17, left: x(score), width: 20, height: 20, marginLeft: -10, borderRadius: 10,
        background: "var(--teal)", border: "3px solid var(--card, #fff)", boxShadow: "0 0 0 1px var(--teal)" }} />
      {[0, 25, 50, 75, 100].map((t) => (
        <span key={t} className="small muted" style={{ position: "absolute", top: 40, left: x(t), transform: "translateX(-50%)" }}>{t === 50 ? "line" : t}</span>
      ))}
    </div>
  );
}

function AddsUp({ r }: { r: WhatIfResult }) {
  const s = r.score!;
  const peak = Math.max(4, ...s.factors.map((f) => Math.abs(f.points)));
  return (
    <Card title="How the score adds up" note="points against the average applicant">
      <div className="row between"><span>Average applicant</span><b>{Math.round(s.base)}</b></div>
      <div className="stack" style={{ gap: 10 }}>
        {s.factors.filter((f) => Math.abs(f.points) >= 0.5).map((f) => (
          <div key={f.factor} className="stack" style={{ gap: 2 }}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr) 56px", gap: 10, alignItems: "center" }}>
              <span style={{ fontWeight: 500 }}>{f.label}</span>
              <div style={{ position: "relative", height: 12 }}>
                <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, borderLeft: "1px solid var(--line)" }} />
                <div style={{ position: "absolute", top: 0, height: 12, borderRadius: 3,
                  background: f.points > 0 ? "var(--teal)" : "var(--grey)",
                  left: f.points > 0 ? "50%" : `${50 - (Math.abs(f.points) / peak) * 50}%`, width: `${(Math.abs(f.points) / peak) * 50}%` }} />
              </div>
              <b style={{ textAlign: "right", color: f.points > 0 ? "var(--teal)" : undefined }}>{f.points > 0 ? "+" : "−"}{Math.abs(f.points).toFixed(1)}</b>
            </div>
            {f.drivers.length > 0 && (
              <span className="small muted">{f.drivers.map((d) => `${featureLabel(d.feature)} ${d.points > 0 ? "+" : "−"}${Math.abs(d.points).toFixed(1)}`).join(" · ")}</span>
            )}
          </div>
        ))}
      </div>
      <div className="row between" style={{ borderTop: "1px solid var(--line)", paddingTop: 8 }}>
        <span>Need score</span><b>{Math.round(s.score)}{s.base + s.factors.reduce((a, f) => a + f.points, 0) > 100.5 ? " (capped at 100)" : ""}</b>
      </div>
      <span className="small muted">Teal raises the score (needier than average), grey lowers it. The model learned these weights from past outcomes; more hardship can never lower a score.</span>
    </Card>
  );
}

function LegacyView({ r }: { r: WhatIfResult }) {
  return (
    <>
      <Card title="The model's view" note={r.model_version}>
        <div className="row" style={{ gap: 28, flexWrap: "wrap" }}>
          <div className="stack" style={{ gap: 0 }}><span className="small muted">Estimated need</span><b className="serif" style={{ fontSize: 36 }}>{need(r.need_mid)}</b><span className="small muted">RWF per person a month below the poverty line</span></div>
          <div className="stack" style={{ gap: 0 }}><span className="small muted">Likely range</span><b style={{ fontSize: 20 }}>{need(r.need_lo)} – {need(r.need_hi)}</b></div>
          {r.context && <div className="stack" style={{ gap: 4 }}><span className="small muted">In {monthLabel(r.context.period_start)} it would be</span>
            <Pill tone={r.context.likely_band === "auto_approve" ? "teal" : r.context.likely_band === "defer" ? "neutral" : "amber"}>{BAND[r.context.likely_band]?.label}</Pill></div>}
        </div>
        <RangeChart lo={r.need_lo} mid={r.need_mid} hi={r.need_hi} cutoff={r.context?.cutoff ?? null} />
        <span className="small muted">This older model has no need score; newer versions show one.</span>
      </Card>
      <Card title="Why" note="left lowers need · right raises it"><DriverBars drivers={r.drivers.map((d) => [d.feature, d.contribution])} /></Card>
    </>
  );
}
