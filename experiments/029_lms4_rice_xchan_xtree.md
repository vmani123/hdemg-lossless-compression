# 017 — LMS4+Rice+xchan_xtree: Chow–Liu maximum-coding-gain spanning-tree channel pairing

- **Cycle:** 16
- **Date:** 2026-08-16
- **Branch:** `compression-cycle-2026-08-16`
- **Candidate:** `LMS4+Rice+xchan_xtree` (a.k.a. `xtree`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #3 — the *graph topology and coding order* of the rank-1 spatial edges)

Chow–Liu: among all first-order (tree) dependency structures, the one minimizing KL
divergence to the true joint is the maximum-weight spanning tree with MI edge weights; for
jointly Gaussian channels the edge MI is `−½log₂(1−ρ²)`, which *is* the rank-1 pairwise
coding gain the incumbent already exploits. The incumbent's per-channel greedy over 4
**raster-causal** neighbours is therefore a provably sub-optimal constrained tree: it forbids
half of every channel's spatial neighbourhood (right/down are `idx > c`) and picks greedily
under a fixed order. Replacing it with a backward-derived maximum-weight spanning tree,
coded in the tree's topological order, relaxes both constraints at **zero side-info** (the
decoder recomputes the same tree from the previous reconstructed block). Each edge stays one
rank-1 adaptive subtract, so this does not re-enter P3's dead multi-tap end. Payoff should
concentrate in (a) the freed right/down directions and (b) raster-boundary channels
(row 0 / col 0) that today have 0–1 candidates.

## Implementation

`research/registry.py` only (additive; `rtl/`, `sim/` untouched).
- `_xtree_edges(C, cols)` — the **named simplification**: radius-restricted undirected
  candidate set = full 8-neighbourhood + same-column ±2 (`XTREE_ROWR=2`), ~10 incident /
  ~5 unique edges per channel, deliberately **not** restricted to `index < g`.
- `_xtree_select_block` — per block, from the **previous raw block only**: integer-LS gain
  in both orientations (`_xtree_beta`, `_bp_opt_beta` semantics vectorized), Rice bits saved
  per orientation via `_xlag_row_bits` (bit-identical to `_bp_score`), symmetric weight
  `w{u,v} = saving(u←v) + saving(v←u)`, Kruskal (descending `w`, ties by `(u,v)`) with
  path-compressed union-find → maximum-weight spanning **forest** (`w ≤ 0` edges dropped),
  each component rooted at its lowest-index channel, BFS → parent map + topological order.
- `_xtree_forward` / `_xtree_inverse` — **block-outer** loops (this is what lets a parent
  have a *higher* index than its child); block 0 bootstraps to no-parent.
- Back-end held fixed: order-4 sign-sign LMS (P2) + adaptive Golomb-Rice (P5). Zero
  side-info (P4): the 12-byte `<HHII` header carries no tree/parent/β data.
Integer-only throughout (all arrays int64, no float in the codec path). Bit-exact on the
registry gate plus 7 extra shapes incl. non-block-multiple `N` — (32,2500,8), (64,1300,8),
(16,700,4), (48,769,8), (8,600,8), (1,600,1), (5,300,16) — and all-zero / all-(−32768) /
all-(+32767). Mechanism verified non-degenerate: on a synthetic volume-conduction grid
(C=64, cols=8) the derived tree used 567 edges over 9 blocks of which **172 (30.3%) have
parent index > child** — edges structurally impossible under `_bp_candidates`.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok` OK, `neural_ok` OK, cost **0.073308**), from
`results/cycle_bench.csv`:

| dataset | C | `xtree` | best `bestpartner` (0.0394) | vs best | top registered on that set |
|---|---:|---:|---:|---:|---|
| **hyser_1dof_f1_s1** | 128 | 1.4822 | 1.4804 | **+0.12%** | `jointbp2` 1.4969 (0.0468) |
| otb_hdsemg_vl | 64 | 2.1707 | 2.1619 | **+0.41%** | `acar_sel+bestpartner` 2.1795 (0.043) |
| capgmyo_dba_s1 | 128 | 1.3527 | 1.3505 | **+0.16%** | `xlag` 1.3579 (0.0982) |
| cemhsey_s1_d1t1 | 320 | 1.9528 | 1.9555 | **−0.14%** | `bestpartner` 1.9555 (0.0394) |

4-set mean **1.7396** vs best 1.7371 (+0.14%) — but below `acar_sel+bestpartner`'s 1.7415.

## Attribution — isolated cross-channel gain on REAL data

Null model = the identical back-end with the spatial front-end removed (order-4 sign-sign
LMS + adaptive Rice, 12-byte header, no side-info), measured directly. Compared against
`bestpartner_adaptive`, which is `xtree`'s exact zero-side-info peer (same predictor, same
back-end, same per-block backward re-selection — only the graph/order differ):

| dataset | C | LMS4+Rice (temporal only) | `xtree` xchan gain | `bestpartner_adaptive` | Δ (structural gain) | ~edges ranked (≈5C) |
|---|---:|---:|---:|---:|---:|---:|
| otb_hdsemg_vl | 64 | 1.8347× | **+18.32%** | +17.36% | **+0.96 pp** | ~320 |
| hyser_1dof_f1_s1 | 128 | 1.3321× | **+11.27%** | +10.88% | **+0.39 pp** | ~640 |
| capgmyo_dba_s1 | 128 | 1.3336× | **+1.43%** | +1.45% | −0.02 pp | ~640 |
| cemhsey_s1_d1t1 | 320 | 1.7280× | **+13.01%** | +13.07% | **−0.06 pp** | ~1600 |

Predictor and back-end are held fixed by construction, so **the whole move is the
cross-channel front-end's graph topology**. `xtree`'s +18.32% on OTB is the **highest
cross-channel gain any registered codec achieves on OTB** (incumbent best-partner +17.84%).

Chow–Liu's structural promise is **real and measurable, and it decays monotonically with
array size**: +0.96 pp at C=64, +0.39 pp at C=128, −0.06 pp at C=320 (CapgMyo, C=128, is
the ≈0-MI negative control and behaves as such at −0.02 pp). The mechanism is a
bias–variance trade the theorem does not price. Chow–Liu is optimal given the **true** edge
MIs; here every edge weight is a backward estimate from **one fixed 256-sample block**,
while the number of edges being ranked grows as ≈5C. At C=64 there are ~1.25 edges per
available sample and the true structure is recovered well enough that the freed right/down
directions and the boundary channels (which the raster set starves of candidates) pay
+0.96 pp. At C=320 there are ~6.25 edges per sample, the ranking is dominated by estimation
noise, and greedy Kruskal *locks in* the noise as global structure — a spurious high-weight
edge does not just waste one channel, it displaces the whole subtree. The incumbent's
4-candidate raster set is, in this light, an accidental **regularizer**: a strong structural
prior that costs a little bias and buys a lot of variance, and that trade turns favourable
exactly as C grows. Same lesson as P2 (deeper prediction fits noise) transposed from the
temporal to the spatial-structure axis.

## Pareto check

Cost 0.073308 — 1.86× the leaderboard best (0.0394) and 1.89× its peer
`bestpartner_adaptive` (0.038743); state 79 B/ch ⇒ 10.1 KB at 128 ch (vs 27 B/ch ⇒ 3.5 KB).
`embedded_ok` OK, `neural_ok` OK.

**Per-dataset it is dominated on every real set** by a strictly cheaper registered codec:
hyser — `joint2` 1.4930×/0.0366; otb — `acar_sel+bestpartner` 2.1795×/0.043; capgmyo —
`bestpartner_adaptive` 1.3529×/0.038743; cemhsey — `bestpartner` 1.9555×/0.0394. It tops
**no** real dataset.

**But no *single* registered codec dominates it across all four** — the codecs that beat it
on Hyser (`joint2` 2.1497×, `jointbp2` 2.1522×) lose to it on OTB (2.1707×), and the codecs
that beat it on OTB/CEMHSEY lose to it on Hyser. Under the strict retire rule (worse ratio
AND higher cost than an already-registered codec) it is **not conclusively dominated** →
kept registered as the non-dominated tight-array structural corner.

## Sanity gates

- Max real ratio across the run 2.1795× ≪ 6× → no leak. `xtree`'s own max real 2.1707×.
- No FAIL bit-exact rows in the run (`bench.py` asserts; exit code 0). `ok=True`,
  `embedded_ok` OK, `neural_ok` OK, cost 0.073308.
- One regression vs the incumbent best: cemhsey −0.14% (−0.0028×). No other real-set
  regression; +0.12/+0.41/+0.16% on the other three.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** It satisfies promotion condition (b)
(unanimous PROMOTE) but not (a): it does **not** beat the current best on real data — it
regresses CEMHSEY by −0.14%, and it holds the top ratio on none of the four real sets
(behind `jointbp2` on Hyser, `acar_sel+bestpartner` on OTB, `bestpartner_adaptive`/`xlag` on
CapgMyo, `bestpartner` on CEMHSEY), all while costing 1.86× the best. That is the same bar
cycles 11/13/15 applied to `joint2`, `jointbp2` and `acar_sel`, which also won a subset of
sets and were kept-not-promoted. Headline / "one codec to port next" unchanged.

The result is nonetheless the **most informative positive of the cycle**: it is the first
measurement that isolates *spatial-structure freedom* from *edge quality*, and it delivers
a clean, monotone C-scaling law (see `INSIGHTS.md` P8) plus a concrete, low-risk next
construction — gate the tree search on the decoder-observable channel count (`C ≤ 64` →
tree, `C ≥ 128` → raster best-partner), exactly the zero-side-info gate `acar_sel` already
proved.
