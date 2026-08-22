# 034 — LMS4+Rice+xchan_cmean: one composite (noise-averaged) virtual parent with a fitted gain

- **Cycle:** 35
- **Date:** 2026-08-22
- **Branch:** `compression-cycle-2026-08-22`
- **Candidate:** `LMS4+Rice+xchan_cmean` (a.k.a. `cmean`), family `cross-channel`, cost **0.0466**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #2 — spatial front-end, estimator SNR)

Every cross-channel front-end in the registry regresses the target channel on a
**single selected** parent. That parent is itself a noisy measurement of the
shared volume-conducted mode, so the fitted gain suffers classical
**errors-in-variables attenuation** (regression dilution, Fuller 1987): the
rank-1 subtract removes less than the true shared component, and what it does
remove it contaminates with the parent's own independent noise. Averaging `K`
causal neighbours should raise the regressor's SNR by ~`K` and let a single
fitted gain remove more of the shared mode.

Construction: replace the selected parent with **one composite virtual parent**
`m[g,t] = (Σ_i s_i·x[i,t]) >> log2(K)`, `K = 4` **fixed** causal grid slots
(left, up, up-left, up-right; off-grid contribute 0), `s_i` a backward alignment
sign from the previous reconstructed block; then the family's **verbatim**
rank-1 subtract with **one** integer-LS gain fitted against `m`. LMS4 and Rice
unchanged, parents left bit-clean. Critically this **removes** the per-block
parent argmin rather than widening it — no selection, hence no P7 selection
variance.

## Implementation

`research/registry.py` only (`rtl/`, `sim/` untouched; the `bcxm` candidate
registered earlier this cycle preserved). New symbols: `XCM_MAGIC=0x434D`,
`XCM_BLOCK=ec.BLOCK` (256), `XCM_SHIFT=BP_SHIFT` (8), `XCM_LOG2K=2`,
`XCM_ORDER=LMS4_ORDER`; `_xcm_slots`, `_xcm_signs`, `_xcm_composite`,
`_bp_opt_beta`, `_xcm_forward`/`_xcm_inverse`, `xcm_encode`/`xcm_decode`
(12-byte header, **no side-info at all**).

- `_xcm_slots(g,cols,C)`: the `K=4` **fixed** slots, `−1` = off-grid (contributes
  0, so the `>>2` stays a constant shift and the fitted gain absorbs the
  edge-channel scale). Every live slot has grid index `< g`.
- `_xcm_signs`: `s_i = +1 if int((x_g·x_i).sum()) >= 0 else −1` over the
  **previous** block — an alignment sign, not a selection.
- `_bp_opt_beta`: the family's verbatim rounded integer-LS gain, int16-clamped.
  `beta == 0` → the stage is the exact identity (a *fitted* zero, not a scored
  option; there is zero selection anywhere in the codec).
- Matched pair: encoder and decoder run byte-identical sign+beta derivation from
  the previous reconstructed block; channels ascending in `g` (all slots `< g`
  fully reconstructed), blocks ascending in time. Block 0 coded as-is.
- Integer-only (`int64` numpy; integer division only inside `_bp_opt_beta`);
  causal, look-ahead 0, `ZERO side-info`.
- Extra bit-exact verification beyond the gate: `(C,N,cols)` = (1,300,1),
  (3,100,2), (16,257,4), (7,1000,16), (5,255,5) — `N` not a multiple of `BLOCK`,
  single channel, `cols > C` — plus full-range int16 input and an antiphase
  2-channel case exercising the `s_i = −1` path.

**Honest cost finding recorded at implementation time (the `xlag_v5` lesson).**
The hypothesis predicted the honest op count would land *below* the incumbent
front-end. It does not. Counted explicitly, on top of `_LMS4_OPS = 26`: form `m`
for the current sample = 8; apply = 3; amortised backward fit = 14 → front-end
25, `enc_ops = dec_ops = 51` (61 cyc, inside the 125-cyc neural budget). The
incumbent `bestpartner_adaptive` **declares** 13 (`_XCHAN_OPS` 3 +
`_LMS4BPA_SELECT` 10), though that 10 omits forming each candidate
cross-residual and Rice-bit-scoring five residual streams, so an apples-to-apples
recount would narrow the gap. The composite front-end's structural saving is
**qualitative** (no argmin, no per-candidate scoring pass, no selection
variance), not a cycle-count saving. Resulting cost **0.0466** — inside the
predicted 0.040–0.050 band, but above the incumbent's 0.0394.

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest
LMS4+Rice+xchan_cmean  2.72x          OK      OK      OK   0.047
registry self-test: ALL round-trips bit-exact
```

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.0466`).

| dataset | C | `cmean` (0.0466) | `bestpartner` (0.0394) | vs incumbent front-end | best `bc` (0.1202) | vs best |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.439590 | **1.480384** | **−2.756%** | 1.485085 | −3.063% |
| otb_hdsemg_vl | 64 | 2.055983 | **2.161938** | **−4.901%** | 2.193438 | −6.267% |
| capgmyo_dba_s1 | 128 | 1.337657 | **1.350480** | **−0.950%** | 1.353146 | −1.145% |
| cemhsey_s1_d1t1 | 320 | 1.804796 | **1.955547** | **−7.709%** | 1.955254 | −7.695% |

4-set real mean **1.65951×** — below *every* active LMS-family codec, and below
even `delta+Rice+xchan` (1.66622× at cost 0.0127).

**And the tell:** `cmean` is the **top-ranked codec on BOTH synthetic sets**,
outright maxima of the entire run — sc0.6 **2.662820×** (next: `jointbp2`
2.637096×), sc0.9 **2.646026×** (next: `jointbp2` 2.614226×).

## Attribution — isolated cross-channel gain on REAL data (achieved, not a ceiling)

The temporal predictor (order-4 sign-sign LMS) and the Rice back-end are
identical to the incumbent's; the *only* thing that changed is the spatial
front-end. Isolated against the shared bias-free `LMS+Rice` null
(`results/cycle_bench.csv`):

| dataset | C | neighbour-MI regime (P1) | `cmean` xchan gain | single-selected-parent `bestpartner` | `LMS+Rice+xchan` (fixed parent) |
|---|---:|---|---:|---:|---:|
| hyser_1dof_f1_s1 | 128 | high | **+8.24%** | +11.31% | +10.81% |
| otb_hdsemg_vl | 64 | high | **+12.63%** | +18.44% | +17.38% |
| capgmyo_dba_s1 | 128 | ≈none (control) | **+0.41%** | +1.37% | +1.28% |
| cemhsey_s1_d1t1 | 320 | high | **+4.36%** | +13.08% | +13.06% |

The composite parent captures **less** cross-channel MI than a single selected
parent on every real set — and on CEMHSEY it captures only **one third** of it
(+4.36% vs +13.08%). On the synthetics the ordering **inverts**: `cmean`
+13.29% / +24.40% versus `bestpartner` +10.45% / +20.44%. The
errors-in-variables mechanism the hypothesis targeted is *real and measurable* —
it just only exists in the synthetic field.

**Theory.** Noise-averaging `K` regressors raises regressor SNR **only if the
regressors are exchangeable**, i.e. each carries the same shared component at
the same gain, so that a single scalar `β` can undo the pooling. That is exactly
what a stationary isotropic synthetic field provides, and exactly what real
HD-sEMG does not: electrode impedance, distance to the innervation zone,
anisotropic conduction and inter-electrode spacing make the target-to-neighbour
gain a **per-pair, time-varying** parameter (the same quantity P11 identified).
Collapsing four parents into `(Σ s_i x_i) >> 2` **destroys that heterogeneity
before the gain is fitted**, and one shared `β` afterwards cannot restore four
different per-pair gains — it can only fit their average. Formally, the
composite trades a variance reduction of order `1/K` in the regressor for a
**specification bias** that is `O(spread of the true per-pair gains)`; where the
spread is large the bias term dominates and the subtract removes less shared
mode than the single best parent did. The `1/K` averaging also **actively
attenuates** the one dominant high-MI parent by ~`1/K` while adding three
lower-MI channels' independent noise — the sign-alignment step only fixes
polarity, never scale.

CEMHSEY (320 ch, grid 5×64) is the sharpest case and confirms the mechanism by
geometry: on a long, thin, 5-row array the four fixed slots span a much larger
physical spread than on an 8×16 grid, so the per-pair gain heterogeneity inside
the pool is maximal — and that is precisely where `cmean` loses two thirds of
the available cross-channel gain. CapgMyo behaves as the control predicts: there
is almost no gain to lose (+1.37% → +0.41%), so the absolute loss is small
(−0.950%) even though the *relative* loss (70% of the lever) is the same story.

This is **not** the retired `xchan_multiparent` failure (that summed *marginal*
subtracts and structurally over-subtracted; `cmean`'s weights sum to 1 after the
shift, so it cannot over-subtract). It is the **fixed-basis** failure of P3/P11
transposed once more — from the rotation angle, to the two-sided interpolation
weight, to the `K`-way pooling weight. And it re-confirms P1b from the opposite
direction: the valid multi-parent form is a **joint solve with one fitted gain
per parent** (`jointbp2`, which does win the synthetics *and* holds the
large-array Hyser corner), never a fixed-weight average with one shared gain.

**Methodological confirmation of P11's warning sign.** `cmean` tops both
synthetics outright while losing all four real sets — the second independent
instance (after `xchan_hint`) of a codec diagnosing its own basis mismatch by
winning the stationary field. The synthetic sweep is mechanism illustration
only; here it was actively misleading and the implementation note's own
synthetic "mechanism sanity" check (2.2460× vs 2.1967× on a high-independent-
noise field) predicted the exact opposite of the real-data outcome.

## Pareto check

Cost 0.0466, `embedded_ok` OK, `neural_ok` OK (61 cyc ≤ 125), 27 B/ch state
(≈3.5 KB @128 ch), zero side-info. **Conclusively Pareto-dominated on real
data** — five cheaper registered codecs beat it on **all four** real sets:

```
LMS+Rice+xchan_joint2                 cost 0.0366  1.493003 / 2.149676 / 1.350441 / 1.954270
LMS4+Rice+xchan_bestpartner_adaptive  cost 0.0387  1.477020 / 2.153106 / 1.352866 / 1.953948
LMS4+Rice+xchan_bestpartner           cost 0.0394  1.480384 / 2.161938 / 1.350480 / 1.955547
LMS4+Rice+acar_sel+bestpartner        cost 0.0430  1.480384 / 2.179540 / 1.350480 / 1.955547
LMS4+Rice+xchan_mst                   cost 0.0464  1.482324 / 2.170168 / 1.352732 / 1.953121
LMS4+Rice+xchan_cmean                 cost 0.0466  1.439590 / 2.055983 / 1.337657 / 1.804796
```

It is off the mean-real-vs-cost front by a wide margin (1.65951 at 0.0466, where
`LMS4+Rice+xchan_bestpartner` holds 1.73709 at 0.0394).

## Sanity gates

- Max real ratio in the run 2.194780× ≪ the 6× ceiling; `cmean`'s own max real
  2.055983×. Its synthetic 2.662820× is the run maximum and still far under the
  ceiling.
- Zero FAIL bit-exact rows (`ok=True` on all 156 rows; `bench.py` exit 0;
  registry self-test "ALL round-trips bit-exact", including after the retirement
  flag was set).
- Zero regressions on previously-registered codecs versus
  `results/consolidated_bench.csv` (nothing >0.05% on any real set).
- Four real-set regressions by the candidate itself (−0.950…−7.709% vs the
  incumbent front-end) — this is the domination that drives retirement.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (The
verifier gate is correctness/embeddability, which `cmean` passes cleanly,
including its self-reported honest op recount — it is the *promotion* and
*retention* bars it fails.)

## Decision

**NOT promoted. RETIRED** — `retired=True` with a one-line
`retired_reason` set on the `Codec("LMS4+Rice+xchan_cmean", …)` registration in
`research/registry.py`. Conclusively Pareto-dominated on real data by
`LMS4+Rice+xchan_bestpartner` (lower cost 0.0394 < 0.0466, strictly higher ratio
on all four real sets) and by four other cheaper codecs.

Registry after this cycle: **33 codecs, 19 active / 14 retired**. The durable
learning is filed as `INSIGHTS.md` **P13** and the dead-ends entry
"fixed-weight composite / pooled spatial parent".
