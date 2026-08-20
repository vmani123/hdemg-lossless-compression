# 031 — LMS4bcxs+Rice+xchan_bestpartner: cross-channel-gradient context for the bias corrector

- **Cycle:** 31
- **Date:** 2026-08-19
- **Branch:** `compression-cycle-2026-08-19`
- **Candidate:** `LMS4bcxs+Rice+xchan_bestpartner` (a.k.a. `bcxs`), family `temporal`, cost **0.1013**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #2 — the *class of conditioning variables* in the proven P9 bias corrector)

P9 established that a divisionless JPEG-LS/CALIC running-mean bias corrector on
the post-LMS residual is the first live temporal-axis lever, and named
**context definition** as the open knob (frontier #1). Both existing correctors
condition on **own-channel temporal** history (`bc_lite`: 27 sign-history
buckets; `bc`: 30 quantized-magnitude buckets). Hypothesis: on an array whose
dominant redundancy is *spatial* (P1), the residual's context-conditional mean
`E[e | ctx]` should be better predicted by a **cross-channel** context than by a
temporal one. Keep the entire bias machinery verbatim and change only the
context word:

`ctx = ( sgn(e[g−1,t] − e[g−cols,t]),  sgn(e[parent(g),t]),  sgn(e[g,t−1]) )` → 3×3×3 = 27 buckets.

This is a clean single-variable A/B against the shipped 27-context sibling
`LMS4bc_lite`: same bucket count, same update law, same bitstream format, only
the conditioning variables differ.

## Implementation

`research/registry.py` only (additive; no other codec touched).
- `BCXS_MAGIC` / `BCXS_ORDER` / `BCXS_NCTX`, `_bcxs_ctx_rows`, `_bcxs_forward`,
  `_bcxs_inverse`, `bcxs_encode`, `bcxs_decode`; registration
  `Codec("LMS4bcxs+Rice+xchan_bestpartner", …, family="temporal")`.
- **The bias machinery is literally reused, not reimplemented:**
  `_bcxs_forward`/`_bcxs_inverse` call the *same* `_bias_new_state()` and
  `_bias_update()` as `LMS4bc_lite` — same 27 buckets, same counter-halving at
  `N=64` by shift, same `(−N,0]` band test, same int8 clamp. The only diff vs
  `_bias_forward`/`_bias_inverse` is the context word.
- Front-end and back-end untouched: `_bp_select`/`_bp_inverse` best-partner
  subtract verbatim, order-4 sign-sign LMS verbatim (P2), plain adaptive Rice
  untouched (P5 — this conditions a *first moment of the residual stream*
  upstream of the coder, it does not touch the coder).
- **Zero side-info (P4):** bitstream byte-format-identical to `LMS4bc_lite`'s;
  the decoder rebuilds every context and accumulator from residuals it has
  already reconstructed.
- **Causality:** `left = g−1` (guarded by `g % cols != 0`), `up = g−cols`
  (guarded by `g ≥ cols`), and `parent(g) < g` by best-partner construction —
  all three rows have index `< g`, restored before channel `g` in the same time
  slice; off-grid neighbours contribute 0 identically on both sides. Own-channel
  term is `e[g,t−1]`.
- Integer-only (`np.int64`, sign/subtract/shift/compare; no float, no multiply,
  no divide in the added stage).

Extra sanity beyond the gate (32×1200 correlated + common-mode field): all 27
buckets exercised (min occupancy 8, max 4175 — the context is
informative-shaped, not collapsing); the stage modifies 30721/38400 residual
samples (not silently an identity); `_bcxs_inverse(_bcxs_forward(e)) == e`.

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py
LMS4bcxs+Rice+xchan_bestpartner  2.72x          OK      OK      OK   0.101
registry self-test: ALL round-trips bit-exact
```

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.1013`).

| dataset | C | `bcxs` (0.1013) | `bc_lite` (0.0983) | vs `bc_lite` | best `bc` (0.1202) | vs best | front-end-only `bestpartner` (0.0394) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | **1.484874** | 1.483533 | **+0.090%** | 1.485085 | −0.014% (dead tie) | 1.480384 (+0.303%) |
| otb_hdsemg_vl | 64 | **2.181863** | 2.180401 | **+0.067%** | 2.193438 | **−0.528%** | 2.161938 (+0.922%) |
| capgmyo_dba_s1 | 128 | **1.353163** | 1.353778 | −0.045% | 1.353146 | +0.001% (dead tie) | 1.350480 (+0.199%) |
| cemhsey_s1_d1t1 | 320 | **1.971616** | 1.969994 | **+0.082%** | 1.955254 | **+0.837%** | 1.955547 (+0.822%) |

- **Highest CEMHSEY ratio of any codec in the run** (1.971616×, next best
  `bc_lite` 1.969994×).
- **Highest 4-set real mean of any codec in the run: 1.747878×** — above the
  leaderboard best `bc` (1.746730×) at **16% lower cost** (0.1013 vs 0.1202).
- Synthetic: sc0.6 2.623351× / sc0.9 2.598751×, both above `bc_lite`
  (2.617310 / 2.591869) and `bc` (2.593272 / 2.559091).

## Attribution — what moved the ratio, and the isolated cross-channel gain (REAL)

The cross-channel *front-end* and the Rice *back-end* are byte-identical to
`bc_lite`'s and `bestpartner`'s, and the temporal predictor is the same order-4
sign-sign LMS, so the entire move is the **bias-corrector context class**.

**Bias-corrector stage, isolated** (`bcxs` vs the identical pipeline without any
bias stage, `LMS4+Rice+xchan_bestpartner`): **+0.303% Hyser, +0.922% OTB,
+0.199% CapgMyo, +0.822% CEMHSEY.** This is the largest bias-stage contribution
measured on CEMHSEY and OTB of any of the three correctors.

**Cross-channel-ness of the context, isolated** (`bcxs` vs `bc_lite` — identical
bucket count, identical update law, only the conditioning variables move):

| dataset | C | neighbour-MI regime (P1) | Δ from making the context cross-channel |
|---|---:|---|---:|
| otb_hdsemg_vl | 64 | high (xchan lever +18.4%) | **+0.067 pp** |
| hyser_1dof_f1_s1 | 128 | high (+11.3%) | **+0.090 pp** |
| cemhsey_s1_d1t1 | 320 | high (+13.1%) | **+0.082 pp** |
| capgmyo_dba_s1 | 128 | **≈none** (+1.4%, negative control) | **−0.045 pp** |

The sign of the isolated effect tracks neighbour mutual information exactly: it
is positive on all three arrays where cross-channel MI exists and **negative on
the one array where it does not**. That is P1 reappearing on a new axis —
*conditioning* rather than *prediction*.

**Theory.** The sign-sign LMS's constant ±1 update leaves a residual whose
conditional mean is offset from zero in a state-dependent way (P9). What P9 did
not settle is *which* state variable indexes that offset. A context is useful
exactly in proportion to `I(e_c ; ctx)`. The spatial gradient
`sgn(e[g−1,t] − e[g−cols,t])` is a *local-activity-direction* indicator: under
volume conduction, adjacent channels share the far-field mode, so the sign
pattern of neighbouring residuals identifies which side of a propagating
excitation the channel sits on — information that the own-channel sign history
cannot supply because the temporal predictor has already whitened the
own-channel axis (P5's mechanism). Where neighbour MI is absent (CapgMyo's
differential array), the same two spatial slots carry only noise, so 2 of the 3
context dimensions become random bucket-splitting: the accumulators fragment
across 27 buckets that are no better than 3, each bucket's leaky mean is
estimated from ~1/9 as many samples, and the estimation-variance cost shows up
as the −0.045 pp loss. Cross-channel conditioning is therefore not a free
refinement — it buys context relevance with context dilution, and the trade is
won or lost by the array's neighbour correlation, the same quantity that sets
P1's ceiling.

## Pareto check

Cost 0.1013, `embedded_ok` OK, `neural_ok` OK (57.6 enc / 48.0 dec cycles per
sample-ch; 18304 B SRAM at the self-test size). On the **mean-real-vs-cost**
front `bcxs` is a **new Pareto point** — the front computed from
`results/cycle_bench.csv` over embeddable codecs is:

```
cost=0.0079 mean_real=1.50472  delta+Rice
cost=0.0127 mean_real=1.66622  delta+Rice+xchan
cost=0.0366 mean_real=1.73685  LMS+Rice+xchan_joint2
cost=0.0394 mean_real=1.73709  LMS4+Rice+xchan_bestpartner
cost=0.0430 mean_real=1.74149  LMS4+Rice+acar_sel+bestpartner
cost=0.0983 mean_real=1.74693  LMS4bc_lite+Rice+xchan_bestpartner
cost=0.1013 mean_real=1.74788  LMS4bcxs+Rice+xchan_bestpartner   <-- new, front tip
```

It **dominates the current leaderboard best on the mean-real axis** (higher mean
real ratio at 16% lower cost) but does **not** dominate it per-dataset: `bc`
holds a genuine +0.528% win on OTB. Symmetrically `bcxs` is not dominated by
anything — it is the outright CEMHSEY maximum. Nothing is retired as a
consequence.

## Sanity gates

- Max real ratio in the run 2.193438× ≪ 6×; `bcxs`'s own max real 2.181863×.
- Zero FAIL bit-exact rows (`ok=True` on all 150 rows, `bench.py` exit 0,
  registry self-test "ALL round-trips bit-exact").
- Zero regressions: no previously-registered codec moved >0.05% versus
  `results/consolidated_bench.csv` on any real set.
- One real-set regression *by the candidate itself* vs the leaderboard best:
  OTB −0.528%. Recorded, not fatal (it wins CEMHSEY by +0.837%).

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** Promotion condition (b)
(unanimous PROMOTE) is met; condition (a) is not. Against the current best
`LMS4bc+Rice+xchan_bestpartner` the per-dataset scorecard is **1 clear win
(CEMHSEY +0.837%), 1 clear loss (OTB −0.528%), 2 dead ties (Hyser −0.014%,
CapgMyo +0.001%)** — under the same bar cycles 11/13/15/30 applied, that is not
"beats the current best on real data", so the headline and the "one codec to
port next" pick are unchanged.

It is nonetheless the strongest positive of the cycle and the natural headline
challenger for the next one: it holds the **best 4-set mean of any codec ever
benched here at 16% less cost than the incumbent best**, and it converts
frontier #1 ("sweep the bias-corrector context") from an untested hyperparameter
into a measured, mechanism-explained result (see `INSIGHTS.md` P9 refinement).
The obvious follow-up — a decoder-observable *neighbour-correlation gate*
selecting the temporal context on low-MI arrays and the spatial context
elsewhere — is filed as next hypothesis #1 in `SURVEY.md`.
