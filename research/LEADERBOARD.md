# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated after the 2026-08-17 consolidation of five cycles
(2026-08-05 → 2026-08-16) that ran in parallel, blind to each other, and were
merged into one PR (see `CYCLE_LOG.md` rows 16–30 for the full per-cycle
detail and the naming-collision/duplicate-mechanism resolution notes). 27
codecs benched (11 retired), all four real sets at 15 000 samples:
`results/consolidated_bench.csv`._

## Best: `LMS4bc+Rice+xchan_bestpartner` (cost 0.120)

Order-4 sign-sign LMS + best-of-4 causal-neighbour cross-channel subtract +
a JPEG-LS/CALIC-style backward-adaptive per-context running-mean bias
corrector (30 buckets, divisionless, zero side-info) applied to the residual
before Rice coding. Beats the prior best on 3 of 4 real sets (CEMHSEY is a
−0.02% dead tie); only offline LZMA is ahead on Hyser/CEMHSEY.

| dataset | ch | best ratio | %-of-FLAC | FLAC | best offline ref |
|---|--:|--:|--:|--:|---|
| **hyser_1dof_f1_s1** (primary) | 128 | **1.4851×** | 152% | 0.98× | lzma 1.67× |
| otb_hdsemg_vl | 64 | **2.1934×** | 179% | 1.23× | — (beats every offline ref) |
| cemhsey_s1_d1t1 | 320 | **1.9553×** (or 1.970× via `_lite`) | 168% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.3638×** (via `xlag` corner) | 139% | 0.98× | — |

### Primary — real Hyser reference bar

| codec | ratio | cost | embedded_ok | note |
|---|---:|---:|:--:|---|
| lzma | 1.67× | — | ref | **offline**, not embeddable |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4851×** | 0.120 | ✅ | **new best** (30-ctx bias corrector) |
| LMS4bc_lite+Rice+xchan_bestpartner | 1.4835× | 0.098 | ✅ | 27-ctx sibling; cheaper, wins CapgMyo+CEMHSEY instead |
| LMS4+Rice+xchan_bprank | 1.4952× | 0.055 | ✅ | wins Hyser alone but below both its own branches on 3/4 sets — not robust |
| LMS4+Rice+xchan_jointbp2 | 1.497× | 0.047 | ✅ | max-Hyser corner (unchanged) |
| LMS4+Rice+xchan_mst | 1.4823× | 0.046 | ✅ | Chow-Liu spatial structure; cheapest improvement over plain best-partner |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.039 | ✅ | prior best; minimal-hardware pick |
| zstd-19 | 1.44× | — | ref | offline |
| wavpack | 1.34× | — | ref | best embeddable-class per-channel ref |
| flac | 0.98× | — | ref | target to beat (expands here) |

- **Achieved cross-channel + bias gain on Hyser: +11.5%** over `LMS+Rice`
  (1.332× → 1.4851×); cross-channel decorrelation remains the dominant term
  (P1), the bias corrector adds a further +0.3–1.5% on top (P9).
- Max real ratio 2.19× ≪ the 6× sanity ceiling → honest broadband EMG.
- **No single codec wins all 4 real sets** for the first time — the front is
  genuinely multi-cornered: `LMS4bc` (Hyser/OTB), `LMS4bc_lite` (CapgMyo tie
  /CEMHSEY), `xlag` (CapgMyo outright max 1.3638×, but fails `neural_ok`).

## Pareto front (ratio vs cost, embedded_ok only — real Hyser)

| config | ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice+xchan | 1.453× | 0.016 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | 1.478× | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS4+Rice+xchan_mst | 1.4823× | 0.046 | ✅ | cheapest front-end improvement over plain best-partner (P8) |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.039 | ✅ | robust across all 4 sets, minimal-hardware ceiling |
| LMS4bc_lite+Rice+xchan_bestpartner | 1.4835× | 0.098 | ✅ | wins CapgMyo+CEMHSEY (P9) |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4851×** | 0.120 | ✅ | **best ratio** — wins Hyser+OTB (P9) |

### What mattered (search ablation from best, real Hyser)
| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+10.8%** | dominant lever, ~70× everything else |
| per-context bias correction on→off | **+0.3–1.5%** | new second lever (P9), temporal axis |
| lms order 4→8 | +0.15% | deeper temporal prediction *hurts* here |
| rice block 512→256 | +0.13% | marginal |
| lag search (any width) | **−0.25% to −1.30%** | net-negative on monopolar arrays, 5x replicated (P6/P7) |

### Cross-channel gain vs. spatial correlation (synthetic sweep — mechanism only)
| spatial-corr | 0.0 | 0.3 | 0.6 | 0.9 |
|---|---:|---:|---:|---:|
| xchan gain (LMS) | −0.1% | +1.4% | +9.4% | +19.1% |

Real HD-sEMG lands at +10.8% (Hyser) to +17.4% (OTB) — same lever, scaled by each
set's real neighbour correlation.

## → The one codec to port next

**`LMS4bc+Rice+xchan_bestpartner`** for max ratio (3× the incumbent's cost for
+0.3–1.5% ratio), **`LMS4+Rice+xchan_mst`** for the best cheap upgrade over the
prior best (cost 0.046, +0.1–0.4% on 3/4 sets), or **`LMS4+Rice+xchan_bestpartner`**
/ **`lms4s7+x6/b512`** for minimal hardware — pick by SRAM/compute budget, not by
ratio alone (`embedded_ok` is a hard gate, never rank on ratio in isolation).

- The essential component remains the **cross-channel grid-neighbour front-end**
  (+10.8–17.4% where redundancy exists); the bias corrector (P9) adds a further,
  smaller +0.3–1.5% on top and is the first positive result on the temporal axis
  since the predictor order/coefficient-count/quadratic-form levers closed (P2).
  If minimal hardware is paramount, `delta+Rice+xchan` (Hyser 1.45×, cost 0.016,
  fixed predictors only) is still ~98% of the pre-bias-corrector ratio.
- **Port caveat (real), unchanged:** the best-partner *selection* + beta underlying
  every codec on this page are still derived **offline over the whole signal** —
  see `EMBEDDED_OK_VERIFICATION.md`. The streaming realization is
  **`LMS4+Rice+xchan_bestpartner_adaptive`**: per-block backward re-selection,
  **zero side-info, look-ahead 0**, holding the offline ratio within ~0.4%. The
  bias-corrector stage itself is already fully backward-adaptive / zero side-info
  in both `LMS4bc` variants — only the front-end they sit on carries the caveat.
- **Branch-hygiene note for future cycles:** this leaderboard update exists
  because five consecutive automated cycles (2026-08-05 → 2026-08-16) each
  branched from the same stale `main` instead of from the latest unmerged PR,
  so none could see another's work — see `CYCLE_LOG.md`'s consolidation note
  above rows 16–30. Future cycles should rebase onto the latest merged `main`
  (not just re-fetch it) before surveying, and this repository's operators
  should merge each cycle's PR before the next cycle starts wherever practical.

## Status vs. the 6-stage plan
All stages complete: registry + cost model, real corpus (Hyser/OTB/CEMHSEY-320/CapgMyo,
cached offline under `sim_data/corpus_npz/`), benchmark, search (Pareto + ablations),
survey, and this report. Hyser is the primary headline; CapgMyo is the negative control.
