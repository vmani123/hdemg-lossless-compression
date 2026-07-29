# Making the search more optimal — a proposal

How to make the codec search find more, faster, and more honestly — borrowing the
loops that AutoML and LLM-driven scientific discovery already use. Ranked by
**expected payoff ÷ effort**; each item names the method it comes from, the concrete
weakness it fixes here, and what to change.

## First, name the two searches

There are **two nested search loops**, and they have different problems:

- **Inner (numeric):** `research/search.py` — a greedy, single-start,
  one-axis-at-a-time **hill-climb** over ~6 discrete knobs (predictor family, LMS
  order, shift, cross on/off, cross-shift, Rice block), ranking on **mean ratio
  across datasets** subject to `embedded_ok`.
- **Outer (mechanism):** the agent cycle — surveyor proposes 2–3 distinct
  candidates from `INSIGHTS.md`, implementer codes each, the benchmark measures,
  two adversarial verifiers gate, the analyst distills learnings and retires
  dominated codecs. This is already a **manual LLM-guided evolutionary search**;
  the improvements below make that structure explicit and more sample-efficient.

The single most consequential fact the search keeps rediscovering by hand — *the
winning mechanism depends on array geometry* (tight arrays → best-partner, large →
joint-pair) — is a signal that the objective and the archive, not the candidates,
are what need upgrading.

---

## Ranked proposals

### 1. Kill the mean-ratio objective; select on a per-dataset dominance rule. `[high payoff, low effort]`
**Fix:** `search.py` ranks on `np.mean(ratios)` across the 4 sets, and the analyst
then *manually* overrides it ("wins Hyser, loses OTB → not promoted") almost every
cycle. Encode that rule in the objective. A candidate **dominates** only if it is
`≥` on every dataset and `>` on one (Pareto in *dataset* space), same as the cost
rule already used. Report the per-dataset vector, never a scalar.
**Method:** multi-objective optimization / Pareto dominance (NSGA-II selection rule).
**Why it pays:** removes the recurring manual correction and stops a mean from
promoting a codec that regresses on a set — the exact failure mode in cycles 10–13.

### 2. Cheap-proxy screening before the expensive eval + double-verify. `[high payoff, low effort]`
**Fix:** every candidate today pays a full 15 000-sample × 4-set encode **plus** two
adversarial verifiers. Most candidates are killed by the *first* dataset or a small
sample. Screen wide and cheap, then promote survivors: evaluate at 2 000 samples on
the single most-discriminative set first; only configs within ε of the incumbent
advance to the full 4-set/15 k eval; only those advance to the two-verifier gate.
**Method:** successive halving / Hyperband; multi-fidelity optimization.
**Why it pays:** 3–10× more candidates per unit compute, concentrating the costly
verification on the few that can win. The corpus is cached offline, so cheap
screening is free.

### 3. Multi-start + a surrogate over the discrete grid, instead of one greedy climb. `[med payoff, low effort]`
**Fix:** the hill-climb starts from one seed and moves one axis at a time, so it
misses **axis interactions** (order × cross-shift, block × cross-shift) and stops at
the first local optimum. Two upgrades, in order of effort: (a) **random restarts**
from several seeds and keep the best basin — near-free, the grid is tiny; (b) fit a
cheap **surrogate** (random forest / GP over the ~6 encoded axes) on all
already-evaluated configs and pick the next config by **expected improvement**.
**Method:** Bayesian optimization / SMAC-style model-based search.
**Why it pays:** the whole grid is a few hundred points and every eval is already
cached — a surrogate turns "climb one path" into "spend evals where the model is
most uncertain and most promising."

### 4. A Quality-Diversity archive (MAP-Elites) keyed on (array-scale × cost). `[high payoff, med effort]`
**Fix:** the loop keeps a single "best" and a flat retired list. But the real
structure is a **map**: which mechanism is champion in each (channel-count regime ×
cost regime) cell. Replace "the best codec" with an archive whose cells are e.g.
`channels ∈ {≤64, 128, ≥320} × cost ∈ {<0.02, <0.04, <0.06}`; each cell keeps its
ratio champion. New candidates are placed by their *behavior* (where they win), not
just accepted/rejected.
**Method:** MAP-Elites / quality-diversity; illumination rather than optimization.
**Why it pays:** the "scale-selected front-end" that is frontier #1 **falls out of
the map for free** — it is literally "take each cell's champion and gate on the cell
coordinate." It also converts the retired pile into a structured atlas of *where*
each mechanism lives, which is exactly the knowledge INSIGHTS accumulates by prose.

### 5. Make the outer LLM loop an explicit island-model program search. `[high payoff, med effort]`
**Fix:** the agent cycle already is evolutionary (propose → evaluate → keep/retire →
distill → re-propose) but the "population" is implicit and the retired codecs are
inert. Formalize it the way FunSearch / AlphaEvolve run: maintain **islands** by
mechanism family (temporal / pairwise-spatial / global-common-mode / entropy),
seed each cycle's surveyor prompt with **best-of-island + the distilled "what
mattered"**, and use **dominated-but-diverse** codecs as *mutation seeds* rather
than dead entries. Apply explicit **novelty pressure** (reject a proposal too close
to a registered or retired one — the surveyor does this by hand today).
**Method:** FunSearch / AlphaEvolve (LLM proposes programs, evaluator scores, an
island database seeds future prompts); genetic programming with an archive.
**Why it pays:** turns the retired registry (already maintained!) into the engine of
new candidates, and the island structure prevents the loop from collapsing onto one
family — which is how it missed *fusing* selection and count for several cycles.

### 6. Allocate cycles by expected information gain, not round-robin. `[med payoff, med effort]`
**Fix:** each cycle picks "2–3 distinct candidates" by analyst judgment. The
`CYCLE_LOG` now has ~15 labeled outcomes per mechanism family — enough to fit a
simple **per-family hit-rate prior** and choose the next family by Thompson
sampling / UCB (explore families with few trials, exploit families that keep
paying). Spatial has paid; entropy-context and multi-tap are proven-dead — the
bandit would have stopped sampling them sooner.
**Method:** multi-armed bandits (Thompson / UCB) for experiment allocation; active
learning (pick the experiment that most reduces frontier uncertainty).
**Why it pays:** formalizes "don't re-propose a spent lever" (INSIGHTS' dead-ends)
into the selection rule instead of relying on the surveyor remembering it.

### 7. Hold-out recordings to stop the search overfitting the 4 reported sets. `[high payoff on honesty, low effort]`
**Fix:** hyperparameters and mechanisms are tuned on the same 4 sets the leaderboard
reports. Split by **subject/recording**: tune on a train fold, report only on a
held-out fold, and rotate (cross-validation across recordings). A +0.3% mean that
vanishes out-of-fold is noise, not a promotion.
**Method:** train/validation/test discipline; nested cross-validation.
**Why it pays:** several recent cycles turned on sub-1% differences; without a
hold-out there is no way to tell a real gain from fitting these four recordings.

### 8. Fold the causality/streaming audit into the loop as a hard pre-gate. `[med payoff, low effort]`
**Fix:** `embedded_ok` rubber-stamps every registered codec (see
`EMBEDDED_OK_VERIFICATION.md`), and the offline-vs-streaming gap is caught only by
prose ("port caveat"). Run `research/embedded_verify.py --strict` **in the cycle**,
before the expensive double-verify, so a non-streaming candidate is flagged (or its
streaming realization measured) up front, and the reported ratio is always the
on-node one.
**Method:** property-based testing / verification-in-the-loop; the "evaluator is
ground truth" principle the loop already espouses, applied to *feasibility* too.
**Why it pays:** closes the one place the loop currently trusts a declaration
instead of a measurement.

---

## If you do only three

1. **(#1) per-dataset dominance** as the objective — stops the mean from lying.
2. **(#2) cheap-proxy screening** — the same compute explores far more candidates.
3. **(#4) MAP-Elites over (array-scale × cost)** — turns the geometry-dependent
   winner the loop keeps rediscovering into the search's native output, and hands
   you the scale-selected frontier codec for free.

Everything else composes on top of these three without reworking them.

## What NOT to change
- The **bit-exact + real-data-decides + Pareto** discipline is correct — these
  proposals change *how candidates are proposed and screened*, never the ground
  truth that decides. Keep the benchmark as the sole source of ratios.
- The **retire-don't-delete** registry is already the right substrate for an
  evolutionary archive — reuse it (#5), don't replace it.
