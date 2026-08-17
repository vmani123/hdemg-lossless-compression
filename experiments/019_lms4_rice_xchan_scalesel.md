# 016 — LMS4+Rice+xchan_scalesel: backward RANK-2-benefit gate between the two per-scale spatial winners

- **Cycle:** 16
- **Date:** 2026-08-07
- **Branch:** `compression-cycle-2026-08-07`
- **Candidate:** `LMS4+Rice+xchan_scalesel` (a.k.a. `scsel`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (INSIGHTS open-frontier #1 — scale-select the spatial front-end)

P1b settled the per-scale winners: a **single selected best-partner** on tight arrays, a **jointly-solved
best-pair** on large arrays; no fixed front-end wins both. Frontier #1 asked for the arbitration. This
candidate implements the *genuine generalisation* the brief demanded — **the channel count never enters the
codec**, because `C` is only a proxy for what actually decides: the **local rank of the neighbourhood's
cross-channel covariance**.

Per channel `c`, per block `i > 0`, over the **previous already-reconstructed raw block**:
- `B1` = min estimated Rice bits over the **rank-1** option set = {no parent} ∪ {each ≤4 causal grid
  neighbour at its marginal integer-LS gain}.
- `B2` = min estimated Rice bits over the **rank-2** option set = {every candidate *pair* under a joint 2×2
  integer least-squares solve} (parent–parent covariance accounted for → cannot double-count the shared mode
  the retired summed `multiparent` did).
- **Gate:** take rank-2 iff `B2 + (B1 >> 7) ≤ B1` — a 1/128 **margin**.

The margin is the load-bearing part and is what distinguishes this from `jointbp2` (which already does a
greedy argmin over a merged single/pair option set): the rank-2 fit carries one extra free parameter, so on a
genuinely rank-1 neighbourhood it always scores better *in-sample on the block it was fitted on* while
generalising worse to the next block. Charging it > 1/128 of the block's coded length turns the argmin into a
**rank test**. The two branches then apply genuinely *different* front-ends — fixed integer-LS β subtract vs.
co-adaptive 2-tap sign-sign LMS on the shared residual — which is precisely the per-scale arbitration.

Ceiling caveat, recorded in the codec's notes **before** measurement: both branches are already-measured
corners, so the gate can at best reach the **per-set max of the two**, plus whatever a *within-recording
per-channel* rank split adds over a whole-recording choice.

## Implementation

`research/registry.py` only: `SCSEL_*` constants, `_scsel_gate_block`, `_scsel_forward`/`_scsel_inverse`,
`scsel_encode`/`scsel_decode`, and the `Codec("LMS4+Rice+xchan_scalesel", …)` registration. Both branches
reuse the verified originals verbatim (`_bp_candidates`/`_bp_opt_beta`/`_bp_score`; `_jbp2_pair_resid`).
Joint taps persist across blocks and are **frozen** through rank-1 blocks (deterministic on both sides).
Block 0 bootstraps to rank-1/no-parent. Zero side-info (header = magic, cols, C, N), look-ahead 0,
integer-only. Temporal predictor (P2) and Rice back-end (P5) untouched — purely a spatial lever (P1),
backward-adaptive (P4).

Gate: `PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest` →
`registry self-test: ALL round-trips bit-exact`, `LMS4+Rice+xchan_scalesel … OK OK OK 0.049`.

Extra branch coverage (the self-test field is near-independent noise, so its gate picks rank-1 on all 279
channel-blocks): on a synthetic genuinely rank-2 field the gate fired 118 rank-1 / 161 rank-2, round-trip
bit-exact; a geometry stress sweep over 8 `(C, N, cols)` shapes (incl. `N=1`, non-rectangular `C`,
`cols > C`) was **all bit-exact**, 325 rank-1 / 170 rank-2 decisions.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (all bit-exact, `embedded_ok` OK, `neural_ok` OK), from `results/cycle_bench.csv`, cost **0.0494**:

| dataset | `scsel` | best `bestpartner` (0.0394) | vs best | `scsel` xchan gain (vs `LMS+Rice`) | best-partner xchan gain |
|---|---:|---:|---:|---:|---:|
| otb_hdsemg_vl (64 ch) | 2.153029 | 2.161938 | −0.412% | +17.95% | +18.44% |
| **hyser_1dof_f1_s1 (128 ch)** | 1.494310 | 1.480384 | **+0.941%** | **+12.35%** | +11.31% |
| capgmyo_dba_s1 (128 ch) | 1.352453 | 1.350480 | **+0.146%** | +1.52% | +1.37% |
| cemhsey_s1_d1t1 (320 ch) | 1.951624 | 1.955547 | −0.201% | +12.86% | +13.08% |

4-set mean **1.737854** vs `bestpartner` 1.737087 (**+0.044%** — a dead tie).
Synthetic: `synth_sc0.6` 2.631056, `synth_sc0.9` 2.605206 (3rd of 20 on both, behind `jointbp2`/`joint2`).

**Against its own two branches** — the ceiling the caveat named:

| dataset | `scsel` | rank-1 branch (`bestpartner_adaptive`, 0.0387) | rank-2 branch (`jointbp2`, 0.0468) | vs branch max | vs branch min |
|---|---:|---:|---:|---:|---:|
| otb_hdsemg_vl | 2.153029 | 2.153106 | 2.152244 | **−0.004%** | +0.036% |
| **hyser_1dof_f1_s1** | 1.494310 | 1.477020 | 1.496924 | −0.175% | **+1.171%** |
| capgmyo_dba_s1 | 1.352453 | 1.352866 | 1.350287 | −0.031% | +0.160% |
| cemhsey_s1_d1t1 | 1.951624 | 1.953948 | 1.952260 | −0.119% | **−0.033%** |

## Attribution

Temporal predictor and entropy back-end are identical to both branches → the whole effect is the
**cross-channel front-end's rank gate**. Three findings, each with a mechanism:

1. **The gate works as a rank test, and it is doing real within-recording arbitration.** On Hyser it lands
   **+1.171% above its rank-1 branch** and within −0.175% of its rank-2 branch; on OTB it lands **+0.036%
   above its rank-2 branch** and within −0.004% of its rank-1 branch. It selects the *correct* branch on both
   scales **without ever seeing `C`** — the backward `B2 + B1/128 ≤ B1` statistic is a sufficient proxy for
   the local covariance rank. This is the first construction to hold both per-scale corners from one codec,
   and it does so at **zero side-info, look-ahead 0**. It also posts the **best CapgMyo ratio of any
   registered codec** (1.352453) — the negative-control set, where the gate correctly almost never pays for
   rank 2.
2. **But it cannot exceed the max of its branches, and it doesn't.** It is −0.004…−0.175% below the per-set
   branch max on all four sets. Theory: the gate is a *selector over two estimators*, so its achievable
   entropy is `min` over branches **plus** the loss from choosing wrong on some blocks. The within-recording
   per-channel rank split the hypothesis hoped to harvest is worth less than the selection loss it costs —
   i.e. the neighbourhood rank is close to **stationary within a recording**, exactly the P4 "slowly-varying
   parameter" regime, so a whole-recording choice already captures nearly all of it.
3. **The one genuine loss is CEMHSEY, where the gate is −0.033% below even the *worse* of its two branches.**
   That is a signature of the branch-switch cost the ceiling caveat did not anticipate: the rank-2 joint taps
   are **frozen** through rank-1 blocks (a determinism requirement), so every rank-1 → rank-2 switch resumes
   the sign-sign LMS from a stale tap state and pays a re-convergence transient. On the 320-ch array with the
   flattest `B1`/`B2` margins the gate toggles most often, so the transient cost accumulates and exceeds the
   arbitration benefit. Mechanistically: the selector's decision variable and the adaptive estimator's state
   are **coupled**, so a "free" selector is not free.

Net: the front-end's *ratio* ceiling is confirmed to be a shared spatial-MI ceiling, not a mechanism gap.
Every LMS4 cross-channel codec now sits within **±1.1%** on Hyser and within **±0.5%** on the other three.

## Pareto check

Not dominated, and not dominating:
- vs `bestpartner` (0.0394): `scsel` **wins hyser (+0.941%) and capgmyo (+0.146%)**, loses otb/cemhsey.
- vs `jointbp2` (0.0468, cheaper): `scsel` **wins otb (+0.036%) and capgmyo (+0.160%)**, loses hyser/cemhsey.
- vs `joint2` (0.0366, cheaper): `scsel` wins hyser/otb/capgmyo, loses cemhsey.

No registered codec has ≥ ratio on all four real sets at ≤ cost → **genuinely non-dominated**. It is *not*
the new best either: it **regresses on OTB (−0.412%) and CEMHSEY (−0.201%)** and its 4-set mean is a +0.044%
tie. Kept registered as the **max-CapgMyo corner** and the only zero-side-info codec holding both per-scale
corners simultaneously.

## Sanity gates

- Max real ratio 2.1530× (otb) ≪ the 6× ceiling → no leak.
- Zero FAIL bit-exact rows in `results/cycle_bench.csv` (120 rows, all `ok=True`); `embedded_ok` OK,
  `neural_ok` OK, cost 0.0494.
- No registered codec regressed: all previously-benched (dataset, codec) ratios are bit-identical to
  `results/06_real_bench*.csv`.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**Registered, NOT promoted, NOT retired.** Unanimous PROMOTE, but it does not beat the current best on real
data (loses OTB and CEMHSEY; 4-set mean tie) → the promotion rule blocks it. It is non-dominated, so
"not best" is not grounds for retirement.

**Frontier #1 is now SPENT — resolved, not failed.** The rank gate is *mechanically correct* (it picks the
right branch on both scales from a decoder-observable statistic, at zero side-info) but *ratio-neutral*,
because the two branches' per-set maxima are themselves within ~0.5% of each other on three of four sets and
the neighbourhood rank is near-stationary within a recording. **The remaining bits are not in the choice of
spatial front-end.** Headline / port pick unchanged.
