# 016 — LMS4+Rice+xchan_mdlsel: MDL-penalized spatial model-order selection

- **Cycle:** 16 (row 17 of `CYCLE_LOG.md`)
- **Date:** 2026-08-05
- **Branch:** `compression-cycle-2026-08-05`
- **Candidate:** `LMS4+Rice+xchan_mdlsel`
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY candidate 2 — fix a diagnosed estimator defect, not a parameter tweak)

`_jbp2_select_block` scores none / single-parent / joint-pair by the **in-sample** estimated Rice bits of
an LS fit on the previous block. The 2-parameter joint pair *contains* the 1-parameter single (β₂ = 0),
so it can never score worse on the block it was fit to → the selector is **structurally biased toward the
higher spatial order**. That is textbook model-order selection without a complexity term, and it matches
`jointbp2`'s observed signature (wins the diffuse large array, loses tight OTB where P1b says the local MI
is rank-1). Adding the exact MDL/BIC parameter code length `(k/2)·log₂B` bits (k = spatial taps) should
make the order fall out of the data per channel *and* per block, at zero side-info, and yield the first
robust 4-set win since cycle 7.

## Implementation

`research/registry.py` only. `_mdl_penalty(k, n) = (k * (n.bit_length()-1)) // 2` — integer-exact, one
add per scored option; on B = 256 this is 0 / 4 / 8 bits for k = 0 / 1 / 2. `_mdlsel_select_block` is a
verbatim copy of `_jbp2_select_block`'s candidate set and fits (`_bp_candidates`, `_bp_opt_beta` marginal
LS for singles, `_jbp2_pair_resid` joint 2×2 integer LS for pairs) with `+pen1` / `+pen2` added.
Transform, predictor and coder are `jointbp2` **verbatim** (joint co-adaptive 2-tap sign-sign LMS,
asymmetric rank-1 residual-only injection, block-0 (up,left) bootstrap, order-4 sign-sign LMS temporal
base, adaptive Rice) — **the only difference from `jointbp2` is the selection criterion**, so any measured
delta is attributable to it alone. Cost 0.0474 (enc = dec = 50 ops/sample-ch = jointbp2's 49 + 1),
state 30 B/ch, look-ahead 0, zero side-info; `embedded_ok` OK, `neural_ok` OK. The penalty gates the
**transform order** only — the Rice coder and its *k* are untouched (that is the retired `xctx` lever, P5).

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all rows `ok=True`, `embedded=OK`, `neural=OK`):

| dataset | mdlsel (0.0474) | unpenalized twin `jointbp2` (0.0468) | best `bestpartner` (0.0394) | vs twin | vs best |
|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 1.496743 | 1.496924 | 1.480384 | **−0.012%** | +1.11% |
| otb_hdsemg_vl | 2.151916 | 2.152244 | 2.161938 | **−0.015%** | −0.46% |
| capgmyo_dba_s1 | 1.350596 | 1.350287 | 1.350480 | **+0.023%** | +0.01% |
| cemhsey_s1_d1t1 | 1.952733 | 1.952260 | 1.955547 | **+0.024%** | −0.14% |
| 4-set mean | 1.7380 | 1.7379 | 1.7371 | +0.005% | +0.052% |

Synthetic (mechanism only): `synth_sc0.6` 2.636727 vs jointbp2 2.637096; `synth_sc0.9` 2.614098 vs
2.614226 — the same ≈0.01% wash.

## Cross-channel gain, isolated, on REAL data (achieved, not a ceiling)

Baseline measured directly (order-4 LMS + adaptive Rice, no cross-channel stage): hyser 1.3321×,
otb 1.8347×, capgmyo 1.3336×, cemhsey 1.7280×.

| dataset | mdlsel xchan gain | jointbp2 xchan gain | best-partner xchan gain |
|---|---:|---:|---:|
| hyser | **+12.36%** | +12.37% | +11.13% |
| otb | **+17.29%** | +17.31% | +17.84% |
| capgmyo | **+1.27%** | +1.25% | +1.27% |
| cemhsey | **+13.01%** | +12.98% | +13.17% |

## Attribution — what moved the ratio, and why

Predictor and back-end unchanged; the transform is `jointbp2` verbatim → the entire (tiny) delta is the
**cross-channel front-end's selection criterion**. Two direct instrumentations on real data settle it:

**(a) The mechanism fires hard — the penalty really does change the selected spatial order.**
Both selectors re-run over every (channel, block) on real data:

| dataset | blocks | selections changed | jointbp2 k-hist (0/1/2) | mdlsel k-hist (0/1/2) | k=2 share |
|---|---:|---:|---|---|---|
| hyser | 7366 | 539 (**7.3%**) | 20 / 1243 / 6103 | 48 / 1738 / 5580 | 82.9% → **75.8%** |
| otb | 3654 | 316 (**8.6%**) | 4 / 962 / 2688 | 11 / 1268 / 2375 | 73.6% → **65.0%** |
| capgmyo | 7366 | 1904 (**25.8%**) | 163 / 1794 / 5409 | 515 / 3181 / 3670 | 73.4% → **49.8%** |
| cemhsey | 18502 | 4486 (**24.2%**) | 125 / 6475 / 11902 | 280 / 10770 / 7452 | 64.3% → **40.3%** |

The diagnosed over-selection bias is **real** and the correction is **large** (the k = 2 share falls by
7–24 pp) — yet the ratio moves by **≤0.025% in either direction**.

**(b) The selection surface is flat — the models it chooses between are near-identical in coded bits.**
On exactly the blocks where the penalty flipped the choice, the *unpenalized* in-sample bit gap between
`jointbp2`'s pick and `mdlsel`'s pick is a **median of 3.0 bits per 256-sample block** (mean 2.6 hyser /
2.7 capgmyo) against a median block cost of ~3030 (hyser) / ~3350 (capgmyo) coded bits — i.e. **0.09–0.10%
of the block**. The MDL penalty for k = 2 is 8 bits, *larger* than the 3-bit in-sample advantage it is
meant to discount, which is why it flips so many blocks; but because the surface is flat, mis-scaling
costs ≈nothing either.

**Theory.** The over-selection was a **labeling** bias, not a **coding** bias. When the second parent
carries little MI, the joint 2×2 integer LS drives its tap toward zero and the fixed-point quantization
of β on the `JBP2_SHIFT` grid rounds a small tap to exactly 0, so a k = 2 *selection* largely degenerates
to the k = 1 *transform* in the emitted stream. Formally: the parameter-count penalty is worth
`(k/2)·log₂B` = 8 bits per 256-sample block = **0.031 bits/sample** against a measured ~11.8 bits/sample
coded (median 3029 bits/block, hyser) — a **≤0.26% ceiling** even if every block were mis-selected, and
the *measured* in-sample gap it arbitrates is smaller still (3 bits/block = 0.10%). The realized effect is
~0.02% because the overfit is already shrunk out of the transform. And what remains is below the **rate
granularity of the
Golomb-Rice back-end**: Rice's rate moves in ~1 bit/sample steps of *k* and cannot spend a 3-bit-per-block
difference. This is P5's floor argument mirrored on the *model-selection* side: a front-end refinement
whose in-sample benefit is a few bits per block is invisible to the coder that has to express it.

## Pareto check

Cost 0.0474 vs `jointbp2` 0.0468 (one extra integer add per scored option). Against `jointbp2` it is
**worse on hyser and otb but better on capgmyo and cemhsey**, so neither dominates the other — mdlsel is
a (marginal) non-dominated point, not a dominated one. Against the leaderboard best `bestpartner`
(0.0394) it wins Hyser (+1.11%) and ties CapgMyo but loses OTB (−0.46%) and CEMHSEY (−0.14%) at higher
cost → not a Pareto improvement and not a new best. Kept registered, not retired.

## Sanity gates

- Max real ratio 2.1519× (otb) ≪ the 6× ceiling → no leak.
- No FAIL bit-exact rows anywhere in `results/cycle_bench.csv` (`ok=True` on all 120 rows);
  `embedded=OK`, `neural=OK`, cost 0.0474 clears both budgets.
- No incumbent regression: it is within ±0.025% of `jointbp2` everywhere and never below the
  spatial-family floor.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** It reproduces `jointbp2`'s profile to within ±0.025% on
every real set — the same shape as cycle 13 (wins primary Hyser, regresses OTB and CEMHSEY) — so it does
not robustly beat the current best on real data. The frontier-#1 *estimator-fix* lever is now **spent, and
spent informatively**: the diagnosed bias was confirmed (7–26% of blocks flip, k = 2 share falls up to
24 pp) and shown to be **worth nothing in bits**, because the spatial model-selection surface is flat at
the ~3-bits-per-block scale the Rice back-end cannot represent. Headline / port pick unchanged.
