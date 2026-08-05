# `research/` — the lossless-compression search layer

The search + analysis layer on top of the primitives in `../host_tools/`
(`embedded_codec.py`, `bench_lossless.py`). It reuses them; it never replaces them.
The top-level [`../README.md`](../README.md) is the front door; start there.

## Read first (every cycle)

| file | role |
|---|---|
| `INSIGHTS.md` | **durable, theory-rooted principles (P1–P5) + open frontier + dead ends** |
| `LEADERBOARD.md` | current best, Pareto front, per-dataset ratios, codec to port next (snapshot) |
| `CYCLE_LOG.md` | append-only ledger — one row per research cycle |
| `EMBEDDED_OK_VERIFICATION.md` | what the `embedded_ok` gate really proves (and where it misleads) |
| `../SURVEY.md` | forward-looking candidate watch-list (proposes only) |

## Code

| file | role |
|---|---|
| `registry.py` | every codec behind one interface (`encode`/`decode`/`meta`/`cost`); `--selftest` round-trips all on random int16 |
| `embedded_cost.py` | the `embedded_ok` hard gate + continuous Pareto cost |
| `embedded_verify.py` | **independent audit of that gate** — streaming/causality probe, measured-vs-declared cost, FPGA resource model (`--strict` for CI) |
| `datasets.py` | the corpus loader (synthetic sweeps + real Hyser/OTB/CapgMyo/CEMHSEY, cached under `../sim_data/corpus_npz/`) |
| `bench.py` | per-codec × dataset benchmark → `../results/*.csv` |
| `search.py` | hill-climb the design space subject to `embedded_ok`; ablations + Pareto front |
| `lm_probe.py` | **learned-model headroom probe** (LMCompress-style): MLP → discretised-logistic NLL = ideal code length, vs the real champion on a held-out tail; `--selftest` checks pmf + gradients. Measures a ceiling, ships no codec — see `experiments/015_*` |
| `lm_probe_transformer.py` | same probe with a **causal Transformer** (attention, context 256, ~470 k params; needs `torch`) — confirms 015's ceiling is model-agnostic (two architectures agree to ~0.7 %). See `experiments/016_*` |
| `bgpt_probe.py` | runs the **actual LMCompress audio model** (110M bGPT-audio) zero-shot on our EMG via `model.loss` = bits/byte; needs `torch`/`transformers`/`samplings` + the [bgpt](https://github.com/sanderwood/bgpt) repo + `weights-audio.pth`. Verdict: ~1.07× lossless (fails). See `experiments/017_*` |
| `bootstrap.sh` | idempotent env setup for an ephemeral session |
| `ROUTINE_PROMPT.md` | the scheduled-routine prompt that runs a committed cycle |

## Agent wiring

The cycle (survey → implement → measure → double-verify → analyze) is driven by
`../.claude/agents/*.md` and the committed workflow
`../.claude/workflows/compression-cycle.js`. Dominated codecs are marked
`retired=True` in `registry.py` (kept, excluded from the default sweep), never deleted.

## History

The original stage-by-stage build records — Stage 0 orientation (`00_STATE.md`),
Stage 1 (`01_STAGE1.md`), Stage 4 (`04_STAGE4.md`), and the full agent-prompt /
harness README the loop was bootstrapped from — are preserved under
[`../archive/`](../archive/).
