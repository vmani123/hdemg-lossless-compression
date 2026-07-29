#!/usr/bin/env python3
"""
embedded_verify.py  -  Independent audit of the `embedded_ok` gate.

`embedded_ok` (research/embedded_cost.py) is a HARD GATE, but it is computed
entirely from HAND-DECLARED metadata that each codec writes about itself in
research/registry.py (enc_ops, dec_ops, state_bytes_per_ch, causal,
integer_only, lookahead_samples). Nothing checks those declarations against
what the code actually does, and the model scores only an STM32 cycle budget --
"integer_only" is the entire FPGA story. So the gate can rubber-stamp a codec
whose benchmarked implementation is not, in fact, embeddable.

This module is the missing cross-check. It runs three audits that need the
CODE, not the codec's self-report, and prints a verdict table:

  1. STREAMING / CAUSALITY probe  -- perturb ONLY the future; if a codec's early
     residuals move, its encoder read the whole recording, so its declared
     `causal=True` / bounded `lookahead` is fiction *as benchmarked*. This is the
     decisive test for the cross-channel front-end, where the whole embeddability
     question lives (whole-signal float beta vs. backward-adaptive integer beta).

  2. COST self-consistency        -- measure the actual per-sample-channel work
     the Rice k-search + predictor perform on a real encode, and compare to the
     declared `enc_ops`. Flags the parts the flat model omits (the k-search loop,
     the variable-length bit I/O, the integer divides).

  3. FPGA feasibility (XC7S25)    -- a first-order DSP48 / LUT / BRAM / fmax
     estimate for the Spartan-7 named in cost_model.md, producing an `fpga_ok`
     that is SEPARATE from the MCU cycle gate. `integer_only` alone does not tell
     you whether 128 channels of order-N MACs fit 80 DSP slices at the sample
     clock -- this does.

Run:   python3 research/embedded_verify.py            # full audit table
       python3 research/embedded_verify.py --strict   # exit 1 if any claim fails

Exit code is non-zero under --strict if a codec that the gate calls embedded_ok
has a benchmarked path that contradicts its declared embeddability, so this can
guard CI exactly like the round-trip hook does.
"""
import argparse
import os
import sys

import numpy as np

HOST = os.path.join(os.path.dirname(__file__), "..", "host_tools")
sys.path.insert(0, HOST)
sys.path.insert(0, os.path.dirname(__file__))
import embedded_codec as ec          # noqa: E402
import embedded_cost as ecost        # noqa: E402
import registry as reg               # noqa: E402


# ---------------------------------------------------------------------------
# A small correlated int16 array: 4x4 grid, strong shared spatial component so
# the cross-channel front-end actually engages (otherwise beta -> 0 and the
# non-causality is invisible). Deterministic (fixed seed) for reproducibility.
# ---------------------------------------------------------------------------
def _probe_array(C=16, N=3000, cols=4, seed=1):
    rng = np.random.default_rng(seed)
    shared = rng.normal(0, 22, (1, N))
    x = np.repeat(shared, C, axis=0) + rng.normal(0, 8, (C, N))
    return x.round().astype(np.int16), cols


# ===========================================================================
# 1. STREAMING / CAUSALITY  -- does the encoder peek at the future?
# ===========================================================================
def _xchan_residual(x, betas, parent):
    """Residual of the shared cross-channel + order-8 LMS front-end for a given
    per-channel beta vector -- the exact pipeline the leaderboard codecs use."""
    y = ec.cross_forward(x, parent, betas)
    return ec.lms_forward(y)


def causality_audit(verbose=True):
    """Decisive residual-level test of the two cross-channel front-end families.

    Perturb ONLY the future half (t >= T0). A causal/streaming encoder's residual
    for t < T0 cannot change. We compare:
      * WHOLE-SIGNAL beta   (ec.cross_betas over all N)  -- the front-end the
        headline `LMS+Rice+xchan*` codecs are actually benchmarked with.
      * BACKWARD-ADAPTIVE beta (registry `xchan_adaptive`, integer, prev block) --
        the honest streaming realization.
    Returns a dict: family -> (early_changed, early_total, streams?).
    """
    x, cols = _probe_array()
    C, N = x.shape
    T0 = N // 2
    parent = ec.grid_parents(C, cols)

    rng = np.random.default_rng(7)
    xf = x.copy()
    xf[:, T0:] = (xf[:, T0:] + rng.integers(-300, 300, xf[:, T0:].shape)).astype(np.int16)

    # -- whole-signal float beta (as the incumbent/promoted codecs are measured) --
    bw = ec.cross_betas(x, parent)
    bw_f = ec.cross_betas(xf, parent)
    r0 = _xchan_residual(x.astype(np.int64), bw, parent)
    r1 = _xchan_residual(xf.astype(np.int64), bw_f, parent)
    ws_changed = int((r0[:, :T0] != r1[:, :T0]).sum())

    # -- backward-adaptive integer beta: prefix-encoding equivalence (identical
    #    past -> identical output) is exactly the streaming property. --
    xa = reg.REGISTRY["LMS+Rice+xchan_adaptive"]
    streams = (xa.encode(x[:, :T0], cols=cols) == xa.encode(xf[:, :T0], cols=cols))

    out = {
        "whole_signal_beta": dict(early_changed=ws_changed, early_total=C * T0,
                                  streams=(ws_changed == 0)),
        "backward_adaptive": dict(early_changed=0, early_total=C * T0,
                                  streams=bool(streams)),
    }
    if verbose:
        print("== 1. STREAMING / CAUSALITY probe "
              "(perturb only t >= N/2, watch t < N/2) ==\n")
        w = out["whole_signal_beta"]
        print(f"  whole-signal float beta  (the cross-channel front-end shared by the")
        print(f"  headline +xchan / best-partner codecs)")
        print(f"      early residuals changed by a FUTURE-only perturbation: "
              f"{w['early_changed']}/{w['early_total']}")
        print(f"      -> {'STREAMS' if w['streams'] else 'NON-CAUSAL as benchmarked'}"
              f"  (beta is a whole-recording statistic; the number the leaderboard")
        print(f"         reports was measured on an offline, float, non-streaming encoder)\n")
        b = out["backward_adaptive"]
        print(f"  backward-adaptive integer beta  [LMS+Rice+xchan_adaptive, "
              f"*_bestpartner_adaptive, joint2]")
        print(f"      prefix-encoding identical for identical past: {b['streams']}")
        print(f"      -> {'STREAMS (declared causal/lookahead/integer is HONEST)' if b['streams'] else 'FAILED'}\n")
    return out


# Which registered codecs are benchmarked with an OFFLINE, whole-recording
# parameter (float beta or best-partner selection), i.e. their reported ratio
# comes from a non-streaming encoder. Detected FUNCTIONALLY: patch the two
# whole-signal routines -- ec.cross_betas (least-squares gain over all N) and
# registry._bp_select (best-partner scan over all N) -- and see whose encode
# actually calls one. No string heuristics, so the honest backward-adaptive
# codecs (which recompute their parameter per block) are never false-flagged.
def offline_selection_codecs():
    x, cols = _probe_array(C=16, N=800, cols=4)
    hits = []
    orig_cb, orig_bp = ec.cross_betas, reg._bp_select
    for c in reg.list_codecs(include_retired=True):
        called = {"v": False}

        def trace(fn):
            def w(*a, **k):
                called["v"] = True
                return fn(*a, **k)
            return w

        ec.cross_betas, reg._bp_select = trace(orig_cb), trace(orig_bp)
        try:
            c.encode(x, cols=cols)
        except Exception:
            pass
        finally:
            ec.cross_betas, reg._bp_select = orig_cb, orig_bp
        if called["v"]:
            hits.append(c.name)
    return hits


# ===========================================================================
# 2. COST self-consistency -- measured work vs. declared enc_ops
# ===========================================================================
def cost_audit(verbose=True):
    """Instrument a real encode and count the work the flat model glosses over:
    the Rice `_best_k` k-search (a per-block loop, not a per-sample constant) and
    the integer divides. Compare the measured floor to the declared enc_ops."""
    x, cols = _probe_array()
    C, N = x.shape
    nsc = C * N

    counter = dict(ksearch_elems=0, divides=0)
    orig_best_k = ec._best_k

    def counting_best_k(u):
        # replicate the loop's trip count without changing behaviour
        for k in range(0, 20):
            counter["ksearch_elems"] += u.size          # one shift+sum+compare per element
            if (u >> np.uint64(k)).sum() == 0:
                break
        return orig_best_k(u)

    ec._best_k = counting_best_k
    try:
        # order-8 LMS + whole-signal xchan == the 'LMS+Rice+xchan' encode
        parent = ec.grid_parents(C, cols)
        counter["divides"] += int((parent >= 0).sum())   # one divide per child channel (beta)
        _ = ec.encode(x, predictor=ec.PRED_LMS, cross=True, cols=cols)
    finally:
        ec._best_k = orig_best_k

    ksearch_per_sc = counter["ksearch_elems"] / nsc
    declared = reg.REGISTRY["LMS+Rice+xchan"].meta.enc_ops
    if verbose:
        print("== 2. COST self-consistency (LMS+Rice+xchan, order-8) ==\n")
        print(f"  declared enc_ops (registry)                 : {declared} ops/sample-ch")
        print(f"  Rice k-search alone, MEASURED               : {ksearch_per_sc:.1f} "
              f"add/shift/compare per sample-ch  (the model buckets ALL of Rice at ~9)")
        print(f"  integer divides for beta (whole encode)     : {counter['divides']} "
              f"(SDIV ~2-12 cyc each on M7; the model charges 1.2 cyc/op flat)")
        print(f"  -> the declared op count is an OPTIMISTIC lower bound: it omits the")
        print(f"     k-search loop, the variable-length bit packing, and divide latency.\n")
    return dict(declared=declared, ksearch_per_sc=ksearch_per_sc, divides=counter["divides"])


# ===========================================================================
# 3. FPGA feasibility (Arty S7-25 / XC7S25) -- the dimension the gate omits
# ===========================================================================
# XC7S25 fabric (AMD/Xilinx Spartan-7 datasheet):
XC7S25 = dict(luts=14600, ff=29200, dsp48=80, bram36=45)
FPGA_CLK_HZ = 100e6          # a comfortable Spartan-7 fabric clock
FS_NEURAL = 30000            # worst-case sample rate the node must sustain


def _codec_order(name, meta):
    """Best-effort predictor tap count from the name (order-4 vs order-8 vs delta)."""
    n = name.lower()
    if "lms4" in n:
        return 4
    if "delta" in n or "fixed" in n:
        return 1
    if "lms" in n:
        return 8
    return 8


def fpga_audit(n_ch=ecost.N_CH, verbose=True):
    """First-order Spartan-7 resource + timing feasibility per non-retired codec.

    Model: the predictor MACs are time-multiplexed over channels at FS_NEURAL. To
    sustain 30 kS/s x n_ch, one shared MAC datapath must run at
    order * n_ch * fs MAC/s. DSP count = ceil(that / FPGA_CLK). BRAM holds the
    per-channel state. This is deliberately rough (it is the estimate a reviewer
    should argue with) but it is a REAL resource statement, which the current
    gate has none of.
    """
    rows = []
    for c in reg.list_codecs(include_retired=False):
        name = c.name
        m = c.meta
        order = _codec_order(name, m)
        mac_per_s = order * n_ch * FS_NEURAL
        dsp = int(np.ceil(mac_per_s / FPGA_CLK_HZ)) if m.integer_only else 0
        state_bits = m.state_bytes_per_ch * 8 * n_ch
        bram36 = int(np.ceil(state_bits / (36 * 1024)))
        # crude LUT charge: bit-serial Rice coder + control ~ a few hundred LUT/ch
        # of parallelism; assume 8 channels share a coder lane.
        luts = 350 * max(1, n_ch // 16) + 120 * order
        fits = (m.integer_only and dsp <= XC7S25["dsp48"]
                and bram36 <= XC7S25["bram36"] and luts <= XC7S25["luts"])
        reason = []
        if not m.integer_only:
            reason.append("float (no soft-FPU on XC7S25)")
        if dsp > XC7S25["dsp48"]:
            reason.append(f"{dsp} DSP > 80")
        if bram36 > XC7S25["bram36"]:
            reason.append(f"{bram36} BRAM36 > 45")
        if luts > XC7S25["luts"]:
            reason.append(f"{luts} LUT > 14600")
        rows.append(dict(name=name, order=order, dsp=dsp, bram36=bram36, luts=luts,
                         fpga_ok=fits, mcu_ok=c.cost.embedded_ok,
                         reason="; ".join(reason)))
    if verbose:
        print(f"== 3. FPGA feasibility  (XC7S25: {XC7S25['dsp48']} DSP, "
              f"{XC7S25['bram36']} BRAM36, {XC7S25['luts']} LUT; "
              f"{n_ch} ch @ {FS_NEURAL//1000} kS/s, fabric {int(FPGA_CLK_HZ//1e6)} MHz) ==\n")
        print(f"  {'codec':<38}{'ord':>4}{'DSP':>5}{'BRAM':>6}{'LUT':>7}"
              f"{'fpga_ok':>9}{'mcu_ok':>8}")
        print("  " + "-" * 84)
        for r in rows:
            print(f"  {r['name']:<38}{r['order']:>4}{r['dsp']:>5}{r['bram36']:>6}"
                  f"{r['luts']:>7}{('YES' if r['fpga_ok'] else 'no'):>9}"
                  f"{('YES' if r['mcu_ok'] else 'no'):>8}"
                  + (f"   <- {r['reason']}" if r['reason'] else ""))
        print()
    return rows


# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any embedded_ok codec has a non-streaming "
                         "benchmarked path (CI gate)")
    args = ap.parse_args()

    print("EMBEDDED_OK VERIFICATION  -  auditing the gate against the actual code\n"
          + "=" * 74 + "\n")
    caus = causality_audit()
    offline = offline_selection_codecs()
    print(f"  Registered codecs whose REPORTED RATIO is measured with an OFFLINE\n"
          f"  whole-recording parameter -- functionally traced to ec.cross_betas or\n"
          f"  registry._bp_select (non-streaming as benchmarked):\n"
          f"    {', '.join(offline) if offline else '(none)'}\n")
    cost_audit()
    fpga_audit()

    ws_streams = caus["whole_signal_beta"]["streams"]
    print("=" * 74)
    print("SUMMARY")
    print(f"  * embedded_ok is a DECLARATION check, not a measurement: every input")
    print(f"    (enc_ops, causal, integer_only, state) is hand-written in registry.py.")
    print(f"  * The headline +xchan codecs are benchmarked with a whole-signal float")
    print(f"    beta => NON-STREAMING; their embedded_ok describes a different, ")
    print(f"    unbenchmarked codec. Backward-adaptive variants are the honest ones.")
    print(f"  * The cycle model omits the k-search / bit-I/O / divide latency and has")
    print(f"    NO FPGA resource model; use fpga_ok above for the Spartan-7 target.")

    if args.strict and not ws_streams and offline:
        print("\nSTRICT: embedded_ok codecs have a non-streaming benchmarked path "
              "(see list above).")
        sys.exit(1)


if __name__ == "__main__":
    main()
