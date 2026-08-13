# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after cycle 2026-08-13 (14 codecs benched → **13 active, 10 retired**; 3 candidates
tried, 1 promoted, 1 retired). All four real sets benched at 15 000 samples:
`results/cycle_bench.csv` (120 rows, **0 bit-exact failures**); search:
`results/cycle_search.csv` (60 configs)._

## Best ratio: `LMS4bc+Rice+xchan_bestpartner` (cost 0.120) — **promoted this cycle**

Order-4 sign-sign LMS + a **context conditional-mean corrector** (`d[t] = e[t] − μ[c,ctx]`,
30 buckets, leaky integer mean, shift-divide only) + adaptive Golomb-Rice, on the unchanged
best-of-4 causal-neighbour cross-channel subtract. Beats the previous best on the primary
Hyser (+0.318%) and on 3 of 4 real sets; **highest 4-set mean real ratio ever measured here
(1.7467× vs 1.7371×, +0.555%)**.

## Best ratio-per-cost — **still `LMS4+Rice+xchan_bestpartner` (cost 0.039)**

The promoted best buys +0.32% Hyser / +1.46% OTB for **3.05× the cost**, almost all of it
SRAM (167 B/ch → ~21 KB at 128 ch). That is a ratio win, not a portability win.

| dataset | ch | **`LMS4bc` (0.120)** | `bestpartner` (0.039) | Δ | %-of-FLAC (bc) | FLAC | best offline ref |
|---|--:|--:|--:|--:|--:|--:|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.4851×** | 1.4804× | +0.318% | 152% | 0.98× | lzma 1.67× |
| otb_hdsemg_vl | 64 | **2.1934×** | 2.1619× | **+1.457%** | 179% | 1.23× | wavpack 1.85× (emb-class) |
| cemhsey_s1_d1t1 | 320 | 1.9553× | **1.9555×** | −0.015% | 167% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.3531×** | 1.3505× | +0.197% | 138% | 0.98× | wavpack 1.35× |

`LMS4bc` is the **outright maximum on OTB and on CapgMyo** of all 20 codecs + references benched.

### Primary — real Hyser reference bar

| codec | ratio | embedded_ok | note |
|---|---:|:--:|---|
| lzma | 1.67× | ref | **offline**, not embeddable |
| LMS4+Rice+xchan_jointbp2 | 1.4969× | ✅ | highest embeddable Hyser ratio (regresses OTB/CEMHSEY) |
| LMS+Rice+xchan_joint2 | 1.4930× | ✅ | zero-side-info joint 2-parent; wins Hyser, regresses OTB |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4851×** | ✅ | **new best ratio** (robust: 3/4 sets, max on OTB+CapgMyo) |
| LMS4+Rice+xchan_mst | 1.4823× | ✅ | Chow-Liu tree topology (this cycle, kept, cost 0.046) |
| LMS4+Rice+xchan_bestpartner | 1.4804× | ✅ | **best ratio-per-cost / port pick** |
| ~~LMS4+Rice+xchan_lag~~ | 1.4767× | ✅ | **RETIRED this cycle** (dominated on all 4 real sets) |
| zstd-19 | 1.44× | ref | offline |
| mtscomp | 1.41× | ref | neuro per-channel reference |
| wavpack | 1.34× | ref | best embeddable-class per-channel ref |
| LMS+Rice | 1.3300× | ✅ | temporal only (no cross-channel) |
| flac | 0.98× | ref | target to beat (expands here) |

- Beats every embeddable-feasible reference (WavPack, mtscomp, even offline zstd-19)
  at a fraction of the compute, bit-exact. **Achieved gain over temporal-only `LMS+Rice`:
  +11.7% Hyser** (1.3300× → 1.4851×) and **+20.2% OTB** (1.8254× → 2.1934×) — composite;
  the isolated cross-channel front-end supplies +11.31% / +18.44% of that and the new
  conditional-mean corrector the remaining +0.32% / +1.46%. Spatial is still the dominant lever.
- Max real ratio 2.193× ≪ the 6× sanity ceiling → honest broadband EMG.
- Cross-channel gain **tracks real spatial redundancy**: strong where neighbour |corr|
  is 0.73–0.79 (Hyser/OTB/CEMHSEY), ~+1.5% on CapgMyo (|corr| 0.29). CapgMyo is the negative
  control — the harness reports gain only where the signal carries it.

## Pareto front (ratio vs cost, embedded_ok only — 4-set mean REAL ratio)

| config | mean real ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice | 1.5047× | 0.008 | ✅ | floor |
| delta+Rice+xchan | 1.6662× | 0.013 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | — (1.820× hyser+otb mean) | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS+Rice+xchan_joint2 | 1.7368× | 0.037 | ✅ | cost-dominant zero-side-info joint 2-parent |
| LMS4+Rice+xchan_bestpartner | 1.7371× | 0.039 | ✅ | **best ratio-per-cost, robust on all 4 sets** |
| LMS4+Rice+acar_sel+bestpartner | 1.7415× | 0.043 | ✅ | scale-gated CAR cascade (OTB corner) |
| **LMS4bc+Rice+xchan_bestpartner** | **1.7467×** | 0.120 | ✅ | **max ratio** (corrector; SRAM-heavy) |

Non-dominated but off the mean front, kept as per-dataset corners:
`LMS4+Rice+xchan_mst` (1.7396×/0.046 — strictly above `acar_sel` on hyser+capgmyo),
`LMS4+Rice+xchan_jointbp2` (1.7379×/0.047 — max embeddable Hyser),
`LMS4+Rice+xchan_bestpartner_adaptive` (1.7342×/0.039 — the zero-side-info streaming form).

### What mattered (search ablation from best, real hyser+otb mean — `results/cycle_search.csv`)
| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+14.83%** (0.2350×) | dominant lever, ~19× everything else |
| lms order 4→8 | +0.79% | deeper temporal prediction *hurts* here |
| rice shift 7→8 | +0.16% | marginal |
| rice block 512→256 | +0.15% | marginal |

Search best embeddable config: `lms4s7+x6/b512`, mean 1.820×, cost 0.027, neural_ok ✅.

### Cross-channel gain vs. spatial correlation (synthetic sweep — mechanism only)
| spatial-corr | 0.6 | 0.9 |
|---|---:|---:|
| xchan gain (LMS) | +9.4% | +19.1% |

Real HD-sEMG lands at +10.8% (Hyser) to +17.4% (OTB) for the plain `+xchan` lever — same
lever, scaled by each set's real neighbour correlation.

## → The one codec to port next

**Unchanged: `LMS4+Rice+xchan_bestpartner`** for max ratio-per-cost, or **`lms4s7+x6/b512`**
(single grid-parent, order-4) for minimal hardware / zero partner side-info.

The newly promoted `LMS4bc+Rice+xchan_bestpartner` takes the **ratio** headline but does **not**
displace the port pick: cost 0.1202 vs 0.0394 (3.05×) for +0.32% on the primary, and the cost is
21 KB of context-accumulator SRAM at 128 ch (~8% of the STM32H745 budget). Port `LMS4bc` only if
that SRAM is available and the tight-array (OTB-like) corner is the target — its compute
(59 enc ops ≈71 cyc/sample-ch) still fits the tight 30 kHz neural budget.

- The essential component is still the **cross-channel grid-neighbour front-end** (+11.3–18.4%
  where redundancy exists); the temporal predictor can be as small as order-4. If minimal
  hardware is paramount, `delta+Rice+xchan` (Hyser 1.4516×, cost 0.013, fixed predictors only)
  is 98% of the best ratio.
- **Port caveat (real):** the best-partner *selection* + beta are currently derived
  **offline over the whole signal** — the reported ratio is **not** from an on-node
  encoder (see `EMBEDDED_OK_VERIFICATION.md`, `embedded_verify.py`). The streaming
  realization is **`LMS4+Rice+xchan_bestpartner_adaptive`**: per-block backward
  re-selection from the previous reconstructed block, **zero side-info, look-ahead 0**,
  holding the offline ratio within ~0.4% (and beating it on CapgMyo). **Port that one**
  if the offline selection is unacceptable on-node. The same caveat applies to `LMS4bc`,
  which reuses that identical front-end.

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
