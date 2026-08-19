# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**What's already been tried lives elsewhere** — read those first so you don't
re-propose a spent lever:
- `research/INSIGHTS.md` — the durable principles (P1–P5), the current open
  frontier, and the dead-ends list.
- `research/CYCLE_LOG.md` — the append-only per-cycle ledger (one row per cycle).
- `research/LEADERBOARD.md` — the current best + Pareto front.

**Survey-cycle note — 2026-08-19.** Slate refreshed against `INSIGHTS.md`
(P1–P10 + open frontier), `CYCLE_LOG.md` rows 1–30, and `registry.py`'s 27
codecs / 11 retired. Incumbent best is `LMS4bc+Rice+xchan_bestpartner`
(cost 0.120). Three new candidates proposed at #1–#3 of the table below, chosen
to be distinct in **mechanism**, one per untouched axis:
`xhint` (scan-order / channel-pairing **topology** — sidedness of the spatial
parent set), `bcxs` (the **class of conditioning variables** in the proven P9
bias corrector — spatial instead of temporal), `LMS4vs` (the **adaptation law**
of the sign-sign LMS — step-size rule instead of order/bank-count/polynomial
degree). No retired codec is re-proposed; each new row names its nearest retired
relative (`xchan_multiparent`, `iklt`, `xctx`, `LMS4rs`, `LMS4v2`) and why it is
a different bet. No retired idea is recommended for revival this cycle.

**Cycle-result note — 2026-08-19 (post-measurement, added by the analyst).** All
three candidates above were measured on the four real sets
(`results/cycle_bench.csv`) and double-verified (three unanimous PROMOTEs, **no
splits**). **None was promoted.** `xhint` (#1) and `LMS4vs` (#3) were
**retired** — conclusively Pareto-dominated on real data, see `INSIGHTS.md`
**P11** (fixed unity-gain two-sided spatial prediction: −1.47…−3.92% on real,
yet **top of both synthetic sets** — a basis-match artifact) and **P12**
(step-size annealing: −0.06…−0.29% on 3/4 real, +0.02% on the synthetics — the
sign-sign LMS is *tracking*-limited, not misadjustment-limited, which closes the
last free parameter of the temporal predictor). `bcxs` (#2) is the cycle's
positive: **kept, non-dominated**, holding the best 4-set real mean of any codec
(1.74788× vs the incumbent best's 1.74673×) at **16% lower cost**, plus the
outright CEMHSEY maximum 1.9716×; not promoted only because it loses OTB by
−0.528% against `LMS4bc` while dead-tying Hyser and CapgMyo. Its isolated
cross-channel-context effect (+0.090/+0.067/+0.082 pp on hyser/otb/cemhsey,
**−0.045 pp on the CapgMyo low-MI negative control**) shows the value of a
spatial context is bounded by the same neighbour MI that bounds P1.

**→ Next hypotheses, ranked by expected payoff** (consistent with the refreshed
`INSIGHTS.md` frontier; proposals only, no codec edits here):

1. **`bcxs_sel` — MI-gate the bias corrector's context class** (P9 refined + P1 +
   P4). Select `bcxs`'s cross-channel-gradient context where neighbour
   correlation is high and fall back to `bc_lite`'s own-channel temporal context
   where it is not. Both branches are already measured, so the expected payoff is
   readable off the table: `bcxs`'s Hyser/OTB/CEMHSEY *and* `bc_lite`'s CapgMyo
   ⇒ **beats `LMS4bc` on all four real sets at ~16% lower cost** and takes the
   headline. The gate must be **decoder-observable, zero-side-info and a fixed
   threshold** — channel count / array geometry as `acar_sel` already proves, or
   a backward neighbour-correlation statistic from the previous reconstructed
   block — **never a learned per-block argmin** (P7's winner's curse). Highest
   payoff, lowest mechanism risk: only the switch is new.
2. **`bcxm` — mix a quantized-magnitude slot into the spatial-sign context**
   (P9 + P1b). `bcxs`'s only genuine loss is OTB −0.528% against `LMS4bc`'s 30
   **quantized-magnitude** buckets, while all of its wins come from **sign**-class
   slots. Sign and magnitude index different moments of the same residual, and
   OTB is the tight 64-ch array where P1b says spatial MI is essentially rank-1 —
   so a 27–30-bucket context combining one spatial-sign slot with one
   quantized-magnitude slot is a cheap single-variable test of whether the two
   correctors' wins are **additive or substitutes**. Medium payoff, low risk, no
   new state, no new side-info.
3. **`mst_sel` — channel-count-gate the spatial front-end** (P1b/P8, carried
   over). Gate `LMS4+Rice+xchan_mst` (P8's tight-array winner, cost 0.046)
   against plain best-partner on decoder-observable channel count, matching the
   `acar_sel` discipline. **Budget for a null or small result:** P7 shows
   backward-selected gates (three attempts, three granularities) land at or below
   the max of their own branches. Lowest of the three, but it is the only
   remaining *spatial* lever now that sidedness (P11) is spent.

Explicitly **not** proposed: any further temporal-predictor internals (order,
coefficient-set count, functional form, step-size rule — all spent, P2/P12), any
entropy back-end change (P5), any bias-corrector **bucket-count** sweep (P9
refined: count is not the productive variable), and any fixed-weight two-sided
spatial predictor (P11).

## Verdict key
- **embeddable** — integer, causal, bounded state/look-ahead, fits the sEMG budget
  (≤1831 cyc/sample-ch) and plausibly the 30 kHz neural budget (125 cyc).
- **borderline** — embeddable only after a specific simplification (noted).
- **watch-list** — expected to fail the cost gate today; track, never auto-promote.

## Live embeddable candidates (not yet spent)

These are the forward proposals still open. The full mechanism rationale is in
`INSIGHTS.md`'s "Open frontier"; this table is the survey-side pointer with the
literature grounding.

**Update 2026-08-17:** old candidates #4 and #5 below were tried (five parallel
cycles, 2026-08-05→2026-08-16, consolidated into one PR — see `CYCLE_LOG.md`
rows 16–30). The temporal functional-form change **succeeded** — a JPEG-LS/CALIC
per-context bias corrector is now the leaderboard best (INSIGHTS P9) — so #7
below is **partially spent**: the bias-correction half of the JPEG-LS mechanism
is done, the full MED/LOCO 2D-predictor replacement remains open. The
scale-selected spatial front-end (#4) was attempted 3 independent ways and found
ratio-neutral-at-best every time (INSIGHTS P7) — kept on the list but re-ranked
down; do not attempt a 4th *learned/estimated* gate criterion without reading P7
first, a *decoder-observable* gate (channel count, à la `acar_sel`) remains the
one form proven to work.

**Update 2026-08-19 (survey cycle, this refresh):** three **new, mechanistically
distinct** proposals added at #1–#3 and ranked above the carry-overs. Each was
checked against `registry.py`'s 11 retired codecs and INSIGHTS' dead-end list;
the nearest retired relative is named per row with the reason this version is
not the same bet. Chosen axes: **(1) scan-order / channel-pairing topology**
(untouched — every prior spatial attempt varied *which* parent or *how many*,
never *how many already-coded sides* a channel has), **(2) the class of
conditioning variables in the proven bias corrector** (frontier #1, but at the
variable level, not the bucket-count level), **(3) the adaptation law of the
sign-sign LMS** (untouched — prior temporal attempts varied order, coefficient-set
count, and polynomial degree, never the step-size rule).

| # | method | why it may beat the current best | verdict | key caveat |
|---|---|---|---|---|
| 1 | **`xhint` — encoding-interleaved two-sided spatial prediction** (quincunx / HINT topology). Split the grid into a geometry-fixed checkerboard; code the "black" half with the incumbent best-partner rank-1 subtract, then predict each "white" channel from a **convex** (sum-to-one, shift-only) average of its already-reconstructed orthogonal black neighbours; unchanged LMS4 + Rice downstream | **Spatial lever (P1, the dominant one), new mechanism: sidedness, not parent count.** For a smooth spatial field, two-sided *interpolation* has strictly lower error variance than one-sided *extrapolation* — for an AR-like array covariance, σ²(1−2ρ₁²/(1+ρ₂)) < σ²(1−ρ₁²) whenever ρ₁>0, so the saved rate is ½log₂ of that variance ratio on half the channels. Second, averaging K **in-phase** neighbours (P6 settled that neighbour MI is zero-lag volume conduction, so they *are* in phase) attenuates each neighbour's independent noise ~1/K while preserving the shared mode — it raises the SNR of the common-mode estimate, i.e. it attacks P7's binding estimation-variance constraint instead of fighting it. No per-block search is added at all (topology is fixed by geometry), so the winner's curse cannot apply. Literature: HINT / interleaved-HINT and quincunx-lifting optimal predictors (Roos & Viergever; Aiazzi–Alparone–Baronti, IEEE TIP 10(1) 2001) report real gains over raster-causal predictors *(paper-reported, unverified here)* | **embeddable** — masks fixed by geometry (zero side-info), one add + one shift per white channel, +1 slice of reconstructed-neighbour buffer (~256 B at 128 ch), no multiply/divide, two ordered sub-passes **inside one time slice** so look-ahead stays 0. Est. cost ≈ 0.045–0.055 (near `mst`); fits both the 2 kS/s and the 125-cyc neural budget | **Not retired `xchan_multiparent`** (cycle 8, retired): that summed two *independently fitted marginal* rank-1 subtracts (β₁+β₂ ≈ 2β ⇒ over-subtracts the shared mode). Convex sum-to-one weights **structurally cannot** over-subtract. **Not retired `iklt`/`iklt_adaptive`** (P3): predict-only lifting, **no update step** — the black channels stay bit-clean, so noise is injected only into the residual, which is exactly P3's stated robustness condition for the rank-1 subtract. **Honest risk:** the black half loses its distance-1 orthogonal parent and falls back to the diagonal (√2) — net gain = white-set improvement − black-set degradation. P1b's note that the dominant partner on tight arrays is *already* a diagonal neighbour is the reason to expect the degradation to be small, but it is a real cost. Expect ~zero on CapgMyo (ρ≈0.29), per P1 |
| 2 | **`bcxs` — cross-channel-gradient context for the bias corrector.** Keep `LMS4bc`'s divisionless (B,N,C) machinery verbatim; **change the conditioning variable class** from own-channel temporal residual history to co-located *spatial* residual gradients: q3(e[left,t]−e[up,t]) × q3(e[parent,t]) × q3(e[t−1]), ~27 buckets | **Combines the two most recently proven facts.** Wu & Memon (*Context-based lossless interband compression — extending CALIC*) show that context modeling of the **prediction-error field** captures higher-order interband correlation that a *simple linear interband predictor* cannot. Our best-partner subtract **is** exactly such a predictor: it removes only the rank-1, scalar-gain, linear projection onto one neighbour. What survives is (a) dependence on neighbours the projection never used — and P1b proved a second parent carries real MI on large arrays — and (b) the amplitude-dependent/nonlinear part. P9 proved the *conditional-mean* correction is a live, non-P5 lever. So: harvest the second parent's MI as a **model-free conditional mean in a table**, not as a second linear subtract (retired) nor a joint 2×2 solve (P1b: pays only on large arrays). A table-based mean cannot over-subtract and degrades gracefully to 0 where the MI is absent | **embeddable** — state identical to `LMS4bc_lite` (27 buckets × (int32,int16,int8)/ch ≈ 190 B/ch, ~24 KB at 128 ch), 3 compares + 2 subtracts to form the context, no multiply/divide. `_bias_forward` already walks channels in index order with a same-slice parent (< g), so the extra neighbour needs no new ordering machinery. Est. cost ≈ 0.10–0.12 | **Not retired `xctx`** (cycle 9, P5): xctx conditioned the **Rice parameter k** — a second-moment/back-end lever. This conditions a **first moment of the residual stream, upstream of an untouched coder** (the same disclosure both shipped `bc` codecs make). **Not a parameter variant of the shipped `bc`s**: those index own-channel *temporal* history (27-ctx signs, 30-ctx quantized magnitudes) plus one parent bit; this changes the *variables*, not the bucket count. **Closest negative evidence:** P5 measured H(e_c \| cross-channel ctx) ≈ H(e_c). A clean null here would sharpen P5 into "the cross-channel conditional law is exhausted in **both** moments after the rank-1 subtract" — a real result either way |
| 3 | **`LMS4vs` — per-tap sign-agreement variable-step sign-sign LMS.** Order stays 4, one coefficient set, ±1 update *direction* unchanged; the step becomes a per-tap power of two adjusted by a saturating counter on agreement of consecutive gradient signs (agree ⇒ larger step, alternate ⇒ smaller). Update = `w_i += sign(e)·sign(h_i) << (SMAX − s_i)` — shifts only | **Attacks the second moment of the defect P9 proved exists.** Sign-sign LMS's steady-state excess MSE (misadjustment) scales with the *fixed* step: with a constant ±1 increment the filter permanently dithers about its fixed point, and that dither is an additive predictor-independent noise floor on **every** residual, inflating the Rice length by ≈½log₂(1+μ_excess/σ²_min) bits/sample. P9 harvested this defect's *first moment* (the context-conditional DC) and it became the leaderboard best — its *variance* term is untouched and the bias corrector structurally cannot reach it. Alternating gradient signs are a directly backward-observable "at the fixed point, dithering" indicator; agreement signals a burst onset needing tracking. Classical variable-step sign algorithm (Harris–Chabries–Bishop VS-LMS, IEEE TASSP 1986; VSS-LMS review literature) *(paper-reported, unverified here)* | **embeddable — cheapest of the three.** 4 counters + 4 shift amounts per channel (~12 B/ch, ~1.5 KB at 128 ch), one compare + one saturating add per tap per sample, multiply-free shift update. Est. cost ≈ 0.045; comfortably inside the 125-cyc neural budget | **Not retired `LMS4rs`** (cycle 14, P2): that forked whole coefficient **banks** by activity regime, splitting the adaptation data. Here there is exactly **one** coefficient set seeing **every** sample; only the learning rate is modulated. **Not retired `LMS4v2`** (cycle 21, P2 extension): that added a quadratic Volterra term and found no exploitable nonlinearity — this changes the *adaptation law*, not the predictor's polynomial form. **Not a P7 widening**: the counter is continuous scalar state, not an argmin over K hypotheses. **Risk:** over-annealing lags burst onsets, raising residual energy exactly where samples are expensive — clamp s_i to a narrow range (e.g. 0..3) so the worst case is within 8× of the incumbent step |
| 4 | **Scale-selected spatial front-end** — gate `LMS4+Rice+xchan_mst`'s Chow-Liu tree (tight arrays) vs plain best-partner (large arrays) on the decoder-observable channel count | Tried 3 ways (MDL in-sample selection, backward rank-statistic, per-channel MDL+hysteresis) — all landed at or below the best of their own branches (P7); a *decoder-observable* channel-count gate (the only form proven to work, via `acar_sel`) is untried for this specific pairing | **embeddable** (both branches already verified; gate mechanism proven elsewhere) | P7's winner's-curse finding predicts a small or null result — budget accordingly, don't assume the branches' peak. Carried over, re-ranked below the three new mechanisms |
| 5 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 6 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2). Note #3 above is the *narrow, divisionless* realization of this row's idea — prefer it over a full NLMS (which needs a divide/reciprocal) |
| 7 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **partially spent — borderline** | the *bias-cancellation* half of JPEG-LS is now proven positive and shipped (P9, `LMS4bc+Rice+xchan_bestpartner`); the *MED/LOCO predictor itself* (replacing the linear LMS, not just correcting its residual mean) remains untried. Entropy-context on the Rice parameter is still spent (P5) |

## Watch-list — DO NOT promote without human approval

Methods that fail the integer / causal / streaming gates today; tracked for
offline baselines and future reference only.

| method | note |
|---|---|
| Integer discrete flows (IDF), L3C, learned entropy models | learned lossless; float/GPU, no streaming budget — offline baselines only |
| Convolutional autoencoder + lossless residual | float core; disqualified on the FPGA target |
| VAE-DCT / neural context models | fail integer + latency gates today |
| TSCom-Bench / chained lightweight neural predictors (arXiv 2509.21002) | learned-lossless time-series; float/GPU, no streaming budget |
| GPU adaptive lossless FP framework (arXiv 2511.04140) | offline/GPU float pipeline; no integer streaming budget |
| Predictability-aware multichannel TS (arXiv 2506.00614) | lossy + neural + non-causal; disqualified, tracked for record |
| Compressive on-chip AP recording (IEEE TBME 11183845) | **LOSSY** (requantise + MI selective sampling); disqualified by lossless-only, listed for record |

**Reference-only (not a contender):** streaming floating-point time-series
compressors (Elf / Chimp / Gorilla, arXiv 2510.07015) are XOR-of-float oriented —
a poor fit for int16 biosignals where Rice/Golomb already dominates. A baseline
bar, not a candidate.

## The two settled spatial facts (from INSIGHTS, so the survey doesn't re-propose them)
- Cross-channel decorrelation is the dominant lever, but it's a **single rank-1
  adaptive subtract** — multi-tap transforms (fixed or adaptive) and summed
  multi-parent subtracts are dead ends (P3, P1b).
- The entropy back-end is at the floor — Rice is optimal for the near-geometric
  residual; neither an ANS swap nor any context-model of the Rice parameter helps (P5).

**Boundary clarification for candidate #1 (added 2026-08-19).** "Single rank-1
adaptive subtract" was established against (a) *energy-preserving multi-tap
rotations* that corrupt both channels (`iklt`, P3) and (b) *summed
independently-fitted marginal* subtracts that double-count the shared mode
(`xchan_multiparent`, P1b). A **predict-only lifting step with convex
(sum-to-one) weights** is neither: it is still a rank-1 removal of one shared
mode — it only estimates that mode from **both sides** instead of one, and it
leaves the parents bit-clean. The proposal is about the *sidedness and variance
of the estimator*, not about adding spatial degrees of freedom. If it loses, the
settled fact strengthens to "one-sided rank-1 is not merely sufficient, the
interleaving cost on the coarse half exceeds the interpolation gain on the fine
half" — which would close the scan-order axis too.

### Literature added this cycle
- Roos & Viergever, *hierarchical interpolation (HINT)*; Aiazzi, Alparone &
  Baronti, "Lossless image compression based on optimal prediction, adaptive
  lifting, and conditional arithmetic coding", IEEE TIP 10(1):1–14, 2001
  (quincunx lifting + optimal interpolating predictors) — grounding for #1
  *(paper-reported, unverified here)*.
- Wu & Memon, "Context-based lossless interband compression — extending CALIC",
  IEEE TIP 9(6), 2000 — context modeling of the *prediction-error field*
  captures interband correlation a simple linear interband predictor cannot;
  grounding for #2 *(paper-reported, unverified here)*.
- Harris, Chabries & Bishop, "A variable step (VS) adaptive filter algorithm",
  IEEE TASSP 34(2), 1986, plus the VSS-LMS review literature — grounding for #3
  *(paper-reported, unverified here)*.
