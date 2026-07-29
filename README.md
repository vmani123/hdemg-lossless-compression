# HD-EMG lossless on-node compression

A self-driving, data-driven search for the best **lossless on-node** compressor for
128-channel RHD2164 neural / HD-sEMG data — one that **beats per-channel FLAC /
WavPack / mtscomp by exploiting cross-channel spatial correlation**, while staying
implementable on an **STM32H745 Cortex-M7** or **Spartan-7 XC7S25** at real-time
rates. Success is **not** beating Shannon (independent per-channel noise caps
lossless at ~3–3.5×); success is **beating per-channel FLAC on real grids, at a
fraction of the compute, proven bit-exact.**

Extracted from the [RHD2164 FPGA emulator](https://github.com/vmani123/RHD2164-FPGA-Emulator)
repo (which the codecs target) into its own home so the research can iterate without
weighing that repo down.

## Current bar

**Best embeddable: `LMS4+Rice+xchan_bestpartner`** — order-4 sign-sign LMS + adaptive
Golomb-Rice + best-of-4 causal-neighbour cross-channel subtract. Real HD-sEMG:
**Hyser 1.480× · OTB 2.162× · CEMHSEY 1.956× · CapgMyo 1.350×** (cost 0.039,
bit-exact). Beats every embeddable reference; only offline LZMA is ahead. Full
picture in [`research/LEADERBOARD.md`](research/LEADERBOARD.md).

> ⚠️ The headline `+xchan` ratios are measured with an **offline whole-signal**
> beta — read [`research/EMBEDDED_OK_VERIFICATION.md`](research/EMBEDDED_OK_VERIFICATION.md)
> for what "embeddable" really means here and which codec is the true on-node one.

## Start here (fresh, informed context — not a glut)

| file | what it is |
|---|---|
| [`research/INSIGHTS.md`](research/INSIGHTS.md) | **the durable, theory-rooted principles** (P1–P5) + the ranked open frontier + dead ends. Read first, every cycle. |
| [`research/LEADERBOARD.md`](research/LEADERBOARD.md) | current best, Pareto front, per-dataset ratios, the codec to port next (snapshot). |
| [`research/CYCLE_LOG.md`](research/CYCLE_LOG.md) | append-only ledger, one row per research cycle. |
| [`SURVEY.md`](SURVEY.md) | forward-looking candidate watch-list (proposes only). |
| [`research/EMBEDDED_OK_VERIFICATION.md`](research/EMBEDDED_OK_VERIFICATION.md) | what the `embedded_ok` gate actually proves, and where it misleads. |
| [`research/SEARCH_IMPROVEMENTS.md`](research/SEARCH_IMPROVEMENTS.md) | proposal: how to make the codec search find more, faster, more honestly. |
| [`experiments/`](experiments/) | the detailed per-experiment records (commands, outputs, verdicts). |
| [`archive/`](archive/) | historical stage-0/1/4 orientation docs + the original agent-prompt/harness README. |

## Run it

```bash
./research/bootstrap.sh                 # venv + numpy/scipy/zstandard/mtscomp; cached real corpus
export PYTHONPATH=host_tools:research

python3 research/registry.py --selftest # every codec round-trips bit-exact on random int16
python3 research/embedded_verify.py      # audit the embedded_ok gate (add --strict for CI)
python3 research/bench.py                # reference bar + candidates, real + synthetic -> CSV
python3 research/search.py --datasets hyser_1dof_f1_s1 --max-samples 15000   # hill-climb on real data
```

The real corpus (Hyser, OTB, CapgMyo, CEMHSEY) is cached under
`sim_data/corpus_npz/`, so the benchmark and search **run fully offline** in any
fresh session; an uncached set downloads on demand via `research/datasets.py`.

## Layout

```
host_tools/     embedded_codec.py (delta/LMS/+xchan primitives, adaptive Rice),
                bench_lossless.py (FLAC/WavPack/mtscomp/zstd/LZMA/gzip reference bar),
                verify_compressed.py, gen_neural_mem.py, load_wfdb.py
research/       registry.py (all codecs behind one interface + declared cost metadata),
                embedded_cost.py (the embedded_ok gate + Pareto cost),
                embedded_verify.py (independent audit of that gate),
                datasets.py, bench.py, search.py, INSIGHTS/LEADERBOARD/CYCLE_LOG, README
compression_spec/  candidates.md, datasets.md, cost_model.md
experiments/    NNN_slug.md — one detailed record per experiment
results/        *.csv benchmark + search outputs
sim_data/       corpus_npz/*.npz (cached real HD-sEMG), params.json
.claude/        agents/, workflows/compression-cycle.js, hooks/verify_codec.py
```

## The research loop (how a cycle runs)

One cycle = **survey → implement 2–3 distinct candidates → measure → adversarially
double-verify each → analyze / update the leaderboard**, driven by the agents in
`.claude/agents/` and the committed workflow `.claude/workflows/compression-cycle.js`.
Learnings compound into `INSIGHTS.md`; dominated codecs are marked `retired=True`
(kept, excluded from the default sweep) rather than deleted.
See [`research/README.md`](research/README.md) for the agent wiring.

## Non-negotiables

1. **Lossless only** — `decode(encode(x)) == x` bit-for-bit, asserted, or fail loudly.
2. **Embedded feasibility is a hard gate** — nothing is a "win" unless `embedded_ok`;
   rank on the ratio-vs-cost **Pareto front**, never ratio alone. (And verify the gate
   — see `embedded_verify.py`.)
3. **Real data decides.** Synthetic is for sweeps only. Any lossless ratio > ~6× on
   realistic broadband ⇒ a leak or degenerate data — stop and report.
4. **No number from an agent's reasoning** — only from the benchmark + the bit-exact
   verifiers, enforced by the `PostToolUse` hook.
5. **Determinism** — reproducible from `--seed`; the corpus is hash-pinned.
