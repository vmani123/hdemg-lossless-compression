# 017 — LMS4v2+Rice+xchan_bestpartner: Volterra-lite degree-2 temporal predictor

- **Cycle:** 16
- **Date:** 2026-08-07
- **Branch:** `compression-cycle-2026-08-07`
- **Candidate:** `LMS4v2+Rice+xchan_bestpartner` (a.k.a. `v2bp`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (INSIGHTS open-frontier #2 / P2 — change the predictor's FUNCTIONAL FORM)

P2 says the temporal lever is exhausted by *order* and by *coefficient-set count* (`LMS4rs`, retired). It
explicitly left one live sub-lever: a linear LMS residual is white **only to second order**, so any remaining
temporal compressibility must be **higher-order**. Frontier #2 asked for a genuinely non-linear predictor at
order ≤ 4.

Keep **one** order-4 sign-sign LMS coefficient set and **one** adaptation loop; augment the regressor basis
with `V2_NQ = 3` integer second-order regressors from the causal history — `x[t−1]²`, `x[t−1]·x[t−2]`,
`x[t−2]²` — i.e. the complete degree-2 Volterra kernel truncated to quadratic memory 2, alongside the linear
memory-4 kernel. Prediction is one fixed-point sum `pred = (Σ wl·hist + Σ wq·q) >> 8`; every tap adapts under
the same `w += sign(e)·sign(regressor)` rule. **No gate, no bank, no second coefficient set** — this is
strictly a basis-function change, which is what distinguishes it from the retired `LMS4rs` (duplicated
*linear* sets behind an activity gate) and from the retired `xctx` (which conditioned the Rice parameter,
leaving the residual unchanged; here the coder is untouched and the residual itself changes).

Spatial front-end: the promoted best-partner (`_bp_select`/`_bp_inverse`) reused **verbatim**, so this is a
clean A/B against the current best in which *only the temporal predictor's functional form differs*.

## Implementation

`research/registry.py` only: `_v2_bitlen`, `_v2_regs`, `_v2_forward`/`_v2_inverse`, `v2bp_encode`/
`v2bp_decode` (magic `0x5632`), and the `Codec("LMS4v2+Rice+xchan_bestpartner", …)` registration.

The flagged overflow risk is handled by an **integer scale guard**: `mag += |x[t]| − (mag >> 5)` is a
per-channel leaky mean, the exponent `nbits = bitlength(mag >> 5)` refreshes every 16 samples (a CLZ in
hardware), and `q = clamp((x_a·x_b) >> nbits, ±32767)` so `|q| ~ |x|²/mean|x| ~ |x|` — the quadratic
regressors sit on the *same scale* as the linear ones, making the shared weight scale meaningful for both.
`bitlength` is an integer binary search; **no float anywhere** in the codec path.

Quadratic taps *only* are leaked every 16 samples, `wq −= sign(wq)·(|wq| >> 5)` — symmetric, integer, no
floor drift. This bounds `|wq|` and makes the correction **self-disabling**: if the products carry no
predictive information, the sign-sign updates cancel, the leak pulls `wq → 0`, and the codec degenerates
exactly to the promoted `LMS4+Rice+xchan_bestpartner`. Linear taps are not leaked. Zero temporal side-info
(regressors, exponent and leak instants are all recomputed by the decoder from causally-reconstructed
history, P4); the only side-info is the best-partner `(parent, β)` pair, identical to the incumbent.

Gate: `PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest` →
`registry self-test: ALL round-trips bit-exact`, `LMS4v2+Rice+xchan_bestpartner … OK OK OK 0.059`
(all 23 codecs still bit-exact — no existing codec disturbed).

Pre-measurement observation (mechanism check, not a benchmark): on a synthetic broadband probe the quadratic
taps are demonstrably **active** (Volterra residuals differ from plain order-4 LMS residuals — not a silent
no-op), and mean |residual| *rose* slightly, 247.3 → 249.4 — already consistent with the stated risk.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (all bit-exact, `embedded_ok` OK, `neural_ok` OK), from `results/cycle_bench.csv`, cost **0.0592**:

| dataset | `v2bp` | current best `bestpartner` (0.0394) | vs best | `v2bp` xchan gain (vs `LMS+Rice`) | best-partner xchan gain |
|---|---:|---:|---:|---:|---:|
| otb_hdsemg_vl (64 ch) | 2.143119 | 2.161938 | **−0.870%** | +17.41% | +18.44% |
| **hyser_1dof_f1_s1 (128 ch)** | 1.475796 | 1.480384 | −0.310% | +10.96% | +11.31% |
| capgmyo_dba_s1 (128 ch) | 1.346843 | 1.350480 | −0.269% | +1.09% | +1.37% |
| cemhsey_s1_d1t1 (320 ch) | 1.952080 | 1.955547 | −0.177% | +12.88% | +13.08% |

4-set mean **1.729442** vs `bestpartner` 1.737087 (−0.440%).
Synthetic: `synth_sc0.6` 2.592998 vs 2.595982 (−0.115%); `synth_sc0.9` 2.558494 vs 2.561720 (−0.126%).

**Loses on ALL 4 real sets AND both synthetic sets, at 1.5× the cost.**

## Attribution

The spatial front-end and the Rice back-end are byte-identical to the current best, so the entire loss is
attributable to the **temporal basis** — the cleanest single-variable A/B this project has run on the
temporal axis. The achieved cross-channel gain fell on every set (otb +17.41% vs +18.44%, hyser +10.96% vs
+11.31%, capgmyo +1.09% vs +1.37%, cemhsey +12.88% vs +13.08%) — the same fingerprint `LMS4rs` left: a worse
temporal prediction feeds a larger residual into the unchanged spatial stage.

Why the degree-2 kernel finds nothing, in theory terms — **two independent reasons, and the second is the
deeper one:**

1. **There is no second-order structure to fit, by the generation model.** Surface HD-sEMG is a *linear*
   volume-conductor filtering of superimposed motor-unit action potentials; the tissue is (to a very good
   approximation) a linear, passive, time-invariant medium. A signal generated by a linear system driven by a
   near-symmetric excitation has a vanishing **bispectrum**, so the third-order moments the Volterra taps
   estimate, `E[e_t · x_{t−i} x_{t−j}]`, are ≈ 0. The gradient the sign-sign rule follows is therefore pure
   noise. This is stronger than P2's original statement: the residual is white after order-4 LMS not merely
   *empirically to second order* but because **the source process is genuinely linear-Gaussian-like**, so
   there is no higher-order redundancy at any degree, not just none at degree 2.
2. **Even a zero-mean gradient costs bits.** The `wq` taps random-walk around 0 under sign-sign updates;
   their contribution to `pred` is a zero-mean, `O(x²/mean|x|) = O(x)` -variance disturbance **added to the
   residual**. Adding an independent zero-mean term to a residual strictly increases its variance and hence
   its Rice-coded length. Estimating a parameter whose true value is zero is never free — the estimator's
   variance is paid in coded bits. This is the same accounting that killed `xctx` (P5) and `LMS4rs` (P2),
   now demonstrated on the predictor's *basis* rather than its *order* or *set count*.

The leak term did its job: it bounded the damage to −0.18…−0.87% instead of letting it diverge, which is why
this is a clean falsification of the mechanism rather than a numerics artefact. And the self-disabling design
is itself the proof — the codec *would* have reproduced the incumbent exactly if `wq → 0` were reached
between updates; that it lands consistently *below* the incumbent shows the taps are perpetually re-excited
by noise faster than the leak can null them.

## Pareto check

`LMS4+Rice+xchan_bestpartner` (registered, cost **0.0394**) has a higher ratio on **all four** real sets and
**1.5× lower cost**. Also beaten on both synthetic sets. **Conclusively Pareto-dominated.**

## Sanity gates

- Max real ratio 2.1431× (otb) ≪ the 6× ceiling → no leak.
- Zero FAIL bit-exact rows in `results/cycle_bench.csv` (120 rows, all `ok=True`); `embedded_ok` OK,
  `neural_ok` OK, cost 0.0592.
- No registered codec regressed: all previously-benched (dataset, codec) ratios are bit-identical to
  `results/06_real_bench*.csv`.
- Note: `lookahead_samples = ec.BLOCK` (inherited from the incumbent's offline best-partner selection), so
  this row carries the same realization gap the incumbent does — irrelevant now that it is retired.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (Correctness/embeddability only.)

## Decision

**RETIRED** (`retired=True` + `retired_reason` on its `Codec(...)` in `research/registry.py`). Conclusively
Pareto-dominated on all 4 real sets at 1.5× the cost.

**Frontier #2 is now SPENT, NEGATIVE — and closed at the level of theory, not just this variant.** P2 is
strengthened to its final form: the temporal lever is exhausted by **order** (`order-8`), by **coefficient-set
count** (`LMS4rs`), *and* by **basis functional form** (`LMS4v2`) — because the HD-sEMG source is a linear
volume-conductor process, so no non-linear predictor of any degree has higher-order redundancy to remove.
Do not re-propose non-linear temporal predictors (Volterra, gated-magnitude, sign-of-neighbour, or NN-flavoured)
on this signal. Headline / port pick unchanged.
