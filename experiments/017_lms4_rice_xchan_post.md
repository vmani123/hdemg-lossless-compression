# 017 — LMS4+Rice+xchan_post: innovation-domain spatial subtract (cascade reorder)

- **Cycle:** 16 (row 18 of `CYCLE_LOG.md`)
- **Date:** 2026-08-05
- **Branch:** `compression-cycle-2026-08-05`
- **Candidate:** `LMS4+Rice+xchan_post`
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY candidate 3 — the untried cascade topology, cost-neutral)

Every registered codec is **spatial-then-temporal** (`_*_forward` → `ec.lms_forward`). Reversing it —
order-4 LMS first per channel, then the proven rank-1 adaptive subtract applied to the *innovations* —
was argued to code fewer bits for two reasons: (i) **stagewise objective mismatch** — the spatial stage
currently minimizes *raw* residual power while the coder pays for the residual *after* whitening, so the
optimal weight is the ratio of innovation cross-spectra, not the broadband raw LS β; (ii) **the mixture is
harder to whiten** — `x[c] − β·x[p]` mixes two AR processes and a sum of AR(p) is ARMA of higher order, so
a fixed order-4 whitener (mandatory per P2) systematically under-fits what the current cascade hands it.

## Implementation

`research/registry.py` only. `xpost_encode`: `e = ec.lms_forward(x, order=4)` **first**, then
`_xpost_forward` applies `z[g,blk] = e[g,blk] − ((β·e[p,blk]) >> BP_SHIFT)` to the innovation rows, with
`(partner, β)` re-selected per block from the **previous block of the innovations** by `_bpa_select_block`
**verbatim** (same `_bp_candidates`, `_bp_opt_beta`, `_bp_score`, same no-partner option, block-0
bootstrap). Zero side-info, look-ahead 0, cost **0.03874263375 — bit-identical to
`LMS4+Rice+xchan_bestpartner_adaptive`** (enc = dec = 39 ops/sample-ch, state 27 B/ch), as the
cost-neutral-reorder hypothesis requires. Stated risk mitigation implemented: `XPOST_BLOCK = 4·ec.BLOCK =
1024` samples (longer spatial time constant for the lower-SNR innovation-domain gradient); the Rice
back-end keeps its own 256-sample *k* blocks. Everything else held fixed, so the delta against
`bestpartner_adaptive` (the same estimator in the RAW domain) is attributable to the cascade order.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all rows `ok=True`, `embedded=OK`, `neural=OK`):

| dataset | xchan_post (0.038743) | raw-domain twin `bestpartner_adaptive` (0.038743) | best `bestpartner` (0.0394) | vs twin | vs best |
|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 1.461168 | 1.477020 | 1.480384 | **−1.07%** | **−1.30%** |
| otb_hdsemg_vl | 2.080072 | 2.153106 | 2.161938 | **−3.39%** | **−3.79%** |
| capgmyo_dba_s1 | 1.347916 | 1.352866 | 1.350480 | **−0.37%** | −0.19% |
| cemhsey_s1_d1t1 | 1.929132 | 1.953948 | 1.955547 | **−1.27%** | **−1.35%** |
| 4-set mean | 1.7046 | 1.7342 | 1.7371 | −1.71% | −1.87% |

Synthetic: `synth_sc0.6` 2.568720, `synth_sc0.9` 2.507811 — also last among the LMS4 cross-channel family.

### Confound isolated: domain vs. spatial block length

`xchan_post` differs from its twin in **two** ways (innovation domain **and** B = 1024 vs 256). Both were
measured directly at matched settings (same order-4 LMS, same `_bpa_select_block` estimator, same Rice
back-end; ratios = raw bytes / Rice bytes):

| dataset | post B=256 | pre B=256 | post B=1024 | pre B=1024 | **domain effect @B=256** | **block effect (pre, 256→1024)** |
|---|---:|---:|---:|---:|---:|---:|
| hyser | 1.4686 | 1.4770 | 1.4612 | 1.4701 | **−0.57%** | −0.47% |
| otb | 2.0975 | 2.1531 | 2.0801 | 2.1368 | **−2.58%** | −0.76% |
| capgmyo | 1.3500 | 1.3529 | 1.3479 | 1.3511 | **−0.21%** | −0.13% |
| cemhsey | 1.9407 | 1.9540 | 1.9291 | 1.9430 | **−0.68%** | −0.56% |

Both terms are negative and separable: the **reorder itself** loses 0.21–2.58% at matched block length,
and the **mitigation backfired** — the 4× longer spatial re-selection block costs a further 0.13–0.83% in
*both* domains.

## Cross-channel gain, isolated, on REAL data (achieved, not a ceiling)

Baseline measured directly (order-4 LMS + adaptive Rice, no cross-channel stage): hyser 1.3321×,
otb 1.8347×, capgmyo 1.3336×, cemhsey 1.7280×.

| dataset | xchan_post xchan gain | raw-domain twin | fraction of the raw-domain gain retained |
|---|---:|---:|---:|
| hyser | **+9.69%** | +10.88% | 89% |
| otb | **+13.37%** | +17.35% | **77%** |
| capgmyo | **+1.07%** | +1.44% | 74% |
| cemhsey | **+11.64%** | +13.08% | 89% |

## Attribution — what moved the ratio, and why

The predictor (order-4 sign-sign LMS), the entropy back-end (adaptive Rice) and the spatial *estimator*
are byte-identical to the raw-domain twin, so the loss is entirely the **cascade order** (plus the
separately-measured block-length term above). Mechanism:

- **The two stages nearly commute, so there was no first-order gain to win.** For a *fixed* β and a filter
  `A` applied identically to both channels, `A(x_c − βx_p) = A x_c − β·A x_p` — reordering is a no-op.
  What breaks the commutation is that the LMS whitener is **per-channel adaptive**: `A_c ≠ A_p`.
- **Spatial-first is the favourable side of that asymmetry.** Subtract first, and the temporal predictor
  adapts to *exactly the sequence that gets coded*. Whiten first, and the spatial stage is handed two
  signals that were whitened by **different** adaptive filters, so their shared component has already been
  partially — and differently — removed from each.
- **Whitening destroys the band that carries the coherence.** Volume-conducted common mode is lowpass and
  high-power; the LMS whitener flattens exactly that band, so the inter-channel correlation *between
  innovations* is strictly lower than between raw channels. Hence the innovation-domain subtract recovers
  only 74–89% of the raw-domain cross-channel gain, and the deficit is **largest on the highest-coherence
  array** (OTB, −2.58% at matched block, retaining 77% of the gain) — a signature a block-length change
  cannot produce.
- **Hypothesis (ii) is refuted.** The "difference of two AR processes is high-order ARMA, so order-4
  under-fits" argument predicts spatial-first should be *harder* to whiten; it is measurably *easier* to
  code, on all four real sets. Consistent with P2: the residual is near-white after order 4 either way.
- **The mitigation is a third real-data learning.** Lengthening the spatial re-selection block 256 → 1024
  hurts in the raw domain too (−0.13…−0.76%), so `(partner, β)` are genuinely non-stationary at the
  ~125 ms scale and *more frequent* backward re-selection is strictly better — a refinement of P4.

## Pareto check

Cost **0.03874263375, exactly equal** to `LMS4+Rice+xchan_bestpartner_adaptive`'s (same enc/dec ops 39,
same state 27 B/ch, same look-ahead 0, same block-legality) with **strictly worse ratio on all four real
sets**. There is no axis — ratio, cost, state, latency, side-info — on which it is better, so it holds
**no Pareto corner**: it is conclusively Pareto-dominated (equal cost, uniformly worse ratio, which is
stronger than the usual "worse ratio AND higher cost" test, not weaker).

## Sanity gates

- Max real ratio 2.0801× (otb) ≪ the 6× ceiling → no leak.
- No FAIL bit-exact rows anywhere in `results/cycle_bench.csv` (`ok=True` on all 120 rows);
  `embedded=OK`, `neural=OK`.
- **Regression flagged and quantified:** worst embeddable cross-channel codec on every real set this
  cycle (−1.30% to −3.79% vs the registered best). No incumbent's numbers changed.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split. (Correctness/embeddability only —
the codec is bit-exact and legitimately embeddable; it simply loses on ratio.)

## Decision

**RETIRED. NOT promoted.** `retired=True` + `retired_reason` set on its `Codec(...)` registration in
`research/registry.py`. It is dominated at *identical* cost by `LMS4+Rice+xchan_bestpartner_adaptive` on
all four real sets, so it can never be a port candidate and re-benching it every cycle would only
re-litigate a settled topology question. **The cascade-order lever is spent NEGATIVE**: spatial-first is
the correct topology, for a stated reason (whitening removes the lowpass band that carries the neighbour
MI, and it must be the *coded* sequence the temporal predictor adapts to). Headline / port pick unchanged.
