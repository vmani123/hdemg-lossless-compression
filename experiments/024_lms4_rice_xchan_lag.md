# 015 — LMS4+Rice+xchan_lag: propagation-delay-aligned cross-channel prediction

- **Cycle:** 16
- **Date:** 2026-08-13
- **Branch:** `compression-cycle-2026-08-13`
- **Candidate:** `LMS4+Rice+xchan_lag` (a.k.a. `xlag`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #1 — attack the zero-lag assumption inside the dominant lever P1)

Every registered cross-channel front-end subtracts a parent at **lag 0**, capturing only the
*instantaneous* slice of the cross-channel MI. HD-sEMG is dominated by MUAPs propagating along the
fibres at ~3–5 m/s; at 8–10 mm IED and 2048 Hz the along-fibre neighbour should be a near-replica
delayed by ≈2–5 samples, so a zero-lag subtract sees a *phase-rotated* copy and throws that MI
away. Predicted: aligning the lag enlarges the P1 lever. Falsifiable predictions filed by the
implementer: (a) transversally-mounted arrays collapse to `d=0` and degenerate to
`bestpartner_adaptive`; (b) **CapgMyo is the upside test** — a differential montage kills the
zero-lag common mode but cannot kill propagation delay.

## Implementation

`research/registry.py` only (+245 lines, additive): `y[c,t] = x[c,t] − ((β·x[p,t−d])>>s)` with
`(parent p ∈ ≤4 causal grid neighbours, lag d ∈ 0…8, gain β)` re-selected per 256-sample block by a
**full joint 4×9 backward search** over the previous already-reconstructed raw block; zero side-info;
decoder mirrors the identical integer search. `_bp_opt_beta` / `_bp_score` reused verbatim, subtract
stays strictly rank-1 (not the retired multi-tap `iklt`, not the retired summed `multiparent`);
temporal back-end unchanged (order-4 sign-sign LMS + adaptive Rice). Reduction check by the
implementer: with `maxd=0` the front-end output is **bit-identical** to `_lms4bpa_forward`, so the
lag is the only new degree of freedom. Cost 0.0995; `state_bytes_per_ch=44`;
**`neural_ok = "-"`** (the 4×9 joint search ≈119 ops/sample-ch ≈143 cyc > the 125-cyc 30 kHz budget).

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok=OK`, **`neural="-"`**), from `results/cycle_bench.csv`:

| dataset | C | `xchan_lag` (0.0995) | best `bestpartner` (0.0394) | vs best | streaming `bestpartner_adaptive` (0.0387) | vs streaming |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.476699 | 1.480384 | **−0.249%** | 1.477020 | **−0.022%** |
| otb_hdsemg_vl | 64 | 2.092333 | 2.161938 | **−3.220%** | 2.153106 | **−2.823%** |
| capgmyo_dba_s1 | 128 | 1.351317 | 1.350480 | +0.062% | 1.352866 | **−0.115%** |
| cemhsey_s1_d1t1 | 320 | 1.953372 | 1.955547 | **−0.111%** | 1.953948 | **−0.029%** |

4-set mean 1.7184× vs best 1.7371× (**−1.07%**). Synthetic (`synth_sc0.6` 2.584654×,
`synth_sc0.9` 2.544000×) is **exactly** `bestpartner_adaptive`'s 2.584705×/2.544000× to 4 decimals —
the synthetic fields have no propagation delay, so the search correctly returns `d=0` there.

## Attribution — which mechanism moved the ratio

The temporal predictor and the entropy back-end are **bit-identical** to
`bestpartner_adaptive`, so 100% of the delta is the front-end's new lag degree of freedom.

**Isolated cross-channel gain on REAL data** (achieved, vs the temporal-only `LMS+Rice` at the same
`results/cycle_bench.csv` rows — not a ceiling):

| dataset | `LMS+Rice` base | `xchan_lag` | **xchan gain** | `bestpartner` xchan gain |
|---|---:|---:|---:|---:|
| hyser | 1.329992 | 1.476699 | **+11.03%** | +11.31% |
| otb | 1.825352 | 2.092333 | **+14.63%** | **+18.44%** |
| capgmyo | 1.332259 | 1.351317 | **+1.43%** | +1.37% |
| cemhsey | 1.729317 | 1.953372 | **+12.96%** | +13.08% |

The lag axis **shrinks** the very lever it was meant to enlarge, catastrophically so on the tight
64-ch OTB array (−3.8 pp of xchan gain). Both filed predictions failed: OTB did **not** gracefully
collapse to `d=0` (it lost 2.8% relative to the lag-0 incumbent it reduces to), and CapgMyo — the
stated upside test — gave **−0.115%** vs the streaming incumbent, i.e. the differential array
carries no recoverable delayed MI either.

**Mechanism.** Two things are wrong with the physics-to-codec step:
1. **The neighbour MI is not in the propagating component.** Tissue volume conduction is
   quasi-static — the far-field potential a neighbour shares with channel `c` arrives with **zero**
   delay. The propagating MUAP part is a minority of the shared variance, and at any instant the
   electrode sums many MUs with different CVs, depths and fibre angles, so the neighbour
   cross-covariance is a **mixture over delays** that peaks broadly at 0. A single-lag rank-1
   operator is mis-specified for a mixture; the correct object would be a multi-tap FIR across lags,
   which P3 already settles as a dead end.
2. **Model-selection variance.** The candidate set grows 4 → ~36 `(p,d)` pairs while the selection
   statistic is still estimated from **one stale 256-sample block**. Taking the max of 36 noisy
   Rice-bit estimates instead of 4 imports a winner's-curse bias: the chosen configuration is partly
   chosen for estimation noise and generalizes *worse* to the current block. This is the
   P4 corollary in the negative — a backward-adaptive parameter only survives if it is
   **slowly varying**, and the winning lag is not.

OTB is hit hardest precisely because it has the largest lag-0 MI (xchan gain +18.44%), so it has the
most to lose from any deviation off `d=0`.

## Pareto check

**Dominated.** `LMS4+Rice+xchan_bestpartner_adaptive` (cost **0.0387**, `neural_ok=OK`) has a
**strictly higher ratio on all four real sets** and **2.6× lower cost**. It is also dominated on the
4-set mean by six registered codecs. There is no dataset and no cost regime where `xlag` is the
right pick.

## Sanity gates

- Max real ratio 2.0923× (otb) ≪ the 6× ceiling → no leak.
- Zero bit-exact failures in `results/cycle_bench.csv` (0/120 rows `ok != True`).
- **Regression flagged:** otb −3.22% vs the registered best — the largest single-set regression of
  the cycle.
- **`neural_ok` FAILS** ("-"): the only registered candidate this cycle that misses the 125-cyc
  30 kHz budget; the declared `enc_ops=119` deliberately does not assume the staged port.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (Verification covers
correctness/embeddability/cost audit only, not ratio — see the CYCLE_LOG column note.)

## Decision

**NOT promoted. RETIRED.** Conclusively Pareto-dominated on REAL data by
`LMS4+Rice+xchan_bestpartner_adaptive` (worse ratio on all 4 sets **and** 2.6× the cost, **and** it
alone fails `neural_ok`). `retired=True` + `retired_reason` set on its `Codec(...)` registration in
`research/registry.py`. The lag axis of the spatial front-end is now a **closed dead end** (see
INSIGHTS P1c); the mechanism, not the tuning, is wrong.
