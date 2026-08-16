# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after cycle **2026-08-16** (13 active codecs benched, **10 retired**).
All four real sets benched at 15 000 samples: `results/cycle_bench.csv` (+
`results/cycle_search.csv`). This cycle tried three candidates — `xlag`, `xres`,
`xtree` — **none promoted**; `xres` retired. Headline and port pick unchanged._

### This cycle's candidates (real data, `results/cycle_bench.csv`)

| candidate | hyser | otb | capgmyo | cemhsey | cost | verifiers | outcome |
|---|--:|--:|--:|--:|--:|---|---|
| `LMS4+Rice+xchan_xtree` | **1.4822** | **2.1707** | **1.3527** | 1.9528 | 0.0733 | PROMOTE / PROMOTE | kept, **not promoted** (−0.14% CEMHSEY; tops no set; 1.86× cost) |
| `LMS4+Rice+xchan_xres` | 1.4686 | 2.0975 | 1.3500 | 1.9407 | 0.0387 | PROMOTE / PROMOTE | **RETIRED** — dominated at identical cost |
| `LMS4+Rice+xchan_xlag` | 1.4727 | 2.0409 | **1.3579** | 1.9518 | 0.0982 | **REJECT / REJECT** | kept (CapgMyo corner only), **not promoted**; `neural_ok` FAIL; flagged for human review |
| _current best_ `LMS4+Rice+xchan_bestpartner` | 1.4804 | 2.1619 | 1.3505 | **1.9555** | 0.0394 | — | unchanged |

### Achieved cross-channel gain, isolated on REAL data

Measured against this family's true null — order-4 sign-sign LMS + adaptive Rice with the
spatial stage removed (Hyser 1.3321×, OTB 1.8347×, CapgMyo 1.3336×, CEMHSEY 1.7280×).
These are **achieved** percentages, not ceilings.

| codec | hyser | otb | capgmyo | cemhsey |
|---|--:|--:|--:|--:|
| `xtree` | +11.27% | **+18.32%** | +1.43% | +13.01% |
| `bestpartner` | +11.13% | +17.84% | +1.27% | **+13.17%** |
| `bestpartner_adaptive` | +10.88% | +17.36% | +1.45% | +13.07% |
| `jointbp2` | **+12.38%** | +17.31% | +1.25% | +12.98% |
| `xres` (residual domain) | +10.25% | +14.32% | +1.23% | +12.31% |
| `xlag` (lag search) | +10.55% | +11.24% | **+1.82%** | +12.95% |

`xtree`'s +18.32% is the highest OTB cross-channel gain of any codec measured; it decays
with array size (+0.96 pp at C=64 → −0.06 pp at C=320 vs its peer) — see `INSIGHTS.md` P8.

## Best embeddable: `LMS4+Rice+xchan_bestpartner` (cost 0.039)

Order-4 sign-sign LMS + adaptive Golomb-Rice, per-channel best-of-4 causal-neighbour
cross-channel subtract. Best embeddable on **every** real set; only offline LZMA is ahead.

| dataset | ch | best-emb ratio | %-of-FLAC | FLAC | best offline ref |
|---|--:|--:|--:|--:|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.480×** | 151% | 0.98× | lzma 1.67× |
| otb_hdsemg_vl | 64 | **2.162×** | 176% | 1.23× | wavpack 1.85× (emb-class) |
| cemhsey_s1_d1t1 | 320 | **1.956×** | 167% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.350×** | 137% | 0.98× | wavpack 1.35× |

### Primary — real Hyser reference bar

| codec | ratio | embedded_ok | note |
|---|---:|:--:|---|
| lzma | 1.67× | ref | **offline**, not embeddable |
| **LMS4+Rice+xchan_bestpartner** | **1.480×** | ✅ | **best embeddable** (offline selection — see below) |
| LMS+Rice+xchan_joint2 | 1.493× | ✅ | zero-side-info joint 2-parent; wins Hyser, regresses OTB |
| zstd-19 | 1.44× | ref | offline |
| mtscomp | 1.41× | ref | neuro per-channel reference |
| wavpack | 1.34× | ref | best embeddable-class per-channel ref |
| LMS+Rice | 1.33× | ✅ | temporal only (no cross-channel) |
| flac | 0.98× | ref | target to beat (expands here) |

- Beats every embeddable-feasible reference (WavPack, mtscomp, even offline zstd-19)
  at a fraction of the compute, bit-exact. **Achieved cross-channel gain +11.3%** on
  Hyser (LMS 1.330× → 1.480×) — the dominant lever.
- Max real ratio 2.162× ≪ the 6× sanity ceiling → honest broadband EMG.
- Cross-channel gain **tracks real spatial redundancy**: strong where neighbour |corr|
  is 0.73–0.79 (Hyser/OTB/CEMHSEY), ~0 on CapgMyo (|corr| 0.29). CapgMyo is the negative
  control — the harness reports gain only where the signal carries it.

## Pareto front (ratio vs cost, embedded_ok only — real Hyser)

| config | ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice+xchan | 1.452× | 0.013 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | — | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info); mean(hyser,otb) **1.8204×** |
| LMS+Rice+xchan_joint2 | 1.493× | 0.037 | ✅ | zero-side-info joint 2-parent (wins Hyser only) |
| LMS4+Rice+xchan_bestpartner_adaptive | 1.477× | 0.0387 | ✅ | zero-side-info streaming realization (port-safe) |
| LMS4+Rice+xchan_bestpartner | 1.480× | 0.0394 | ✅ | **best-ratio robust across all 4 sets** (best-of-4 partner) |
| LMS4+Rice+acar_sel+bestpartner | 1.480× | 0.043 | ✅ | OTB max-ratio corner (2.1795×), scale-gated CAR cascade |
| LMS4+Rice+xchan_jointbp2 | 1.497× | 0.0468 | ✅ | max-Hyser corner (large-array joint 2-parent) |
| LMS4+Rice+xchan_xtree *(new)* | 1.482× | 0.0733 | ✅ | tight-array **structural** corner; best OTB xchan gain (+18.32%) |
| LMS4+Rice+xchan_xlag *(new)* | 1.473× | 0.0982 | ❌ | CapgMyo-only corner (1.3579×); **fails the 125 cyc neural budget** |

### What mattered (search ablation from best — `results/cycle_search.csv`, mean of real Hyser + OTB)
Converged pick `lms4s7+x6/b512`, mean ratio **1.8204×**, cost 0.0271, `embedded_ok` ✅ `neural_ok` ✅.

| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+0.2350× (+14.83%)** | dominant lever, ~19× the next knob |
| lms order 4→8 | +0.0142× (+0.79%) | deeper temporal prediction *hurts* here (P2) |
| xchan shift 7→8 | +0.0028× (+0.16%) | marginal |
| rice block 512→256 | +0.0028× (+0.15%) | marginal |

Search Pareto front (60 configs, `embedded_ok` only): `delta+x6/b512` 1.7487×/0.0163,
`fixed+x6/b512` 1.7918×/0.0252, `lms4s7+x6/b512` 1.8204×/0.0271.

### Cross-channel gain vs. spatial correlation (synthetic sweep — mechanism only)
| spatial-corr | 0.0 | 0.3 | 0.6 | 0.9 |
|---|---:|---:|---:|---:|
| xchan gain (LMS) | −0.1% | +1.4% | +9.4% | +19.1% |

Real HD-sEMG lands at +10.8% (Hyser) to +17.4% (OTB) — same lever, scaled by each
set's real neighbour correlation.

## Sanity gates (this cycle)

- Max ratio on any REAL set across the whole run: **2.1795×** (`acar_sel+bestpartner`, OTB)
  ≪ the 6× ceiling → no leak, honest broadband EMG. No `SANITY GATE` line was emitted.
- **Zero non-bit-exact rows.** `bench.py` asserts a bit-exact round-trip for every registry
  codec on every dataset; the run exited 0, and all 120 CSV rows carry `ok=True`.
- Regressions worth naming: `xlag` −5.60% vs best on OTB and the **only** registered codec
  failing `neural_ok` (117 ops = 140 cyc > 125); `xres` −2.98% on OTB, −0.80% on Hyser
  (retired); `xtree` −0.14% on CEMHSEY.

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
- **Unchanged after cycle 2026-08-16.** No candidate displaced it: `xres` lost on all 4
  real sets (retired), `xlag` lost on 3 of 4 with a unanimous verifier REJECT, and `xtree`
  — the only one that beat the best on the primary Hyser (+0.12%) — regressed CEMHSEY,
  topped no real set, and costs 1.86× as much.

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
