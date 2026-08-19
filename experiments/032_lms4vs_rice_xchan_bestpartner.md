# 032 — LMS4vs+Rice+xchan_bestpartner: per-tap sign-agreement variable-step sign-sign LMS

- **Cycle:** 31
- **Date:** 2026-08-19
- **Branch:** `compression-cycle-2026-08-19`
- **Candidate:** `LMS4vs+Rice+xchan_bestpartner` (a.k.a. `LMS4vs`), family `temporal`, cost **0.0516**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #3 — the *adaptation law* of the sign-sign LMS)

P2 closed predictor **order** and **coefficient-set count**; P9 changed the
residual's first moment but not the predictor. The one untouched degree of
freedom in the temporal stage is the **step-size rule**. Classical VS-LMS
(Harris, Chabries & Bishop, IEEE TASSP 34(2):309–316, 1986): a constant step is
a fixed compromise between convergence/tracking speed and steady-state
misadjustment; annealing the step per tap on gradient-sign agreement should hold
tracking speed during transients while cutting steady-state gradient noise —
i.e. lower excess MSE ⇒ lower residual entropy ⇒ fewer Rice bits, at zero
side-info and no change to the update *direction*.

## Implementation

`research/registry.py` only (additive; no other codec touched; the cycle's other
two candidates intact).
- Order stays 4; **one** coefficient set; update direction unchanged
  (`g_i = sign(e)·sign(h_i)`).
- Per tap, a 4-bit saturating counter `cnt_i ∈ [0,15]`: `+1` when `g_i` agrees
  with the last non-zero gradient sign, `−1` when it alternates, hold when
  `g_i == 0`. `VS_HYST=2` ⇒ 4 counts of hysteresis per step level, so the step
  cannot flip every sample.
- Step shift is the counter's top bits: `w_i += g_i << (cnt_i >> 2)`. Shifts
  only — multiply-free and divide-free (the divisionless VS-LMS realization
  preferred to NLMS on the FPGA target).
- **Key design point:** the weight fixed point gains `SMAX=3` fractional bits
  (`VS_SHIFT = ec.LMS_SHIFT + 3 = 11`) so annealing reaches *below* the
  incumbent's step. The coarsest step (`1<<3` in the finer units) is **exactly**
  the incumbent's constant ±1 and the finest is 1/8 of it. Counters initialize
  saturated high, so at `t=0` the filter is behaviourally identical to
  `LMS4+Rice+xchan_bestpartner` (weights merely 8× scaled) and can only anneal
  away from it — the incumbent is this design's exact fast-tracking corner.
- `_vs_update()` is called from both `_vs_forward` and `_vs_inverse` with
  identical arguments; counters, remembered gradient signs, step and weights all
  evolve from causally-available reconstructed history. **Zero temporal
  side-info**; the only side-info is the best-partner `(parent, β)` pair, reused
  verbatim from `_bp_select`/`_bp_inverse` exactly as the incumbent does.
- Respects P2 (order 4, one coefficient set — distinct from retired `LMS4rs`;
  functional form untouched — distinct from retired `LMS4v2`), P4, P5, P7
  (scalar counter state, not an argmin over K hypotheses — no winner's curse).
- All `np.int64`; no float anywhere in the codec path.

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py
LMS4vs+Rice+xchan_bestpartner  2.72x          OK      OK      OK   0.052
registry self-test: ALL round-trips bit-exact
```

Diagnostic on the synthetic self-test field (mechanism check, **not** a
benchmark): step-shift occupancy across the four levels
[1/8, 1/4, 1/2, 1× incumbent] was [0.242, 0.247, 0.252, 0.258] — the annealing
genuinely engages rather than pinning at one level; total Rice bits 464418 (vs)
against 464575 (incumbent) on identically best-partner-decorrelated input
(−0.03%).

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.0516`).

| dataset | C | `LMS4vs` (0.0516) | incumbent `LMS4+Rice+xchan_bestpartner` (0.0394) | vs incumbent |
|---|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.479529 | 1.480384 | **−0.058%** |
| otb_hdsemg_vl | 64 | 2.155639 | 2.161938 | **−0.291%** |
| capgmyo_dba_s1 | 128 | 1.347197 | 1.350480 | **−0.243%** |
| cemhsey_s1_d1t1 | 320 | 1.955617 | 1.955547 | **+0.0036%** (dead tie) |

4-set real mean **1.734498** vs incumbent **1.737088** (−0.15%).

**Synthetic (mechanism illustration only):** synth_sc0.6 2.596442× vs incumbent
2.595983× (**+0.018%**); synth_sc0.9 2.562242× vs 2.561720× (**+0.020%**).

## Attribution — what moved the ratio

The cross-channel front-end (`_bp_select`/`_bp_inverse`) and the Rice back-end
are byte-identical to the incumbent's, and there is no new side-info, so 100% of
the move is the **temporal adaptation law**. There is no `+xchan` lever of its
own to isolate; for completeness the front-end's contribution measured through
this codec (vs the shared `LMS+Rice` null) is +11.24% Hyser / +18.09% OTB /
+13.09% CEMHSEY / +1.12% CapgMyo — in every case *slightly below* the
incumbent's (+11.31 / +18.44 / +13.08 / +1.37), i.e. the annealed predictor
returns a marginally worse-conditioned residual to an unchanged spatial stage.

**Mechanism.** The result is a clean sign flip between stationary and
non-stationary data: `LMS4vs` **wins both synthetics** (+0.018%, +0.020%) and
**loses three of four real sets** (−0.06% to −0.29%, CEMHSEY a dead tie). That
is the textbook VS-LMS trade appearing with the wrong sign for this signal.
Steady-state excess MSE of sign-sign LMS scales with the step, so annealing
reduces *misadjustment variance* — which is exactly what pays off on the
synthetic near-stationary AR field. But tracking lag on a time-varying optimum
scales *inversely* with the step, and real HD-sEMG is strongly non-stationary at
the block scale (MUAP bursts, recruitment/derecruitment, amplitude modulation at
tens of ms). The measurement says the order-4 sign-sign LMS on real HD-sEMG sits
on the **tracking-limited** side of the trade, not the misadjustment-limited
side: any step reduction costs more in lag-induced prediction error than it
recovers in gradient noise. The incumbent's constant ±1 is therefore not an
untuned hyperparameter with headroom — it is at or past the optimum for this
signal class, and the design's own fast-tracking corner (counters saturated
high) is the best point in its own family.

This closes the loop with P9: the excess entropy left in the post-LMS residual
is a context-conditional **first moment** (a bias, removable by the P9
corrector — `bcxs` in this same cycle takes +0.30…+0.92% out of it) and **not** a
step-size **variance** term. Reducing predictor variance and removing predictor
bias are not substitutes here; only the bias term is live.

## Pareto check

Cost 0.0516 vs the incumbent's 0.0394 (+31%: `_VS_XTRA` 12 extra ops/sample-ch,
+9 B/ch state → 5120 B at 128 ch), `embedded_ok` OK, `neural_ok` OK.
`LMS4+Rice+xchan_bestpartner` is cheaper **and** higher-ratio on Hyser, OTB and
CapgMyo, with CEMHSEY a +0.0036% dead tie (well inside the ±0.02% convention
this repo already used to call `LMS4bc`'s −0.015% CEMHSEY result a tie), and a
higher 4-set mean. `LMS4vs` tops **no** real dataset and sits below the mean-real
Pareto front at its cost. Conclusively dominated.

## Sanity gates

- Max real ratio in the run 2.193438× ≪ 6×; `LMS4vs`'s own max real 2.155639×.
- Zero FAIL bit-exact rows (`ok=True` on all 150 rows, `bench.py` exit 0,
  registry self-test "ALL round-trips bit-exact").
- Zero regressions on previously-registered codecs vs
  `results/consolidated_bench.csv` (nothing moved >0.05%).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**RETIRED** (`retired=True` + `retired_reason` set on the `Codec(...)`
registration). Unanimous PROMOTE satisfies condition (b) but not (a), and the
codec is additionally conclusively Pareto-dominated on real data by the cheaper
`LMS4+Rice+xchan_bestpartner`. Headline unchanged.

The value of the negative is that it **closes the last untouched degree of
freedom in the temporal stage** — order (P2), coefficient-set count (P2),
functional form (`LMS4v2`, retired), and now the step-size rule — with a clear
theoretical reason (tracking-limited, not misadjustment-limited) rather than a
bare number. See `INSIGHTS.md` P12.
