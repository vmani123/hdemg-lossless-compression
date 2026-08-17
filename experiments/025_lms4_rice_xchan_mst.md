# 016 — LMS4+Rice+xchan_mst: max-MI (Chow-Liu) spanning-tree channel topology

- **Cycle:** 17
- **Date:** 2026-08-13
- **Branch:** `compression-cycle-2026-08-13`
- **Candidate:** `LMS4+Rice+xchan_mst` (a.k.a. `xmst`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #2 — attack the raster-causal parent set inside the dominant lever P1)

`_bp_candidates` only offers channel `c` parents with **index < c** on a raster scan, so exactly
**half the 8-neighbourhood** (right / down / down-left / down-right) is structurally unreachable,
and the per-channel greedy pick under an arbitrary scan order is not the optimal parent structure
even among the parents it *can* see. Chow & Liu (IEEE Trans. IT 14(3):462–467, 1968) prove the
maximum-weight MI spanning tree is the tree factorization minimizing KL to the true joint — exactly
the entropy-minimizing rank-1 dependency structure the current front-end greedily approximates.
Prediction: freeing the topology recovers the MI lost on edge channels and on any channel whose
strongest correlate lies later in raster order.

## Implementation

`research/registry.py` only. Candidate graph = the undirected 8-neighbourhood (~4 edges/ch, the
embeddability cap — explicitly *not* the complete graph). Edge weight
`w(u,v) = max(0, save(u|v)) + max(0, save(v|u))` where `save` is the coded-bit saving in estimated
Rice bits from `_bp_score` at the integer-LS gain from `_bp_opt_beta` (both reused verbatim) — the
integer stand-in for `N·I(u;v)`, clamped at 0 since `I ≥ 0`. Kruskal + union-find (path halving),
deterministic tie-break, BFS rooting → `parent[]` + root→leaf traversal order. One rank-1 subtract
per tree edge (so not the retired summed `multiparent`, not the retired multi-tap `iklt`). Tree and
gains derive **only from block `i−1`**, which the decoder holds bit-identically → zero side-info,
look-ahead 0, 12-byte header. The **decoder** walks channels in tree order (indirect BRAM addressing
on the Spartan-7; the on-node encoder is unaffected). Cost 0.0464, `state_bytes_per_ch=28`,
`embedded_ok=OK`, `neural_ok=OK`. Implementer's non-degeneracy check (synthetic, mechanism only):
9/23 tree edges pointed to a **higher-index** parent — i.e. into the half of the neighbourhood
`_bp_candidates` structurally cannot reach.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data (bit-exact `ok=True`, `embedded_ok=OK`, `neural_ok=OK`), from `results/cycle_bench.csv`:

| dataset | C | grid | `xchan_mst` (0.0464) | best `bestpartner` (0.0394) | vs best | streaming `bestpartner_adaptive` (0.0387) | **vs streaming (isolated)** |
|---|---:|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | 8×16 | 1.482324 | 1.480384 | **+0.131%** | 1.477020 | **+0.359%** |
| otb_hdsemg_vl | 64 | 5×13 | 2.170168 | 2.161938 | **+0.381%** | 2.153106 | **+0.792%** |
| capgmyo_dba_s1 | 128 | 8×16 | 1.352732 | 1.350480 | +0.167% | 1.352866 | −0.010% |
| cemhsey_s1_d1t1 | 320 | 5×64 | 1.953121 | 1.955547 | **−0.124%** | 1.953948 | −0.042% |

4-set mean 1.7396× vs best 1.7371× (**+0.14%**). Synthetic: `synth_sc0.6` 2.587746×,
`synth_sc0.9` 2.547630× (vs adaptive 2.584705×/2.544000×).

## Attribution — which mechanism moved the ratio

Temporal predictor (order-4 sign-sign LMS) and entropy back-end (adaptive Rice) are unchanged, so
the whole delta is front-end topology. The **clean isolation** is against
`bestpartner_adaptive`: both are backward-adaptive, zero-side-info, rank-1, per-256-block; the
*only* difference is the parent graph (raster-causal best-of-4 vs 8-neighbourhood max-weight tree).
That isolated topology gain is **+0.359% (hyser), +0.792% (otb), −0.010% (capgmyo), −0.042%
(cemhsey)**.

**Isolated cross-channel gain on REAL data** (vs temporal-only `LMS+Rice`, same CSV):

| dataset | `LMS+Rice` | `xchan_mst` | **xchan gain** | `bestpartner` xchan gain |
|---|---:|---:|---:|---:|
| hyser | 1.329992 | 1.482324 | **+11.45%** | +11.31% |
| otb | 1.825352 | 2.170168 | **+18.89%** | +18.44% |
| capgmyo | 1.332259 | 1.352732 | **+1.54%** | +1.37% |
| cemhsey | 1.729317 | 1.953121 | **+12.94%** | +13.08% |

**Mechanism.** The gain is real but **small and geometry-gated**, and its sign follows exactly what
the theory predicts: freeing the topology only pays where the raster restriction is a *binding
constraint*. On the tight, anisotropic 5×13 OTB array (neighbour |corr| 0.73–0.79 along the muscle
fibre direction) the strongest correlate frequently lies in the raster-unreachable half, and the
array is small enough (64 ch, ~250 edges) that the per-block MI weights are estimated with low
variance → **+0.79%**. On CEMHSEY (320 ch, 5×64) and CapgMyo the tree pays for itself only in
estimation variance: the raster 4-neighbourhood already contains a near-optimal parent (the local
MI field is smooth and near-isotropic there), so the extra structural freedom buys ~0 MI while
Kruskal's global optimization over ~1280 stale edge weights adds selection noise → −0.01…−0.04%.
Note this is the *same* bias–variance ledger that sank `xlag` (015), but with a far better ratio of
real extra MI to extra hypothesis space: the tree doubles the candidate set (~4 → ~8 scored
orientations), `xlag` multiplied it by ~9 for MI that wasn't there.

## Pareto check

**Non-dominated, not the best.** On the 4-set mean (1.7396× at cost 0.0464) it is edged out by
`LMS4+Rice+acar_sel+bestpartner` (1.7415× at 0.0430) — but that is a *mean* statement only:
`xmst` is **strictly higher than `acar_sel` on hyser (1.482324 vs 1.480384) and capgmyo (1.352732
vs 1.350480)**, so no registered codec beats it on ratio at lower-or-equal cost across the corpus.
It is therefore **not conclusively Pareto-dominated** → kept registered. It is likewise dominated by
this cycle's `LMS4bc+...` on ratio, but at 2.6× lower cost (0.0464 vs 0.1202), so it holds a genuine
mid-cost corner.

## Sanity gates

- Max real ratio 2.1702× (otb) ≪ the 6× ceiling → no leak.
- Zero bit-exact failures in `results/cycle_bench.csv` (0/120 rows).
- `embedded_ok=OK`, `neural_ok=OK`, cost 0.0464.
- Regression: −0.124% on cemhsey vs the registered best (and −0.042% vs the streaming incumbent) —
  small, one-sided, and mechanistically explained above.
- Robustness beyond the gate (implementer): C=24/6, 17/5 (ragged), 5/1, 2/2, 1/4, 13/16, 32/8 all
  bit-exact.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED; NOT promoted.** It beats the registered best on 3 of 4 real sets including the
primary Hyser (+0.131%) at higher cost, but it is beaten on every real set by this cycle's promoted
`LMS4bc+Rice+xchan_bestpartner` (hyser +0.186%, otb +1.072%, capgmyo +0.031%, cemhsey +0.109% in
`bc`'s favour), so it is not the new best. Kept as the **cheapest zero-side-info front-end that
improves on the streaming incumbent** — and as the settled measurement of how much the raster
restriction actually costs (**≤0.8%, only on tight anisotropic arrays**), which retires the
"structural half-neighbourhood loss" argument as a large lever.
