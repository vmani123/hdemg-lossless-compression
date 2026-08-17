# 016 — LMS4+Rice+xchan_bprank: per-channel backward-adaptive spatial model-ORDER gate (rank-1 vs joint rank-2)

- **Cycle:** 13
- **Date:** 2026-08-10
- **Branch:** `compression-cycle-2026-08-10`
- **Candidate:** `LMS4+Rice+xchan_bprank` (a.k.a. `bprank`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY row 2 — the *repaired* form of INSIGHTS frontier #1)

P1b established that spatial *selection* and *count* are substitutes set by geometry: a single selected
best-partner wins the tight 64-ch OTB array, a jointly-solved best **pair** wins the large 128/320-ch arrays.
Geometry is not uniform *within* an array either (edge/corner channels have fewer parents; channels over a
second muscle are rank-1; interior channels of a diffuse array are rank ≥ 2), so the optimum that flips
*between* arrays should also flip *between channels*. Selecting per channel and per block by empirical code
length over the **union** of the two hypothesis classes has expected code length ≤ min of either fixed class,
up to an O(log) selection-noise term an MDL penalty controls. Deliberately the *right-granularity* gate, not
the naive global channel-count gate (which would send 320-ch CEMHSEY to the rank-2 branch and inherit
`jointbp2`'s −0.17% there).

## Implementation

`research/registry.py` only (`bprank_encode`/`bprank_decode`, magic `0x5252`). H1 = `bestpartner_adaptive`'s
search (`_bp_candidates`/`_bp_opt_beta`/`_bp_score`) keeping the winning **bit count**; H2 = `jointbp2`'s
joint 2×2 integer LS over ≤6 causal-neighbour pairs (`_jbp2_pair_resid`). Gate: `s1 = bits1`,
`s2 = bits2 + ½log₂(B)` (BIC, = 4 bits at B=256) `+ max(0, log₂#pairs − log₂#singles)`; mode flips only if the
challenger beats the incumbent by more than `incumbent >> 7` (~0.8% hysteresis). The winning branch applies
its **own** estimator (closed-form per-block integer-LS subtract for rank-1; joint co-adaptive 2-tap
sign-sign LMS for rank-2, taps frozen during rank-1 blocks) — this is what makes it a model-**order** gate
rather than `jointbp2`'s flat argmin. All gate inputs come from the previous reconstructed raw block and
parents with grid idx < c ⇒ **zero side-info**, look-ahead 0. Integer only; `rtl/`, `sim/` untouched.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all `ok=True`, `embedded=OK`, `neural=OK`), cost **0.0554**:

| dataset | C | `bprank` | best `bestpartner` (0.0394) | vs best | rank-1 branch `bp_adaptive` (0.0387) | rank-2 branch `jointbp2` (0.0468) |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 1.495235 | 1.480384 | **+1.003%** | 1.477020 (**+1.233%**) | 1.496924 (**−0.113%**) |
| otb_hdsemg_vl | 64 | 2.149587 | 2.161938 | **−0.571%** | 2.153106 (**−0.163%**) | 2.152244 (**−0.123%**) |
| capgmyo_dba_s1 | 128 | 1.351456 | 1.350480 | +0.072% | 1.352866 (**−0.104%**) | 1.350287 (+0.087%) |
| cemhsey_s1_d1t1 | 320 | 1.952097 | 1.955547 | −0.176% | 1.953948 (**−0.095%**) | 1.952260 (−0.008%) |
| *4-set mean* | | | | +0.082% | +0.218% | −0.040% |

**The decisive row is not the "vs best" column — it is the two branch columns.** On **three of the four real
sets (otb, capgmyo, cemhsey) `bprank` is below BOTH of its own branches.** Only on Hyser does the gate add
anything over rank-1 (+1.233%), and even there it under-delivers the fixed rank-2 branch by −0.113%.

Achieved cross-channel gain vs temporal-only `LMS+Rice`: **+12.42% (hyser) / +17.76% (otb) / +1.44%
(capgmyo) / +12.88% (cemhsey)**, versus the incumbent's +11.31% / +18.44% / +1.37% / +13.08%. Achieved, not a
ceiling.

Synthetic (mechanism only): synth_sc0.6 2.632145, synth_sc0.9 2.605568 — third of 20 on both, essentially
`jointbp2`'s numbers, again showing the gate lands on the rank-2 answer.

## Attribution

Front-end only: temporal predictor and Rice back-end are the branches' unchanged ones, so 100% of the delta
is the spatial model-order gate. The measurement says the gate **converges to the rank-2 branch and then pays
a small selection tax to get there**: `bprank` sits within −0.123%…+0.087% of `jointbp2` on all four real
sets, at cost 0.0554 vs 0.0468 (+18%).

Theory for why the union bound did not materialise: the bound "E[code length of selector] ≤ min of the fixed
classes" holds for an *oracle* selector. Here the selector is **backward** — it scores both hypotheses on
block *k−1* and commits for block *k*. When the two hypotheses' true code lengths differ by less than the
per-block estimation noise of the score (which is the case on real HD-sEMG: the fixed branches differ by only
0.04%–1.2%), the selector's decisions are dominated by noise, and its expected code length is *worse* than
committing to either fixed class — an instance of the classic model-selection variance penalty. The MDL term
(4 bits/block/channel at B=256) is far too small to arbitrate a decision whose true margin is ~10⁻³ of the
block's bits, and the 0.8% hysteresis band, added to suppress chatter, also freezes wrong decisions. The
per-channel geometry premise is not refuted — it is simply **unmeasurable at block granularity from a causal
estimate**. Note the OTB row: the *tight* array, where P1b says rank-1 should win per-channel, is where the
gate does worst against rank-1 (−0.163%) — precisely because the margin there is smallest.

## Cross-channel gain, isolated (REAL)

The isolated lever here is the **gate**, not the cross-channel subtract (both branches already have one):
against rank-1 **+1.233 / −0.163 / −0.104 / −0.095%** and against rank-2 **−0.113 / −0.123 / +0.087 /
−0.008%**. Net over the four sets versus the better fixed branch per set: **−0.113 / −0.163 / −0.104 /
−0.095%** — negative everywhere.

## Pareto check

Cost 0.0554 > `jointbp2` 0.0468, and `jointbp2` has the higher ratio on hyser, otb and cemhsey. `bprank`'s
**only** non-dominated point is CapgMyo, where it is +0.087% over `jointbp2` (1.351456 vs 1.350287) — and
CapgMyo is the negative-control set where all cross-channel codecs sit inside a 0.3% band. It is therefore
**near-dominated but not conclusively Pareto-dominated** (no single registered codec beats it on all four
real sets at lower cost), so under the retirement rule it stays registered. **Flagged as the first retirement
candidate for next cycle** if the CapgMyo edge does not survive a different sample window.

## Sanity gates

- Max real ratio 2.1496× (otb) ≪ 6× ceiling → no leak.
- 120/120 bench rows `ok=True`; `embedded_ok` OK, `neural_ok` OK, cost 0.0554.
- **Regression flagged:** −0.571% vs the leaderboard best on OTB, −0.176% on CEMHSEY.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split (correctness/embeddability only).

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** It wins the primary Hyser (+1.003%) but regresses OTB
(−0.571%) and CEMHSEY (−0.176%), so it does not beat the best on real data — and, more damningly, it is
below **both** of its own branches on three of four real sets. **INSIGHTS frontier #1 (adaptive selection
between the two proven per-scale spatial front-ends) is now spent ≈0/negative at per-channel-per-block
granularity.**
