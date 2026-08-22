# INSIGHTS — distilled learnings for codec selection

**Read this first, every cycle.** This is the durable, theory-rooted knowledge
base: what the harness has **proven on REAL HD-sEMG** about which compression
mechanisms work here and *why*, stated so it guides the next candidate. It is the
condensed successor to ~15 cycles of `experiments/NNN_*.md` (kept as the detailed
record) and the append-only `CYCLE_LOG.md`.

**Maintenance:** after a cycle's measurement + verification, refine the relevant
principle with the new evidence — but only a learning **measured on real data**
(synthetic is mechanism-illustration only), and always state the *theory* for why
it holds, not just the number. A number without a mechanism doesn't generalize.

**Latitude:** candidates need not come from a paper. Designing a **novel** codec by
combining the primitives (predictive coding, reversible integer transforms/lifting,
context modeling, Golomb/Rice, ANS) is welcome **if rooted in sound theory** — you
can state *why* it should lower residual entropy or decorrelate the array better
before measuring. Every design still faces: lossless + bit-exact, `embedded_ok`
(see `EMBEDDED_OK_VERIFICATION.md` for what that gate really proves), real-data-decides.

---

## The current best

`LMS4bc+Rice+xchan_bestpartner` — the proven best-partner front-end (order-4
sign-sign LMS + best-of-4 causal-neighbour cross-channel subtract) plus a
**JPEG-LS/CALIC-style backward-adaptive per-context running-mean bias
corrector** (30 buckets, divisionless, zero side-info) applied to the residual
before Rice coding. Real ratios: **Hyser 1.4851×, OTB 2.1934×, CapgMyo 1.3531×,
CEMHSEY 1.9553×**; cost 0.120 (`results/consolidated_bench.csv`). Beats the
prior best (`LMS4+Rice+xchan_bestpartner`, Hyser 1.4804×) on 3 of 4 real sets
(CEMHSEY is a −0.015% dead tie) at 3× the cost — both stay registered as
distinct Pareto points. A cheaper 27-context sibling,
`LMS4bc_lite+Rice+xchan_bestpartner` (cost 0.098), trades a little Hyser/OTB
ratio for a **win on CapgMyo and CEMHSEY** instead — genuinely non-dominated,
not a duplicate (P9). If the bias stage's extra state/compute is unacceptable
on-node, `LMS4+Rice+xchan_bestpartner` (cost 0.039) remains the
minimal-hardware pick, and `LMS4+Rice+xchan_bestpartner_adaptive` is its
zero-side-info streaming realization (ratio within ~0.4%). A third,
cost-efficient corner worth knowing: `LMS4+Rice+xchan_mst` (Chow-Liu spanning
tree spatial front-end, cost 0.046) beats the plain best-partner front-end on
3 of 4 real sets for barely more than its cost (P8).

**Update 2026-08-19 — the headline's strongest challenger.** A third bias
corrector, `LMS4bcxs+Rice+xchan_bestpartner` (27 buckets like `bc_lite`, but
conditioned on a **cross-channel gradient** instead of own-channel history),
now holds the **best 4-set real mean of any codec ever benched here — 1.74788×
at cost 0.1013**, versus the headline's 1.74673× at 0.1202 (16% cheaper).
Real ratios: Hyser 1.484874×, OTB 2.181863×, CapgMyo 1.353163×, **CEMHSEY
1.971616× (an outright maximum)** — `results/cycle_bench.csv`. It was **not**
promoted: against `LMS4bc` it is 1 clear win (CEMHSEY +0.837%), 1 clear loss
(OTB −0.528%) and 2 dead ties, which is not "beats the best on real data" under
the bar this log has applied since cycle 11. It is the obvious headline
challenger for the next cycle and is on the mean-real Pareto front (P9).

**Update 2026-08-22 — the headline survives a three-way attack; one new
per-dataset maximum.** Three candidates measured (`results/cycle_bench.csv`),
all three unanimous PROMOTE, **none promoted**.
`LMS4bcpool+Rice+xchan_bestpartner` (cost 0.1282) now holds the **highest real
ratio ever recorded here — OTB 2.194780×** — and the bias-family Hyser maximum
(1.485974×), beating the headline on 3 of 4 real sets; it is not promoted
because its three wins (+0.060%, +0.061%, +0.022%) are dwarfed by its one loss
(CapgMyo −0.186%) and its 4-set mean is a dead tie (1.74677 vs 1.74673) at +6.7%
cost. `bcxs` therefore still holds the mean-real front tip (1.74788 at cost
0.1013) and `LMS4bc` still holds the headline. One candidate was retired
(`LMS4+Rice+xchan_cmean`, P13). Registry: **33 codecs, 19 active / 14 retired.**

## Established principles (proven on real HD-sEMG)

### P1 — Cross-channel spatial decorrelation is the dominant lever, bounded by real neighbour correlation.
- **Evidence:** cross-channel gain +10.8% (Hyser) / +17.4% (OTB) / +13.1% (CEMHSEY),
  but **+1.3% on CapgMyo** (differential 8×16 array, neighbour |corr|≈0.29). The
  `+xchan` on/off ablation is worth ~70× every temporal knob.
- **Theory:** a per-channel coder can't remove redundancy that lives *between*
  channels. Reducible bits ≈ the mutual information between a channel and its
  neighbours, which grows with correlation. Where neighbour correlation is low, the
  achievable gain is small *by the physics*, not codec weakness. CapgMyo is the
  honest negative control.
- **Implication:** prioritize spatial mechanisms only where neighbour correlation is
  high. The cross-channel MI splits into **non-interchangeable slices set by array
  scale**: a **global common-mode (CAR)** dominates *tight* arrays (OTB 64-ch: array
  mean CAR ≈ +14.4%) but collapses on large arrays; a **local pairwise** subtract
  dominates *large* arrays (128–320 ch), where shared content is spatially local.
  Match the spatial basis to the redundancy's scale. A **decoder-observable channel
  count** cleanly gates which basis to use with zero side-info (`acar_sel`).

### P1b — A JOINT 2-parent solve recovers a second parent's MI, but selection and count are substitutes set by geometry.
- **Evidence:** a joint co-adaptive 2-tap sign-LMS on both parents got the **highest
  Hyser cross-channel gain of any codec (+12.55%, `jointbp2`)** — the second parent
  genuinely adds MI on the diffuse-local large array — yet stayed **below** a single
  *selected* best-partner on tight OTB.
- **Theory:** a *summed* pair of marginal rank-1 subtracts double-counts the parents'
  shared mode → over-subtracts. A **joint** 2×2 solve (taps co-adapting against the
  shared residual) is the correct fix and works. But on a tight array the local
  pairwise MI is essentially rank-1 (one dominant diagonal neighbour), so a second
  degree of freedom — whether *count* (joint pair) or a *second selected partner* —
  finds little MI and only adds estimation variance. On a large array it's rank≥2, so
  the extra jointly-solved parent finds real MI.
- **Implication:** per-scale winner is settled — **single selected partner on tight
  arrays, jointly-solved best-pair on large arrays.** No single *fixed* front-end wins
  both; a *scale-selected* one is the open lever (frontier #1).

### P2 — Temporal prediction saturates early; deeper prediction *hurts* on real data.
- **Evidence:** order-4 LMS beats order-8 on Hyser and OTB across three independent
  cycles; dropping 8→4 *raised* ratio on all 4 sets **and** cut cost 0.063→0.039
  (the promotion of the current best).
- **Theory:** after a low-order linear predictor the HD-sEMG residual is near-white;
  extra taps fit **noise** (raising coded entropy) while state/compute grow with order.
- **Implication:** keep the temporal predictor **small (order ≤4)**; spend complexity
  on the spatial front-end. Multiplying predictor **coefficient sets** (an activity-
  regime bank, `LMS4rs`) is the same mistake as deeper order — it fragments adaptation
  and fits noise; **spent NEGATIVE, retired.** To lower temporal residual entropy the
  predictor's *functional form* must change (genuinely non-linear), not its tap/set count.

### P3 — For the spatial transform, data-dependent beats data-independent; rank-1 adaptive beats multi-tap.
- **Evidence:** a fixed 45° integer-KLT captured ~half the adaptive single-neighbour
  gain (+8.8% vs +18% OTB); making the KLT angle backward-adaptive was *worse still*
  (+1.7–3.3%, −0.5% CapgMyo). Both retired, dominated on all 4 sets.
- **Theory:** the KLT is optimal only when its basis matches the covariance; a fixed
  45° rotation assumes stationary isotropic equal-variance pairs, violated by real
  anisotropic non-stationary HD-sEMG. A backward-estimated angle is stale/noisy, and a
  Givens rotation is energy-preserving so it corrupts **both** channels — whereas the
  rank-1 subtract injects estimation noise only into the residual and leaves the parent
  clean. The rank-1 adaptive subtract is not just cheaper, it's **more robust** under
  causal estimation noise.
- **Implication:** multi-tap spatial transforms (fixed or adaptive) are a **settled dead
  end** here. The spatial gain lives in the data-dependent pairwise weight.

### P4 — Embeddability is a hard gate; prefer backward-adaptive (zero side-info).
- **Evidence:** the headline `+xchan` beta is a float whole-signal value computed
  offline — **not producible on-node** (see `EMBEDDED_OK_VERIFICATION.md`). Per-block
  backward re-selection of (partner, β) from the previous reconstructed block holds
  the offline ratio within −0.08…−0.41% (and *beats* it on CapgMyo) at **zero side-info,
  look-ahead 0** (`bestpartner_adaptive`).
- **Theory:** anything the decoder can recompute from reconstructed causal history costs
  zero side-info and is streaming-legal; anything from the whole recording trades
  on-node feasibility for ratio. A **slowly-varying** parameter (best-partner identity is
  stable within a recording) costs ~zero ratio to make backward-adaptive.
- **Implication:** prefer backward-adaptive estimation. Treat any offline/whole-signal
  parameter as a realization gap, not a real on-node result — and confirm the streaming
  form's ratio before quoting it as embeddable.

### P5 — Golomb-Rice is at the entropy floor; the entropy back-end is NOT a lever here.
- **Evidence:** a LOCO-ANS-style tANS coder on the identical predictor was **1.4–1.8%
  SMALLER at ~2× cost** on all 4 real sets (retired). Conditioning the Rice *k* on a
  cross-channel energy context (`xctx`) lost 2.3–2.8% — below even plain LMS+Rice (retired).
- **Theory:** Rice is the optimal prefix code for an exactly-geometric residual, and real
  post-LMS HD-sEMG residual blocks are near-geometric — Rice already sits at the floor, so
  there is no sub-Golomb fraction to amortize an ANS table or a context-frequency split.
  After LMS whitening, `H(e_c | cross-channel context) ≈ H(e_c)` — the conditional entropy
  the context meant to exploit was already removed by the predictor.
- **Implication:** the entropy back-end (engine *or* the Rice parameter's context) is a
  **spent, dead lever for ratio**. Lower residual entropy upstream (better decorrelation),
  never at the coder. A back-end swap is justifiable only for throughput/hardware, never ratio.

**Principles P6–P10 below were distilled 2026-08-17 from consolidating five
cycles (2026-08-05 through 2026-08-16) that ran in parallel, blind to each
other, because each was branched from the same unmerged `main`. Where multiple
independent implementations of the same mechanism converged on the same
qualitative result, that convergence is called out explicitly — it is
materially stronger evidence than a single cycle's finding.**

### P6 — Cross-channel MI is instantaneous volume conduction, not a propagating wavefront — settled by 5x independent replication.
- **Evidence:** five *independently implemented* per-block backward-adaptive lag
  searches (different authors' cycles, different search ranges, different tap
  structures) all found lag=0 selected in 92–98% of blocks on every monopolar
  array (Hyser/OTB/CEMHSEY), and all five *lost* ratio there (−0.25% to −1.30%
  vs the zero-lag incumbent). The one consistent exception across all five: the
  CapgMyo *differential* array, where a narrow lag search gains up to +0.9% —
  because the differential electrode has already cancelled the zero-lag common
  mode, so what little MI remains is genuinely non-zero-lag.
- **Theory:** HD-sEMG's dominant neighbour coherence is the shared *far-field*
  volume-conducted signal, which reaches adjacent electrodes effectively in
  phase at these inter-electrode spacings and sample rates — the propagating
  near-field MUAP wavefront every attempt was motivated by is a much smaller
  term. A lag search can only find a delay that is actually there; five
  independent estimators finding lag=0 in >92% of blocks is not a search-space
  or implementation artifact, it is the physics.
- **Implication:** the lag axis is now a **closed, high-confidence dead end**
  for monopolar arrays — do not re-propose without a specific reason a 6th
  attempt would differ. On differential/bipolar arrays it remains a small,
  real, low-priority lever.

### P7 — Backward-search width trades ratio for selection variance ("winner's curse") — the general form of P6's failure mode.
- **Evidence:** every widened per-block backward argmin measured this round —
  the multi-sample lag search (P6), rank-1-vs-rank-2 gating at 3 independent
  granularities (in-sample MDL order selection, a backward rank-statistic
  gate, and a per-channel MDL+hysteresis gate — none beat the better of their
  own two branches, and one landed *below* both), and a radius-expanded
  Chow-Liu spanning tree (P8) — either lost ratio outright or delivered at
  best a statistical tie with the narrower incumbent, even where the wider
  hypothesis class is a **strict superset** (so the true optimum is bounded
  below by the incumbent's).
- **Theory:** a per-block backward selector fits its choice on ~250–2000
  causal samples of the *previous* block only. Enlarging the option set grows
  the selection bias/variance (the empirical-best-of-K systematically
  overestimates the true best as K grows — winner's curse) faster than it
  grows the achievable signal, whenever the true margin between the best and
  next-best option is small relative to single-block estimation noise — the
  common case once a narrow, physically-motivated option set already captures
  most of the real structure.
- **Implication:** before widening any backward-adaptive search, estimate the
  true margin it is chasing (e.g. an oracle/whole-signal upper bound) against
  the single-block estimation-noise floor. Widening a search is a
  **selection-variance cost paid up front for MI that may not exist**, not a
  free strict improvement, even when the option set is a superset.

### P8 — Optimal spatial STRUCTURE (Chow-Liu spanning tree) beats the fixed raster-neighbour set, but the gain is small and array-size-limited.
- **Evidence:** two independently implemented Chow-Liu maximum-weight spanning
  trees over the channel graph (different edge-candidate radii, different
  cost models) both replicate the same qualitative result: a small real gain
  on tight/anisotropic arrays (OTB, 64ch: +0.4–0.8% vs the raster-restricted
  incumbent) that shrinks to roughly zero by 320 channels (CEMHSEY). The
  cheaper implementation (radius-restricted 8-neighbourhood, cost 0.046,
  `LMS4+Rice+xchan_mst`) is registered; the costlier one (0.073, statistically
  the same ratios) is superseded and not carried forward in code.
- **Theory:** Chow-Liu is optimal *given the true* pairwise edge weights, but
  every weight here is estimated from one 256-sample backward block while the
  number of candidate edges grows with array size — so on a large array,
  estimation noise in the edge weights corrupts the greedy max-weight-tree
  construction faster than the freed non-raster edges add real MI (P7's
  mechanism, transposed to the spatial-structure axis). The fixed 4-neighbour
  raster set is, in effect, an accidental regularizer that happens to help
  more than it costs once the array is large.
- **Implication:** structural freedom in the spatial graph is worth pursuing
  only on small/tight arrays (≲64ch); do not extend it to the primary 128ch
  or 320ch arrays without a channel-count gate.

### P9 — Backward-adaptive per-context bias cancellation is the first genuinely positive temporal-axis result since P2/P5 closed order, coefficient-set, and quadratic form.
- **Evidence:** two independently implemented JPEG-LS/CALIC-style running-mean
  bias correctors (27 sign-history contexts vs. 30 quantized-magnitude
  contexts; different authors, different cycles) both beat the pre-cycle
  incumbent on Hyser and OTB, and this is now **the leaderboard best**
  (`LMS4bc+Rice+xchan_bestpartner`, +0.32% Hyser, +1.46% OTB vs the prior
  best, cost 0.120). The cheaper 27-context sibling
  (`LMS4bc_lite+Rice+xchan_bestpartner`, cost 0.098) wins CapgMyo and CEMHSEY
  instead — a genuine, non-dominated cost/context-richness trade-off, not a
  duplicate.
- **Theory:** the sign-sign LMS's constant ±1 update is not MMSE-optimal — its
  fixed point is offset from the Wiener solution, so the post-LMS residual
  retains a small but real context-dependent conditional mean E[e|ctx] that no
  *linear* predictor of any order (P2) can remove. Subtracting a backward
  leaky-mean estimate of that context-conditional mean, entirely divisionless
  and zero side-info, lowers H(e) by the law of total variance
  (H(e) ≥ H(e − E[e|ctx])). This is mechanistically distinct from the retired
  `xctx` (which conditioned the *Rice parameter*, a P5-closed lever, and left
  the residual stream itself untouched) — here the residual stream itself is
  corrected, upstream of the coder.
- **Refined 2026-08-19 — the useful axis is the context's *class*, not its
  count, and its value is bounded by the same neighbour MI as P1.** A third
  corrector (`LMS4bcxs`) holds bucket count, update law, bitstream format and
  every other stage **byte-identical to `bc_lite`** and changes only the
  conditioning variables, from own-channel temporal history to a **cross-channel
  gradient**: `ctx = (sgn(e[g−1,t] − e[g−cols,t]), sgn(e[parent(g),t]),
  sgn(e[g,t−1]))`. Isolated effect of making the context cross-channel
  (`bcxs` − `bc_lite`, `results/cycle_bench.csv`): **+0.090 pp Hyser, +0.067 pp
  OTB, +0.082 pp CEMHSEY, −0.045 pp CapgMyo**. The sign tracks neighbour mutual
  information exactly — positive on all three arrays where cross-channel MI
  exists, **negative on the one array (CapgMyo, differential, xchan lever only
  +1.4%) where it does not**. The bias stage as a whole is worth **+0.303%
  Hyser / +0.922% OTB / +0.199% CapgMyo / +0.822% CEMHSEY** over the identical
  bias-free pipeline — the largest bias-stage contribution measured on OTB and
  CEMHSEY of the three correctors.
- **Theory for the refinement:** a context helps in proportion to
  `I(e_c ; ctx)` and hurts in proportion to how much it fragments each bucket's
  sample count. The own-channel axis is the one the temporal predictor has
  already whitened (P5's mechanism), so own-channel history is a *weak* index
  of the residual bias; the spatial gradient sign is a local-activity-direction
  indicator drawn from the axis that still carries MI (P1). Where that MI is
  absent, two of the three context dimensions are noise: 27 buckets do the work
  of 3, each leaky mean is estimated from ~1/9 as many samples, and the
  estimation-variance cost shows up as a real loss. **Context relevance is
  bought with context dilution; the exchange rate is the array's neighbour
  correlation.** Count (27 vs 30) moved cost 22% for a small dataset-dependent
  shift; *class* moved ratio further, at essentially equal cost.
- **Refined 2026-08-22 (a) — the two winning context classes are SUBSTITUTES,
  not additive, and what made the spatial slot work was its DOMAIN.** `LMS4bcxm`
  holds `LMS4bc` byte-identical (30 buckets, same thresholds, same integrator,
  same front-end, same coder) and swaps exactly one slot — the own-channel
  magnitude `q3(e[g,t−2])` — for a spatial gradient sign, testing whether the
  magnitude-class and sign-class wins compose. They do not. Isolated slot-swap
  effect (`bcxm` − `bc`, `results/cycle_bench.csv`): **−0.029 pp Hyser,
  −0.085 pp OTB, −0.133 pp CapgMyo, −0.012 pp CEMHSEY** — the mixed word is
  below `bc` on all four real sets and below `bcxs` on three of four.
- **Theory (a).** Two mechanisms, and the pair of measurements separates them.
  (i) **Domain, not spatiality.** `bcxs` conditioned on the *same-slice residual*
  gradient `sgn(e[g−1,t] − e[g−cols,t])`; `bcxm` conditions on the
  *previous-slice reconstructed-signal* gradient
  `sgn(d[g−1,t−1] − d[g−cols,t−1])`. A context is worth exactly `I(e_c ; ctx)`,
  and the signal-domain neighbour gradient is dominated by the shared far-field
  volume-conducted mode — the very component the best-partner subtract and then
  the LMS high-pass have **already removed** from `e_c` (P10's mechanism read
  forwards). Conditioning a residual's bias on a statistic of what was removed
  from it yields near-zero MI: the *same* spatial slot gains +0.067…+0.090 pp in
  residual domain and loses −0.012…−0.133 pp in signal domain, on the same three
  high-MI arrays. (ii) **Slot redundancy at a fixed budget.** A magnitude
  (second-moment) slot and a direction (first-moment) slot both index the local
  *activity state*; a second direction-class slot buys a small conditional-MI
  increment and pays the full 30-bucket dilution. Two independently-winning slots
  are not additive when they are alternative parameterizations of one latent
  variable. **Corollary: for a bias context, specify the DOMAIN and the TIMING
  of every slot, not just which axis (temporal/spatial) it comes from.**
- **Refined 2026-08-22 (b) — there is a THIRD live axis: the ESTIMATOR's sample
  support, gated by inter-channel HOMOGENEITY (a different quantity from
  neighbour MI).** `LMS4bcpool` holds context class, bucket count, update law
  and bitstream byte-identical to `LMS4bc` and changes only the *read*,
  shrinking each per-channel bucket mean toward an array-wide pooled mean by a
  fixed power-of-two weight (`mu = (3·mu_c + mu_bar) >> 2`, James-Stein /
  empirical Bayes, one shared 300 B table, +3 B/ch). Isolated pooling effect:
  **+0.062 pp OTB, +0.060 pp Hyser, +0.022 pp CEMHSEY, −0.187 pp CapgMyo.** It
  turns `bc`'s slightly *negative* CEMHSEY bias stage (−0.015%) positive
  (+0.007%) — the 320-ch array is exactly where per-channel bucket support is
  scarcest — and it produces the **highest real ratio ever recorded in this
  repo (OTB 2.194780×)**.
- **Theory (b).** The per-channel bucket mean is a leaky integrator with a ~32-hit
  effective window estimating a correction of magnitude ≈0.4 LSB — a
  high-variance estimate of a small parameter. Shrinking toward a ~512-hit
  pooled mean cuts that variance; the price is a bias equal to the shrinkage
  weight times the channel's deviation from the array mean. James-Stein's
  precondition is that the per-channel parameters be exchangeable draws from a
  common distribution — and on a **monopolar** array they nearly are, because
  the quantity being estimated is the offset between the sign-sign LMS fixed
  point and the Wiener solution, a property of the *adaptation law and the
  signal class*, not of the individual electrode. On **CapgMyo** the
  precondition fails structurally: it is a **differential** montage, each
  channel's bias carries the sign of its own electrode pair's geometry,
  opposite-signed biases coexist, the pooled mean averages to ≈0 — so shrinkage
  displaces every channel by 1/4 toward a target carrying no signal and
  **destroys 94% of the bias stage's value** (+0.197% → +0.011%). Note this gate
  is *not* P1's neighbour MI: it is cross-channel homogeneity of the predictor's
  **bias field**. The two are correlated on this corpus (CapgMyo is the negative
  control for both) but only pooling is sensitive to the montage's sign
  cancellation.
- **Implication:** stop sweeping bucket *counts*; sweep context *classes*, and
  gate a spatial context on a decoder-observable proxy for neighbour
  correlation (the `acar_sel` zero-side-info gate discipline, P1/P4) so the
  low-MI arrays keep the temporal context. Do **not** try to compose two winning
  context classes into one word at a fixed budget — refinement (a) shows they
  are substitutes. The freshest lever on this stage is now refinement (b)'s
  **estimator support**, made adaptive: shrink hard where the pooled and
  per-channel estimates agree and not at all where they disagree, which is
  decoder-observable at zero side-info and would keep the monopolar +0.06 pp
  while zeroing the CapgMyo −0.19 pp.

### P10 — Reversing the pipeline (temporal-then-spatial) is conclusively worse than spatial-then-temporal.
- **Evidence:** two independent implementations of the reordered pipeline
  (cross-channel subtract applied to the *post-LMS residual* instead of the
  raw signal, one additionally fixing a genuine scoring-criterion mismatch in
  the incumbent) both lost on every real set at cost identical to the
  incumbent — conclusively Pareto-dominated, both retired.
- **Theory:** the per-channel temporal LMS is spectrally a high-pass filter —
  it removes exactly the shared low-frequency volume-conduction content that
  carries most of the inter-channel mutual information, before the
  cross-channel stage gets a chance to use it. Fixing the (real) scoring
  mismatch in the reordered pipeline did not recover the loss, confirming the
  dominant effect is the pipeline order, not the selection criterion.
- **Implication:** spatial-then-temporal is now a **settled pipeline order** —
  any future refinement to either stage should assume this ordering rather
  than re-litigate it.

### P11 — Two-sided (quincunx/HINT) spatial prediction loses to one-sided *gain-fitted* prediction: on real arrays, amplitude tracking beats geometric symmetry.
- **Evidence:** `LMS4+Rice+xchan_hint` splits the grid into a checkerboard,
  codes the black half with the incumbent's own best-partner subtract
  (restricted to same-parity parents), then predicts every white channel from
  **both** sides with a convex, sum-to-one, shift-only mean — zero side-info on
  the white half, half the incumbent's on the black. It **lost on all four real
  sets**: Hyser 1.458679× (−1.47% vs the incumbent front-end), OTB 2.115166×
  (−2.16%), CapgMyo 1.314593× (−2.66%), CEMHSEY 1.878935× (−3.92%). Isolated
  cross-channel gain vs the shared `LMS+Rice` null is **below the one-sided
  incumbent on every real set** — Hyser +9.68% vs +11.31%, OTB +15.88% vs
  +18.44%, CEMHSEY +8.65% vs +13.08%, and CapgMyo **−1.33% vs +1.37%**, i.e.
  *worse than having no spatial stage at all*. And the tell: it is the
  **top-ranked codec on both synthetic sets** (sc0.6 2.636577×, sc0.9
  2.615727×), beating everything it loses to on real data.
- **Theory:** two effects, both bounded by information, not by geometry.
  (i) A convex sum-to-one interpolator is a **unity-gain** predictor: it assumes
  the neighbour's amplitude equals the target's. That is true of a smooth
  stationary synthetic field and false of real HD-sEMG, where electrode
  impedance, distance to the innervation zone and anisotropic conduction make
  the neighbour amplitude ratio a real, per-pair, time-varying parameter. The
  incumbent's fitted integer-LS `β` removes exactly that component; the
  two-sided mean leaves it in the residual. **Prediction-variance reduction
  from a second, symmetric sample cannot pay for the bias introduced by
  mis-specifying the gain.** (ii) The parity split deletes every dist-1
  orthogonal edge from the black half's candidate set — precisely the
  highest-MI edges, since volume-conducted coherence decays with
  inter-electrode distance — so half the array is predicted from strictly
  weaker parents. Note this is *not* the retired `xchan_multiparent` failure
  (total gain is exactly 1, so it structurally cannot over-subtract); it is the
  **fixed-basis** failure of P3 transposed from the rotation angle to the gain.
- **Implication:** the *sidedness* axis is closed. Two-sided spatial prediction
  is only worth revisiting in a form that keeps a **fitted per-pair gain** on
  both sides (i.e. a jointly-solved two-parent subtract, P1b, which already
  works) — never as a fixed-weight interpolator. Second, methodological:
  **a codec that wins the synthetics and loses the real sets is diagnosing its
  own basis mismatch.** Synthetic-set leadership is now a documented warning
  sign, not encouragement.

### P12 — The sign-sign LMS is TRACKING-limited, not misadjustment-limited: annealing the step size is a dead lever, and this closes the last free parameter of the temporal predictor.
- **Evidence:** `LMS4vs+Rice+xchan_bestpartner` keeps order 4, one coefficient
  set, the update *direction*, the spatial front-end and the Rice back-end
  identical, and changes only the step **size**: a per-tap 4-bit saturating
  gradient-sign-agreement counter selects a power-of-two step, shifts only,
  zero side-info, constructed so its coarsest step *is* the incumbent's constant
  ±1 and it can only anneal downward from there. Result: **loses 3 of 4 real
  sets** (Hyser 1.479529× −0.058%, OTB 2.155639× −0.291%, CapgMyo 1.347197×
  −0.243%) with CEMHSEY a +0.0036% dead tie, at +31% cost (0.0516 vs 0.0394) —
  while **winning both synthetics** (+0.018%, +0.020%). Step-shift occupancy was
  near-uniform across all four levels, so the mechanism genuinely engaged; this
  is not a null implementation.
- **Theory:** steady-state excess MSE of sign-sign LMS scales *with* the step,
  while tracking lag against a time-varying optimum scales *inversely* with it —
  a single trade with one crossing point. The sign flip between stationary
  synthetic (annealing wins) and real HD-sEMG (annealing loses on every set)
  locates the incumbent on the **tracking-limited** side: real HD-sEMG is
  strongly non-stationary at the block scale (MUAP bursts, recruitment /
  derecruitment, tens-of-ms amplitude modulation), so every bit of step
  reduction costs more in lag-induced prediction error than it recovers in
  gradient noise. The constant ±1 is not an untuned hyperparameter with headroom;
  it is at or past the optimum for this signal class.
- **Implication:** read together with P9, this **partitions the post-LMS residual's
  excess entropy**: it is a context-conditional **first moment** (a bias — live,
  removable, worth +0.3…+0.9% via P9's corrector) and **not** a step-size
  **variance** term. Predictor-variance reduction and predictor-bias removal are
  not substitutes here; only bias is live. The temporal predictor's free
  parameters are now all spent — order (P2), coefficient-set count (P2),
  functional form (`LMS4v2`, retired), and step-size rule (this) — so **the
  temporal axis is closed except for what sits downstream of the predictor**
  (P9's context-conditional correction).

### P13 — Averaging spatial parents to denoise the regressor is a net LOSS on real arrays: per-pair gain heterogeneity costs more than regressor variance buys.
- **Evidence:** `LMS4+Rice+xchan_cmean` replaces the *selected* parent with ONE
  composite virtual parent `m[g,t] = (Σ s_i·x[i,t]) >> 2` over `K=4` fixed causal
  grid slots (sign-aligned from the previous reconstructed block), then applies
  the family's verbatim rank-1 subtract with ONE backward-fitted integer-LS gain
  — zero side-info, no argmin anywhere. Isolated cross-channel gain against the
  shared `LMS+Rice` null (`results/cycle_bench.csv`) is **below the single
  selected parent on every real set**: Hyser **+8.24%** vs +11.31%, OTB
  **+12.63%** vs +18.44%, CapgMyo **+0.41%** vs +1.37%, and CEMHSEY
  **+4.36%** vs +13.08% — one *third* of the lever on the 320-ch array. Ratios
  1.439590 / 2.055983 / 1.337657 / 1.804796, i.e. −0.950…−7.709% versus the
  incumbent front-end at +18% cost. **Retired**, dominated by five cheaper
  codecs. And the tell: it is the **top-ranked codec on BOTH synthetic sets**
  (sc0.6 2.662820×, sc0.9 2.646026×, outright run maxima).
- **Theory:** noise-averaging `K` regressors raises regressor SNR **only if the
  regressors are exchangeable** — each carrying the shared component at the same
  gain, so one scalar `β` can undo the pooling. A stationary isotropic synthetic
  field satisfies this exactly; real HD-sEMG does not, because electrode
  impedance, distance to the innervation zone and anisotropic conduction make
  the target-to-neighbour gain a **per-pair, time-varying** parameter.
  Collapsing four parents into a fixed `1/K` sum **destroys that heterogeneity
  before the gain is fitted**, and one shared `β` can then only fit the average
  of four different true gains. The trade is a variance reduction of order `1/K`
  against a specification bias of order the *spread* of the true per-pair gains;
  on real arrays the bias term wins. The pooling also **attenuates the one
  dominant high-MI parent by ~1/K** while injecting three lower-MI channels'
  independent noise — sign alignment fixes polarity, never scale. Geometry
  confirms it: the loss is worst on CEMHSEY's long thin 5×64 grid, where the
  four fixed slots span the largest physical spread and hence the largest gain
  heterogeneity.
- **Relation to prior principles:** this is *not* the retired `xchan_multiparent`
  over-subtraction failure (weights sum to 1 after the shift, so it structurally
  cannot over-subtract). It is the **fixed-basis** failure of P3/P11 transposed
  a third time — from the KLT rotation angle, to the two-sided interpolation
  weight, to the `K`-way pooling weight. Read with P1b it closes the multi-parent
  question from both sides: the valid multi-parent form is a **joint solve with
  one fitted gain per parent** (`jointbp2`), never a fixed-weight average with
  one shared gain, and never a sum of marginal subtracts.
- **Implication:** any future spatial front-end must keep **one fitted degree of
  freedom per parent it uses**. Reducing regressor measurement noise
  (errors-in-variables / regression dilution) is a real effect but is *not* a
  live lever here — the parents are not noisy copies of one signal, they are
  differently-scaled views of it. Also: `cmean` is the **second independent
  confirmation of P11's methodological warning** — a codec that wins both
  synthetics and loses all four real sets is diagnosing its own basis mismatch.

---

## Open frontier (ranked by expected payoff/cost)

_Re-ranked 2026-08-22. **Old #2 (compose a spatial-sign slot with a
quantized-magnitude slot at the same bucket budget) is SPENT NEGATIVE** — `bcxm`
measured it and the two classes are substitutes, below both parents on 3/4 real
sets (P9 refinement (a)); it moves to the dead-ends list. In exchange the cycle
**opened a genuinely new axis**: the bias corrector's **estimator sample
support** (`bcpool`, P9 refinement (b)) is live at +0.06 pp on the monopolar
headline sets with a clean, mechanistically-explained −0.19 pp on the
differential control — which is a gate-shaped result, so it enters at **#1** in
gated form. Old #1 (MI-gate the context class) is unchanged in mechanism and
drops to **#2**; it is now additionally constrained by refinement (a)'s
domain/timing corollary. Old #3 (scale-gate the spatial front-end) is unchanged
at **#3**. One lever was spent negative with nothing suggested in return
(fixed-weight composite spatial parent, P13)._

1. **Make the bias corrector's shrinkage weight adaptive and
   decoder-observable** (P9 refinement (b) + P4 + P7): `bcpool`'s fixed 1/4
   shrinkage toward the array-pooled bucket mean **wins every monopolar set**
   (+0.060/+0.062/+0.022 pp) and loses only the differential control
   (−0.187 pp), where the pooled mean is structurally signal-free. A weight
   derived from the *agreement between the pooled and per-channel accumulators*
   — e.g. shrink by 1/4 when `sgn(mu_bar) == sgn(mu_c)` and by 0 otherwise, or a
   2-level power-of-two weight keyed on `|Sbar[q]|` against a fixed threshold —
   is computable on both sides from already-reconstructed state at **zero
   side-info**, costs a compare and a shift, and would keep the monopolar gain
   while zeroing the CapgMyo loss. That is a genuine 4-set win over `LMS4bc`,
   which no codec has yet posted. Must be a **fixed rule, not a per-block
   argmin** (P7). Highest payoff, lowest mechanism risk: both branches
   (shrink / don't shrink) are already measured on all four real sets.
2. **MI-gate the bias corrector's context class** (P9 refinement + P1 + P4):
   `bcxs`'s cross-channel context wins on all three high-neighbour-MI arrays and
   loses only on the low-MI negative control, by −0.045 pp. A codec that selects
   the spatial context where neighbour correlation is high and falls back to
   `bc_lite`'s temporal context where it is not should hold `bcxs`'s CEMHSEY /
   Hyser / OTB numbers **and** `bc_lite`'s CapgMyo number — which would beat
   `LMS4bc` on all four real sets and take the headline at ~16% less cost. The
   gate must be **decoder-observable and zero-side-info** — a backward
   neighbour-correlation statistic from the previous reconstructed block, or the
   channel count / array geometry as `acar_sel` already does — and must be a
   **fixed threshold, not a learned per-block argmin** (P7). Both branches are
   already measured and both mechanisms are proven; only the switch is new.
   **Constraint added 2026-08-22:** refinement (a) shows the spatial slot only
   carries MI in the **residual domain, same slice** — the gate must select
   `bcxs`'s `sgn(e[g−1,t] − e[g−cols,t])`, never a signal-domain or
   previous-slice restatement of it. And note the ceiling: a two-way gate can
   reach at most the max of its own two branches per set (P7), and **neither**
   branch holds the OTB corner (that is `LMS4bc`'s magnitude context, and now
   `bcpool`'s pooled variant of it) — so expect a strong mean-real/cost Pareto
   point, not the headline.
3. **Scale-gate the spatial front-end** (P1b/P8, carried over, unchanged rank):
   gate `LMS4+Rice+xchan_mst` (P8's tight-array winner) against the plain
   best-partner front-end on decoder-observable channel count, matching the
   proven `acar_sel` discipline — but budget for a **null or small result**: P7
   shows backward-selected gates (3 attempts, 3 granularities) tend to land at
   or below the max of their own branches. Do not add a 4th learned/estimated
   gate criterion.

**No longer on the frontier:** temporal predictor internals of any kind — order,
coefficient-set count, functional form, step-size rule are all spent (P2, P12).
Sidedness of the spatial parent set is spent negative (P11). The entropy
back-end has been closed since P5.

## Dead ends — do NOT re-propose (a genuinely different variant must say why)

- **Multi-tap inter-channel transform, fixed or adaptive** (`iklt`, `iklt_adaptive`):
  mismatched/stale basis, corrupts both channels; the rank-1 adaptive subtract dominates (P3).
- **Entropy back-end swap** (`xchan_tans`) and **any context-modeling of the Rice
  parameter** (`xctx`): Rice is at the floor; model side-info is pure loss (P5).
- **Summed multi-parent rank-1 subtract** (`xchan_multiparent`): double-counts the parents'
  shared mode → over-subtracts. The valid multi-parent form is a *joint* solve (P1b), not a sum.
- **Activity-regime / coefficient-set predictor bank** (`LMS4rs`): fragments adaptation, fits
  noise once the residual is white (P2). Same failure as `xctx`, predictor side.
- **Always-on global CAR cascade** (`acar+bestpartner`): superseded by its *scale-gated*
  form `acar_sel` (same tight-array corner, no large-array regression) — always gate a
  geometry-dependent lever on a decoder-observable variable (P1).
- **Time-lagged cross-channel prediction on monopolar arrays**, any implementation
  (P6): closed by 5x independent replication — real neighbour MI is instantaneous
  volume conduction, not a delayed propagating wavefront. Differential/bipolar
  arrays remain a minor, low-priority exception.
- **Widening ANY per-block backward-adaptive search** without first bounding the
  true margin against single-block estimation noise (P7): the general failure mode
  behind P6, the three independent rank-1-vs-rank-2 gating attempts, and the
  radius-expanded spanning tree. A superset option set is not a free win.
- **Temporal-then-spatial pipeline order**, any implementation (P10): the LMS
  high-pass destroys the shared low-frequency mode the cross-channel stage needs,
  confirmed by 2 independent implementations losing on every real set.
- **Two-sided / quincunx / HINT spatial prediction with FIXED (unity, convex,
  sum-to-one) weights** (`xchan_hint`, P11): geometric symmetry does not
  compensate for mis-specifying the neighbour amplitude ratio, and the parity
  split starves half the array of its highest-MI dist-1 orthogonal parents. Lost
  on all 4 real sets (−1.47…−3.92%) while topping both synthetics — the
  signature of a basis matched to a stationary field, not to real HD-sEMG. Only
  a *fitted-gain* two-sided form (i.e. the joint 2-parent solve, P1b) is still
  open.
- **Step-size / adaptation-law tuning of the sign-sign LMS**, any schedule
  (`LMS4vs`, P12): the predictor is tracking-limited on real non-stationary
  HD-sEMG, so annealing trades a real tracking loss for a misadjustment gain
  that isn't there. Wins the stationary synthetics, loses 3/4 real sets at +31%
  cost. Together with P2 and `LMS4v2` this closes **every** free parameter of
  the temporal predictor itself.
- **Sweeping the bias corrector's BUCKET COUNT** (P9 refinement): 27 vs 30
  buckets moves cost 22% for a small dataset-dependent shift; the productive
  variable is the context's **class** (which variables condition it), and its
  value is bounded by the array's neighbour MI. Propose a new context *class*
  with a gate, never a new count.
- **COMPOSING two winning bias-context classes into one word at a fixed bucket
  budget** (`LMS4bcxm`, P9 refinement (a)): magnitude (second-moment) slots and
  spatial-sign (direction) slots are **substitutes** — alternative
  parameterizations of the same latent local-activity state — so a mixed word
  buys a near-zero conditional-MI increment and pays the full dilution. Lost to
  `LMS4bc` on all 4 real sets and to `bcxs` on 3 of 4. Related and stronger:
  **a spatial context slot taken from the SIGNAL domain or from a PREVIOUS
  slice is a dead slot** — the shared volume-conducted mode it indexes has
  already been removed from the residual by the spatial subtract and the LMS
  high-pass (P10 read forwards), so `I(e ; that slot) ≈ 0`. Only the
  **same-slice residual** gradient carries MI. Specify domain and timing, not
  just the axis.
- **Fixed-weight composite / pooled spatial parent** (`xchan_cmean`, P13):
  averaging `K` neighbours into one virtual parent with **one shared fitted
  gain** destroys per-pair gain heterogeneity before the gain is fitted and
  attenuates the dominant high-MI parent by ~1/K. Captured less cross-channel MI
  than a single selected parent on **every** real set (only ⅓ of the lever on
  CEMHSEY) while topping **both** synthetics — P11's basis-mismatch signature,
  second independent instance. Errors-in-variables / regression dilution is not
  a live lever here: the parents are differently-scaled views of the shared
  mode, not noisy copies of one signal. Any multi-parent front-end must keep
  **one fitted degree of freedom per parent** (the joint solve, P1b).

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.
