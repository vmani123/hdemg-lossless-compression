# 015 — LMS4+Rice+xchan_lagpartner: lag-matched (spatiotemporal) cross-channel partner

- **Cycle:** 16 (row 16 of `CYCLE_LOG.md`)
- **Date:** 2026-08-05
- **Branch:** `compression-cycle-2026-08-05`
- **Candidate:** `LMS4+Rice+xchan_lagpartner` (a.k.a. `lagp`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY candidate 1 — attack P1's bound instead of re-dividing under it)

P1 caps the spatial gain at the neighbour mutual information, but **every registered codec measures that
MI at τ = 0 only**. HD-sEMG is dominated by MUAPs propagating along the fibre at 3–5 m/s, so the
inter-electrode cross-correlation should peak at `τ* = IED/CV` ≈ **3–7 samples at 2048 Hz**. Keeping the
proven rank-1 asymmetric subtract but selecting the parent as a *(neighbour, integer lag τ)* **pair** —
backward-adaptively per block, zero side-info — should therefore expose a **new MI slice**:
residual variance `1−ρ(0)²` → `1−ρ(τ*)²`, worth `½·log₂((1−ρ(0)²)/(1−ρ(τ*)²))` bits/sample.

## Implementation

`research/registry.py` only. `LAGP_BLOCK=256`, `LAGP_MAX=7`, coarse grid `(-6,-4,-2,0,2,4,6)`,
`LAGP_DECIM=2`. Two-stage search per (channel, block): 4 parents × 7 coarse lags scored on a stride-2
**decimated** previous raw block, then τ−1/τ/τ+1 re-scored at full rate against the no-partner option
(coarse never compared against fine). Signed τ (innervation zone is mid-array → MUAPs propagate both
ways); negative τ costs the **encoder** ≤7 samples of look-ahead on the parent delay line, the decoder
none (channel-sequential order restores parent `p < c` first). Predictor (order-4 sign-sign LMS, P2),
candidate neighbourhood, integer-LS β and the adaptive Rice back-end (P5) are **byte-identical** to
`LMS4+Rice+xchan_bestpartner_adaptive`, so the whole measured delta is attributable to the widened
selection domain `{partner}` → `{partner}×{lag}`. Zero side-info, header = magic/cols/C/N.
Cost 0.0775 (enc=dec=75 ops/sample-ch, state 58 B/ch, look-ahead 7) — `embedded_ok` OK, `neural_ok` OK.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all rows `ok=True`, `embedded=OK`, `neural=OK`):

| dataset | lagpartner (0.0775) | zero-lag sibling `bestpartner_adaptive` (0.0387) | best `bestpartner` (0.0394) | vs sibling | vs best |
|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 1.476197 | 1.477020 | 1.480384 | −0.06% | **−0.28%** |
| otb_hdsemg_vl | 2.055884 | 2.153106 | 2.161938 | **−4.51%** | **−4.91%** |
| capgmyo_dba_s1 | **1.357519** | 1.352866 | 1.350480 | **+0.34%** | **+0.52%** |
| cemhsey_s1_d1t1 | 1.953420 | 1.953948 | 1.955547 | −0.03% | −0.11% |
| 4-set mean | 1.7108 | 1.7342 | 1.7371 | — | −1.52% |

Synthetic (mechanism only): `synth_sc0.6` 2.582924, `synth_sc0.9` 2.542321 — mid-pack, ≈ the zero-lag
sibling (2.584705 / 2.544000), as expected for fields synthesized without propagation delay.

**1.357519× on CapgMyo is the highest ratio of any codec *or* reference in the whole bench table**
(next: `bestpartner_adaptive` 1.352866, `mdlsel` 1.350596, `bestpartner` 1.350480).

## Cross-channel gain, isolated, on REAL data (achieved, not a ceiling)

Baseline measured directly: order-4 LMS + adaptive Rice, **no cross-channel stage**
(`ec.lms_forward(x, order=4)` + `ec.rice_encode_1d` per channel):
hyser 1.3321×, otb 1.8347×, capgmyo 1.3336×, cemhsey 1.7280×.

| dataset | lagpartner xchan gain | zero-lag sibling xchan gain |
|---|---:|---:|
| hyser | **+10.82%** | +10.88% |
| otb | **+12.06%** | +17.35% |
| capgmyo | **+1.79%** | +1.44% |
| cemhsey | **+13.05%** | +13.08% |

The lag axis **adds +0.35 pp of achieved cross-channel gain on CapgMyo** (+1.44% → +1.79%, a +24%
relative lift on the negative-control array) and **destroys 5.29 pp on OTB** (+17.35% → +12.06%).

## Attribution — what moved the ratio, and why

Predictor and entropy back-end are unchanged, so 100% of the delta is the **cross-channel front-end**,
specifically its *selection domain*. Direct instrumentation of `_lagp_select_block` over every
(channel, block) on real data (script re-run of the registry's own selector, 15 000 samples):

| dataset | blocks | τ = 0 | τ ≠ 0 | dominant non-zero τ | \|τ\| ≥ 3 |
|---|---:|---:|---:|---|---:|
| hyser | 7366 | 7163 | 200 (**2.7%**) | −1 (54), +1 (26) | 90 (1.2%) |
| otb | 3654 | 2564 | 1086 (**29.7%**) | +1 (544), −1 (361) → 83% of all non-zero | 66 (1.8%) |
| capgmyo | 7366 | 2577 | 4745 (**64.4%**) | −1 (2469), +1 (934) → 72% of all non-zero | 611 (8.3%) |
| cemhsey | 18502 | 17921 | 437 (**2.4%**) | −1 (34), +1 (57) | 270 (1.5%) |

Two mechanisms, in opposition:

1. **The predicted τ\* = 3–7-sample propagation slice does not exist in the data.** Across all four real
   sets, **≤8.3%** of blocks select \|τ\| ≥ 3 and the non-zero mass is overwhelmingly ±1. Theory: the
   neighbour MI in a surface array is carried by the **quasi-static volume-conducted field**, which is
   *instantaneous* — a neighbouring electrode sees the same source potential with no delay. Only the
   travelling depolarization zone is delayed, and it is a small fraction of the shared power at
   inter-electrode distances of 8–10 mm. So `ρ(τ)` peaks at τ = 0 and the extra lag dimension is mostly
   empty. The physics prediction in the survey is **refuted on real data**.
2. **The widened search buys estimation variance.** The candidate set grows from 5 (4 parents + none) to
   29 (4×7 coarse, +3 fine, +none). The score is *in-sample* Rice bits on the previous 256-sample block,
   so the argmin over ~6× more options suffers a winner's-curse bias — and the lag is the **least
   stationary** axis: partner identity and β are slowly varying (P4), but a *phase/delay* parameter has a
   coherence time shorter than the 125 ms block, so a τ selected from block *i−1* is stale for block *i*
   and a misaligned subtract *increases* residual variance rather than reducing it. This is exactly the
   OTB signature: 29.7% of blocks pick τ ≠ 0 and the set loses 4.51% against its own zero-lag sibling.
3. **Where mechanism 1 is weakest, mechanism 2's cost is also weakest — and net is positive.** CapgMyo
   is a *differential* (bipolar) array: the derivation already cancels the instantaneous common mode
   (neighbour \|corr\| ≈ 0.29 at τ = 0), so the only surviving shared structure is the propagating
   wavefront, mostly at ±1 sample @ 1 kS/s. There the lag lever is the *only* MI left, and it pays
   (+0.34% over the zero-lag sibling; a new CapgMyo record).

## Pareto check

Cost 0.0775 — the most expensive front-end in the cross-channel family, ~2× `bestpartner_adaptive`
(0.03874) and ~2× the best (0.03939). It is **worse ratio at higher cost on hyser, otb and cemhsey**, so
it is dominated *there* — but it is **strictly better than every registered codec on capgmyo**
(1.357519 > 1.352866), so it holds a genuine **non-dominated max-CapgMyo corner** and is **not**
conclusively Pareto-dominated on real data. Kept registered.

## Sanity gates

- Max real ratio 2.0559× (otb) ≪ the 6× ceiling → no leak; the highest ratio anywhere in the run is
  2.1795× (`acar_sel+bestpartner`, otb).
- No FAIL bit-exact rows anywhere in `results/cycle_bench.csv` (`ok=True` on all 120 rows);
  `embedded=OK`, `neural=OK`, cost 0.0775 within both the sEMG and the 125-cyc neural budget.
- **Regression flagged:** −4.91% vs the registered best on OTB and −0.28% on the primary Hyser. Nothing
  in the incumbent set changed (best-partner/adaptive/jointbp2 ratios are unchanged from cycle 15).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (The verifier gate is
correctness/embeddability only: bit-exact round-trip, `embedded_ok`, cost audit.)

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** It does not beat the current best on real data — it
loses on 3 of 4 real sets including the primary Hyser, at 2× the cost. It is kept because it holds the
non-dominated **max-CapgMyo corner** (the first codec to find any cross-channel MI in the
negative-control array beyond the zero-lag ceiling). **The lag lever is spent as a general ratio play**
but is now a *characterised* one: worth ~+0.35 pp of cross-channel gain **only** on differential arrays
where ρ(0) has been cancelled by the derivation, and worth −5 pp on monopolar arrays where ρ(0) is high.
Headline / port pick unchanged.
