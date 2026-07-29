# What `embedded_ok` actually means — a verification

> Answering three questions directly: **what does `embedded_ok` mean, does it
> actually tell you what can be implemented on a small MCU or FPGA, and how does
> it work?** Every claim below is reproduced by
> `python3 research/embedded_verify.py` (add `--strict` to make it a CI gate).

## TL;DR

`embedded_ok` is a **hard gate on hand-declared design intent — not a measurement
of the code.** It answers *"did the codec's author claim an integer, causal,
bounded-look-ahead realization whose self-reported op-count fits an idealized
Cortex-M7 cycle budget?"* It does **not** answer *"will the thing that produced
this ratio actually run in real time on the node / fit the Spartan-7?"* Those are
different questions, and for the headline codecs they have different answers.

It is a useful **sanity filter** with the right *shape* (gate on feasibility, then
rank on a ratio-vs-cost Pareto front). But taken as a feasibility *proof* it is
unsound in five specific ways, three of which bite the current leaderboard.

## How it works (mechanically)

`research/embedded_cost.py`:

```
enc_cycles = enc_ops * 1.2                       # CYC_PER_OP, flat
sram_bytes = state_bytes_per_ch * n_ch
embedded_ok = integer_only AND causal
              AND lookahead_samples <= 4096
              AND enc_cycles <= 1831              # 480 MHz / (2048 Hz * 128 ch)
              AND sram_bytes  <= 262144           # 256 KiB
neural_ok   = embedded_ok AND enc_cycles <= 125  # 480 MHz / (30 kHz * 128 ch)
cost        = enc_cycles/1831 + sram_bytes/262144 # continuous, for the Pareto front
```

Every input — `enc_ops`, `dec_ops`, `state_bytes_per_ch`, `causal`,
`integer_only`, `lookahead_samples` — is a **literal written by hand** in each
codec's `CodecMeta(...)` in `research/registry.py`. For example
`_LMS_OPS = 50` with the comment `~ 50`, `_XCHAN_OPS = 3`, `_RICE_STATE = 4`.
Nothing derives them from, or checks them against, the code in
`host_tools/embedded_codec.py`.

**Consequence #0:** the gate can only ever be as honest as the metadata. Run the
registry self-test and *every one of the 20 codecs reports `emb_ok=OK` and
`neural_ok=OK`* — the gate has never once rejected a codec that got registered,
because everything registered was declared to pass. A gate that never fires on
the population it sees is not filtering; it is rubber-stamping.

## Does it accurately decide MCU/FPGA feasibility? The five gaps

### Gap 1 — Declared, not measured (the whole gate is self-report)
`enc_ops = 50` is an estimate in a comment. `research/embedded_verify.py`
(audit 2) instruments a real encode and finds the Rice `_best_k` k-search **alone**
executes ~**7.7 add/shift/compare per sample-channel** — comparable to the entire
`~9` the model budgets for *all* of Rice — plus **15 integer divides** per encode
that the flat `1.2 cyc/op` prices as ordinary ops (an M7 `SDIV` is ~2–12 cycles,
and division has no single-cycle path). The declared op count is an **optimistic
lower bound** that omits the k-search loop, the variable-length bit-packing
(branch-heavy, not flat ALU), and divide latency. It is fine for *ranking* similar
codecs; it is not a real-time-fit proof.

### Gap 2 — The ratio and the `embedded_ok` verdict describe *different programs* (the big one)
The metadata for `LMS+Rice+xchan` declares `causal=True, lookahead=256,
integer_only=True`. The code that actually produced its leaderboard ratio computes
the cross-channel gain `beta` as a **floating-point least-squares ratio over the
entire recording** (`embedded_codec.cross_betas`: `round(<x_c,x_p>/<x_p,x_p> *
2^shift)` with `.sum()` over all N). Audit 1 proves it: perturb **only the future
half** of the signal and **22032 / 24000 of the *past* residuals change** — the
encoder demonstrably read samples it hasn't reached yet. So the number on the
leaderboard was measured on an **offline, float, non-streaming** encoder, while
`embedded_ok=True` is asserted about a hypothetical integer/causal/one-block
encoder **that was never benchmarked.** The harness calls this a "port caveat";
it is more than that — the feasibility verdict does not apply to the artifact that
earned the ratio.

Functionally traced (audit prints the list), the codecs whose **reported ratio**
comes from an offline whole-recording parameter are:
`delta+Rice+xchan`, `LMS+Rice+xchan`, `LMS+Rice+xchan_bestpartner`,
`LMS4+Rice+xchan_bestpartner` (**the promoted best**), `LMS+Rice+xchan_tans`,
`LMS4+Rice+acar+bestpartner`, `LMS4+Rice+acar_sel+bestpartner`.

**In fairness — the honest half.** The *backward-adaptive* variants
(`LMS+Rice+xchan_adaptive`, `LMS4+Rice+xchan_bestpartner_adaptive`,
`LMS+Rice+xchan_joint2`) recompute `beta` per block from the **previous
reconstructed block**, integer-only. Audit 1 confirms they genuinely stream
(prefix-encoding is identical for identical past), so *their* `causal/lookahead/
integer` declarations are true and their ratios were measured on the real
embeddable codec. INSIGHTS **P4** already prefers these; the point here is that the
gate itself cannot tell the two families apart — a human has to read the notes.

### Gap 3 — "MCU" and "FPGA" are conflated; neither is modeled faithfully
The disqualification string for float is `"(FPGA-disqualified)"`, but the cycle
budget it gates on is a **Cortex-M7** number (480 MHz). The M7 on the named
STM32H745 *has a hardware FPU* — it can do float in a few cycles — so `integer_only`
is being used as an FPGA proxy while the arithmetic budget is an MCU model. The
two targets have different constraints and the model serves neither cleanly.

### Gap 4 — There is no FPGA resource model at all
`compression_spec/cost_model.md` asks for "rough LUT / DSP / BRAM feasibility …
note whether the predictor maps to DSP slices." `embedded_cost.py` implements
**none** of it — `integer_only` is the entire FPGA story. An integer codec can
still blow the LUT budget, exceed the 80 DSP48 slices, or miss timing.
`embedded_verify.py` (audit 3) adds the missing dimension: a first-order XC7S25
model (time-multiplexed MACs → DSP count, per-channel state → BRAM36, a LUT charge)
that yields a separate **`fpga_ok`**. On the *current* codecs it (correctly) says
they all fit comfortably — a single time-shared MAC at 100 MHz covers
`order × 128 ch × 30 kS/s` — so this is not a "gotcha" today; the point is the gate
**never checked**, and this model *would* catch the codec that doesn't (a wide FIR,
a matrix solve, a big context table).

### Gap 5 — `neural_ok` inherits every weakness above
The tight 30 kHz / 125-cyc verdict is computed from the same unmeasured `enc_ops`,
so "fits the neural budget" is exactly as trustworthy as the hand-declared count —
which Gap 1 shows is an underestimate.

## What it gets right (don't overcorrect)
- **The structure is correct:** a hard gate on integer/causal/bounded-look-ahead,
  then rank on a continuous ratio-vs-cost Pareto front. That is the right way to
  keep ratio from deciding alone.
- **The budgets are correctly derived** (1831 and 125 cyc/sample-ch from
  clock/fs/n_ch) and the whole model is documented and hand-reproducible.
- **`causal`, `integer_only`, `lookahead` are real, checkable properties** — the
  problem is nobody checks them, not that they're meaningless.
- For the **backward-adaptive** codecs the declarations are accurate, so the gate
  is telling the truth about *those*.

## How to use it going forward
1. **Treat `embedded_ok` as "declared-feasible," never "proven-feasible."** Read
   `meta.notes`; if it says the parameter is derived offline / over the whole
   signal, the ratio is an offline number — compare it only against the
   backward-adaptive realization's ratio for an apples-to-apples on-node figure.
2. **Run `research/embedded_verify.py --strict` in CI** next to the round-trip
   hook. It fails the build when an `embedded_ok` codec has a non-streaming
   benchmarked path, catching Gap 2 automatically.
3. **Report `fpga_ok` alongside `embedded_ok`** for anything headed for the
   Spartan-7; refine the XC7S25 constants in `embedded_verify.py` from a real
   Vivado utilization report once one exists.
4. **The real fix (future work):** replace the hand-declared `enc_ops` with a
   measured op/state model derived from each codec's own execution, and make the
   benchmark encode the *streaming* realization (per-block `beta`) so the ratio and
   the feasibility verdict finally describe the same program. `embedded_verify.py`
   is the scaffold for step one.

_Reproduce everything here: `python3 research/embedded_verify.py`._
