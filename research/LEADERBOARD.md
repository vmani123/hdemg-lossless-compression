# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after cycle 2026-08-05 (13 active codecs benched, 10 retired). All four
real sets benched at 15 000 samples: `results/cycle_bench.csv` (+ `results/cycle_search.csv`)._

## Best embeddable: `LMS4+Rice+xchan_bestpartner` (cost 0.039) — UNCHANGED

Order-4 sign-sign LMS + adaptive Golomb-Rice, per-channel best-of-4 causal-neighbour
cross-channel subtract. Best embeddable on **every** real set; only offline LZMA is ahead.
Cycle 16's three candidates (`xchan_lagpartner`, `xchan_mdlsel`, `xchan_post`) did **not**
displace it — see "This cycle" below.

| dataset | ch | best-emb ratio | %-of-FLAC | FLAC | best offline ref |
|---|--:|--:|--:|--:|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.480×** | 151% | 0.98× | lzma 1.67× |
| otb_hdsemg_vl | 64 | **2.162×** | 176% | 1.23× | wavpack 1.85× (emb-class) |
| cemhsey_s1_d1t1 | 320 | **1.956×** | 167% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.350×** | 137% | 0.98× | wavpack 1.35× |

### This cycle (2026-08-05) — three candidates, none promoted, one retired

All three passed the double-verifier gate **unanimously (no splits)**; promotion is the
separate, stricter question of beating the best on REAL data, and none of them does.

| candidate | cost | hyser | otb | capgmyo | cemhsey | verdict |
|---|---:|---:|---:|---:|---:|---|
| `LMS4+Rice+xchan_lagpartner` | 0.0775 | 1.4762 (−0.28%) | 2.0559 (−4.91%) | **1.3575 (+0.52%)** | 1.9534 (−0.11%) | kept — non-dominated **max-CapgMyo corner**; not promoted |
| `LMS4+Rice+xchan_mdlsel` | 0.0474 | 1.4967 (+1.11%) | 2.1519 (−0.46%) | 1.3506 (+0.01%) | 1.9527 (−0.14%) | kept — non-dominated, ≈`jointbp2` ±0.025%; not promoted |
| `LMS4+Rice+xchan_post` | 0.03874 | 1.4612 (−1.30%) | 2.0801 (−3.79%) | 1.3479 (−0.19%) | 1.9291 (−1.35%) | **RETIRED** — dominated at *identical* cost by `bestpartner_adaptive` on all 4 sets; not promoted |

Percentages are vs. the best embeddable (`LMS4+Rice+xchan_bestpartner`). `1.3575×` is the
highest CapgMyo ratio of any codec *or* reference in the table. Full attribution:
`experiments/015`–`017`; durable learnings (P1c, P1d, P6): `INSIGHTS.md`.

### Primary — real Hyser reference bar

| codec | ratio | embedded_ok | note |
|---|---:|:--:|---|
| lzma | 1.667× | ref | **offline**, not embeddable |
| LMS4+Rice+xchan_jointbp2 | 1.4969× | ✅ | highest embeddable Hyser ratio; regresses OTB/CEMHSEY (cycle 13) |
| LMS4+Rice+xchan_mdlsel | 1.4967× | ✅ | MDL-penalized order selection — ≡ jointbp2 ±0.025% (cycle 16) |
| LMS+Rice+xchan_joint2 | 1.4930× | ✅ | zero-side-info joint 2-parent; wins Hyser, regresses OTB |
| **LMS4+Rice+xchan_bestpartner** | **1.4804×** | ✅ | **best embeddable** across all 4 sets (offline selection — see below) |
| LMS4+Rice+xchan_lagpartner | 1.4762× | ✅ | lag-matched partner; wins only CapgMyo, 2× cost (cycle 16) |
| zstd-19 | 1.440× | ref | offline |
| mtscomp | 1.414× | ref | neuro per-channel reference |
| wavpack | 1.337× | ref | best embeddable-class per-channel ref |
| LMS+Rice | 1.330× | ✅ | temporal only (no cross-channel), order-8 |
| flac | 0.977× | ref | target to beat (expands here) |

Temporal-only order-4 reference measured directly this cycle (order-4 LMS + adaptive Rice,
**no** cross-channel stage): hyser **1.3321×**, otb **1.8347×**, capgmyo **1.3336×**,
cemhsey **1.7280×** — the denominator for every isolated cross-channel gain quoted below.

- Beats every embeddable-feasible reference (WavPack, mtscomp, even offline zstd-19)
  at a fraction of the compute, bit-exact. **Achieved cross-channel gain +11.13%** on
  Hyser (LMS4 1.3321× → 1.4804×) — the dominant lever. Best achieved gain per set:
  otb **+18.80%** (`acar_sel+bestpartner` 2.1795×), cemhsey **+13.17%**, capgmyo
  **+1.79%** (`xchan_lagpartner` 1.3575×), hyser **+12.37%** (`jointbp2` 1.4969×).
- Max real ratio 2.180× ≪ the 6× sanity ceiling → honest broadband EMG. All 120 bench
  rows bit-exact (`ok=True`); no FAIL, no `embedded_ok`/`neural_ok` regression.
- Cross-channel gain **tracks real spatial redundancy**: strong where neighbour |corr|
  is 0.73–0.79 (Hyser/OTB/CEMHSEY), ~0 on CapgMyo (|corr| 0.29). CapgMyo is the negative
  control — the harness reports gain only where the signal carries it. Cycle 16 added the
  one exception: on that *differential* array a **±1-sample lagged** partner finds MI the
  zero-lag subtract cannot (+1.44% → +1.79%), because the bipolar derivation has already
  cancelled the instantaneous common mode (INSIGHTS P1c).

## Pareto front (ratio vs cost, embedded_ok only — real Hyser)

| config | ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice+xchan | 1.452× | 0.013 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | 1.820×\* | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS+Rice+xchan_joint2 | 1.493× | 0.037 | ✅ | zero-side-info joint 2-parent (wins Hyser only) |
| LMS4+Rice+xchan_bestpartner | 1.480× | 0.039 | ✅ | **best-ratio robust across all 4 sets** (best-of-4 partner) |
| LMS4+Rice+xchan_jointbp2 | 1.497× | 0.047 | ✅ | max-Hyser corner (joint best-pair) |
| LMS4+Rice+xchan_lagpartner | 1.476× | 0.077 | ✅ | max-CapgMyo corner (1.3575× there); dominated on the other 3 |

\* `lms4s7+x6/b512` is the search harness's mean over hyser+otb (`results/cycle_search.csv`),
not a Hyser-only figure; the other rows are Hyser from `results/cycle_bench.csv`.
`LMS4+Rice+xchan_post` was **retired this cycle** — identical cost to
`bestpartner_adaptive` (0.03874) with strictly worse ratio on all 4 real sets, so it holds
no corner.

### What mattered (search ablation from best, real hyser+otb mean — `results/cycle_search.csv`)
| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+14.83%** | dominant lever, ~19× the next knob |
| lms order 4→8 | +0.79% | deeper temporal prediction *hurts* here |
| lms shift 7→8 | +0.15% | marginal |
| rice block 512→256 | +0.15% | marginal |

Search converged at `lms4s7+x6/b512`, mean ratio **1.8204×**, cost 0.0271, `embedded_ok` and
`neural_ok` True (60 configs evaluated).

### Cross-channel gain vs. spatial correlation (synthetic sweep — mechanism only)
| spatial-corr | 0.0 | 0.3 | 0.6 | 0.9 |
|---|---:|---:|---:|---:|
| xchan gain (LMS) | −0.1% | +1.4% | +9.4% | +19.1% |

Real HD-sEMG lands at +10.8% (Hyser) to +17.4% (OTB) — same lever, scaled by each
set's real neighbour correlation.

## → The one codec to port next

**`LMS4+Rice+xchan_bestpartner`** for max ratio, or **`lms4s7+x6/b512`** (single
grid-parent, order-4) for minimal hardware / zero partner side-info — essentially
tied on ratio (Hyser+OTB mean within +0.04%).

- The essential component is the **cross-channel grid-neighbour front-end** (+10.8–17.4%
  where redundancy exists); the temporal predictor can be as small as order-4. If minimal
  hardware is paramount, `delta+Rice+xchan` (Hyser 1.45×, cost 0.016, fixed predictors only)
  is 98% of the best ratio.
- **Port caveat (real):** the best-partner *selection* + beta are currently derived
  **offline over the whole signal** — the reported ratio is **not** from an on-node
  encoder (see `EMBEDDED_OK_VERIFICATION.md`, `embedded_verify.py`). The streaming
  realization is **`LMS4+Rice+xchan_bestpartner_adaptive`**: per-block backward
  re-selection from the previous reconstructed block, **zero side-info, look-ahead 0**,
  holding the offline ratio within ~0.4% (and beating it on CapgMyo). **Port that one**
  if the offline selection is unacceptable on-node.
- **Cycle 16 (2026-08-05) did not displace this pick.** The three candidates were unanimously
  verified but none beat the best on real data: `xchan_lagpartner` wins only CapgMyo at 2×
  cost, `xchan_mdlsel` reproduces `jointbp2` (wins Hyser, regresses OTB/CEMHSEY), and
  `xchan_post` was retired. Headline and port pick carry over unchanged.

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
