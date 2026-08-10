# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after cycle 2026-08-10 (20 codecs benched, 120/120 rows bit-exact, 9
retired). All four real sets benched at 15 000 samples: `results/cycle_bench.csv`;
search: `results/cycle_search.csv`._

## Best embeddable: `LMS4bc+Rice+xchan_bestpartner` (cost 0.098) — **NEW this cycle**

Order-4 sign-sign LMS + per-channel best-of-4 causal-neighbour cross-channel subtract
+ a **JPEG-LS-style context-conditioned integer bias corrector** (27 sign contexts,
divisionless, zero side-info) between the predictor and the adaptive Golomb-Rice coder.
The only candidate since cycle 7 to **beat the previous best on all four real sets**
(+0.21…+0.85%, mean +0.51%) — see `experiments/017_*`.

| dataset | ch | best-emb ratio | vs prior best | %-of-FLAC | FLAC | best offline ref |
|---|--:|--:|--:|--:|--:|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.4835×** | +0.213% | 152% | 0.98× | lzma 1.67× |
| otb_hdsemg_vl | 64 | **2.1804×** | +0.854% | 178% | 1.23× | wavpack 1.85× (emb-class), lzma 1.58× (beaten) |
| cemhsey_s1_d1t1 | 320 | **1.9700×** | +0.739% | 168% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.3538×** | +0.244% | 138% | 0.98× | wavpack 1.35× (beaten) |

Prior best `LMS4+Rice+xchan_bestpartner` (cost 0.039): 1.4804 / 2.1619 / 1.9555 / 1.3505.
It is **not** retired — the new best is higher ratio *and* higher cost, so both stay on
the front; the cheap one remains the value/port-economy pick.

### Primary — real Hyser reference bar

| codec | ratio | cost | embedded_ok | note |
|---|---:|---:|:--:|---|
| lzma | 1.6674× | ref | ref | **offline**, not embeddable |
| LMS4+Rice+xchan_jointbp2 | 1.4969× | 0.047 | ✅ | max-Hyser corner; regresses OTB/CEMHSEY → never promoted |
| LMS4+Rice+xchan_bprank | 1.4952× | 0.055 | ✅ | this cycle; wins Hyser, below **both** its own branches on 3 of 4 sets |
| LMS+Rice+xchan_joint2 | 1.4930× | 0.037 | ✅ | zero-side-info joint 2-parent |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4835×** | 0.098 | ✅ | **best embeddable** (only codec ≥ prior best on all 4 real sets) |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.039 | ✅ | prior best; value corner |
| LMS4+Rice+xchan_xlag | 1.4684× | 0.106 | ✅ (neural ✗) | this cycle; lag axis, −6.1% on OTB |
| zstd-19 | 1.4399× | ref | ref | offline |
| mtscomp | 1.4145× | ref | ref | neuro per-channel reference |
| wavpack | 1.3366× | ref | ref | best embeddable-class per-channel ref |
| LMS+Rice | 1.3300× | 0.052 | ✅ | temporal only (no cross-channel) |
| flac | 0.9774× | ref | ref | target to beat (expands here) |

- Beats every embeddable-feasible reference (WavPack, mtscomp, even offline zstd-19)
  at a fraction of the compute, bit-exact. **Achieved cross-channel gain +11.5%** on
  Hyser (LMS 1.3300× → 1.4835×), **+19.5%** on OTB, **+13.9%** on CEMHSEY — the highest
  achieved xchan gain of any registered codec on OTB and CEMHSEY, and still the dominant lever.
- Max real ratio 2.1804× ≪ the 6× sanity ceiling → honest broadband EMG. No FAIL rows.
- Cross-channel gain **tracks real spatial redundancy**: strong where neighbour |corr|
  is 0.73–0.79 (Hyser/OTB/CEMHSEY), ~+1.6% on CapgMyo (|corr| 0.29). CapgMyo is the negative
  control — the harness reports gain only where the signal carries it.

### Non-dominated corners kept this cycle (registered, not promoted)

| codec | corner it holds | cost | why not promoted |
|---|---|---:|---|
| LMS4+Rice+xchan_jointbp2 | max Hyser 1.4969× | 0.047 | regresses OTB −0.45%, CEMHSEY −0.17% |
| **LMS4+Rice+xchan_xlag** | max CapgMyo **1.3638×** | 0.106 | −6.13% OTB; **fails `neural_ok`** (154 > 125 cyc) |
| **LMS4+Rice+xchan_bprank** | +0.087% over `jointbp2` on CapgMyo only | 0.055 | below **both** its branches on otb/capgmyo/cemhsey; near-dominated by `jointbp2` — **first retirement candidate next cycle** |
| LMS4+Rice+acar_sel+bestpartner | tight-array CAR cascade, OTB 2.1795× | 0.043 | now beaten on OTB by `LMS4bc` (2.1804×) |
| LMS4+Rice+xchan_bestpartner_adaptive | zero-side-info streaming realization | 0.039 | never a ratio play — the embeddability lever (P4) |

## Pareto front (ratio vs cost, embedded_ok only — real Hyser)

| config | ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice+xchan | 1.4516× | 0.013 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | 1.478× | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS+Rice+xchan_joint2 | 1.4930× | 0.037 | ✅ | zero-side-info joint 2-parent |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.039 | ✅ | robust cheap corner across all 4 sets |
| LMS4+Rice+xchan_jointbp2 | 1.4969× | 0.047 | ✅ | max-Hyser corner |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4835×** | 0.098 | ✅ | **new best: max ratio on OTB + CEMHSEY, ≥ prior best on all 4** |

Cost 0.098 is dominated by the 27-context table's SRAM (141 B/ch = 18.0 KB at 128 ch),
not compute (+8 ops/sample-ch, enc 45 / dec 37) — a context-count reduction is the
obvious way to pull the new best down the cost axis.

### What mattered (search ablation from best, `results/cycle_search.csv`, hyser+otb mean)
| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+14.83%** | dominant lever, ~19× everything else |
| lms order 4→8 | +0.79% | deeper temporal prediction *hurts* here |
| rice shift 7→8 | +0.16% | marginal |
| rice block 512→256 | +0.15% | marginal |

Search best embeddable config: `lms4s7+x6/b512`, mean ratio 1.8204×, cost 0.0271,
`embedded_ok`+`neural_ok`; Pareto front 3 configs (`delta+x6/b512` 1.7487×/0.0163,
`fixed+x6/b512` 1.7918×/0.0252, `lms4s7+x6/b512` 1.8204×/0.0271), 60 configs evaluated.

### Cross-channel gain vs. spatial correlation (synthetic sweep — mechanism only)
| spatial-corr | 0.0 | 0.3 | 0.6 | 0.9 |
|---|---:|---:|---:|---:|
| xchan gain (LMS) | −0.1% | +1.4% | +9.4% | +19.1% |

Real HD-sEMG lands at +10.8% (Hyser) to +17.4% (OTB) for the plain `+xchan` pair —
same lever, scaled by each set's real neighbour correlation.

## → The one codec to port next

**`LMS4bc+Rice+xchan_bestpartner`** for max ratio, or **`lms4s7+x6/b512`** (single
grid-parent, order-4) for minimal hardware / zero partner side-info.

- The essential component is still the **cross-channel grid-neighbour front-end**
  (+11.5–19.5% where redundancy exists); the temporal predictor can be as small as
  order-4. The new increment on top of it is the **context bias corrector**, worth
  +0.21…+0.85% for +8 ops/sample-ch and a 27-entry table. If minimal hardware is
  paramount, `delta+Rice+xchan` (Hyser 1.45×, cost 0.013, fixed predictors only) is
  still ~98% of the best ratio.
- **Port caveat (real, unchanged and inherited):** `LMS4bc` sits on the **offline
  whole-signal** best-partner *selection* + β, transmitted as side-info — exactly like
  the codec it displaces (see `EMBEDDED_OK_VERIFICATION.md`, `embedded_verify.py`), so
  the headline ratio is **not** from an on-node encoder. The **bias stage itself is pure
  streaming: zero side-info, look-ahead 0, divisionless.** The streaming realization of
  the *front-end* is **`LMS4+Rice+xchan_bestpartner_adaptive`** (per-block backward
  re-selection, holds the offline ratio within ~0.4%). **The bias stage stacked on the
  adaptive front-end is not yet measured — that is this cycle's top open item** and must
  be measured before quoting 1.4835×/2.1804× as an on-node number.
- `LMS4+Rice+xchan_xlag` **fails the 30 kS/s neural budget** (154 > 125 cyc/sample-ch),
  the first registered codec to do so; it is sEMG-embeddable only.

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
