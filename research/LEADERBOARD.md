# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after cycle 2026-08-07 (20 codec rows benched incl. references, 11 retired).
All four real sets benched at 15 000 samples: `results/cycle_bench.csv` (120 rows, all
round-trips bit-exact); search: `results/cycle_search.csv` (60 configs)._

### This cycle (2026-08-07) — 3 candidates, 0 promoted, 2 retired

| candidate | hyser | otb | capgmyo | cemhsey | cost | verifiers | outcome |
|---|--:|--:|--:|--:|--:|---|---|
| `LMS4+Rice+xchan_lagbp` | 1.4767× | 2.0923× | 1.3513× | 1.9534× | 0.0706 | PROMOTE / PROMOTE | **RETIRED** — dominated on all 4 real sets by `bestpartner_adaptive` (0.0387); sub-sample propagation delay ⇒ the lag axis buys no MI, only selection variance (−2.8% OTB) |
| `LMS4+Rice+xchan_scalesel` | **1.4943×** | 2.1530× | **1.3525×** | 1.9516× | 0.0494 | PROMOTE / PROMOTE | **kept, not promoted** — wins Hyser (+0.94%) and CapgMyo (best of any codec) but regresses OTB (−0.41%) and CEMHSEY (−0.20%); 4-set mean tie (+0.044%). Non-dominated |
| `LMS4v2+Rice+xchan_bestpartner` | 1.4758× | 2.1431× | 1.3468× | 1.9521× | 0.0592 | PROMOTE / PROMOTE | **RETIRED** — dominated on all 4 real sets by the headline (0.0394); degree-2 Volterra taps fit a bispectrum that vanishes for a linear volume-conductor source |

**Headline unchanged.** No candidate beat the current best on real data. The cycle's durable
result is negative-and-informative: the spatial front-end's *choice* and the temporal predictor's
*functional form* are both now measured-and-closed levers (INSIGHTS P1c, P1d, P2b).

## Best embeddable: `LMS4+Rice+xchan_bestpartner` (cost 0.039)

Order-4 sign-sign LMS + adaptive Golomb-Rice, per-channel best-of-4 causal-neighbour
cross-channel subtract. Best embeddable on **every** real set; only offline LZMA is ahead.

| dataset | ch | headline ratio | %-of-FLAC | FLAC | best offline ref | best *any* embeddable (corner codec) |
|---|--:|--:|--:|--:|---|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.480×** | 151% | 0.98× | lzma 1.67× | 1.4969× `xchan_jointbp2` |
| otb_hdsemg_vl | 64 | **2.162×** | 176% | 1.23× | wavpack 1.85× (emb-class) | 2.1795× `acar_sel+bestpartner` |
| cemhsey_s1_d1t1 | 320 | **1.956×** | 167% | 1.17× | lzma 2.06× | 1.9555× (headline) |
| capgmyo_dba_s1 | 128 | **1.350×** | 137% | 0.98× | wavpack 1.35× | 1.3525× `xchan_scalesel` |

The headline is the only codec that is **best-or-tied on every set within 0.5%**; the corner
column shows no single codec holds all four. INSIGHTS **P1c** now argues that ±1.1% spread is a
shared spatial-MI ceiling, not a mechanism gap.

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
| delta+Rice+xchan | 1.4516× | 0.0127 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | 1.478× | 0.0271 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS+Rice+xchan_joint2 | 1.4930× | 0.0366 | ✅ | zero-side-info joint 2-parent (wins Hyser only) |
| LMS4+Rice+xchan_bestpartner_adaptive | 1.4770× | 0.0387 | ✅ | zero-side-info streaming realization of the headline (look-ahead 0) |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.0394 | ✅ | **best-ratio robust across all 4 sets** (best-of-4 partner) |
| LMS4+Rice+acar_sel+bestpartner | 1.4804× | 0.0430 | ✅ | OTB max-ratio corner (2.1795×), no large-array regression |
| LMS4+Rice+xchan_jointbp2 | 1.4969× | 0.0468 | ✅ | Hyser max-ratio corner (joint best-pair) |
| LMS4+Rice+xchan_scalesel | 1.4943× | 0.0494 | ✅ | *new this cycle* — CapgMyo max corner (1.3525×); zero-side-info rank gate holding **both** per-scale branches from one codec |

Search (`results/cycle_search.csv`, 60 configs, mean over hyser+otb) is unchanged: converged to
`lms4s7+x6/b512`, mean **1.8204×**, cost 0.0271, `embedded_ok`/`neural_ok` OK. Ablation from best:
cross-channel on→off **−14.83%**, order 4→8 −0.79%, shift 7→8 −0.16%, block 512→256 −0.15%.

### What mattered (search ablation from best, real Hyser)
| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+10.8%** | dominant lever, ~70× everything else |
| lms order 4→8 | +0.15% | deeper temporal prediction *hurts* here |
| rice block 512→256 | +0.13% | marginal |

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

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
