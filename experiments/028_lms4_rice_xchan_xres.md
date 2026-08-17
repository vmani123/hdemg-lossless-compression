# 016 — LMS4+Rice+xchan_xres: residual-domain cross-channel prediction, bit-matched selection

- **Cycle:** 16
- **Date:** 2026-08-16
- **Branch:** `compression-cycle-2026-08-16`
- **Candidate:** `LMS4+Rice+xchan_xres` (a.k.a. `xres`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #2 — the *domain* in which the rank-1 spatial edge is fitted and scored)

Reorder the pipeline: run the order-4 temporal LMS **first**, then apply the
backward-adaptive rank-1 subtract between *temporal residuals*, `d = e_c − ((β·e_p) >> 8)`,
with the partner/gain chosen by scoring the **post-LMS** residual bits. Two arguments:
(i) volume conduction is instantaneous linear mixing of shared MU innovation trains, and the
channels' shared *autocorrelation* (low-frequency, high-energy) is removed by the
per-channel predictor for free — so a β fitted on raw signals spends its single degree of
freedom on redundancy that dies downstream, while a β fitted on innovations targets the band
where the coded bits actually live; (ii) **criterion mismatch** — `_bp_score` today ranks
partners by the Rice length of the *pre*-LMS residual while the encoder emits the *post*-LMS
one, an argmin of a proxy rather than of the objective. `xres` makes scored quantity ==
coded quantity. Stated failure mode in the survey: if the innovations' `ρ_e` is materially
below the raw `ρ_x`, the residual-domain subtract recovers less.

## Implementation

`research/registry.py` only (additive; `rtl/`, `sim/` untouched). `XRES_MAGIC/BLOCK/ORDER`,
`_xres_forward`, `_xres_inverse`, `xres_encode`, `xres_decode`. Everything except the stage
order and the scoring domain is held fixed against `LMS4+Rice+xchan_bestpartner_adaptive`:
same ≤4 causal grid-neighbour candidate set (`_bp_candidates`), same integer least-squares
gain (`_bp_opt_beta`), same estimated-Rice-bits score (`_bp_score`), same per-block backward
re-selection routine (`_bpa_select_block`, reused **verbatim** — it is domain-agnostic and
simply receives the residual array), same order-4 sign-sign LMS (P2) and adaptive Rice (P5).
Zero side-info, look-ahead 0, block 256, integer/fixed only. Registry gate bit-exact on the
first run; extra round-trips bit-exact at `(C,N,cols)` = (1,300,1), (17,777,4), (64,1024,8),
(8,255,8), (5,257,16), (32,600,16), plus all-(−32768) and full-range uniform int16.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok` OK, `neural_ok` OK, cost **0.038743**), from
`results/cycle_bench.csv`:

| dataset | C | `xres` | `bestpartner_adaptive` (**same cost 0.038743**) | vs it | best `bestpartner` (0.0394) | vs best |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.4686 | 1.4770 | −0.57% | 1.4804 | **−0.80%** |
| otb_hdsemg_vl | 64 | 2.0975 | 2.1531 | −2.58% | 2.1619 | **−2.98%** |
| capgmyo_dba_s1 | 128 | 1.3500 | 1.3529 | −0.21% | 1.3505 | −0.03% |
| cemhsey_s1_d1t1 | 320 | 1.9407 | 1.9539 | −0.68% | 1.9555 | −0.76% |

4-set mean 1.7142 vs best 1.7371 (−1.32%).

## Attribution — isolated cross-channel gain on REAL data

Null model = the identical back-end with the spatial front-end removed (order-4 sign-sign
LMS + adaptive Rice, 12-byte header, no side-info), measured directly:

| dataset | LMS4+Rice (temporal only) | `xres` achieved xchan gain | `bestpartner_adaptive` (raw domain) | Δ |
|---|---:|---:|---:|---:|
| hyser_1dof_f1_s1 | 1.3321× | **+10.25%** | +10.88% | −0.63 pp |
| otb_hdsemg_vl | 1.8347× | **+14.32%** | +17.36% | **−3.04 pp** |
| capgmyo_dba_s1 | 1.3336× | **+1.23%** | +1.45% | −0.22 pp |
| cemhsey_s1_d1t1 | 1.7280× | **+12.31%** | +13.07% | −0.76 pp |

The predictor and back-end are unchanged by construction, and `_bpa_select_block` is reused
verbatim, so **100% of the delta is the front-end's operating domain** — the cleanest
attribution of this cycle: a single-variable A/B on stage order.

The survey's stated failure mode is what happened, and it is stronger than the "criterion
mismatch" argument it was traded against. The order-4 sign-sign LMS is, spectrally, a
per-channel **high-pass**: it whitens each channel by removing its predictable
low-frequency content. But that shared low-frequency volume-conduction mode is precisely
*where the inter-channel mutual information lives* — `ρ_e ≪ ρ_x` on real HD-sEMG. So the
temporal stage destroys the redundancy before the spatial stage can claim it, and the
spatial-then-temporal order is not an accident of history but the correct one: the rank-1
subtract removes the shared mode, and the LMS then whitens whatever is left. The estimator
refinement (scored quantity == coded quantity) is real and correct, but it is a
second-order improvement applied to a first-order-worse-conditioned signal. **Operator
order dominates estimator matching.** The gap scales with the size of the shared mode: it is
largest on OTB (−3.04 pp), where the raw-domain gain was largest (+17.36%), and vanishingly
small on CapgMyo (−0.22 pp), where there is almost no shared mode to lose.

## Pareto check

`xres` has a **bit-identical cost profile** to `LMS4+Rice+xchan_bestpartner_adaptive` —
`enc_ops = dec_ops = 39`, `state_bytes_per_ch = 27`, `causal=True`,
`lookahead_samples=0`, `block_size=256`, `cost = 0.038743` for both (verified by dumping
`CodecMeta` from the registry). At **equal cost it is strictly worse on all four real
sets**. There is no remaining trade-off in either objective → **conclusively Pareto-
dominated**, the same standard under which cycle 15 retired the always-on
`acar+bestpartner` (equal cost, weakly-worse ratio).

## Sanity gates

- Max real ratio across the run 2.1795× ≪ 6× → no leak. `xres`'s own max real 2.0975×.
- No FAIL bit-exact rows in the run (`bench.py` asserts; exit code 0). `ok=True`,
  `embedded_ok` OK, `neural_ok` OK.
- Regression: −2.98% vs best on OTB, −0.80% on the primary Hyser; below every registered
  `LMS4+Rice+xchan_*` codec on every real set.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (Verification is on
correctness/embeddability only — it never speaks to ratio, and this cycle it did not.)

## Decision

**NOT promoted** (loses to the current best on all 4 real sets) and **RETIRED**:
`retired=True` + `retired_reason` set on its `Codec(...)` registration in
`research/registry.py`. Conclusively Pareto-dominated by `LMS4+Rice+xchan_bestpartner_adaptive`
at identical cost. The **residual-domain / stage-order axis is spent NEGATIVE** and enters
the `INSIGHTS.md` dead-ends list with its mechanism (see P7).
