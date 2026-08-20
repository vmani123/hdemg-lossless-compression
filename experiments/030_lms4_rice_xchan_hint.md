# 030 — LMS4+Rice+xchan_hint: quincunx/HINT two-sided spatial prediction

- **Cycle:** 31
- **Date:** 2026-08-19
- **Branch:** `compression-cycle-2026-08-19`
- **Candidate:** `LMS4+Rice+xchan_hint` (a.k.a. `xhint`), family `cross-channel`, cost **0.0371**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #1 — the *sidedness* of the spatial parent set)

Every registered cross-channel front-end predicts a channel from **one-sided**
(raster-causal) parents. Interleaved-HINT / quincunx lifting (Roos & Viergever;
Aiazzi, Alparone & Baronti, IEEE TIP 10(1):1–14, 2001) splits the grid into a
checkerboard, codes the "black" half first, and then predicts each "white"
channel from parents on **both** sides. For a smooth field a two-sided
interpolator has strictly lower prediction variance than a one-sided
extrapolator of the same order, so half the array should see a residual-entropy
drop at *zero* added side-info — the split is pure geometry, derivable on both
sides from `(C, cols)`. The single variable versus the incumbent
`LMS4+Rice+xchan_bestpartner` is the sidedness of the parent set.

**Pre-stated honest risk (from the hypothesis):** the black half loses its
dist-1 orthogonal parents (they are all white by construction) and must fall
back on dist-√2 diagonals and dist-2 orthogonals — a degradation term that must
be paid for by the white half's two-sided gain.

## Implementation

`research/registry.py` only (additive; no other codec touched; `rtl/`, `sim/`
untouched — neither exists in this tree).
- `XHINT_MAGIC=0x4849`, `_xhint_black` (geometry-only `(row+col)`-parity mask
  from `(C, cols)`, identical on both sides ⇒ **zero mask side-info**),
  `_xhint_black_cands`, `_xhint_orth`, `_xhint_predict`, `_xhint_forward`,
  `_xhint_inverse`, `xhint_encode`, `xhint_decode`.
- **Pass 1 (black, `(row+col)` even):** the incumbent rank-1 best-partner
  subtract reused verbatim (`_bp_opt_beta` integer-LS gain, `_bp_score` Rice-bits
  criterion, `BP_SHIFT=8`, 2×int16 side-info) but restricted to **same-parity**
  causal neighbours `{g−cols−1, g−cols+1, g−2, g−2·cols}` — ≤4 candidates, the
  same search width as `_bp_candidates`, so no widening (P7). Side-info emitted
  for the black half only (half the incumbent's).
- **Pass 2 (white, `(row+col)` odd):** every orthogonal dist-1 neighbour is
  black hence already reconstructed; prediction is a convex, sum-to-one,
  multiplier-free average `h=(left+right+1)>>1`, `v=(up+down+1)>>1`,
  `pred=(h+v+1)>>1`, degrading per axis at edges. Predict-only lifting, no
  update step (P3's robustness condition), total gain exactly 1 so it cannot
  over-subtract the way the retired summed `xchan_multiparent` did. No search,
  no gain fit, no side-info.
- Both sub-passes live inside **one** time slice ⇒ spatial look-ahead 0.
  Downstream unchanged: order-4 sign-sign LMS (P2) + adaptive Rice (P5).
- Integer/fixed-point throughout (`np.int64`, arithmetic `>>`).

Bit-exact on the registry gate plus extra geometries `(C, cols)` =
(1,1), (2,1), (3,16), (5,2), (7,3), (17,4), (32,64), (64,8), (33,8).

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py
LMS4+Rice+xchan_hint  2.69x          OK      OK      OK   0.037
registry self-test: ALL round-trips bit-exact
```

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.0371` on every row).

| dataset | C | `xhint` | incumbent `bestpartner` (0.0394) | vs incumbent | cheaper `joint2` (0.0366) | vs `joint2` |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | **1.458679** | 1.480384 | **−1.47%** | 1.493003 | **−2.30%** |
| otb_hdsemg_vl | 64 | **2.115166** | 2.161938 | **−2.16%** | 2.149676 | **−1.61%** |
| capgmyo_dba_s1 | 128 | **1.314593** | 1.350480 | **−2.66%** | 1.350441 | **−2.66%** |
| cemhsey_s1_d1t1 | 320 | **1.878935** | 1.955547 | **−3.92%** | 1.954270 | **−3.86%** |

4-set real mean **1.69184** vs incumbent 1.73709 (−2.60%); the *lowest*
mean-real of any active LMS-class cross-channel codec in the run.

**Synthetic (mechanism illustration only, not a result):** `xhint` is the
**top** codec on both synthetic sets — synth_sc0.6 **2.636577×** (vs
`bestpartner` 2.595983×) and synth_sc0.9 **2.615727×** (vs 2.561720×).

## Attribution — what moved the ratio, and the isolated cross-channel gain (REAL)

The temporal predictor (order-4 sign-sign LMS) and the entropy back-end
(adaptive Rice) are **byte-for-byte the incumbent's**, so 100% of the move is
the cross-channel front-end. Isolated against the shared temporal-only null
model `LMS+Rice` (`results/cycle_bench.csv`):

| dataset | `LMS+Rice` (null) | `xhint` xchan gain | incumbent `bestpartner` xchan gain | Δ (sidedness) |
|---|---:|---:|---:|---:|
| otb_hdsemg_vl | 1.825354× | **+15.88%** | +18.44% | **−2.56 pp** |
| hyser_1dof_f1_s1 | 1.329988× | **+9.68%** | +11.31% | **−1.63 pp** |
| cemhsey_s1_d1t1 | 1.729324× | **+8.65%** | +13.08% | **−4.43 pp** |
| capgmyo_dba_s1 | 1.332258× | **−1.33%** | +1.37% | **−2.70 pp** |

This is the achieved gain, not a ceiling: the two-sided front-end extracts
**less** cross-channel MI than the one-sided incumbent on **every** real set,
and on CapgMyo it is net **negative** — it costs more bits than no spatial
stage at all.

**Mechanism for the loss (two additive terms, both predicted by theory):**
1. **Unity gain vs. fitted gain.** The white half's predictor is a convex
   sum-to-one mean: it implicitly assumes `E[x_c] = E[x_neighbour]` with unit
   amplitude ratio. Real HD-sEMG neighbours differ in gain (electrode
   impedance, distance to the innervation zone, anisotropic conduction), so a
   unity-gain mean leaves the amplitude-mismatch component of the neighbour
   entirely in the residual, whereas the incumbent's fitted `β` (integer LS,
   Rice-bits-scored) removes exactly that component. Two-sided *geometry* does
   not compensate for one-sided *amplitude tracking*.
2. **Parity starvation of the black half.** Restricting black parents to
   same-parity channels deletes all dist-1 orthogonal neighbours — precisely
   the highest-MI edges under volume conduction, whose coherence decays with
   inter-electrode distance. Half the array is therefore predicted from
   strictly weaker edges. The pre-stated honest risk materialised.

The synthetic inversion is the clean confirmation: on a **stationary, smooth,
equal-amplitude** synthetic field the unity-gain two-sided interpolator is the
matched basis and wins outright (top of both synth sets); on real anisotropic
non-stationary arrays it loses everywhere. This is the same basis-match failure
mode as the retired fixed 45° integer-KLT (P3), one axis over: there the fixed
*rotation angle* was mismatched, here the fixed *unit gain* is.

## Pareto check

Cost 0.0371, `embedded_ok` OK, `neural_ok` OK. `LMS+Rice+xchan_joint2` is
**strictly cheaper (0.0366 < 0.0371) and strictly higher-ratio on all four real
sets** (−1.61% to −3.86% for `xhint`). That is conclusive Pareto domination by
an already-registered codec under the strict retire rule. It also fails to top
any real dataset and is below `delta+Rice+xchan`'s cost-efficiency corner on
mean-real-per-cost.

## Sanity gates

- Max real ratio in the whole run **2.193438×** (`LMS4bc`, OTB) ≪ 6× → no leak;
  `xhint`'s own max real is 2.115166×.
- **Zero** FAIL bit-exact rows: every row in `results/cycle_bench.csv` has
  `ok=True`; `bench.py` exited 0; registry self-test "ALL round-trips bit-exact".
- **Zero regressions** on previously-registered codecs: comparing all real-set
  rows of `results/cycle_bench.csv` against `results/consolidated_bench.csv`,
  no registered codec moved by more than 0.05% (n_changed = 0).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split (the
verifier gate is correctness/embeddability/cost only; both confirmed bit-exact
round-trip, `embedded_ok`, and the cost audit).

## Decision

**RETIRED** (`retired=True` + `retired_reason` set on the `Codec(...)`
registration). Unanimous PROMOTE satisfies promotion condition (b) but not (a) —
it loses to the current best on all four real sets — and it is additionally
**conclusively Pareto-dominated** by the cheaper `LMS+Rice+xchan_joint2` on all
four. Headline / "one codec to port next" unchanged.

The negative is high-signal: it is the first measurement that isolates
*sidedness* from *edge quality* and *gain fitting*, and it converts the "would
two-sided prediction help?" question into a settled dead end for this array
class (see `INSIGHTS.md` P11).
