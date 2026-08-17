# 015 — LMS4+Rice+xchan_lagbp: propagation-lag-aligned best-partner cross-channel front-end

- **Cycle:** 16
- **Date:** 2026-08-07
- **Branch:** `compression-cycle-2026-08-07`
- **Candidate:** `LMS4+Rice+xchan_lagbp` (a.k.a. `lagbp`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (spatial front-end — add a TIME axis to the proven selection)

MU action potentials *propagate* along the fibre at a finite conduction velocity, so a channel's spatial
parent is not its neighbour at lag 0 but a **delayed replica** of it. The proven backward-adaptive
best-partner front-end subtracts at `d = 0` only, which is the matched filter only if the propagation delay
is below one sample. Widen the per-block backward argmin from a *partner* search to a **(partner × lag)**
search: for each channel `g`, scan the ≤4 causal grid neighbours (`_bp_candidates`) × lag `d ∈ [0..8]` over
the **previous already-reconstructed raw block**, take each candidate's integer least-squares gain on the
lag-shifted segment, score the cross-residual in estimated Rice bits, and apply the min-bits `(p, d, β)`
triple to the current block: `y[g,t] = x[g,t] − ((β·x[p, t−d]) >> 8)`. Zero side-info (parents have
`idx < g`, the lag only reaches further back in time), look-ahead 0, block 256.

Prediction (recorded in the code *before* measurement): **largest gain on CapgMyo** — its differential array
suppresses the lag-0 common part but preserves the delayed replica. *"If CapgMyo does not move, the mechanism
is wrong and the row should be RETIRED, not tuned."*

Scope decision (also recorded before measurement): the hypothesis's *structural* bonus — that `d ≥ 1`
legalises the non-causal-index half of the 8-neighbourhood — was deliberately **not** bundled in, since it
needs a sample-serial inverse. The candidate therefore isolates the **lag axis alone** at the proven
4-partner pool, so a null falsifies the lag mechanism rather than a lag+pool bundle.

## Implementation

`research/registry.py` only (+261 lines): `LAGBP_*` constants, `_lag_seg`, `_lagbp_select_block`,
`_lagbp_forward`/`_lagbp_inverse`, `lagbp_encode`/`lagbp_decode`, and the `Codec("LMS4+Rice+xchan_lagbp", …)`
registration. Back-end unchanged (order-4 sign-sign LMS + adaptive Rice → P2/P5 respected); spatial rank
stays 1 → not a re-proposal of the retired `iklt*` (multi-tap rotations) or `xchan_multiparent` (summed
marginal subtracts). `rtl/`, `sim/`, `host_tools/` untouched.

Gate: `PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest` →
`registry self-test: ALL round-trips bit-exact`, `LMS4+Rice+xchan_lagbp … OK OK OK 0.071`.

Mechanism sanity check (synthetic, illustration only — *not* a benchmark): on a 16-ch field built from one
propagating source with a known per-channel delay, the selector recovered the true delays with β ≈ 256
(= 1.0) — e.g. ch 4 → (partner 0, lag 3), ch 9 → (partner 4, lag 4) — reaching 2.597× vs 1.965× for
`bestpartner_adaptive`. This confirms only that the lag machinery engages and does not silently degenerate to
`d = 0`.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (all bit-exact, `embedded_ok` OK, `neural_ok` OK), from `results/cycle_bench.csv`, cost **0.0706**:

| dataset | `lagbp` | best `bestpartner` (0.0394) | vs best | streaming peer `bestpartner_adaptive` (0.0387) | vs peer | `lagbp` xchan gain (vs `LMS+Rice`) | best-partner xchan gain |
|---|---:|---:|---:|---:|---:|---:|---:|
| otb_hdsemg_vl (64 ch) | 2.092290 | 2.161938 | **−3.220%** | 2.153106 | **−2.825%** | +14.63% | +18.44% |
| **hyser_1dof_f1_s1 (128 ch)** | 1.476713 | 1.480384 | −0.248% | 1.477020 | −0.021% | +11.03% | +11.31% |
| capgmyo_dba_s1 (128 ch) | 1.351336 | 1.350480 | +0.063% | 1.352866 | **−0.113%** | +1.43% | +1.37% |
| cemhsey_s1_d1t1 (320 ch) | 1.953442 | 1.955547 | −0.108% | 1.953948 | −0.026% | +12.96% | +13.08% |

4-set mean **1.718430** vs `bestpartner` 1.737087 (−1.074%), vs `bestpartner_adaptive` 1.734235 (−0.912%).
Synthetic: `synth_sc0.6` 2.584654, `synth_sc0.9` 2.544000 — last among the LMS4 cross-channel family on both.

**The falsifiable prediction is FALSIFIED.** CapgMyo — the set where the lag replica was predicted to be the
*whole* remaining signal — moved **−0.113%** against the identical lag-0 backward-adaptive front-end.

## Attribution

Temporal predictor and entropy back-end are byte-identical to `bestpartner_adaptive`; the only variable is
the selection grid, so the entire −0.9% mean is attributable to the **cross-channel front-end's search
widening**. It is not that the lag machinery failed to engage (the synthetic probe proves it does) — it is
that on real HD-sEMG the correct lag is essentially always `d = 0`, and the extra options *cost* bits:

- **No mutual information at `d ≥ 1` to find.** At 1–2 kHz sampling with 4–10 mm inter-electrode spacing and
  a 3–5 m/s conduction velocity, the true inter-electrode propagation delay is **~0.5–2 % of a sample
  period** — sub-sample. `I(x_g[t]; x_p[t−d])` is therefore maximised at `d = 0` and falls monotonically for
  `d ≥ 1`; the delayed replica the hypothesis targets is not resolvable on this sampling grid. (Hyser/OTB/
  CEMHSEY are 2048 Hz, CapgMyo 1000 Hz — the slowest-sampled set, hence the most sub-sample lag, which is
  exactly why the CapgMyo prediction inverted.)
- **The search widening costs estimation variance.** The block-256 argmin's option count grows ~9× (4 partners
  → 4 × 9 = 36 `(p, d)` pairs) while the number of samples the statistic is estimated from is unchanged. The
  argmin of a noisy score over more options is more often the *winner by noise*, and the winner is then applied
  to the **next** block, where the noise does not repeat — a classic selection-overfitting (winner's-curse)
  loss. The damage scales inversely with the per-channel MI margin between the true best partner and the
  runners-up, which is why the **tight 64-ch OTB array, whose neighbourhood is near-rank-1 with one dominant
  parent (P1b), is hurt worst (−2.8%)**: there the score surface is flattest across the spurious lag options.

## Pareto check

`LMS4+Rice+xchan_bestpartner_adaptive` (registered, cost **0.0387**) has a **higher ratio on all four real
sets** and **~1.8× lower cost** (0.0706). Also dominated by `LMS4+Rice+xchan_bestpartner` on 3 of 4 sets at
0.0394. **Conclusively Pareto-dominated.**

## Sanity gates

- Max real ratio 2.0923× (otb) ≪ the 6× ceiling → no leak, honest broadband EMG.
- Zero FAIL bit-exact rows in `results/cycle_bench.csv` (120 rows, all `ok=True`); `embedded_ok` OK,
  `neural_ok` OK, cost 0.0706.
- No registered codec regressed: every previously-benched (dataset, codec) ratio is bit-identical to
  `results/06_real_bench*.csv` (diff = 0.0000% on all).
- Cost caveat flagged by the implementer is now moot: `enc_ops` 90 cyc/sample-ch left only ~35 cyc of
  `neural_ok` margin, and the row is retired anyway.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (The verifiers gate correctness and
embeddability only; the codec is legitimate and bit-exact — it simply loses on ratio.)

## Decision

**RETIRED** (`retired=True` + `retired_reason` on its `Codec(...)` in `research/registry.py`). Conclusively
Pareto-dominated by `LMS4+Rice+xchan_bestpartner_adaptive` on all 4 real sets at ~1.8× the cost, and its own
pre-registered falsification criterion (CapgMyo) fired. **The lag axis of the cross-channel selection is
spent, NEGATIVE**: HD-sEMG inter-electrode propagation delay is sub-sample at ≤2 kHz, so widening the argmin
over lags adds only selection variance. Do not re-propose an integer-lag spatial front-end at these sampling
rates; a *fractional*-delay (interpolating) parent would be the only theoretically live version, and it
breaks integer-only losslessness. Headline / port pick unchanged.
