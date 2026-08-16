# 015 — LMS4+Rice+xchan_xlag: lag-aligned (parent, delay) cross-channel predictor

- **Cycle:** 16
- **Date:** 2026-08-16
- **Branch:** `compression-cycle-2026-08-16`
- **Candidate:** `LMS4+Rice+xchan_xlag` (a.k.a. `xlag`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #1 — the *temporal alignment* of the rank-1 spatial edge)

HD-sEMG is a travelling-wave field: a MUAP propagates along the fibre at 3–5 m/s, so at
8–10 mm IED / 2 kS/s it reaches a neighbour ~4–7 samples later. Every cross-channel codec
registered so far maximizes the rank-1 gain `½log₂(1/(1−ρ²))` over *parent* but is pinned at
**d = 0**, so it can only cancel the zero-phase part of a cross-spectrum whose dominant term
should be a pure linear phase. Extending the per-block backward search from `(parent)` to
`(parent, integer delay d ∈ [0, 8])` should raise `ρ_max = max_d ρ_cp(d) ≥ ρ_cp(0)`.
Structural bonus: with `d ≥ 1` the parent sample is strictly in the past for **every** p, so
the `idx < c` raster restriction lifts and all 8 grid neighbours become legal parents. The
option set is a strict superset of the incumbent's (`no-parent` and `d=0`-with-past-parent
stay scored), so the search can only shorten the code — *modulo estimation noise*.
Standing negative control: ≈0 expected on CapgMyo (differential array already differentiates
along the fibre).

## Implementation

`research/registry.py` only (+330 lines, additive; `rtl/`, `sim/`, `host_tools/` untouched).
`_xlag_forward` / `_xlag_inverse` / `xlag_encode` / `xlag_decode`, `XLAG_DMAX = 8`,
`XLAG_SHIFT = ec.CROSS_SHIFT = 8`, block 256. Back-end held fixed to the promoted family:
order-4 sign-sign LMS (P2) + adaptive Golomb-Rice (P5), so the ONLY variable vs
`LMS4+Rice+xchan_bestpartner_adaptive` is that the search runs over `(parent, delay)`.
Selection for block *i* reads block *i−1* only (window `[(i−1)B+D, iB)`, 248 of 256 samples,
so every lagged read lands inside it), which is raw-exact on both sides before block *i*
starts — that is what makes future-index parents decodable at **zero side-info**.
Reconstruction walks time-chunks of `G` = the smallest delay any future-index parent uses,
and inside a chunk applies channels in dependency levels (one vectorized gather per level).
Integer/fixed-point only. Bit-exact on the registry gate plus a 13-case adversarial suite
(synthetic travelling-wave MUAP fields with controlled conduction velocity, 279/288
channel-blocks selecting FUTURE-index parents at mixed lags 1..8; `G=1` worst case; lags
beyond DMAX; `C` not a multiple of `cols`; 3-sample trailing block; single row/column;
all-zeros; int16 extremes; `N` < one block).

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok` OK, **`neural_ok` FAIL**, cost 0.098161),
from `results/cycle_bench.csv`:

| dataset | C | `xlag` | best `bestpartner` (0.0394) | vs best | `bestpartner_adaptive` (0.0387) |
|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.4727 | 1.4804 | **−0.52%** | 1.4770 |
| otb_hdsemg_vl | 64 | **2.0409** | 2.1619 | **−5.60%** | 2.1531 |
| capgmyo_dba_s1 | 128 | **1.3579** | 1.3505 | **+0.55%** | 1.3529 |
| cemhsey_s1_d1t1 | 320 | 1.9518 | 1.9555 | −0.19% | 1.9539 |

4-set mean 1.7058 vs best 1.7371 (−1.80%).

## Attribution — isolated cross-channel gain on REAL data

Null model = the identical back-end with the spatial front-end removed (order-4 sign-sign
LMS + adaptive Rice, 12-byte header, no side-info), measured directly:

| dataset | LMS4+Rice (temporal only) | `xlag` achieved xchan gain | `bestpartner_adaptive` |
|---|---:|---:|---:|
| hyser_1dof_f1_s1 | 1.3321× | **+10.55%** | +10.88% |
| otb_hdsemg_vl | 1.8347× | **+11.24%** | +17.36% |
| capgmyo_dba_s1 | 1.3336× | **+1.82%** | +1.45% |
| cemhsey_s1_d1t1 | 1.7280× | **+12.95%** | +13.07% |

The move is entirely in the **cross-channel front-end** — predictor (order-4 LMS) and
back-end (adaptive Rice) are byte-for-byte the incumbent's, so the temporal and entropy
levers are held exactly fixed by construction.

The strict-superset argument is **falsified in practice, and the mechanism is estimation
variance, not the physics**. Enlarging the per-block hypothesis space from ≤4 options to
≤72 `(parent, delay)` options while the sample budget stays at 248 samples/block inflates
the *selection* variance: the argmin of an empirical Rice length over 72 candidates is
biased low on the block it was fitted on and generalizes worse to the block it is applied
to. The loss is largest exactly where the true structure is most nearly rank-1 and lag-0 —
tight OTB, where the incumbent already captures +17.36% and `xlag` gives back 6.1 pp. The
one set where the extra degree of freedom **pays** is CapgMyo (+1.82% vs +1.45%): there the
lag-0 correlation is weak (|corr| ≈ 0.29) so the incumbent's estimate is itself near-noise
and a lag can find a little genuine residual structure — the opposite of the hypothesis's
prediction that CapgMyo would be the null.

## Pareto check

Cost **0.098161** — the most expensive registered codec, 2.5× the leaderboard best (0.0394)
— and the only registered codec that **fails `neural_ok`** (117 ops = 140 cyc > 125). It is
beaten on 3 of the 4 real sets by codecs that cost less than half as much.
It is **not** conclusively Pareto-dominated by any *single* registered codec, because it
holds the **CapgMyo max-ratio corner (1.3579×, the highest CapgMyo ratio of any codec in
`results/cycle_bench.csv`)**: `bestpartner_adaptive` (1.3529×) and `bestpartner` (1.3505×)
both lose there. Under the strict retire rule (worse ratio AND higher cost than an
already-registered codec) it therefore survives — but only on the negative-control set.

## Sanity gates

- Max real ratio across the whole run 2.1795× (`acar_sel+bestpartner`, otb) ≪ 6× → no leak.
  `xlag`'s own max real ratio 2.0409×.
- No FAIL bit-exact rows anywhere in the run (`bench.py` asserts; exit code 0). `ok=True`.
- **Regression flags:** −5.60% vs best on OTB (below even `delta+Rice+xchan` at 2.0410×,
  cost 0.0127, and below plain `LMS+Rice+xchan`); `neural_ok` FAIL at D=8.

## Verification

**Verifier A — REJECT. Verifier B — REJECT.** Unanimous REJECT (no split).

## Decision

**NOT promoted** — fails both promotion conditions: it does not beat the current best on
real data (loses on 3 of 4 sets, −1.80% on the 4-set mean) and its verifiers were a
unanimous REJECT, not a unanimous PROMOTE. **Not retired** — the strict rule requires
conclusive Pareto-domination on real data, and no registered codec matches or beats its
CapgMyo 1.3579×. **Flagged for human review**: a double-REJECT codec that also fails
`neural_ok` and regresses OTB by 5.6% is kept registered here only because the retire rule
is deliberately conservative; a human should decide whether the CapgMyo corner justifies
keeping it in the sweep. Headline / port pick unchanged. The **lag axis is spent NEGATIVE**
as a ratio lever (see `INSIGHTS.md` P6).
