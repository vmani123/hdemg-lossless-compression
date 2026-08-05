#!/usr/bin/env python3
"""
xchan_structure_probe.py -- WHERE does the learned model's cross-channel gain live?

015-017 showed a learned model only beats our linear codec on CapgMyo (the low-
linear-correlation differential array), by finding *nonlinear cross-channel*
structure a rank-1 linear best-partner subtract misses.  Before building a codec
primitive we ask, cheaply (numpy, no training loop, no neural net), the design
question that decides which primitive is worth building:

  Of the bits a neural model recovers over linear xchan, how many come from
    (A) a better PREDICTION mu  -- a nonlinear function of neighbours reduces the
        residual magnitude                     -> build a nonlinear predictor term
    (B) a better SCALE s        -- the residual's spread is heteroscedastic in
        neighbour energy (predictable variance) -> build a context-dependent
                                                   Rice-k from neighbour energy
        (the cheapest, most embeddable win)

Method = compression-is-prediction (the paper's core tool): measure each option by
the order-0 entropy (ideal memoryless code length, bits/sample) of the integer
residual it leaves.  Predictors are FIT on the first 70% of time and all entropies
measured on the held-out last 30% (so a nonlinear fit can't cheat).  Delta domain,
concurrent lower-index neighbour -- exactly the context the probes used.
"""
import argparse, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host_tools"))
import datasets as dsmod  # noqa: E402


def H(r):
    """Order-0 entropy (bits/sample) of an integer stream = ideal memoryless code."""
    r = np.rint(r).astype(np.int64)
    _, cnt = np.unique(r, return_counts=True)
    p = cnt / cnt.sum()
    return float(-(p * np.log2(p)).sum())


def deltas(x):
    d = np.zeros_like(x, dtype=np.float64)
    d[:, 1:] = np.diff(x.astype(np.float64), axis=1)
    return d


def fit_ls(X, y):
    """least squares y ~ X (no intercept); returns coefficients."""
    return np.linalg.lstsq(X, y, rcond=None)[0]


def probe(x, name, holdout=0.30, nbin=8):
    C, N = x.shape
    d = deltas(x)
    split = int(N * (1 - holdout))
    # concurrent causal partners: nearest lower-index neighbour (grid vertical) + one more
    # Build residual streams over ALL channels c>=2, pooled.
    tr = slice(1, split)          # train time range (skip t=0)
    te = slice(split, N)

    # --- gather pooled samples (channels 2..C-1 so p2=c-2 exists) ---
    def gather(rng):
        dc, dp, dp2 = [], [], []
        for c in range(2, C):
            dc.append(d[c, rng]); dp.append(d[c - 1, rng]); dp2.append(d[c - 2, rng])
        return (np.concatenate(dc), np.concatenate(dp), np.concatenate(dp2))
    dc_tr, dp_tr, dp2_tr = gather(tr)
    dc_te, dp2_te = None, None
    dc_te, dp_te, dp2_te = gather(te)

    out = {}
    out["H(delta) temporal-only"] = H(dc_te)

    # (P1) LINEAR xchan: d_c ~ b*d_p  (fit b on train, apply on test)
    b = fit_ls(dp_tr[:, None], dc_tr)[0]
    r1 = dc_te - b * dp_te
    out["+linear xchan (best-partner)"] = H(r1)

    # (P2A) NONLINEAR-MEAN: d_c ~ [d_p, |d_p|, d_p^2, sign(d_p), d_p2, |d_p2|]
    def feats(dp, dp2):
        return np.stack([dp, np.abs(dp), dp * dp, np.sign(dp), dp2, np.abs(dp2)], axis=1)
    coef = fit_ls(feats(dp_tr, dp2_tr), dc_tr)
    r2 = dc_te - feats(dp_te, dp2_te) @ coef
    out["+nonlinear-mean predictor (A)"] = H(r2)

    # (P2B) HETEROSCEDASTIC SCALE on the LINEAR residual r1: condition on |d_p|.
    # bits recoverable by a context-dependent scale = H(r1) - sum_bin w*H(r1|bin).
    energy = np.abs(dp_te)
    edges = np.quantile(energy, np.linspace(0, 1, nbin + 1)[1:-1])
    binid = np.digitize(energy, edges)
    hcond = 0.0
    for bindex in range(nbin):
        m = binid == bindex
        if m.sum() > 50:
            hcond += (m.mean()) * H(r1[m])
    out["+heteroscedastic scale on r1 (B)"] = hcond

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+",
                    default=["capgmyo_dba_s1", "hyser_1dof_f1_s1", "otb_hdsemg_vl", "cemhsey_s1_d1t1"])
    args = ap.parse_args()
    sets = {ds.name: ds for ds in dsmod.corpus()}
    print(f"{'dataset':<20}{'H(delta)':>10}{'+lin xchan':>12}{'+nl-mean(A)':>13}"
          f"{'+het-scale(B)':>14}   gains vs linear (bits/samp)")
    for name in args.datasets:
        x = np.ascontiguousarray(sets[name].load(max_samples=0)[0])
        r = probe(x, name)
        h_d = r["H(delta) temporal-only"]
        h_lin = r["+linear xchan (best-partner)"]
        h_nl = r["+nonlinear-mean predictor (A)"]
        h_het = r["+heteroscedastic scale on r1 (B)"]
        gA = h_lin - h_nl
        gB = h_lin - h_het
        glin = h_d - h_lin
        print(f"{name:<20}{h_d:>10.3f}{h_lin:>12.3f}{h_nl:>13.3f}{h_het:>14.3f}"
              f"   linxchan {glin:+.3f} | (A) {gA:+.3f} | (B) {gB:+.3f}")
    print("\n(A) = extra bits from a NONLINEAR neighbour predictor; "
          "(B) = extra bits from a neighbour-energy-driven SCALE (cheap integer Rice-k).")


if __name__ == "__main__":
    raise SystemExit(main())
