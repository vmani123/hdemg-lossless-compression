# 015 — LMS4+Rice+xchan_xlag: propagation-aware (time-lagged) rank-1 cross-channel predictor

- **Cycle:** 13
- **Date:** 2026-08-10
- **Branch:** `compression-cycle-2026-08-10`
- **Candidate:** `LMS4+Rice+xchan_xlag` (a.k.a. `xlag`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY row 1 — enlarge the reachable cross-channel MI along a lag axis)

Every registered spatial front-end (`xchan`, `bestpartner(_adaptive)`, `multiparent`, `joint2`, `jointbp2`,
`iklt(_adaptive)`, `acar`) evaluates the parent channel at time *t* only. HD-sEMG MUAPs *propagate* along the
fibres at ~3–5 m/s; at 8–10 mm IED that is ~1.6–3.3 ms ≈ **3–7 samples at 2048 Hz**, so the inter-channel
cross-correlation should peak at a **non-zero** lag τ\*. For a jointly-Gaussian pair the reducible bits are
−½·log₂(1−ρ²), monotone in |ρ|, and ρ(τ\*) ≥ ρ(0) by definition of the peak. Predicted: a per-block backward
search over (parent, τ ∈ [−7..+7]) plus an MPEG-4-ALS-MCC 3-tap cross-filter on the winner should beat the
τ=0 front-ends on the 2048 Hz sets. CapgMyo (differential montage, 1 kHz, sub-sample delay) was declared the
expected negative control **before** measurement.

## Implementation

`research/registry.py` only (`xlag_encode`/`xlag_decode`, magic `0x474C`). Per channel, per block, over the
**previous already-reconstructed raw block**: integer cross-correlogram peak τ\*ₚ = argmax\_{|τ|≤7} |⟨x\_c,
x\_p(τ)⟩| over the ≤4 causal grid neighbours (`_bp_candidates` verbatim); then rounded integer-LS gain
(`_bp_opt_beta`) and estimated-Rice-bit scoring (`_bp_score`) at each parent's own peak lag, plus the
no-parent option; then an optional ridge-regularised 3×3 integer-LS 3-tap filter at lags (τ−1, τ, τ+1) kept
only if it scores fewer Rice bits. Apply: `y[c,t] = x[c,t] − ((Σ_m b_m·x[p, t−τ−m]) >> 8)`. **Zero side-info**
(decoder recomputes the identical selection), look-ahead 0 (parents have grid idx < c, indices clamped to the
current block end). Forcing τ≡0 reduces the codec *exactly* to `LMS4+Rice+xchan_bestpartner_adaptive`, which
is what makes the lag lever isolable. Integer/fixed only; `rtl/`, `sim/` untouched.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all rows `ok=True`, `embedded=OK`), cost **0.1063**:

| dataset | C | `xlag` | best `bestpartner` (0.0394) | vs best | τ=0 control `bestpartner_adaptive` (0.0387) | **isolated lag lever** |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.468446 | 1.480384 | −0.806% | 1.477020 | **−0.581%** |
| otb_hdsemg_vl | 64 | 2.029392 | 2.161938 | **−6.131%** | 2.153106 | **−5.746%** |
| capgmyo_dba_s1 | 128 | **1.363847** | 1.350480 | **+0.990%** | 1.352866 | **+0.812%** |
| cemhsey_s1_d1t1 | 320 | 1.952341 | 1.955547 | −0.164% | 1.953948 | −0.082% |
| *4-set mean* | | | | −1.528% | | **−1.399%** |

Achieved cross-channel gain vs temporal-only `LMS+Rice` (hyser 1.3300 / otb 1.8254 / capgmyo 1.3323 /
cemhsey 1.7293): **+10.41% / +11.18% / +2.37% / +12.90%** — versus the incumbent's **+11.31% / +18.44% /
+1.37% / +13.08%**. The lag axis *shrinks* the harvested cross-channel MI on three of four real sets and
enlarges it only on CapgMyo. This is an achieved figure, not a ceiling.

Synthetic (mechanism only, `results/cycle_bench.csv`): synth_sc0.6 2.584035, synth_sc0.9 2.542327 — i.e.
essentially the τ=0 control (2.584705 / 2.544000), confirming the lag machinery is inert where no wavefront
was injected.

## Attribution

The delta is **entirely** the cross-channel front-end: the temporal predictor (order-4 sign-sign LMS) and the
entropy back-end (adaptive Rice) are byte-for-byte the τ=0 control's, so the −1.399% mean is the lag search +
3-tap filter and nothing else. Three compounding mechanisms explain the sign:

1. **The shared mode is instantaneous, not propagating.** Neighbour redundancy in HD-sEMG is dominated by
   *volume conduction* — a quasi-static resistive field, therefore **zero-lag by construction** — plus a
   global common mode. OTB is the direct proof: it is the array where the global CAR mode is worth the most
   (`acar` +14.4% array-mean there, P1), and it is exactly where the lag search loses most (−5.75%). Shifting
   the parent by τ mis-aligns the *large* instantaneous component in order to chase the *small* travelling
   one, so ρ(τ\*) ≥ ρ(0) — true for the population correlogram of a pure travelling wave — is **false for the
   mixture** that real electrodes see.
2. **τ\* is not slowly varying, so P4's cheap-backward-adaptation condition fails.** Best-partner identity
   and β are stable within a recording, which is why backward re-selection costs ~0.4% (P4). The propagation
   delay is only *defined* while a MUAP traverses; firing is a point process and the dominant motor unit
   changes block to block. Estimating τ on block *k−1* and applying it to block *k* is therefore a
   high-variance extrapolation, unlike β.
3. **Selection variance on a flat surface.** The search maximises |⟨·,·⟩| over 15 lags × ≤4 parents = up to
   60 hypotheses with no MDL penalty. Where the true ρ(τ) surface is flat, E[max of 60 noisy correlations] is
   biased upward and a spurious τ ≠ 0 wins; the sign-free |·| doubles the hypothesis space again.

CapgMyo — the *predicted negative control* — is the only real gain (+0.812%), which inverts the hypothesis.
Its differential montage cancels the instantaneous common mode (neighbour |corr| ≈ 0.29, P1), so there is
almost no zero-lag component left to mis-align; the lag search's extra degree of freedom then finds a small
amount of genuinely local structure at no alignment cost. Read plainly: **the lag lever pays only where the
zero-lag lever is already empty.**

## Cross-channel gain, isolated (REAL)

Isolated against the exact τ=0 reduction of the same codec (see table above): **−0.581% / −5.746% / +0.812%
/ −0.082%**, mean **−1.399%**. Achieved, not a ceiling.

## Pareto check

Cost **0.1063** — the most expensive registered embeddable codec, driven by the un-subsampled correlogram
(70 of 128 ops/sample-ch). It is beaten on ratio *and* on cost by `bestpartner_adaptive` (0.0387) on hyser,
otb and cemhsey. **But on capgmyo it is the highest ratio of any codec in the sweep** (1.363847 > `LMS4bc`
1.353778 > `bestpartner_adaptive` 1.352866 > wavpack 1.347), so **no registered codec dominates it on all
four real sets** → it is a genuine, if expensive, non-dominated CapgMyo corner. **Not retired.**

## Sanity gates

- Max real ratio this cycle 2.1804× (otb, `LMS4bc`) ≪ the 6× ceiling → no leak. `xlag`'s own max is 2.0294×.
- 120/120 bench rows `ok=True` — no FAIL bit-exact.
- **Regression flagged:** −6.131% vs the leaderboard best on OTB is the largest single-set regression of the
  cycle.
- **`neural_ok` FAIL:** 154 cyc/sample-ch > the 125-cyc 30 kS/s budget — the **first registered codec to
  miss the neural gate**. `embedded_ok` (sEMG, 1831 cyc) still passes. Recorded as `-` in the CSV's
  `neural` column on all six datasets.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (Verification is a
correctness/embeddability gate only; both verifiers passed the bit-exactness, zero-side-info and cost audit.
It says nothing about ratio.)

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** Loses to the leaderboard best on 3 of 4 real sets including
a −6.13% OTB regression, at 2.7× the cost, and fails `neural_ok`. Kept only because it is the strict
max-ratio corner on CapgMyo. **The lag axis for cross-channel prediction is spent NEGATIVE** and is moved to
the INSIGHTS dead-ends list: the cross-channel MI in HD-sEMG is carried by the *instantaneous* volume-
conduction/common-mode component, so a time-shifted parent is a basis mismatch, not a richer basis.
