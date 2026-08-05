#!/usr/bin/env python3
"""
xscale_poc.py -- validate the ONE lever the structure probe found: a cross-channel
context-adaptive Rice scale ("xscale").  Measures REAL Golomb-Rice code lengths
(not entropy) with a causal, integer, decodable k-rule, so the number is what an
actual embeddable codec would bank -- not an oracle.

Design (all causal / decodable, so bit-exact-lossless by construction -- Rice is a
bijection given k, and k here depends only on already-decoded past + the concurrent
lower-index neighbour):

  residual   r[c,t] = d[c,t] - round(beta[c]*d[c-1,t])     (delta + integer linear
                                                            best-partner xchan)
  BASELINE   adaptive Rice: k from an EWMA of this channel's own |residual|
             (temporal-adaptive scale -- what our Rice back-end already does)
  XSCALE     same, but nudge k by the concurrent NEIGHBOUR's energy vs its own
             EWMA: neighbour hot  -> +1 (this channel likely hot too, co-activation)
                   neighbour cold -> -1
             (one compare + add per sample-channel; no multiply, fully integer)

If XSCALE's real Rice bits beat BASELINE -- especially on CapgMyo -- the primitive
is worth porting into registry.py as `...+xscale`.
"""
import argparse, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host_tools"))
import datasets as dsmod  # noqa: E402


def deltas(x):
    d = np.zeros_like(x, dtype=np.int64)
    d[:, 1:] = np.diff(x.astype(np.int64), axis=1)
    return d


def zigzag(r):
    return (np.abs(r) << 1) - (r > 0).astype(np.int64)   # 0,1,2,... bijection on Z


def rice_len(u, k):
    return (u >> k) + 1 + k                               # Golomb-Rice code length in bits


def run(x, beta_bits=5, a_shift=4, pool=4, lam=1.0):
    """Return (baseline_bpp, xscale_bpp) as real Rice bits/sample-channel.

    xscale here: pool the CONCURRENT energy of the `pool` nearest lower-index
    neighbours (co-activation), compare to its EWMA, and SMOOTHLY scale this
    channel's Rice scale by (coact_ratio ** lam) before choosing k -- the faithful
    volume-conduction version (a leading indicator of a concurrent spike the own
    EWMA lags on).  Floats here to test ACHIEVABILITY; an embeddable version would
    use a small fixed-point LUT.
    """
    C, N = x.shape
    d = deltas(x)
    beta = np.zeros(C)
    for c in range(1, C):
        denom = float(np.dot(d[c - 1], d[c - 1])) + 1e-9
        beta[c] = float(np.dot(d[c], d[c - 1])) / denom
    bq = np.round(beta * (1 << beta_bits)).astype(np.int64)
    r = d.copy()
    r[1:] = d[1:] - ((bq[1:, None] * d[:-1]) >> beta_bits)

    u = zigzag(r)
    e = np.abs(d).astype(np.float64)
    # pooled concurrent neighbour energy: mean |delta| over channels c-1..c-pool
    epool = np.zeros((C, N))
    cnt = np.zeros(C)
    for j in range(1, pool + 1):
        epool[j:] += e[:-j] if j < C else 0
        cnt[j:] += 1
    epool[1:] /= np.maximum(cnt[1:, None], 1)

    mu_u = np.maximum(u[:, :64].mean(1), 1.0)
    mu_p = np.maximum(epool[:, :64].mean(1), 1.0)
    base_bits, xs_bits = 0, 0
    inv = 1.0 / (1 << a_shift)
    for t in range(1, N):
        ut = u[:, t]
        kt = np.clip(np.floor(np.log2(mu_u + 1e-9)).astype(np.int64), 0, 20)
        base_bits += int(rice_len(ut, kt).sum())
        # smooth co-activation scale on TOP of the own-EWMA scale
        ratio = np.ones(C)
        ratio[1:] = np.clip((epool[1:, t] + 1.0) / (mu_p[1:] + 1.0), 0.25, 4.0) ** lam
        scale_x = mu_u * ratio
        kx = np.clip(np.floor(np.log2(scale_x + 1e-9)).astype(np.int64), 0, 20)
        xs_bits += int(rice_len(ut, kx).sum())
        mu_u = mu_u + (ut - mu_u) * inv
        mu_p = mu_p + (epool[:, t] - mu_p) * inv
    n = C * (N - 1)
    return base_bits / n, xs_bits / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+",
                    default=["capgmyo_dba_s1", "hyser_1dof_f1_s1", "otb_hdsemg_vl", "cemhsey_s1_d1t1"])
    ap.add_argument("--pool", type=int, default=4)
    ap.add_argument("--lam", type=float, default=1.0)
    args = ap.parse_args()
    sets = {ds.name: ds for ds in dsmod.corpus()}
    print(f"# pool={args.pool} lam={args.lam}")
    print(f"{'dataset':<20}{'baseline b/s':>13}{'xscale b/s':>12}{'gain':>9}{'ratio base->xs':>18}")
    for name in args.datasets:
        x = np.ascontiguousarray(sets[name].load(max_samples=0)[0])
        b, xs = run(x, pool=args.pool, lam=args.lam)
        g = 100 * (b - xs) / b
        print(f"{name:<20}{b:>13.3f}{xs:>12.3f}{g:>8.2f}%   {16/b:>7.3f}x -> {16/xs:>.3f}x")
    print("\nReal Golomb-Rice bits (bijective => lossless); k causal & integer. "
          "xscale = neighbour-energy-conditioned Rice-k on the linear-xchan residual.")


if __name__ == "__main__":
    raise SystemExit(main())
