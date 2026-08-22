# 035 — LMS4bcpool+Rice+xchan_bestpartner: James-Stein pooling of the bias corrector's per-context means

- **Cycle:** 36
- **Date:** 2026-08-22
- **Branch:** `compression-cycle-2026-08-22`
- **Candidate:** `LMS4bcpool+Rice+xchan_bestpartner` (a.k.a. `bcpool`), family `temporal`, cost **0.1282**
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey

## Hypothesis (SURVEY #3 — the bias stage's THIRD axis: estimator sample support)

P9's two explored axes are the context's **class** (`bcxs`) and its **bucket
count** (`bc` vs `bc_lite`, closed as a dead end). Both trade *relevance*
against *dilution*: a richer context indexes the residual bias better but
fragments each bucket's sample count, and the exchange rate is the array's
neighbour correlation. `bcpool` attacks the **denominator of that trade
directly** — not what the buckets condition on, but how well each bucket's mean
is *estimated*.

Each per-channel bucket mean is a leaky integrator with an effective ~32-hit
window (`S += e − (S>>5)`), so it is a **high-variance** estimate. Classical
James-Stein / empirical-Bayes says that when many channels estimate the same
parameter family, shrinking each channel's estimate toward the **pooled** mean
strictly reduces total risk whenever the per-channel means are drawn from a
common distribution. Construction: hold context class, bucket count (30),
per-channel update law and bitstream layout **byte-identical to `LMS4bc`** and
change only the read:

`mu = ((2^w − 1)·mu_c + mu_bar) >> w`, `w = 2` → `mu = (3·mu_c + mu_bar) >> 2`

with `mu_c = (S[c,q]+16)>>5` (the incumbent's read, unchanged) and
`mu_bar = (Sbar[q]+256)>>9` from ONE array-wide accumulator `Sbar[30]`.

## Implementation

Only `research/registry.py` touched (`rtl/`, `sim/` untouched; no existing codec
altered; the two earlier candidates of this cycle preserved). New section before
`class Codec` (~line 4954): `BCPOOL_MAGIC=0x4350`, `BCPOOL_W=9`, `BCPOOL_RND`,
`BCPOOL_SHR=2`, `_bcpool_mu`, `_bcpool_slice_update`, `_bcpool_forward`,
`_bcpool_inverse`, `bcpool_encode`, `bcpool_decode`; registration constants
`_BCPOOL_XTRA`, `_BCPOOL_SHARED_B`, `_BCPOOL_STATE`, `_BCPOOL_NOTE`.

- `_bc_context` (30 buckets, quantized `e[t−1] × e[t−2] × parent-residual sign`,
  scale-free thresholds) and the per-channel leaky integrator are reused
  **verbatim** from the shipped `_bc_forward`; stage-1 order-4 sign-sign LMS and
  the `_bp_select`/`_bp_inverse` front-end are verbatim; header/side-info layout
  is byte-identical to `LMS4bc`'s (only the magic differs).
- The `3×` is a shift+add: **shifts and adds only, no multiply, no divide** in
  the per-sample path.
- **Pooled update is end-of-slice**: per-slice per-bucket integer sums
  (`np.add.at` — deliberately not `bincount`-with-weights, which routes through
  float64) and counts, then `Sbar[q] += tot[q] − cnt[q]·(Sbar[q]>>9)` using the
  **pre-slice** `Sbar` every channel already read. The estimate at time `t`
  therefore depends only on slices `< t`, and the update is
  **channel-order-independent**, so the vectorized host loop and a sequential
  on-node loop reach bit-identical state.
- Matched pair: the decoder forms the same context from data strictly before
  `t`, reads the same two accumulators, recovers `e = d + mu`, and only then runs
  the identical per-channel and pooled updates. **Zero side-info** beyond the
  incumbent's `(parent, beta)`.
- Parameter choices: `BCPOOL_W = 9` (512-hit pooled window) gives ~16× the
  sample support of the per-channel 32-hit window while staying temporally fresh
  (~120 slices at 128 ch), and makes the pooled recursion contract for any
  per-bucket occupancy < 512 (satisfied by construction at `C ≤ 320`).
  `BCPOOL_SHR = 2` keeps the per-channel estimate dominant at 3/4, bounding the
  heterogeneity risk.
- Cost: `enc_ops = 26+22+10+3+8 = 69`, `dec_ops = 61`; state
  `_BC_STATE + _BP_STATE + 3` = 267 B/ch — the added pooled table is
  **array-wide** (30 × (int32 acc + int32 slice sum + uint16 count) = 300 B
  TOTAL, i.e. `ceil(300/128) = 3` B/ch). Cost **0.1282** vs `LMS4bc`'s 0.1202;
  the +10 ops/sample-ch dominate the increase, the memory is negligible by
  design.
- The "pure-pooled corner" (drop the per-channel tables entirely) was
  deliberately **not** implemented — that is a second codec and would be scope
  creep.
- Engagement check (not a null implementation): against `_bc_forward` on
  identical input the corrected residual differs on **39.9%** of samples, mean
  `|diff|` 0.42. Bit-exact round-trips also confirmed on `(C,N,cols)` =
  (64,1200,8), (17,300,4), (128,600,16), (3,50,2) with injected bursts.

```
$ PYTHONPATH=host_tools ./.venv/bin/python research/registry.py --selftest
LMS4bcpool+Rice+xchan_bestpartner  2.72x          OK      OK      OK   0.128
registry self-test: ALL round-trips bit-exact
```

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

All numbers from `results/cycle_bench.csv` (`ok=True`, `embedded=OK`,
`neural=OK`, `cost=0.1282`).

| dataset | C | `bcpool` (0.1282) | best `bc` (0.1202) | vs best | `bcxs` (0.1013) | bias-free `bestpartner` (0.0394) |
|---|---:|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | **1.485974** | 1.485085 | **+0.060%** | 1.484874 | 1.480384 (+0.378%) |
| otb_hdsemg_vl | 64 | **2.194780** | 2.193438 | **+0.061%** | 2.181863 | 2.161938 (+1.519%) |
| capgmyo_dba_s1 | 128 | 1.350623 | **1.353146** | **−0.186%** | 1.353163 | 1.350480 (+0.011%) |
| cemhsey_s1_d1t1 | 320 | **1.955683** | 1.955254 | **+0.022%** | 1.971616 | 1.955547 (+0.007%) |

- **2.194780× on OTB is the highest real ratio of any codec in the run**, and the
  highest OTB ratio recorded in this repository (previous max: `LMS4bc`
  2.193438×).
- **1.485974× on Hyser is the highest of the entire bias-corrector family**
  (`bc` 1.485085, `bcxs` 1.484874, `bc_lite` 1.483533) — though still below the
  non-bias corners `jointbp2` (1.496924) and `bprank` (1.495235).
- 4-set real mean **1.74677×** vs `bc`'s 1.74673× — a **+0.002% dead tie** — and
  below `bcxs`'s 1.74788× at 27% higher cost.
- Synthetic: sc0.6 2.595286×, sc0.9 2.561132× (above `bc`'s 2.593270 /
  2.559087, far below `bcxs`'s 2.623350 / 2.598751).

## Attribution — what moved the ratio and why

Context class, bucket count, update law, predictor, front-end, back-end and
bitstream layout are byte-identical to `LMS4bc`'s. **The entire move is the
shrinkage read.** Isolated effect, expressed as pp added to the bias stage's
contribution over the shared bias-free `LMS4+Rice+xchan_bestpartner` null:

| dataset | C | inter-channel regime | bias stage, `bc` | bias stage, `bcpool` | Δ from pooling |
|---|---:|---|---:|---:|---:|
| otb_hdsemg_vl | 64 | monopolar, tight, high MI | +1.457% | **+1.519%** | **+0.062 pp** |
| hyser_1dof_f1_s1 | 128 | monopolar, high MI | +0.318% | **+0.378%** | **+0.060 pp** |
| cemhsey_s1_d1t1 | 320 | monopolar, high MI | −0.015% | **+0.007%** | **+0.022 pp** |
| capgmyo_dba_s1 | 128 | **differential**, ≈no MI | +0.197% | **+0.011%** | **−0.187 pp** |

**Theory — the estimator-support axis is genuinely live, and its exchange rate
is inter-channel HOMOGENEITY, not neighbour MI.** Each per-channel bucket mean
is estimated from an effective ~32-hit window, so its variance is large relative
to the size of the bias it is estimating (the correction is `|mu| ≈ 0.4` LSB;
see the engagement check). Shrinking toward a pooled mean estimated from ~512
hits reduces that variance by roughly the shrinkage weight squared times the
support ratio; the price is a **shrinkage bias** equal to the shrinkage weight
times the channel's deviation from the array mean. James-Stein's condition is
that the per-channel parameters be exchangeable draws from a common
distribution.

On the three **monopolar** arrays that condition essentially holds: every
channel runs the identical sign-sign LMS on signals from the same volume
conductor, so the offset between the sign-sign fixed point and the Wiener
solution — the quantity P9 says the corrector removes — is a **shared property
of the adaptation law and the signal class**, not of the individual electrode.
The pooled mean is then a near-unbiased, low-variance target, variance reduction
dominates, and the ratio improves by ~+0.06 pp on the two headline sets. Notably
it also **rescues CEMHSEY**: on the 320-ch array `bc`'s bias stage was slightly
*negative* (−0.015%, the per-channel buckets never accumulate enough hits at 320
channels) and pooling turns it positive (+0.007%) — exactly the regime where
sample support is scarcest and pooling should help most.

On **CapgMyo** the condition fails, and it fails structurally rather than by
degree. It is a **differential** array: each channel is already a difference of
two electrodes, so its residual bias carries the sign of that local pair's
geometry, and biases of opposite sign coexist across the array. Pooling averages
them toward ≈0, so `mu_bar` carries almost no signal while still displacing
every channel's own estimate by 1/4 — pure injected bias. The measured effect is
that pooling **destroys essentially the whole bias-corrector gain there**
(+0.197% → +0.011%, i.e. 94% of the stage's value), the largest single-set
isolated loss any of the four correctors has posted on that control.

This is the same shape as P1 and the P9 refinement — a mechanism whose sign is
set by an array property, positive where the property holds and negative where
it does not — but the **property is a different one**. `bcxs`'s context class
was gated by *neighbour mutual information*; `bcpool`'s pooling is gated by
*cross-channel homogeneity of the predictor's bias field*. These are correlated
on this corpus (CapgMyo is the negative control for both) but not the same
quantity, and only pooling is sensitive to the differential montage's sign
cancellation.

**No cross-channel front-end lever to isolate.** `bcpool` carries the incumbent
`+xchan_bestpartner` front-end verbatim; its isolated cross-channel gain is the
incumbent's (+11.31% Hyser / +18.44% OTB / +1.37% CapgMyo / +13.08% CEMHSEY vs
the shared `LMS+Rice` null).

## Pareto check

Cost 0.1282, `embedded_ok` OK, `neural_ok` OK. On the mean-real-vs-cost front:

```
cost=0.0079 mean_real=1.50472  delta+Rice
cost=0.0127 mean_real=1.66622  delta+Rice+xchan
cost=0.0366 mean_real=1.73685  LMS+Rice+xchan_joint2
cost=0.0394 mean_real=1.73709  LMS4+Rice+xchan_bestpartner
cost=0.0430 mean_real=1.74149  LMS4+Rice+acar_sel+bestpartner
cost=0.0983 mean_real=1.74693  LMS4bc_lite+Rice+xchan_bestpartner
cost=0.1013 mean_real=1.74788  LMS4bcxs+Rice+xchan_bestpartner   <-- front tip
```

`bcpool` (0.1282, 1.74677) is **off** the mean-real front — it is the most
expensive codec in the registry and buys a mean-real dead tie with `LMS4bc`.
It is nonetheless **not Pareto-dominated per-dataset**: no cheaper registered
codec matches it on all four real sets, because it holds the outright OTB and
bias-family-Hyser maxima. `LMS4bc` (0.1202) loses to it on Hyser, OTB and
CEMHSEY; `bcxs` (0.1013) loses OTB by −0.588%; `bc_lite` (0.0983) loses OTB and
Hyser. **Kept registered, not retired** — a genuine per-dataset corner
(highest-ratio-on-OTB point on the whole front) at the top of the cost axis.

## Sanity gates

- Max real ratio in the run is `bcpool`'s own 2.194780× ≪ the 6× ceiling —
  honest broadband EMG, consistent with the 1.3–2.2× anchor.
- Zero FAIL bit-exact rows (`ok=True` on all 156 rows; `bench.py` exit 0;
  registry self-test "ALL round-trips bit-exact").
- Zero regressions on previously-registered codecs versus
  `results/consolidated_bench.csv` (nothing >0.05% on any real set).
- One real-set regression by the candidate itself: CapgMyo −0.186% vs the
  leaderboard best. Recorded — and it is precisely this regression that blocks
  promotion.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**KEPT REGISTERED (not retired); NOT promoted.** Promotion condition (b)
(unanimous PROMOTE) is met. Condition (a) — "beats the current best on REAL
data" — is **not** met under the bar this log has applied since cycle 11:

- The scorecard vs `LMS4bc` is **3 wins / 1 loss**, but the wins are +0.060%,
  +0.061% and +0.022% while the loss is **−0.186%**, i.e. the single regression
  is three times larger than the largest win.
- The 4-set real mean moves **+0.002%** (1.74677 vs 1.74673) — a dead tie by the
  repo's own ±0.02% convention — while cost rises **+6.7%** (0.1282 vs 0.1202).
- Contrast with the promotion that *did* clear this bar (cycle 27, `LMS4bc`):
  3 wins of +0.32%/+1.46%/+0.20% against a −0.015% **dead tie**, not a real loss.

So the headline and the "one codec to port next" pick are **unchanged**.

The durable value of this candidate is that it opens a **third, previously
unexplored axis** of the P9 bias stage — estimator sample support — and shows it
is live at ~+0.06 pp on the monopolar headline sets, with a clean,
mechanistically-explained negative on the differential control. The obvious
follow-up, filed as next hypothesis #1 in `SURVEY.md`, is to make the shrinkage
weight **decoder-observable and adaptive** (shrink hard where the pooled and
per-channel estimates agree, not at all where they disagree) so the CapgMyo loss
becomes ~0 while the monopolar gains are kept — which would convert this dead
tie into a genuine 4-set win. See `INSIGHTS.md` P9 (refined, third axis).
