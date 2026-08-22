# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**What's already been tried lives elsewhere** — read those first so you don't
re-propose a spent lever:
- `research/INSIGHTS.md` — the durable principles (P1–P12), the current open
  frontier, and the dead-ends list.
- `research/CYCLE_LOG.md` — the append-only per-cycle ledger (one row per cycle).
- `research/LEADERBOARD.md` — the current best + Pareto front.

**MEASUREMENT OUTCOME + NEXT HYPOTHESES — 2026-08-22 (appended by the analyst
after the cycle measured; the proposal note for this cycle follows below).**
All three proposed candidates were implemented, benched on all four real sets
(`results/cycle_bench.csv`), and returned **unanimous PROMOTE / PROMOTE** with
**no verifier splits**. **None was promoted** — the headline stays
`LMS4bc+Rice+xchan_bestpartner`. Scorecard: **#3 `bcpool` is the cycle's win**
(hyser 1.485974×, otb **2.194780× — the highest real ratio ever recorded in this
repo**, capgmyo 1.350623×, cemhsey 1.955683×; beats the headline on 3/4 but
loses CapgMyo −0.186% against wins of only +0.060/+0.061/+0.022%, 4-set mean a
dead tie at +6.7% cost) — **kept, non-dominated**. **#1 `bcxm` answered its
question NEGATIVE** (loses all 4 real sets; the magnitude and spatial-sign
context classes are substitutes, not additive) — kept only because `LMS4bc` is
dearer than it, and **flagged for retirement review**. **#2 `xchan_cmean` was
RETIRED** (loses all 4 real sets by −0.95…−7.71%, dominated by five cheaper
codecs) while topping **both** synthetics — the second confirmed instance of
P11's basis-mismatch warning sign. Durable learnings: `INSIGHTS.md` **P9
refinement (a)** (context-class composition is a dead end; a spatial slot only
carries MI in the *same-slice residual* domain), **P9 refinement (b)** (a new
live third axis: the bias corrector's *estimator sample support*), and the new
**P13** (fixed-weight composite spatial parent). Records:
`experiments/033`–`035`; ledger rows `CYCLE_LOG.md` 34–36.

**Next hypotheses, ranked by expected payoff (consistent with the refreshed
`INSIGHTS.md` frontier):**

1. **`bcpool_gate` — decoder-observable adaptive shrinkage weight** (INSIGHTS
   frontier #1; P9 refinement (b) + P4 + P7). Keep `bcpool` byte-identical and
   replace its *fixed* 1/4 shrinkage with a two-level power-of-two weight chosen
   by a fixed rule on state both sides already hold — e.g. shrink by 1/4 when
   `sgn(mu_bar[q]) == sgn(mu_c[c,q])` and by 0 otherwise, or key it on
   `|Sbar[q]|` against a fixed threshold. Costs one compare and one shift, zero
   side-info, look-ahead 0, no new state class, and it is a **fixed rule, not a
   per-block argmin** (P7). *Expected payoff: highest of the three.* Both
   branches are already measured on all four real sets, so the target is
   concrete — keep `bcpool`'s +0.060/+0.062/+0.022 pp on the monopolar arrays
   while zeroing its −0.187 pp on CapgMyo, which would be **the first codec to
   beat `LMS4bc` on all four real sets** and take the headline. *Risk:* the
   agreement statistic may be too noisy per bucket at 30 buckets × ~32-hit
   windows; mitigate by keying the gate on the *array-wide* accumulator only
   (one decision per bucket per slice, not per channel).
2. **`bcxs_sel` — MI-gated bias-context class** (INSIGHTS frontier #2, carried
   over from this cycle's row #4, now with a domain constraint). Select `bcxs`'s
   **same-slice residual** spatial-gradient context where a backward
   neighbour-correlation statistic (or the `acar_sel` channel-count/geometry
   proxy) says neighbour MI exists, and `bc_lite`'s temporal context where it
   does not. *Expected payoff: medium.* Ceiling stated honestly: a two-way gate
   reaches at most the max of its own two branches per set (P7), and neither
   branch holds the OTB corner — so expect a strong **mean-real/cost** Pareto
   point (`bcxs`'s 1.74788 at 0.1013 with CapgMyo repaired), not the headline.
   **`bcxm` closed the alternative route to the same goal** (composing the two
   context classes in one word), so the gate is now the only live form.
3. **`jointbp2_sel` — scale-gate the JOINT 2-parent front-end** (P1b + P1 + P8,
   re-pointed). P1b says a jointly-solved best-*pair* wins on large diffuse
   arrays (`jointbp2` holds the outright embeddable Hyser max 1.496924×) while a
   single selected parent wins tight ones (OTB 2.161938× vs `jointbp2`'s
   2.152244×). Gate the two on **decoder-observable channel count / grid
   geometry**, exactly as `acar_sel` already does. *Expected payoff: medium-low
   but on the dominant lever* (P1: the spatial front-end is worth ~19× every
   temporal knob), and it is the only frontier item that touches it. *Risk:* P7
   — three prior gating attempts landed at or below the max of their own
   branches; this one is cheap because both branches are already registered and
   the gate variable is a header field, not an estimate. **Do not** re-attempt
   any fixed-weight or averaged multi-parent form (P13, retired this cycle).

**Survey-cycle note — 2026-08-22 (current).** Slate refreshed against
`INSIGHTS.md` (P1–P12 + the re-ranked open frontier), `CYCLE_LOG.md` rows 1–33,
`LEADERBOARD.md` (2026-08-19 snapshot) and `registry.py`'s **30 codecs, 13
retired** (verified by running `registry.py --selftest`, which tags each retired
entry). Incumbent headline is `LMS4bc+Rice+xchan_bestpartner` (cost 0.120,
30 scale-free quantized-**magnitude** buckets); its challenger is
`LMS4bcxs+Rice+xchan_bestpartner` (cost 0.101, 27 spatial-**sign** buckets, best
4-set real mean, CEMHSEY max), which fails to take the headline only on OTB.
Three new candidates are proposed at **#1–#3** below, each on a **different
stage of the pipeline and a different information lever**:

- **#1 `bcxm`** — *bias stage, context **composition***: swap one own-channel
  slot of the headline's 30-bucket context word for the spatial-gradient slot
  that `bcxs` proved carries cross-channel MI. Same bucket budget, same
  machinery, one variable changed.
- **#2 `xchan_cmean`** — *spatial front-end, **estimator SNR***: replace the
  single **selected** parent with a **composite (averaged) causal-neighbour
  parent** carrying one **fitted** integer gain. Attacks regressor measurement
  noise (errors-in-variables attenuation) instead of widening a hypothesis
  class — it *removes* the per-block parent search rather than enlarging it.
- **#3 `bcpool`** — *bias stage, **estimator sample support***: leave the
  context class and bucket count alone and shrink each per-channel bucket mean
  toward an **array-pooled** bucket mean with a fixed power-of-two weight
  (James–Stein / empirical-Bayes). The first mechanism here that attacks P9's
  *dilution* constraint rather than trading against it; its pure-pooled corner
  also collapses the bias family's dominant state cost (per-channel tables →
  one array-wide table).

**Retired-ledger check.** All 13 retired codecs were enumerated and none is
re-proposed: `LMS+Rice+xchan_adaptive`, `LMS+Rice+xchan_bestpartner` (order-8),
`iklt`, `iklt_adaptive`, `xchan_tans`, `LMS4rs`, `acar+bestpartner`,
`xchan_multiparent`, `xctx`, `LMS4v2`, `xchan_xres`, `xchan_hint`, `LMS4vs`.
Each new row names its nearest retired relative and the axis on which it is a
different bet. **One partial revival is flagged explicitly:** #2 revives the
*mean-of-many-channels-as-parent* idea from the retired always-on
`LMS4+Rice+acar+bestpartner` — but at **local** scale instead of global and with
a **fitted** integer gain instead of `acar`'s unity-gain subtraction, which is
precisely the mis-specified-gain failure P11 diagnosed in `xchan_hint`. See the
boundary clarification below the table.

**Correction to the frontier's expected payoff (`bcxs_sel`, INSIGHTS frontier
#1).** The frontier states that gating `bcxs`'s spatial context against
`bc_lite`'s temporal context on a neighbour-MI proxy "would beat `LMS4bc` on all
four real sets". That ceiling does not follow from the recorded per-dataset
table: a two-way gate can at best reach the **max of its own two branches** on
each set (P7), and **neither** branch holds the OTB corner — that belongs to the
headline's 30-bucket quantized-**magnitude** context, a third context class the
gate never selects. So the gate is expected to yield a strong Pareto point
(mean-real and cost) but **not** the headline. The productive move is therefore
to first *compose* the two winning slots into one context word at the same
budget (#1) and only then gate — which is why #1 outranks the gate this cycle.
`bcxs_sel` stays on the table as carry-over row **#4**, unchanged in mechanism,
re-ranked with this ceiling stated.

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

**→ Next hypotheses, ranked by expected payoff** (written 2026-08-19;
**superseded by the 2026-08-22 slate above** — item 1 is re-ranked to table row
#4 with a corrected ceiling, item 2 is promoted and made concrete as table row
#1 `bcxm`, item 3 is unchanged as table row #5. Kept for the record):

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
per-context bias corrector is now the leaderboard best (INSIGHTS P9) — so the JPEG-LS/LOCO row (that cycle's #7, now row **#8**)
below is **partially spent**: the bias-correction half of the JPEG-LS mechanism
is done, the full MED/LOCO 2D-predictor replacement remains open. The
scale-selected spatial front-end (that cycle's #4, now row **#5**) was attempted 3 independent ways and found
ratio-neutral-at-best every time (INSIGHTS P7) — kept on the list but re-ranked
down; do not attempt a 4th *learned/estimated* gate criterion without reading P7
first, a *decoder-observable* gate (channel count, à la `acar_sel`) remains the
one form proven to work.

**Update 2026-08-19 (survey cycle):** three new proposals were added at #1–#3 —
`xhint` (sidedness of the spatial parent set), `bcxs` (class of the bias
corrector's conditioning variables), `LMS4vs` (adaptation law of the sign-sign
LMS). **All three are now spent and their rows have been retired from this
table:** `xhint` and `LMS4vs` are Pareto-dominated and retired in the registry
(INSIGHTS **P11**, **P12**); `bcxs` measured positive, is registered and
non-dominated, and is now an *incumbent* the new slate builds on rather than a
proposal. The durable learnings live in `INSIGHTS.md`; the outcome summary is in
the cycle-result note above.

**Update 2026-08-22 (survey cycle, this refresh):** three **new, mechanistically
distinct** proposals added at #1–#3 and ranked above the carry-overs, one per
stage/lever: **(1) context *composition* inside the proven bias corrector**
(mix the two winning slot classes at a fixed bucket budget — the axis INSIGHTS
P9's refinement names productive, applied to the *headline's* machinery rather
than `bc_lite`'s), **(2) the *estimator* of the rank-1 spatial projection**
(a composite, noise-averaged parent with one fitted gain — attacks
errors-in-variables attenuation of β, and *removes* a per-block search instead
of widening one, per P7), **(3) the *sample support* of the bias corrector's
per-context statistics** (cross-channel pooling / shrinkage — attacks the
context-dilution constraint itself, and collapses the bias family's state).
Each was checked against `registry.py`'s **13** retired codecs and INSIGHTS'
dead-end list; the nearest retired relative is named per row with the reason
this version is not the same bet. **Row numbering shifted this refresh:** the
2026-08-19 rows #1–#3 are spent and removed, the frontier gate enters at #4, and
every earlier carry-over moved down one (old #4→#5, #5→#6, #6→#7, #7→#8).

| # | method | why it may beat the current best | verdict | key caveat |
|---|---|---|---|---|
| 1 | **`bcxm` — mixed-moment context word for the headline bias corrector.** Keep `LMS4bc`'s 30-bucket, scale-free, divisionless machinery verbatim (leaky per-context mean, thresholds at 0.5x/1.5x the channel's backward leaky mean abs(e), shift-only) and swap **exactly one slot**: the weakest own-channel slot `q2(e[g,t-2])` (3 levels) is replaced by the 3-level **spatial residual-gradient sign** `sgn(d[g-1,t-1] - d[g-cols,t-1])` that `bcxs` proved carries cross-channel MI. Word stays `q1(e[t-1]) x q_spatial x sgn(parent)` = 5x3x2 = **30 buckets, unchanged budget** | **Bias-stage lever (P9), new axis: context COMPOSITION at fixed budget.** The two shipped correctors win on disjoint dataset pairs and index **different moments** of the same residual: the headline's quantized-magnitude slots index the residual's *scale* (which multiplies the sign-sign LMS's misadjustment offset, so E[e ; ctx] grows with local activity), while `bcxs`'s spatial-gradient sign indexes the *direction of local activity* on the one axis that still carries MI after LMS whitening (P1/P9-refined). Information-theoretically the two slots are near-orthogonal indices of E[e ; ctx]: `I(e; q_mag, q_spatial) ~ I(e; q_mag) + I(e; q_spatial)` to the extent the two statistics are conditionally independent, so at **fixed** bucket count the composed word should lower `H(e - E[e ; ctx])` further than either alone, with **no** extra dilution (P9's refined exchange rate is paid only when the bucket count grows or a slot is uninformative). The slot deleted is the one P9's theory calls weakest — a second own-channel *temporal* lag, on the axis the order-4 predictor has already whitened (P5's mechanism). This is the single-variable test of whether the two correctors' wins are **additive or substitutes** | **embeddable** — state and ops are `LMS4bc`'s (30 x int32 leaky accumulators + one leaky abs(e) scale per channel, ~130 B/ch, ~17 KB at 128 ch) plus **one subtract and one sign test** to form the gradient, minus the compares freed by dropping `q2`. No multiply, no divide, no new side-info, no new state class. Est. cost ~= `LMS4bc`'s 0.12 (within +/-5%); `LMS4bc` already passes both the sEMG and the 125-cyc neural budget. Prefer the **previous-slice** gradient `d[.,t-1]` (as `bc` already does for the parent term) so the time-major, channel-vectorized loop and its decoder are kept verbatim; a same-slice gradient is also legal but forces `bcxs`'s sequential per-channel inner pass | **Not a bucket-count sweep** (P9-refined dead end): the count is pinned at 30 and the 5x3x2 factorization is unchanged — only *which variable* fills one slot moves. **Not retired `xctx`** (P5): that conditioned the Rice parameter k, a back-end lever; this corrects the residual stream upstream of an untouched coder. **Not a re-proposal of `bcxs`** (registered, kept): `bcxs` replaced the whole 27-bucket sign word of `bc_lite`; this changes one slot of the *30-bucket magnitude* word of the headline, i.e. it is the first codec to hold **both** winning slot classes at once. **Honest risk:** if the two wins are substitutes (the same MI reached two ways), the result is a tie with the better parent on each set — still a real, P9-sharpening result. On the CapgMyo negative control expect the spatial slot to cost ~the same -0.045 pp `bcxs` paid (P1: no neighbour MI to index), which row #4's gate exists to recover |
| 2 | **`xchan_cmean` — composite (noise-averaged) parent with ONE fitted gain.** For each channel form a single virtual parent `m[g,t] = (sum_i s_i * x[i,t]) >> log2(K)` over its **causal** grid neighbours (left, up, up-left, up-right; off-grid contribute 0), where `s_i` in {+1,-1} is a backward alignment sign from the previous reconstructed block's inner product (differential arrays can have anti-correlated neighbours). Then apply the family's existing rank-1 subtract with **one** integer-LS gain fitted against `m`: `y[g] = x[g] - ((beta_g * m[g]) >> s)`; LMS4 + Rice downstream unchanged, parents left bit-clean | **Spatial lever (P1, the dominant one), new axis: the QUALITY OF THE REGRESSOR, not the size of the hypothesis class.** Write each neighbour as `x_i = s + n_i`: a shared volume-conducted mode `s` (P6 settled it is **instantaneous**, so the neighbours are in phase and may be summed without any lag search) plus a locally-generated part `n_i` that is approximately independent across electrodes. Regressing on ONE neighbour is a textbook errors-in-variables problem: the LS gain is attenuated by `SNR/(1+SNR)` and the achievable residual variance is `sigma^2 (1 - rho^2 * SNR/(1+SNR))`, so regressor noise directly caps how much of the shared mode a rank-1 subtract can remove. Averaging K in-phase neighbours multiplies the regressor SNR by ~K (shared mode adds coherently, independent parts add in power), which raises `rho_eff^2` and lowers the residual variance — the coded rate falls by 1/2 log2 of that variance ratio. Crucially this **shrinks** the free-parameter count instead of growing it: one gain and **zero** selection, versus best-partner's (parent index + gain). P7 says every widened backward search here has paid selection variance for MI that was not there; this is the same constraint attacked from the other side — reduce the estimator's variance at fixed model order. Basis: classical attenuation/regression-dilution theory (Fuller, *Measurement Error Models*); composite/matrixed reference channels are standard in lossless multichannel audio (Dolby TrueHD/MLP integer matrixing, US 7,392,195) and in multichannel biosignal coders that pair channels by cross-correlation (Rzepka, *Biomed. Signal Process. Control* 57:101705, 2020) *(paper-reported, unverified here)* | **embeddable — cheaper than the incumbent front-end.** Per sample-channel: 3 adds + 1 shift to form `m`, then the family's 1 multiply + 1 shift + 1 subtract; the per-block backward beta fit is **one** integer-LS solve instead of `bestpartner_adaptive`'s 4-candidate scored scan, so the honest op count should come in **below** it (count it explicitly — cycle 28's `xlag_v5` failed verification precisely by under-counting selection scoring). State: K alignment sign bits + one beta per channel (~4 B/ch) + the current reconstructed time slice (~256 B at 128 ch). Est. cost 0.040–0.050, i.e. the `bestpartner`/`mst` corner; fits the 2 kS/s budget with room and plausibly the 125-cyc neural budget | **Not retired `xchan_multiparent`** (cycle 8): that summed **two independently fitted marginal** subtracts (`beta_1 + beta_2 ~ 2 beta`), which double-counts the shared mode. Here there is **one** regressor and **one** gain fitted against it — the exact LS solution restricted to the equal-weight direction, which structurally cannot over-subtract. **Not retired `xchan_hint`** (P11): no parity split (all causal neighbours stay available to every channel) and the gain is **fitted**, not unity/convex — P11's stated failure was mis-specifying the neighbour amplitude ratio, and its stated escape hatch is exactly a fitted-gain multi-neighbour form. **Partial revival, declared:** the retired always-on `LMS4+Rice+acar+bestpartner` also subtracts a mean of many channels — but **globally** and at **unity gain**; this is **local** (matching P1's finding that shared content on large arrays is spatially local) and **fitted** (so it degrades gracefully to identity where no shared mode exists, instead of injecting the array mean's noise). **Not `jointbp2`** (P1b): that spends 2 free taps plus a pair search; this spends 1 tap and no search — the opposite corner of the bias/variance trade. **Not multi-tap (P3)**: predict-only, parents untouched, one rank-1 removal. **Honest risks:** (i) where one dominant neighbour carries nearly all the MI (P1b says tight arrays are essentially rank-1) the average dilutes the good parent with weaker ones — expect neutral, not negative, since beta re-fits; (ii) on the differential CapgMyo control the alignment signs are load-bearing — if they mis-estimate, the composite can cancel and the codec degrades toward *no* spatial stage, which is worse than best-partner. Report the isolated cross-channel gain against the shared `LMS+Rice` null, as P11 did |
| 3 | **`bcpool` — cross-channel pooled (shrunk) bias statistics.** Keep the context class, the bucket count, the update law and the bitstream of the chosen bias corrector **byte-identical**; change only *how each bucket's mean is estimated*. Alongside the per-channel accumulator `S_c[q]`, maintain **one array-wide** accumulator `S_bar[q]` fed by every channel's sample in bucket `q`, and apply the shrunk correction `mu = ((2^w - 1) * mu_c[q] + mu_bar[q]) >> w` with a **fixed** power-of-two weight (e.g. w = 2). Pooled accumulators are updated at the **end** of each time slice, so the estimate used at time t depends only on slices < t — decoder-reproducible, zero side-info | **Bias-stage lever (P9), new axis: the ESTIMATOR's sample support, not the context's definition.** P9's refinement identifies the binding constraint exactly: *context relevance is bought with context dilution* — each bucket's leaky mean is estimated from ~1/NCTX of a channel's samples, so estimation variance, not available MI, is what caps context richness. Pooling multiplies a bucket's sample support by the channel count (128–320 here), cutting estimator variance by the same factor, at the cost of a bias equal to the channel's deviation from the array-mean bias. Stein's phenomenon / empirical Bayes gives the condition precisely: a convex combination of the per-channel and pooled estimates has **strictly lower MSE** than the per-channel estimate whenever the between-channel spread of the true `E[e ; ctx]` is small relative to the per-channel estimation variance — the small-correction, few-samples-per-bucket regime this stage demonstrably lives in (the shipped corrections are int8-clamped and worth tenths of a percent). A lower-MSE estimate of `E[e ; ctx]` subtracts closer to the true conditional mean, so the law of total variance bites harder and `H(e - mu)` falls further — the same principle two-level context models use in CM/CALIC-class coders. Basis: James–Stein / Efron–Morris shrinkage; the corrector machinery is this registry's own measured construction | **embeddable — and the only candidate that can *lower* the bias family's cost.** Shrinkage form: incumbent state + one array-wide table (30 x int32 ~ 130 B **total**, not per channel) + 1 add + 1 shift per sample-channel; est. cost ~= incumbent's 0.10–0.12. **Pure-pooled corner** (w = 0: drop the per-channel tables entirely): state collapses from ~130 B/ch (~17 KB at 128 ch) to ~130 B for the whole array — a >100x cut in the bias stage's dominant memory term, est. cost 0.05–0.06, which would put a bias-corrected codec on the cheap end of the Pareto front for the first time. Integer, divisionless, causal, zero side-info. **Implementation note:** requires the **time-major** loop (`bc`'s existing `for t: vectorized over channels` form, not `bc_lite`/`bcxs`'s channel-major pass), since a shared table's update order must match on both sides — this is also the on-node order, so it is a fidelity improvement, not a compromise | **Not a bucket-count sweep and not a new context class** (both P9-refined axes are held fixed — that is the point: this is the first orthogonal knob on this stage). **Not a backward argmin** (P7): nothing is selected, the weight is a fixed constant, so there is no winner's-curse surface. **Not `LMS4rs`** (retired, P2): that *split* adaptation data across predictor banks; this *merges* estimation data across channels — the opposite operation, and applied to a scalar mean rather than a 4-tap filter. **Honest risk:** channel amplitude heterogeneity (electrode impedance, distance to the innervation zone — the physical non-uniformity P11 named) biases the pooled mean; the fixed shrinkage weight bounds the damage by keeping the per-channel estimate dominant, and the pure-pooled corner should be reported separately since it is the one at risk. Composable with #1 and #4 — but measure it on the *unchanged* incumbent context first, so the estimator effect is isolated |
| 4 | **`bcxs_sel` — MI-gate the bias corrector's context class** (INSIGHTS frontier #1, carried over, re-ranked). Select `bcxs`'s cross-channel-gradient context where neighbour correlation is high and fall back to `bc_lite`'s own-channel temporal context where it is not; **decoder-observable, zero-side-info, fixed threshold** (channel count / array geometry as `acar_sel` already proves, or a backward neighbour-correlation statistic from the previous reconstructed block) | Both branches are already measured with **opposite-signed** isolated effects that track neighbour MI exactly (positive on all three monopolar arrays, negative on the differential control), so a fixed-threshold selector collects each set's better branch with no new mechanism | **embeddable** — both branches verified; gate mechanism proven by `acar_sel`. Prefer a **recording-level** gate so only one table set is ever instantiated (a per-block gate would need both, doubling state) | **Ceiling correction (2026-08-22):** a two-way gate can only reach the max of its own branches per set (P7), and neither branch holds the OTB corner — that is the headline's 30-bucket quantized-magnitude context, a third class this gate never selects. Expect a strong mean-real/cost Pareto point, **not** the headline. Best run *after* #1 settles which context word is the better spatial branch |
| 5 | **Scale-selected spatial front-end** — gate `LMS4+Rice+xchan_mst`'s Chow-Liu tree (tight arrays) vs plain best-partner (large arrays) on the decoder-observable channel count | Tried 3 ways (MDL in-sample selection, backward rank-statistic, per-channel MDL+hysteresis) — all landed at or below the best of their own branches (P7); a *decoder-observable* channel-count gate (the only form proven to work, via `acar_sel`) is untried for this specific pairing | **embeddable** (both branches already verified; gate mechanism proven elsewhere) | P7's winner's-curse finding predicts a small or null result — budget accordingly, don't assume the branches' peak. Carried over, re-ranked below the three new mechanisms |
| 6 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 7 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2). Note #3 above is the *narrow, divisionless* realization of this row's idea — prefer it over a full NLMS (which needs a divide/reciprocal) |
| 8 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **partially spent — borderline** | the *bias-cancellation* half of JPEG-LS is now proven positive and shipped (P9, `LMS4bc+Rice+xchan_bestpartner`); the *MED/LOCO predictor itself* (replacing the linear LMS, not just correcting its residual mean) remains untried. Entropy-context on the Rice parameter is still spent (P5) |

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

**Boundary clarification for the 2026-08-22 candidate #2 (`xchan_cmean`).** The
settled fact above rules out (a) *energy-preserving multi-tap rotations* that
corrupt both channels (`iklt`, P3), (b) *summed independently-fitted marginal*
subtracts that double-count the shared mode (`xchan_multiparent`, P1b), and now
(c) *fixed unity-gain* multi-neighbour interpolation (`xchan_hint`, P11). A
**composite parent** is none of these: the K neighbours are collapsed into **one
regressor** before any fitting, and **one** gain is then fitted against it — so
the model order stays exactly rank-1 (fewer free parameters than best-partner,
which also spends a selection), it structurally cannot over-subtract (the gain
is the LS solution for the regressor actually used), the parents stay bit-clean
(predict-only), and the amplitude ratio is *fitted*, not assumed. What changes
is the **measurement noise of the regressor**, which is a different axis from
every one of (a)–(c): those were about the basis or the weights, this is about
the SNR of the variable the basis is fitted against. If it loses, the settled
fact sharpens usefully to "the neighbour that carries the MI also carries the
noise — averaging in weaker neighbours costs more shared-mode dilution than it
buys in regressor SNR", which would close the composite-parent axis and leave
selection as the only spatial estimator worth building.

**Boundary clarification for the 2026-08-19 candidate #1 (`xhint`) — RESOLVED,
kept for the record.** The hypothesis below was measured and **lost on all four
real sets**; the settled fact strengthened exactly as the last sentence
predicted, and the sidedness axis is now closed (INSIGHTS **P11**). "Single rank-1
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

### Literature added this cycle (2026-08-22)
- W. A. Fuller, *Measurement Error Models* (Wiley, 1987) — classical
  errors-in-variables attenuation: a regression slope fitted against a noisy
  regressor is biased toward zero by `SNR/(1+SNR)`, capping the variance a
  rank-1 subtract can remove. Grounding for the composite-parent argument in #2
  *(textbook result, unverified on this corpus)*.
- Dolby TrueHD / MLP lossless multichannel matrixing (US 7,392,195 and
  US 8,239,210, "Lossless multi-channel audio codec") — integer, reversible
  matrixed/composite reference channels in a shipping lossless codec; the
  industrial precedent for predicting from a *combination* of channels rather
  than one *(patent-reported, unverified here)*.
- D. Rzepka, "Low-complexity lossless multichannel ECG compression based on
  selective linear prediction", *Biomedical Signal Processing and Control*
  57:101705, 2020 — cross-channel correlation used to pair strongly dependent
  channels for a second decorrelation stage in a low-complexity portable coder;
  the closest published relative of this registry's spatial front-end family
  *(paper-reported, unverified here)*.
- B. Efron & C. Morris, "Stein's estimation rule and its competitors — an
  empirical Bayes approach", *JASA* 68(341), 1973 (and the James–Stein result it
  builds on) — pooling many small, noisily-estimated means toward a common
  centre strictly lowers total MSE in exactly the small-effect / low-sample
  regime the bias corrector's buckets occupy. Grounding for #3
  *(classical result, unverified on this corpus)*.
- Weinberger, Seroussi & Sapiro, "The LOCO-I lossless image compression
  algorithm: principles and standardization into JPEG-LS", *IEEE TIP* 9(8),
  2000 — the divisionless per-context bias corrector both #1 and #3 modify;
  cited here for the *context-word design* discipline (few, well-populated
  buckets), not for a ratio claim *(paper-reported, unverified here)*.

### Literature added 2026-08-19
_(the #1/#2/#3 below refer to the **2026-08-19** slate — `xhint`, `bcxs`,
`LMS4vs` — not to the current table.)_

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
