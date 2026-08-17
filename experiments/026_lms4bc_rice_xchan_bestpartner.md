# 017 — LMS4bc+Rice+xchan_bestpartner: context bias-cancellation two-stage predictor

- **Cycle:** 18
- **Date:** 2026-08-13
- **Branch:** `compression-cycle-2026-08-13`
- **Candidate:** `LMS4bc+Rice+xchan_bestpartner` (a.k.a. `biascorr` / `bc`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (INSIGHTS open-frontier #2 — change the predictor's FUNCTIONAL FORM)

P2 established that *more* taps and *more* coefficient sets both fail (order-8 loses to order-4;
`LMS4rs`'s regime bank was retired). The remaining live temporal lever is a genuinely different
functional form. A linear predictor whitens only *to second order*, and sign-sign LMS is not even
MMSE-optimal — its fixed ±1 gradient-noise misadjustment leaves a **context-dependent non-zero
conditional mean** in the residual. Since `H(e) ≥ H(e − E[e|ctx])`, removing that DC lowers residual
variance by `E[μ_ctx²]`, worth ≈ `½·log₂(1 + E[μ²]/σ²)` bits/sample — the mechanism behind JPEG-LS's
measurable gain over bare MED.

## Implementation

`research/registry.py` only. Stage 1 = the promoted order-4 sign-sign LMS, **bit-identical** to the
incumbent and fed the *pre-correction* residual `e` on both sides (the decoder recovers
`e = d + μ` before updating), so the corrector is a purely **additive second stage**, not extra taps
and not extra coefficient sets. Stage 2 = `d[t] = e[t] − μ[c,ctx]` with `μ` a leaky integrator
`S += e − (S>>5)`, `μ = (S+16)>>5` — **shift-divide only**, no multiplies, no divides, no counter
halving. Context = 30 buckets: `q5(e[t−1]) × q3(e[t−2]) × sign(d[parent, t−1])`, quantizer
thresholds at 0.5×/1.5× the channel's backward leaky mean `|e|` (scale-free across bursts and
quiescence). The **parent sign is taken at lag 1** deliberately — same-`t` would force a serial
per-sample chain down the parent tree; the implementer flagged this as the one design compromise.
Rice back-end and the `_bp_select`/`_bp_inverse` best-partner front-end are reused verbatim with
**zero new side-info**. Cost **0.1202**, `state_bytes_per_ch=167` (~21 KB at 128 ch),
`embedded_ok=OK`, `neural_ok=OK` (59 enc ops ≈71 cyc/sample-ch, inside the 125-cyc 30 kHz budget) —
the cost is dominated by the **SRAM term (0.082)** from the 120 B/ch of context accumulators, not by
compute.

Retired-lever separation (verified): the coder is untouched — one global adaptive-Rice, no
context-split tables, no `k` model → not `xctx`; exactly one predictor and one weight set, the
context indexing a single scalar first moment → not `LMS4rs`.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok=OK`, `neural_ok=OK`), from `results/cycle_bench.csv`:

| dataset | C | `LMS4bc+bestpartner` (0.1202) | best `bestpartner` (0.0394) | **vs best (isolated corrector gain)** | streaming `bestpartner_adaptive` (0.0387) | vs streaming |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | **1.485085** | 1.480384 | **+0.318%** | 1.477020 | +0.546% |
| otb_hdsemg_vl | 64 | **2.193438** | 2.161938 | **+1.457%** | 2.153106 | +1.873% |
| capgmyo_dba_s1 | 128 | **1.353146** | 1.350480 | **+0.197%** | 1.352866 | +0.021% |
| cemhsey_s1_d1t1 | 320 | 1.955254 | 1.955547 | **−0.015%** | 1.953948 | +0.067% |

4-set mean **1.7467×** vs best 1.7371× (**+0.555%**) — the highest mean real ratio of any registered
codec. `LMS4bc` is the **outright maximum on OTB (2.193438×) and on CapgMyo (1.353146×)** across all
20 codecs+references benched. Synthetic: `synth_sc0.6` 2.593270×, `synth_sc0.9` 2.559087×.

## Attribution — which mechanism moved the ratio

The cross-channel front-end is **bit-identical** to `bestpartner`'s and the entropy back-end is the
unchanged adaptive Rice, so **100% of the delta is the temporal stage** — the conditional-mean
corrector. This is the isolated measurement of INSIGHTS frontier #2 on real data.

Cross-channel gain (composite, front-end + corrector, vs temporal-only `LMS+Rice`) for completeness:
hyser +11.66%, otb **+20.17%** (the largest xchan-lever gain of any codec on OTB), capgmyo +1.57%,
cemhsey +13.07% — but note this is **not isolated**; the front-end contribution is `bestpartner`'s
+11.31/+18.44/+1.37/+13.08% and the corrector supplies the remainder.

**Mechanism.** The corrector wins **4.6× more on OTB (+1.46%) than on Hyser (+0.32%)** and is flat
on the 320-ch CEMHSEY (−0.015%). Theory: `μ[ctx]` estimates `E[e | ctx]`, which is non-zero exactly
where the linear predictor is *biased* — i.e. where sign-sign LMS's fixed-step adaptation cannot
track the envelope. OTB VL at 2048 Hz over 64 channels is the burstiest, highest-SNR set in the
corpus (its post-LMS residual is the *least* white — it also has the largest xchan gain), so during
each burst the sign-sign update lags the amplitude ramp and leaves a **signed, context-persistent
residual bias** that the leaky mean removes directly. CEMHSEY's 320 channels at 2048 Hz have lower
per-channel SNR and a flatter envelope, so `E[e|ctx] ≈ 0` and the 30-bucket estimator returns
essentially noise — the −0.015% is the estimation-variance cost of the buckets themselves.

This is the first **positive** result on the temporal axis in the log, and it is positive precisely
because it changed the predictor's *functional form* (an additive, piecewise-constant nonlinearity)
rather than its tap count or its coefficient-set count. P2's "temporal lever is spent" was a
statement about *linear capacity*, and this candidate is the clean falsification of the broader
reading of it. Note the gain is nowhere near the spatial lever's (+1.5% peak vs +18–20%) — it is a
second-order refinement of P1's residual, exactly as the ordering in the frontier predicted.

## Pareto check

**On the front, at a steep price.** Cost 0.1202 = **3.05× the incumbent best's 0.0394**. On the
4-set mean it is the **maximum-ratio point and non-dominated** (nothing has both a higher mean ratio
and a lower cost). Per dataset: it is the outright max on OTB and CapgMyo; on Hyser it is
**dominated by `LMS4+Rice+xchan_jointbp2`** (1.496924× at cost 0.0468 — higher ratio, 2.6× cheaper);
on CEMHSEY it is dominated by `bestpartner` (1.955547× at 0.0394). So it is a genuine non-dominated
max-ratio corner overall, **not** a Pareto improvement: the ~0.08 of cost is bought almost entirely
with SRAM (120 B/ch of accumulators → 21 KB at 128 ch, ~8% of the STM32H745 budget).

## Sanity gates

- Max real ratio **2.1934×** (otb) ≪ the 6× ceiling → no leak. It is the highest real ratio in the
  whole cycle and still well inside the honest broadband band (1.3–2.2×).
- Zero bit-exact failures in `results/cycle_bench.csv` (0/120 rows `ok != True`).
- `embedded_ok=OK`, `neural_ok=OK`; zero side-info beyond the incumbent's `(parent, β)`.
- Only regression: cemhsey −0.015% vs the registered best (−0.000293× absolute) — an order of
  magnitude smaller than the regressions that blocked promotion in cycles 11 (otb −0.57%) and
  13 (otb −0.45%, cemhsey −0.17%).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**PROMOTED — new leaderboard best on ratio.** It beats the registered best on the primary Hyser
(+0.318%) and on 3 of 4 real sets, holds the 4th to −0.015% (a dead tie), posts the highest 4-set
mean real ratio ever measured here (1.7467×), and both verifiers returned PROMOTE — the promotion
rule is met.

**The "one codec to port next" headline is deliberately NOT changed.** A +0.32% Hyser / +1.46% OTB
gain for **3.05× the cost and 21 KB of context SRAM** does not displace the port pick, which is a
ratio-per-cost judgement; `LMS4+Rice+xchan_bestpartner` (offline selection) /
`LMS4+Rice+xchan_bestpartner_adaptive` (streaming) remain the port recommendation, and
`lms4s7+x6/b512` remains the minimal-hardware pick. Port `LMS4bc` only if the SRAM is available and
the tight-array OTB corner is the target.
