# 033 — LMS4bcxm+Rice+xchan_bestpartner: mixing a spatial-sign slot into the headline's magnitude context word

- **Cycle:** 34
- **Date:** 2026-08-22
- **Branch:** `compression-cycle-2026-08-22`
- **Candidate:** `LMS4bcxm+Rice+xchan_bestpartner` (a.k.a. `bcxm`), family `temporal`, cost **0.1189**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #1 — INSIGHTS frontier #2, "are the two correctors' wins additive or substitutes?")

P9's 2026-08-19 refinement left an explicit, single-variable open question. The
headline `LMS4bc` conditions its 30-bucket bias corrector on **own-channel
quantized magnitudes** — `q5(e[g,t−1]) × q3(e[g,t−2]) × sgn(d[parent,t−1])` —
and wins OTB. The challenger `LMS4bcxs` conditions 27 buckets on **spatial
signs** and wins CEMHSEY/Hyser. Frontier #2 asked whether magnitude and sign
slots, which index *different moments* of the same residual, are **additive**
(a mixed word should hold both wins) or **substitutes** (a mixed word buys
nothing and pays the dilution).

`bcxm` is the minimal test: hold **everything** byte-identical to `LMS4bc` —
30 buckets, the same 0.5×/1.5× scale-free mean-|e| thresholds, the same leaky
integrator `S += e − (S>>5)`, `mu = (S+16)>>5`, LMS adaptation on the
PRE-correction residual, the verbatim `_bp_select`/`_bp_inverse` front-end, the
verbatim order-4 sign-sign LMS, the untouched adaptive-Rice back-end, the
identical `(parent, beta)` header — and **swap exactly one slot**:

`q3(e[g,t−2])` → `sgn(d[g−1,t−1] − d[g−cols,t−1])`

Bucket budget pinned at 5×3×2 = 30 (P9: never sweep the count), factorization
and bitstream format unchanged.

## Implementation

`research/registry.py` only, purely additively (+337 lines, 0 deletions); no
other codec modified, `rtl/` and `sim/` untouched. New symbols:
`BCXM_MAGIC=0x4D58`, `BCXM_ORDER`, `BCXM_NQ1=5`, `BCXM_NQS=3`, `BCXM_NCTX=30`,
`_bcxm_neighbours`, `_bcxm_context`, `_bcxm_grad`, `_bcxm_forward`,
`_bcxm_inverse`, `bcxm_encode`, `bcxm_decode`; registration constants
`_BCXM_XTRA = _BC_XTRA + 1`, `_BCXM_STATE = _BC_STATE − 4`, `_BCXM_NOTE`.

- **Domain/timing of the new slot (load-bearing, see Attribution):** the
  gradient is the **previous-slice** one and it is taken on the **reconstructed
  signal** `d`, not on the residual `e` — `sgn(d[g−1,t−1] − d[g−cols,t−1])`.
  This is what keeps the corrector a single time-major vectorized channel sweep
  with no intra-sample channel chain, so the decoder is `LMS4bc`'s verbatim
  structure. (`bcxs`, by contrast, used the **same-slice residual** gradient
  `sgn(e[g−1,t] − e[g−cols,t])`.)
- Off-grid neighbours (column 0 has no left, row 0 has no up) contribute 0; the
  `d=0` bootstrap gives gradient sign 0 — deterministic and identical on both
  sides.
- Matched pair: at time `t` the decoder holds `d[·,t]` from the stream and
  `d[·,t−1]` from the previous iteration, recovers `e = d + mu`, and updates
  every table (mu accumulators, LMS weights, leaky mean-|e| scale, `e[t−1]`,
  `d[t−1]`) with identical arithmetic. Integer/`int64` throughout, no float.
- **Zero side-info (P4)**, look-ahead 0, block `ec.BLOCK`.
- Cost accounting: net ~+1 op/sample-ch vs `LMS4bc`'s 22 (+2 neighbour gathers,
  +1 subtract, +1 sign test, −2 `q2` compares, −1 register shift); state
  `_BC_STATE − 4 + _BP_STATE` ≈ 132 B/ch for the bias stage (the `e[t−2]`
  register is freed) → ~17 KB at 128 ch. No multiply, no divide, no new state
  class. Cost **0.1189** vs `LMS4bc`'s 0.1202.

**Mechanism verified non-null before measuring:** on a 32×2000 correlated
synthetic field the spatial slot's occupancy (levels 0/1/2) is
**47.6% / 5.2% / 47.3%** — near-balanced, genuinely driving bucket selection,
not degenerate to one level. The bitstream differs from `LMS4bc`'s on every
multi-channel shape tested.

Extra round-trip stress beyond the gate, all bit-exact: `(C,N,cols)` =
(1,1,16), (1,300,16), (3,50,16), (17,400,4), (64,600,16), (33,257,8) including a
non-rectangular channel count and a spike burst; plus saturation fields of all
−32768, all +32767, and full-range uniform random int16.

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest
LMS4bcxm+Rice+xchan_bestpartner  2.72x          OK      OK      OK   0.119
registry self-test: ALL round-trips bit-exact
```

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.1189`).

| dataset | C | `bcxm` (0.1189) | best `bc` (0.1202) | vs best | `bcxs` (0.1013) | vs `bcxs` | bias-free `bestpartner` (0.0394) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.484662 | **1.485085** | −0.028% | 1.484874 | −0.014% | 1.480384 (+0.289%) |
| otb_hdsemg_vl | 64 | 2.191593 | **2.193438** | −0.084% | 2.181863 | **+0.446%** | 2.161938 (+1.372%) |
| capgmyo_dba_s1 | 128 | 1.351343 | **1.353146** | −0.133% | 1.353163 | −0.135% | 1.350480 (+0.064%) |
| cemhsey_s1_d1t1 | 320 | 1.955021 | 1.955254 | −0.012% | **1.971616** | −0.842% | 1.955547 (−0.027%) |

Synthetic: sc0.6 2.592958×, sc0.9 2.558826× — both **below** `bc` (2.593270 /
2.559087) and far below `bcxs` (2.623350 / 2.598751). 4-set real mean
**1.74565×**, below `bc` (1.74673) and `bcxs` (1.74788).

## Attribution — what moved the ratio and why

The temporal predictor, the cross-channel front-end and the Rice back-end are
byte-identical to `LMS4bc`'s, the bucket count is pinned, and the bitstream
layout is unchanged. **The entire move is the one swapped context slot.**

**Isolated effect of the slot swap** (`bcxm` − `bc`, expressed as pp added to
the isolated bias-stage contribution measured against the shared bias-free
`LMS4+Rice+xchan_bestpartner` null):

| dataset | C | bias stage, `bc` | bias stage, `bcxm` | Δ from the swap |
|---|---:|---:|---:|---:|
| hyser_1dof_f1_s1 | 128 | +0.318% | +0.289% | **−0.029 pp** |
| otb_hdsemg_vl | 64 | +1.457% | +1.372% | **−0.085 pp** |
| capgmyo_dba_s1 | 128 | +0.197% | +0.064% | **−0.133 pp** |
| cemhsey_s1_d1t1 | 320 | −0.015% | −0.027% | **−0.012 pp** |

**The answer to frontier #2 is: substitutes, and worse than either pure form.**
The mixed word loses to `bc` on all four real sets and loses to `bcxs` on three
of four. It is not a "best of both" — it is below both parents everywhere
except OTB, where it beats `bcxs` (+0.446%) precisely because it retained two of
`bc`'s three magnitude slots.

**Theory — two mechanisms, one of which the measurement can separate.**

1. **Domain, not spatiality, is what made `bcxs`'s slot informative.** `bcxs`
   conditioned on the **same-slice residual** gradient
   `sgn(e[g−1,t] − e[g−cols,t])`; `bcxm` conditions on the **previous-slice
   reconstructed-signal** gradient `sgn(d[g−1,t−1] − d[g−cols,t−1])`. A context
   is worth exactly `I(e_c ; ctx)`. The signal-domain neighbour gradient is
   dominated by the shared far-field volume-conducted mode — which is precisely
   the component that the best-partner subtract and then the order-4 LMS
   high-pass have **already removed** from `e_c` (P10's mechanism, read
   forwards). Conditioning the residual's bias on a statistic of the component
   that has been removed from it yields near-zero mutual information. The
   residual-domain gradient carries MI because it lives in the same domain as
   the quantity being predicted. This is the dominant term: the same *spatial*
   slot gains +0.067…+0.090 pp in residual domain (`bcxs`, cycle 32) and loses
   −0.012…−0.133 pp in signal domain (here) on the same three high-MI arrays.
2. **Slot redundancy inside a fixed bucket budget.** Even setting domain aside,
   `q3(e[g,t−2])` (a **second-moment**, magnitude statistic) and the retained
   `sgn(d[parent,t−1])` (a **first-moment**, direction statistic) already
   between them index the local-activity state; adding a second direction-class
   slot buys a small conditional-MI increment while paying the full dilution
   cost of the 30-bucket budget. Two independently-winning slot classes are not
   additive when they are alternative parameterizations of the same latent
   variable.

The CapgMyo control is consistent and sharpens the reading: the swap's largest
loss (−0.133 pp) is on the **differential** array where P1 says there is no
neighbour MI at all — exactly where a spatial slot of *any* domain must be pure
bucket-splitting noise. The pre-registered risk in the implementation note
("expect the spatial slot to cost about what `bcxs` paid there, −0.045 pp")
under-predicted the loss by ~3×, which is itself evidence for mechanism (1):
the signal-domain slot is not merely uninformative, it is *more* uninformative
than the residual-domain one.

**No cross-channel front-end lever to isolate.** `bcxm` carries the incumbent
`+xchan_bestpartner` front-end verbatim; its isolated cross-channel gain is
therefore the incumbent's (+11.31% Hyser / +18.44% OTB / +1.37% CapgMyo /
+13.08% CEMHSEY vs the shared `LMS+Rice` null). Nothing here is a claim about
the spatial front-end.

## Pareto check

Cost 0.1189, `embedded_ok` OK, `neural_ok` OK. On the mean-real-vs-cost front
(embeddable codecs, `results/cycle_bench.csv`):

```
cost=0.0079 mean_real=1.50472  delta+Rice
cost=0.0127 mean_real=1.66622  delta+Rice+xchan
cost=0.0366 mean_real=1.73685  LMS+Rice+xchan_joint2
cost=0.0394 mean_real=1.73709  LMS4+Rice+xchan_bestpartner
cost=0.0430 mean_real=1.74149  LMS4+Rice+acar_sel+bestpartner
cost=0.0983 mean_real=1.74693  LMS4bc_lite+Rice+xchan_bestpartner
cost=0.1013 mean_real=1.74788  LMS4bcxs+Rice+xchan_bestpartner   <-- front tip
```

`bcxm` (0.1189, 1.74565) is **off** this front. It is nonetheless **not
conclusively Pareto-dominated** in the per-dataset sense the retirement rule
requires: the only codec that beats it on all four real sets is `LMS4bc`, and
`LMS4bc` is **more expensive** (0.1202 > 0.1189). Every cheaper codec
(`bcxs` 0.1013, `bc_lite` 0.0983, `xlag` 0.1063, `mst` 0.0464, `acar_sel`
0.0430) loses to it on at least one real set — `bcxs` and `bc_lite` both lose
OTB, where `bcxm`'s retained magnitude slots hold 2.191593× against their
2.181863× / 2.180401×.

Verdict: **kept registered, not retired**, on a 1.1%-cost technicality — and
explicitly **flagged as the leading retirement candidate for the next cycle**
(the precedent is `bprank`, cycle 23). It survives the letter of the rule, not
its spirit.

## Sanity gates

- Max real ratio in the run 2.194780× (OTB, `bcpool`) ≪ the 6× ceiling;
  `bcxm`'s own max real 2.191593×.
- Zero FAIL bit-exact rows: `ok=True` on all 156 rows of
  `results/cycle_bench.csv`; `bench.py` exited 0; registry self-test "ALL
  round-trips bit-exact".
- Zero regressions on previously-registered codecs: nothing moved >0.05% on any
  real set versus `results/consolidated_bench.csv`.
- Four real-set regressions **by the candidate itself** vs the leaderboard best
  (−0.012…−0.133%). Recorded; not fatal (not a domination, see Pareto check).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** Promotion condition (b)
(unanimous PROMOTE) is met; condition (a) is not — `bcxm` loses to
`LMS4bc+Rice+xchan_bestpartner` on all four real sets. The headline and the
"one codec to port next" pick are unchanged.

The value of this candidate is the **negative answer it closes**: INSIGHTS
frontier #2 asked whether the magnitude and spatial-sign context classes are
additive. They are not, and the failure is informative rather than merely null —
it localizes `bcxs`'s win in the **residual domain** of its gradient, not in its
spatiality. See `INSIGHTS.md` P9 (refined) and the new dead-end entry.
