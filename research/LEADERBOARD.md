# LEADERBOARD — lossless on-node compression for 128-ch RHD2164 / HD-EMG

Current best per category, the ratio-vs-cost Pareto front, per-dataset ratios, and
**the one codec to port next**. Every number is produced by the harness
(`research/bench.py` + `research/search.py`), asserted **bit-exact**, and gated by
`embedded_ok` — never by reasoning. This is a **snapshot** (overwritten each cycle);
the append-only cross-cycle ledger is `CYCLE_LOG.md`, and the durable *why* is
`INSIGHTS.md`. Read `EMBEDDED_OK_VERIFICATION.md` for what `embedded_ok` actually
proves (short version: the headline `+xchan` ratios are measured with an offline
whole-signal beta; the on-node figure is the backward-adaptive variant's).

_Last updated **2026-08-19** (branch `compression-cycle-2026-08-19`,
`CYCLE_LOG.md` rows 31–33, `results/cycle_bench.csv`, all four real sets at
15 000 samples). Three candidates measured — `LMS4+Rice+xchan_hint`,
`LMS4bcxs+Rice+xchan_bestpartner`, `LMS4vs+Rice+xchan_bestpartner` — all three
unanimous PROMOTE from both verifiers, **no verifier splits this cycle**, and
**none promoted**: none beats the current best on real data. Two were retired as
conclusively Pareto-dominated (`xchan_hint`, `LMS4vs`); `LMS4bcxs` is kept as a
new, non-dominated Pareto tip. Registry now 30 codecs, **17 active / 13
retired**. Zero bit-exact failures and zero regressions on previously-registered
codecs versus `results/consolidated_bench.csv` (nothing moved >0.05% on any real
set). The prior baseline remains the 2026-08-17 consolidation of five parallel
cycles (2026-08-05 → 2026-08-16), `CYCLE_LOG.md` rows 16–30._

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
| cemhsey_s1_d1t1 | 320 | **1.9716×** (new max, via `bcxs`) | 168% | 1.17× | lzma 2.06× |
| capgmyo_dba_s1 | 128 | **1.3638×** (via `xlag` corner) | 139% | 0.98× | — |

### Primary — real Hyser reference bar

| codec | ratio | cost | embedded_ok | note |
|---|---:|---:|:--:|---|
| lzma | 1.67× | — | ref | **offline**, not embeddable |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4851×** | 0.120 | ✅ | **best, unchanged** (30-ctx bias corrector) |
| LMS4bcxs+Rice+xchan_bestpartner | 1.4849× | 0.101 | ✅ | **new (2026-08-19)** — cross-channel-gradient bias context; dead-ties Hyser, **best 4-set mean of any codec (1.74788×) at 16% less cost**, outright CEMHSEY max 1.9716×; loses OTB −0.53% ⇒ not promoted |
| LMS4bc_lite+Rice+xchan_bestpartner | 1.4835× | 0.098 | ✅ | 27-ctx sibling; cheaper, wins CapgMyo |
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
- **No single codec wins all 4 real sets** — the front is genuinely
  multi-cornered: `LMS4bc` (Hyser/OTB), `LMS4bcxs` (CEMHSEY outright max
  1.9716× and best 4-set mean), `LMS4bc_lite` (CapgMyo among the bias family),
  `xlag` (CapgMyo outright max 1.3638×, but fails `neural_ok`).

### This cycle's candidates (2026-08-19) — measured, none promoted

| candidate | cost | hyser | otb | capgmyo | cemhsey | 4-set mean | verifiers | outcome |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `LMS4bcxs+Rice+xchan_bestpartner` | 0.101 | 1.4849 | 2.1819 | 1.3532 | **1.9716** | **1.74788** | PROMOTE / PROMOTE (unanimous) | **kept, non-dominated** — new mean-real Pareto tip; 1 win / 1 loss / 2 ties vs best ⇒ not promoted |
| `LMS4vs+Rice+xchan_bestpartner` | 0.052 | 1.4795 | 2.1556 | 1.3472 | 1.9556 | 1.73450 | PROMOTE / PROMOTE (unanimous) | **RETIRED** — dominated by `LMS4+Rice+xchan_bestpartner` (0.039, worse-or-tied on all 4 real) |
| `LMS4+Rice+xchan_hint` | 0.037 | 1.4587 | 2.1152 | 1.3146 | 1.8789 | 1.69184 | PROMOTE / PROMOTE (unanimous) | **RETIRED** — dominated by cheaper `LMS+Rice+xchan_joint2` (0.0366) on all 4 real |

No verifier split occurred this cycle, so **nothing is held for human review**.
Full attribution in `experiments/030–032`, durable learnings in `INSIGHTS.md`
P9 (refined), **P11** (two-sided spatial prediction) and **P12** (step-size rule).

## Pareto front (ratio vs cost, embedded_ok only — real Hyser)

| config | ratio | cost | neural_ok | character |
|---|---:|---:|:--:|---|
| delta+Rice+xchan | 1.453× | 0.016 | ✅ | cheapest embeddable with xchan (fixed predictors only) |
| `lms4s7+x6/b512` (search pick) | 1.478× | 0.027 | ✅ | best **value/minimal-hardware** (single parent, zero partner side-info) |
| LMS4+Rice+xchan_mst | 1.4823× | 0.046 | ✅ | cheapest front-end improvement over plain best-partner (P8) |
| LMS4+Rice+xchan_bestpartner | 1.4804× | 0.039 | ✅ | robust across all 4 sets, minimal-hardware ceiling |
| LMS4bc_lite+Rice+xchan_bestpartner | 1.4835× | 0.098 | ✅ | wins CapgMyo among the bias family (P9) |
| **LMS4bcxs+Rice+xchan_bestpartner** | 1.4849× | 0.101 | ✅ | **new front tip on 4-set mean (1.74788×)** — cross-channel bias context (P9 refined) |
| **LMS4bc+Rice+xchan_bestpartner** | **1.4851×** | 0.120 | ✅ | **best ratio** — wins Hyser+OTB (P9) |

The **mean-real-vs-cost** front, recomputed from `results/cycle_bench.csv` over
embeddable codecs (this is the axis on which `bcxs` is a strict improvement —
higher mean real ratio at 16% lower cost than the headline):
`delta+Rice` (0.0079, 1.50472) → `delta+Rice+xchan` (0.0127, 1.66622) →
`LMS+Rice+xchan_joint2` (0.0366, 1.73685) → `LMS4+Rice+xchan_bestpartner`
(0.0394, 1.73709) → `LMS4+Rice+acar_sel+bestpartner` (0.0430, 1.74149) →
`LMS4bc_lite+…` (0.0983, 1.74693) → **`LMS4bcxs+…` (0.1013, 1.74788)**.
`LMS4bc` (0.1202, 1.74673) is off this front but keeps the headline because it
holds a genuine per-dataset win on OTB (+0.53%), so it is not conclusively
dominated.

### What mattered (search ablation, re-run 2026-08-19 on real hyser+otb)

`PYTHONPATH=host_tools ./.venv/bin/python research/search.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl --max-samples 15000 --csv results/cycle_search.csv`
→ best embeddable config `lms4s7+x6/b512`, mean ratio **1.8204×**, cost 0.027,
`embedded_ok`/`neural_ok` OK, 60 configs evaluated. Search Pareto front:
`delta+x6/b512` 1.749× / 0.016, `fixed+x6/b512` 1.792× / 0.025,
`lms4s7+x6/b512` 1.820× / 0.027.

| axis | Δ ratio | |
|---|---:|---|
| cross-channel on→off | **+14.83%** (+0.2350×) | dominant lever, ~19× the next one, ~100× the rest |
| per-context bias correction on→off | **+0.20–0.92%** | second lever (P9); `bcxs` measured +0.303 hyser / +0.922 otb / +0.199 capgmyo / +0.822 cemhsey |
| lms order 4→8 | +0.79% | deeper temporal prediction *hurts* here (P2) |
| lms shift 7→8 | +0.16% | marginal |
| rice block 512→256 | +0.15% | marginal |
| lag search (any width) | **−0.25% to −1.30%** | net-negative on monopolar arrays, 5× replicated (P6/P7) |
| **step-size annealing (VS-LMS)** | **−0.06% to −0.29%** | **new, 2026-08-19**: predictor is tracking-limited, not misadjustment-limited (P12) |
| **two-sided/quincunx spatial prediction** | **−1.47% to −3.92%** | **new, 2026-08-19**: unity-gain interpolation cannot track neighbour amplitude (P11) |

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
- **Headline unchanged this cycle, but note the challenger.** `LMS4bcxs+Rice+xchan_bestpartner`
  (cost 0.101) holds the **best 4-set real mean ever measured here (1.74788× vs
  the headline's 1.74673×) at 16% lower cost**, and the outright CEMHSEY maximum
  (1.9716×). It keeps the headline only because it loses OTB by −0.528% while
  dead-tying Hyser (−0.014%) and CapgMyo (+0.001%) — 1 win, 1 loss, 2 ties is
  not "beats the best on real data". If a future cycle recovers that OTB loss
  (see `INSIGHTS.md` frontier #1/#2 — an MI-gated context class), the port pick
  changes to `bcxs` and gets *cheaper*.
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
