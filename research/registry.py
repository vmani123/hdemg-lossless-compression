#!/usr/bin/env python3
"""
registry.py  -  Uniform codec registry for the lossless-compression search
(Stage 1 of COMPRESSION_RESEARCH_AGENT_PROMPT.md).

Every candidate the search ranks is registered here behind ONE interface:

    codec.encode(x, cols=16) -> bytes
    codec.decode(blob)       -> int16 [C, N]   (bit-exact inverse)
    codec.meta               -> embedded_cost.CodecMeta   (feasibility inputs)
    codec.cost               -> embedded_cost.CostScore   (embedded_ok + Pareto cost)

It **wraps** the existing, already-verified codecs in `host_tools/embedded_codec.py`
(delta+Rice, LMS+Rice, and the +xchan cross-channel front-end) -- it does NOT
re-implement them -- and **seeds** the first new candidate from
`compression_spec/candidates.md`: FLAC's four fixed polynomial predictors with
pick-best-per-block order selection, sharing embedded_codec's adaptive Golomb-Rice
back-end.

Run `python research/registry.py --selftest` to round-trip every registered codec
on random int16 and print ratio + cost. This is the command the PostToolUse
verifier hook runs, so a broken/lossy codec here blocks the loop.
"""
import argparse
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host_tools"))
import embedded_codec as ec  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
import embedded_cost as cost  # noqa: E402
from embedded_cost import CodecMeta  # noqa: E402


# ===========================================================================
# NEW seeded candidate: fixed polynomial predictors (orders 0-3) + Rice.
# ---------------------------------------------------------------------------
# FLAC's "fixed" subframe predictors are integer differences of order 0..3:
#     p=0: pred = 0                       (res = x)
#     p=1: pred = x[t-1]                  (1st difference)
#     p=2: pred = 2x[t-1] - x[t-2]        (2nd difference)
#     p=3: pred = 3x[t-1] - 3x[t-2] + x[t-3]   (3rd difference)
# res[t] = x[t] - pred. All integer-exact and causal (samples before t=0 are
# treated as 0, identically in encode and decode). We pick the best order PER
# BLOCK (same BLOCK as the Rice coder) by estimated coded length, and store one
# order byte per block as tiny side-info. The candidate residuals for every order
# depend only on x (not on which order neighbouring blocks chose), so selection
# is free to switch per block and the decoder can still invert sequentially.
# ===========================================================================
FIXED_MAGIC = 0x4658  # 'FX'
FBLOCK = ec.BLOCK      # reuse the Rice block size so order/k blocks align


def _fixed_residuals(xc):
    """All four fixed-predictor residual streams for a 1-D channel (int64)."""
    xc = xc.astype(np.int64)
    x1 = np.concatenate(([0], xc[:-1]))
    x2 = np.concatenate(([0, 0], xc[:-2]))
    x3 = np.concatenate(([0, 0, 0], xc[:-3]))
    r = np.empty((4, xc.size), np.int64)
    r[0] = xc
    r[1] = xc - x1
    r[2] = xc - (2 * x1 - x2)
    r[3] = xc - (3 * x1 - 3 * x2 + x3)
    return r


def _block_bits(res_block):
    """Estimated Rice-coded length (bits) of a residual block, at its best k."""
    u = ec.zigzag(res_block)
    k = ec._best_k(u)
    return int((u >> np.uint64(k)).sum()) + res_block.size * (1 + k)


def _fixed_choose(xc):
    """Return (chosen residual 1-D, per-block order uint8) for one channel."""
    r = _fixed_residuals(xc)
    n = xc.size
    nblocks = (n + FBLOCK - 1) // FBLOCK
    orders = np.zeros(nblocks, np.uint8)
    chosen = np.empty(n, np.int64)
    for b in range(nblocks):
        s, e = b * FBLOCK, min((b + 1) * FBLOCK, n)
        costs = [_block_bits(r[p, s:e]) for p in range(4)]
        p = int(np.argmin(costs))
        orders[b] = p
        chosen[s:e] = r[p, s:e]
    return chosen, orders


def _diff_at(hist, j):
    """D^j x evaluated at the sample just before a block, from the last
    reconstructed samples hist = [x[t-1], x[t-2], x[t-3]] (0 for indices < 0)."""
    if j == 0:
        return hist[0]
    if j == 1:
        return hist[0] - hist[1]
    return hist[0] - 2 * hist[1] + hist[2]  # j == 2


def _fixed_reconstruct(res, orders, n):
    """Invert _fixed_choose for one channel: res (1-D) + per-block orders -> x."""
    x = np.empty(n, np.int64)
    for b in range(len(orders)):
        s, e = b * FBLOCK, min((b + 1) * FBLOCK, n)
        p = int(orders[b])
        hist = [x[s - 1] if s - 1 >= 0 else 0,
                x[s - 2] if s - 2 >= 0 else 0,
                x[s - 3] if s - 3 >= 0 else 0]
        a = res[s:e].astype(np.int64)
        # res is the p-th finite difference of x; integrate p times, each level
        # seeded by that difference's value at the block boundary.
        for j in range(p - 1, -1, -1):
            a = _diff_at(hist, j) + np.cumsum(a)
        x[s:e] = a
    return x


def fixed_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    body = []
    for c in range(C):
        chosen, orders = _fixed_choose(x[c])
        nblocks = orders.size
        body.append(struct.pack("<I", nblocks) + orders.tobytes()
                    + ec.rice_encode_1d(chosen))
    hdr = struct.pack("<HII", FIXED_MAGIC, C, N)
    return hdr + b"".join(body)


def fixed_decode(buf):
    magic, C, N = struct.unpack_from("<HII", buf, 0)
    assert magic == FIXED_MAGIC, "bad fixed-codec magic"
    off = 10
    out = np.empty((C, N), np.int64)
    for c in range(C):
        (nblocks,) = struct.unpack_from("<I", buf, off); off += 4
        orders = np.frombuffer(buf, np.uint8, nblocks, off); off += nblocks
        res, off = ec.rice_decode_1d(buf, off)
        out[c] = _fixed_reconstruct(res, orders, N)
    return out.astype(np.int16)


# ===========================================================================
# NEW candidate: backward-adaptive per-block cross-channel beta.
# ---------------------------------------------------------------------------
# The existing +xchan front-end (embedded_codec.cross_betas/forward/inverse)
# derives ONE gain `beta` per channel over the WHOLE recording (a float
# least-squares ratio) and ships it as header side-info -- i.e. it needs the
# whole signal offline to pick beta. This variant makes the gain (i) track
# non-stationarity and (ii) removes the look-ahead AND the side-info:
#
#   * beta for block i is (re)estimated from the PREVIOUS block's ALREADY-
#     reconstructed samples of the channel and its grid parent, using
#     integer-only fixed-point arithmetic (two dot-products + one rounded
#     integer divide per block-channel). Because the reconstruction is lossless,
#     the parent/child samples the decoder has after block i-1 are bit-identical
#     to the encoder's, so the decoder recomputes the SAME beta causally and NO
#     beta is transmitted.
#   * Block 0 bootstraps with beta = 0 (no prior block exists yet), so the first
#     block is coded as if xchan were off; the gain then adapts each block.
#
# Everything downstream (grid parent tree, order-8 sign-sign LMS, adaptive
# Golomb-Rice) is identical to the current best codec "LMS+Rice+xchan"; only the
# gain-estimation is swapped from whole-signal side-info to backward-adaptive.
# ===========================================================================
XADAPT_MAGIC = 0x5841        # 'XA'
XADAPT_BLOCK = ec.BLOCK      # cross-channel adaptation block (samples); tunable
XADAPT_SHIFT = ec.CROSS_SHIFT  # fixed-point scale for beta (matches the family)


def _int_beta(num, den, shift=XADAPT_SHIFT):
    """Integer-only fixed-point gain ~= round(num/den * 2**shift) for den > 0,
    clamped to int16. No float anywhere; deterministic and therefore identical
    on encode and decode. `den` is a sum of squares so it is always >= 0."""
    d = int(den)
    if d <= 0:
        return 0
    numer = int(num) << shift
    if numer >= 0:
        b = (numer + d // 2) // d          # symmetric round-half-up
    else:
        b = -(((-numer) + d // 2) // d)
    if b > 32767:
        return 32767
    if b < -32768:
        return -32768
    return b


def _beta_from_block(xc_blk, xp_blk, shift=XADAPT_SHIFT):
    """Backward-adaptive gain from ONE already-reconstructed block: the
    least-squares ratio <x_c, x_p> / <x_p, x_p>, integer/fixed-point. Identical
    call on both sides guarantees the same beta bit-for-bit."""
    xc = xc_blk.astype(np.int64)
    xp = xp_blk.astype(np.int64)
    num = int((xc * xp).sum())
    den = int((xp * xp).sum())
    return _int_beta(num, den, shift)


def _xadapt_forward(x, parent, B=XADAPT_BLOCK, shift=XADAPT_SHIFT):
    """Cross-channel decorrelation with backward-adaptive per-block gain.
    y[c,t] = x[c,t] - ((beta[c,block(t)] * x[parent,t]) >> shift), beta derived
    from the previous block. Operates on the RAW signal, which the decoder
    reconstructs bit-exactly, so the betas match."""
    x = x.astype(np.int64)
    C, N = x.shape
    y = x.copy()
    nblocks = (N + B - 1) // B
    for c in range(C):
        p = parent[c]
        if p < 0:                          # root channel: no parent to subtract
            continue
        beta = 0                           # block-0 bootstrap
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i > 0:
                beta = _beta_from_block(x[c, (i - 1) * B:i * B],
                                        x[p, (i - 1) * B:i * B], shift)
            y[c, s:e] = x[c, s:e] - ((beta * x[p, s:e]) >> shift)
    return y


def _xadapt_inverse(y, parent, B=XADAPT_BLOCK, shift=XADAPT_SHIFT):
    """Invert _xadapt_forward. parent[c] < c so the parent channel is fully
    reconstructed before c; within a channel, block i's beta is recomputed from
    the already-reconstructed block i-1 -- exactly mirroring the encoder."""
    y = y.astype(np.int64)
    C, N = y.shape
    x = y.copy()                           # root channels already correct
    nblocks = (N + B - 1) // B
    for c in range(C):
        p = parent[c]
        if p < 0:
            continue
        beta = 0
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i > 0:
                beta = _beta_from_block(x[c, (i - 1) * B:i * B],
                                        x[p, (i - 1) * B:i * B], shift)
            x[c, s:e] = y[c, s:e] + ((beta * x[p, s:e]) >> shift)
    return x


def xadapt_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    parent = ec.grid_parents(C, cols)
    y = _xadapt_forward(x, parent)
    res = ec.lms_forward(y)                # order-8 sign-sign LMS (same as family)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", XADAPT_MAGIC, cols, C, N)  # NO beta side-info
    return hdr + body


def xadapt_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XADAPT_MAGIC, "bad xadapt magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res)
    x = _xadapt_inverse(y, ec.grid_parents(C, cols))
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: best-partner cross-channel selection + LMS + Rice.
# ---------------------------------------------------------------------------
# The incumbent +xchan front-end subtracts a SINGLE fixed grid parent (left, or
# up for the first column) with an optimal integer gain. On a near-isotropic
# electrode grid the fixed parent is demonstrably not always the best-correlated
# neighbour (LEADERBOARD flags this), so here we let each channel CHOOSE its
# partner from a bounded set of causally-available neighbours -- all with grid
# index < g, so the decoder can reconstruct in channel order:
#     left   = g-1        (col > 0)
#     up     = g-cols     (row > 0)
#     up-left= g-cols-1   (row > 0 and col > 0)
#     up-right=g-cols+1   (row > 0 and col < cols-1)
# For each candidate we derive the optimal integer gain beta (rounded integer
# least-squares, no float in the transform) and estimate the Rice-coded length of
# the resulting cross-residual; we keep the partner (or NONE) with the fewest
# estimated bits. The chosen (parent, beta) pair per channel is tiny explicit
# side-info (two int16 / channel) carried in the format, so encoder and decoder
# use identical, causally-available data. Everything downstream (LMS temporal
# predictor + adaptive Rice) is reused verbatim from embedded_codec.
# ===========================================================================
BP_MAGIC = 0x5042   # 'BP'
BP_SHIFT = ec.CROSS_SHIFT   # same fixed-point gain scale as the incumbent xchan


def _bp_candidates(g, cols, C):
    """Causally-available grid neighbours of channel g (all index < g)."""
    r, c = divmod(g, cols)
    cands = []
    if c > 0:
        cands.append(g - 1)               # left
    if r > 0:
        cands.append(g - cols)            # up
    if r > 0 and c > 0:
        cands.append(g - cols - 1)        # up-left
    if r > 0 and c < cols - 1:
        cands.append(g - cols + 1)        # up-right
    return cands


def _bp_opt_beta(xg, xp, shift):
    """Rounded integer least-squares gain beta ~ <xg,xp>/<xp,xp> * (1<<shift).
    Integer-only (rounded division), clamped to int16 side-info range."""
    denom = int((xp * xp).sum())
    if denom <= 0:
        return 0
    num = int((xg * xp).sum()) << shift
    if num >= 0:
        b = (num + denom // 2) // denom
    else:
        b = -(((-num) + denom // 2) // denom)
    return max(-32768, min(32767, b))


def _bp_score(res1d):
    """Estimated Rice-coded length (bits) of a residual channel at its best k."""
    u = ec.zigzag(np.asarray(res1d, np.int64))
    k = ec._best_k(u)
    return int((u >> np.uint64(k)).sum()) + int(u.size) * (1 + k)


def _bp_select(x, cols):
    """Per-channel best-partner selection. Returns (xt, parents, betas) where
    xt[g] is the cross-decorrelated channel and parents/betas are int64 side-info
    (parent = -1 means the channel is coded as-is)."""
    C, N = x.shape
    x = x.astype(np.int64)
    parents = np.full(C, -1, np.int64)
    betas = np.zeros(C, np.int64)
    xt = x.copy()
    for g in range(C):
        best_bits = _bp_score(x[g])       # option: no cross-channel subtract
        best_p, best_b, best_y = -1, 0, x[g]
        for p in _bp_candidates(g, cols, C):
            b = _bp_opt_beta(x[g], x[p], BP_SHIFT)
            if b == 0:
                continue
            y = x[g] - ((b * x[p]) >> BP_SHIFT)
            bits = _bp_score(y)
            if bits < best_bits:
                best_bits, best_p, best_b, best_y = bits, p, b, y
        parents[g] = best_p
        betas[g] = best_b
        xt[g] = best_y
    return xt, parents, betas


def _bp_inverse(xt, parents, betas):
    """Invert the best-partner front-end. parents[g] < g so the parent channel is
    already reconstructed when we reach g."""
    C, N = xt.shape
    x = xt.astype(np.int64).copy()
    for g in range(C):
        p = int(parents[g])
        if p >= 0:
            x[g] = xt[g] + ((int(betas[g]) * x[p]) >> BP_SHIFT)
    return x


def bestpartner_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)
    res = ec.lms_forward(xt)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", BP_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def bestpartner_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == BP_MAGIC, "bad best-partner codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = ec.lms_inverse(res)
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: fixed reversible integer inter-channel transform (integer-KLT
# via lifting) + per-channel LMS + Rice.
# ---------------------------------------------------------------------------
# Every shipped front-end so far subtracts exactly ONE reference channel (the
# grid parent in +xchan; a selected best partner in +xchan_bestpartner) -- a
# rank-1, single-tap operation. On a near-isotropic HD-EMG grid (neighbour
# correlations ~0.73-0.79) several partners carry shared content one subtraction
# cannot remove. This front-end is the untried MULTI-TAP spatial lever: a fixed,
# offline/data-independent, MULTIPLIERLESS reversible INTEGER transform that
# decorrelates each time-slice across the electrode array, applied BEFORE the
# existing per-channel LMS+Rice temporal back-end.
#
# Reversible integer KLT via lifting (Hao & Shi; Srinivasan et al. IntSKLT):
# any orthogonal transform factors into Givens rotations, and each rotation is
# realised losslessly by THREE integer "lifting" (shear) steps with rounded
# fixed-point coefficients -- reversible by construction (each step adds a
# rounded integer function of the current integer state; the inverse subtracts
# the identical value). No eigendecomposition, no per-block basis, NO side-info.
#
# Data-independent FIXED basis: for two equal-variance channels with covariance
# [[1, r],[r, 1]], the KLT is EXACTLY the +/-45 degree rotation (sum/difference)
# for ANY correlation r -- so a fixed 45-degree rotation is the true KLT of a
# stationary isotropic neighbour pair, needing no training data. We cascade
# these fixed rotations over a fixed grid-neighbour schedule (all horizontal
# adjacent pairs, then all vertical adjacent pairs, in channel order). The
# cascade makes each transformed channel a reversible integer mixture across a
# whole neighbourhood -- genuinely multi-tap, distinct from the rank-1 subtracts.
#
# The transform is applied WITHIN each time-slice (columns are independent), so
# temporal look-ahead is ZERO -- better than the +xchan variants, which need a
# block to estimate beta. The decoder applies the inverse rotations in reverse
# schedule order. Coefficients are global constants (no per-channel state).
# ===========================================================================
IKLT_MAGIC = 0x4B54          # 'KT' (integer-KLT)
IKLT_SHIFT = 12              # fixed-point scale for the lifting coefficients
# 45-degree rotation lifting coefficients (Hao-Shi 3-step factorization):
#   shear P = (cos t - 1)/sin t,  update U = sin t,  at t = 45 deg.
IKLT_P = int(round((0.7071067811865476 - 1.0) / 0.7071067811865476 * (1 << IKLT_SHIFT)))  # -1697
IKLT_U = int(round(0.7071067811865476 * (1 << IKLT_SHIFT)))                                # 2896


def _rmul(coef, v, shift=IKLT_SHIFT):
    """Rounded fixed-point product round(coef * v / 2**shift), integer-only and
    symmetric about zero, vectorized over an int64 array v. Identical on encode
    and decode (same function, same operands) -> the lifting steps cancel
    exactly. `>>` on a non-negative int64 is a floor; we negate for v*coef < 0 so
    rounding is symmetric rather than toward -inf."""
    p = coef * v.astype(np.int64)
    half = np.int64(1 << (shift - 1))
    pos = (p + half) >> np.int64(shift)
    neg = -(((-p) + half) >> np.int64(shift))
    return np.where(p >= 0, pos, neg)


def _rot_forward(a, b, P=IKLT_P, U=IKLT_U, shift=IKLT_SHIFT):
    """One reversible integer Givens rotation of two channel rows (each 1-D over
    time), as three lifting steps. In-place-safe: returns new arrays."""
    a = a + _rmul(P, b, shift)
    b = b + _rmul(U, a, shift)
    a = a + _rmul(P, b, shift)
    return a, b


def _rot_inverse(a, b, P=IKLT_P, U=IKLT_U, shift=IKLT_SHIFT):
    """Exact inverse of _rot_forward: undo the three lifting steps in reverse."""
    a = a - _rmul(P, b, shift)
    b = b - _rmul(U, a, shift)
    a = a - _rmul(P, b, shift)
    return a, b


def _iklt_pairs(C, cols):
    """Fixed grid-neighbour rotation schedule: all horizontal adjacent pairs in
    channel order, then all vertical adjacent pairs. Deterministic from (C, cols)
    so encode and decode build the identical list."""
    pairs = []
    for g in range(C):
        r, c = divmod(g, cols)
        if c > 0:
            pairs.append((g - 1, g))       # horizontal neighbour pair
    for g in range(C):
        r, c = divmod(g, cols)
        if r > 0:
            pairs.append((g - cols, g))    # vertical neighbour pair
    return pairs


def _iklt_forward(x, cols):
    """Apply the fixed reversible integer inter-channel transform per time-slice
    (vectorized over time). Returns the transformed [C, N] int64 array."""
    C = x.shape[0]
    y = x.astype(np.int64).copy()
    for a, b in _iklt_pairs(C, cols):
        y[a], y[b] = _rot_forward(y[a], y[b])
    return y


def _iklt_inverse(y, cols):
    """Invert _iklt_forward by applying the inverse rotations in REVERSE order."""
    C = y.shape[0]
    x = y.astype(np.int64).copy()
    for a, b in reversed(_iklt_pairs(C, cols)):
        x[a], x[b] = _rot_inverse(x[a], x[b])
    return x


def iklt_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _iklt_forward(x, cols)
    res = ec.lms_forward(y)                 # order-8 sign-sign LMS (same as family)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", IKLT_MAGIC, cols, C, N)   # NO transform side-info
    return hdr + body


def iklt_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == IKLT_MAGIC, "bad integer-KLT codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res)
    x = _iklt_inverse(y, cols)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: DATA-DEPENDENT adaptive integer-lifting rotation cascade
# (backward-adaptive Givens angle) + per-channel LMS + Rice.
# ---------------------------------------------------------------------------
# This is the retired fixed integer-KLT (`LMS+Rice+iklt`) with its ONE fatal
# assumption removed. The retired variant rotated every grid-neighbour pair by a
# FIXED 45 degrees -- the exact KLT only of a *stationary, isotropic,
# equal-variance* pair. INSIGHTS P3 MEASURED that this fixed basis captured only
# ~+8.8% real cross-channel gain vs the data-dependent single-neighbour subtract's
# +18.0%, because real HD-sEMG covariance is anisotropic and non-stationary: the
# whole gap is basis mismatch. Here the rotation ANGLE becomes data-dependent and
# backward-adaptive, closing that gap while staying multiplierless and lossless.
#
# Mechanism (keeps the reversible 3-lift shear butterfly of the iklt verbatim --
# multiplierless, lossless by construction for ANY integer lift coefficients):
#   * Per grid-neighbour pair (a,b) and per time-block i, choose a QUANTIZED
#     Givens angle theta from the pair's 2x2 covariance [[saa,sab],[sab,sbb]]
#     accumulated over the PREVIOUS block (i-1) of the already-reconstructed RAW
#     channels. The chosen angle is the tabulated theta that minimizes the
#     post-rotation off-diagonal |s'_ab| = |0.5(sbb-saa)sin2t + sab cos2t| -- i.e.
#     the discrete argmin of the true 2x2 decorrelating rotation, evaluated with
#     an integer sin/cos table (no atan, no float, no eigendecomposition).
#   * theta[block i] depends only on RAW block i-1, which the decoder reconstructs
#     bit-exactly before it reaches block i (it inverts the cascade block-by-block
#     in time order), so the decoder recomputes the SAME angle -> ZERO side-info,
#     fully causal, look-ahead 0 (backward-adaptive, INSIGHTS P4). Block 0
#     bootstraps to the identity angle (theta=0), so it is coded as if the spatial
#     transform were off; the basis then adapts each block.
#   * The angles are applied as a CASCADE over the fixed grid-neighbour schedule
#     (all horizontal adjacent pairs, then all vertical) -- reusing _iklt_pairs --
#     so each transformed channel becomes a reversible integer mixture across a
#     whole neighbourhood: genuinely MULTI-TAP, distinct from the rank-1
#     single-neighbour subtract of +xchan/xadapt/bestpartner.
#
# Distinct from BOTH retired mechanisms on the axis INSIGHTS P3 names decisive:
#   - vs `LMS+Rice+iklt` (retired): data-INDEPENDENT fixed 45deg basis -> here
#     data-DEPENDENT per-pair/per-block angle (the exact lever P3 says is decisive).
#   - vs `LMS+Rice+xchan_adaptive` (retired): an asymmetric rank-1 subtract of ONE
#     channel with a scalar beta -> here an energy-preserving ORTHOGONAL rotation of
#     BOTH channels, cascaded to a multi-tap transform.
# Behind it: the identical order-8 sign-sign LMS + adaptive Rice back-end as the
# whole family (unchanged, so the ONLY variable vs the retired iklt is the basis).
#
# Bases: Srinivasan et al. IntSKLT (reversible-integer KLT via ladder/lifting,
# IEEE 7071329); RGate (lifted-Givens integer-reversible transform + backward-
# adaptive Golomb-Rice, 221578983); reversible integer TDLT/KLT cross-channel
# decorrelation (IEEE 5075592). Paper-reported context; unverified here.
# ===========================================================================
ITSKLT_MAGIC = 0x4954         # 'IT'  (Integer adaptive Transform)
ITSKLT_SHIFT = IKLT_SHIFT     # lift-coefficient fixed point (as the retired iklt)
ITSKLT_TRIG_SHIFT = 14        # sin/cos fixed point used only for angle SELECTION
ITSKLT_BLOCK = ec.BLOCK       # backward-adaptation block (aligns with Rice block)


def _itsklt_build_table():
    """Build the quantized-angle lifting/selection tables. Float is used HERE, at
    import, to precompute integer constants only (exactly like IKLT_P/IKLT_U
    above) -- the encode/decode PATH that follows uses these integer tables and no
    float. Returns per-angle lift coeffs (P,U at ITSKLT_SHIFT) and selection
    trig (sin2t,cos2t at ITSKLT_TRIG_SHIFT), plus the identity-angle index."""
    degs = np.arange(-60, 61, 4)              # 31 angles incl. 0 (identity)
    P = np.empty(degs.size, np.int64)
    U = np.empty(degs.size, np.int64)
    SIN2 = np.empty(degs.size, np.int64)
    COS2 = np.empty(degs.size, np.int64)
    for j, d in enumerate(degs):
        t = float(np.deg2rad(float(d)))
        s, c = float(np.sin(t)), float(np.cos(t))
        # 3-step lifting factorization of R(theta): P = (cos t - 1)/sin t =
        # -tan(t/2), U = sin t (Hao-Shi / IntSKLT). theta=45deg reproduces IKLT.
        P[j] = 0 if abs(s) < 1e-12 else int(round((c - 1.0) / s * (1 << ITSKLT_SHIFT)))
        U[j] = int(round(s * (1 << ITSKLT_SHIFT)))
        SIN2[j] = int(round(float(np.sin(2.0 * t)) * (1 << ITSKLT_TRIG_SHIFT)))
        COS2[j] = int(round(float(np.cos(2.0 * t)) * (1 << ITSKLT_TRIG_SHIFT)))
    zero_idx = int(np.flatnonzero(degs == 0)[0])
    return P, U, SIN2, COS2, zero_idx


_ITSKLT_P, _ITSKLT_U, _ITSKLT_SIN2, _ITSKLT_COS2, _ITSKLT_ZERO = _itsklt_build_table()


def _itsklt_angle(saa, sbb, sab):
    """Integer-only backward angle selection for the 2x2 covariance
    [[saa,sab],[sab,sbb]]: return the index of the tabulated Givens angle that
    minimizes the post-rotation off-diagonal covariance. Since
    s'_ab = 0.5(sbb-saa)sin2t + sab cos2t, we minimize |(sbb-saa)sin2t + 2 sab
    cos2t| (a common positive scale 2 dropped). All operands are integers, so the
    argmin is deterministic and identical on encode and decode. (saa,sbb,sab are
    sums over <=256 int16 products -> |.| < 3e11; times the <=2^14 trig entries and
    a factor 2 stays < 1e16, comfortably inside int64.)"""
    f = (int(sbb) - int(saa)) * _ITSKLT_SIN2 + (2 * int(sab)) * _ITSKLT_COS2
    return int(np.argmin(np.abs(f)))


def _itsklt_block_angles(xprev, pairs):
    """Angle index for every schedule pair from the previous RAW block xprev
    ([C, B] int64). Covariance per pair is over the ORIGINAL channels (not the
    partially-rotated state), so the decoder -- which reconstructs the raw
    previous block exactly -- derives identical angles."""
    idx = {}
    for (a, b) in pairs:
        xa = xprev[a]
        xb = xprev[b]
        saa = int((xa * xa).sum())
        sbb = int((xb * xb).sum())
        sab = int((xa * xb).sum())
        idx[(a, b)] = _itsklt_angle(saa, sbb, sab)
    return idx


def _itsklt_forward(x, cols, B=ITSKLT_BLOCK):
    """Apply the backward-adaptive integer rotation cascade, per time-block.
    Angles for block i come from RAW block i-1 (block 0 -> identity). Returns the
    transformed [C, N] int64 array."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    pairs = _iklt_pairs(C, cols)
    nblocks = (N + B - 1) // B
    for i in range(nblocks):
        s, e = i * B, min((i + 1) * B, N)
        if i == 0:
            idx = {pr: _ITSKLT_ZERO for pr in pairs}          # identity bootstrap
        else:
            idx = _itsklt_block_angles(x[:, (i - 1) * B:i * B], pairs)
        for (a, b) in pairs:
            j = idx[(a, b)]
            y[a, s:e], y[b, s:e] = _rot_forward(
                y[a, s:e], y[b, s:e], _ITSKLT_P[j], _ITSKLT_U[j], ITSKLT_SHIFT)
    return y


def _itsklt_inverse(y, cols, B=ITSKLT_BLOCK):
    """Invert _itsklt_forward. We rebuild the RAW signal block-by-block in time
    order; before block i is inverted, block i-1's raw samples are already in x, so
    the same per-pair angles are recomputed and the cascade is undone in REVERSE
    pair order."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    pairs = _iklt_pairs(C, cols)
    nblocks = (N + B - 1) // B
    for i in range(nblocks):
        s, e = i * B, min((i + 1) * B, N)
        if i == 0:
            idx = {pr: _ITSKLT_ZERO for pr in pairs}
        else:
            idx = _itsklt_block_angles(x[:, (i - 1) * B:i * B], pairs)
        for (a, b) in reversed(pairs):
            j = idx[(a, b)]
            x[a, s:e], x[b, s:e] = _rot_inverse(
                x[a, s:e], x[b, s:e], _ITSKLT_P[j], _ITSKLT_U[j], ITSKLT_SHIFT)
    return x


def itsklt_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _itsklt_forward(x, cols)
    res = ec.lms_forward(y)                  # order-8 sign-sign LMS (same as family)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", ITSKLT_MAGIC, cols, C, N)  # NO transform side-info
    return hdr + body


def itsklt_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == ITSKLT_MAGIC, "bad adaptive integer-KLT codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res)
    x = _itsklt_inverse(y, cols)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: table-driven tANS residual entropy back-end vs Rice, on the
# IDENTICAL LMS+Rice+xchan predictor and cross-channel front-end.
# ---------------------------------------------------------------------------
# Every cycle so far moved only the cross-channel FRONT-END; the entropy
# BACK-END (adaptive Golomb-Rice) is the one axis never touched (INSIGHTS P5,
# open-frontier #1). Rice/Golomb is the optimal prefix code ONLY for an exactly
# geometric residual; real EMG residual blocks deviate sub-Golomb, so a
# table-driven ANS coder can recover the sub-Golomb fraction and approach the
# true block entropy. This candidate keeps the incumbent's front-end verbatim
# (grid-parent cross-channel decorrelation with the same fixed-point beta, then
# the order-8 sign-sign LMS temporal predictor) and swaps ONLY the per-channel
# Rice coder for a table-driven tANS (LOCO-ANS style) -- a clean head-to-head
# that isolates the back-end's marginal bits on the identical predictor.
#
# tANS realization (FPGA-friendly: table lookups + renorm, NO per-symbol divide
# on the runtime path; the divisions live only in the once-per-block table
# build). The residual coder is a LOCO-ANS-style bucket+remainder split:
#   * zigzag the residual to u >= 0, split into a "category" c = bit-length(u)
#     (the exponent/bucket, a small bounded alphabet) and c-1 raw "mantissa"
#     bits (the low bits of u). Only the category is entropy-coded; the mantissa
#     bits are near-uniform and shipped raw -- exactly the LOCO-ANS structure
#     that keeps the ANS alphabet small and bounded for ANY int16 input.
#   * Per bounded block (ANS_BLOCK samples) a STATIC normalized frequency table
#     over the categories is built (counts -> integer-normalized to sum = 2^R),
#     shipped as tiny side-info, and used to build the tANS encode/decode
#     tables. The table is deterministic and integer, so encoder and decoder
#     build bit-identical tables from the shipped freqs.
#   * tANS state is normalized to [2^R, 2^(R+1)); the tables are derived from
#     the bitwise-rANS transition C(x,s) = (x//f_s)*M + cum_s + (x mod f_s) but
#     PRECOMPUTED per state (symbol, #renorm-bits, base) so the runtime coder is
#     pure table lookups + a variable-length bit renorm -- the tANS/LOCO-ANS
#     property (no per-symbol division at encode/decode time).
#   * The encoder runs the ANS pass in REVERSE over the block (the reverse-order
#     encode buffer LOCO-ANS/tANS require) and the decoder reads the bitstream
#     forward; ordering is reconciled by reversing the emitted bit list once.
# Embeddability is borderline BY DESIGN (P5): the per-block frequency table is
# real side-info and the reverse pass needs a block buffer, so the payoff is
# expected small and uncertain -- a refinement to MEASURE on real data, not a
# headline lever. Bounded look-ahead = one ANS_BLOCK (streaming-legal).
# ===========================================================================
ANS_MAGIC = 0x414E           # 'AN'
ANS_R = 10                   # tANS table log; table size M = 2**R = 1024
ANS_BLOCK = 2048             # static-frequency-table block (samples); bounded look-ahead


def _ans_bitlen(u):
    """Integer bit-length of each element of a uint64 array (0 -> 0). Pure
    integer (no float log), identical on encode and decode."""
    u = u.astype(np.uint64)
    c = np.zeros(u.size, np.int64)
    tmp = u.copy()
    while tmp.any():
        c += (tmp > 0).astype(np.int64)
        tmp = tmp >> np.uint64(1)
    return c


def _ans_normalize(counts, R):
    """Integer-normalize category counts to a frequency table summing to 2**R,
    with every used symbol getting freq >= 1 (so it stays encodable) and unused
    symbols freq 0. Runs ONLY in the encoder; the decoder reads the resulting
    freqs verbatim, so no cross-side determinism issue -- the shipped table is
    the single source of truth for both sides' identical table build."""
    M = 1 << R
    counts = np.asarray(counts, np.int64)
    total = int(counts.sum())
    freq = np.zeros(counts.size, np.int64)
    for s in np.flatnonzero(counts > 0):
        f = (int(counts[s]) * M) // total
        freq[s] = f if f > 0 else 1
    diff = M - int(freq.sum())               # small: |diff| <= #used symbols
    while diff > 0:                           # give surplus to the commonest symbol
        freq[int(np.argmax(counts))] += 1
        diff -= 1
    while diff < 0:                           # reclaim from a symbol with slack (freq>1)
        freq[int(np.argmax(np.where(freq > 1, freq, -1)))] -= 1
        diff += 1
    return freq


def _ans_build(freq, R, build_enc=True):
    """Build the tANS tables from a frequency table (sum = 2**R). Returns per-
    state decode tables (symbol `symt`, renorm-bit-count `nb`, renorm `base`,
    each length M) and, for the encoder, `enc_slot[s]` mapping the current state
    (x-M) to the destination slot. Derived from the bitwise-rANS transition but
    precomputed so the runtime coder never divides. Deterministic + integer:
    encode and decode build bit-identical tables from the same freqs."""
    M = 1 << R
    A = len(freq)
    cum = np.zeros(A + 1, np.int64)
    for s in range(A):
        cum[s + 1] = cum[s] + int(freq[s])
    symt = np.empty(M, np.int64)
    for s in range(A):
        if freq[s] > 0:
            symt[cum[s]:cum[s + 1]] = s          # cumulative (range-ANS) layout
    nb = np.empty(M, np.int64)
    base = np.empty(M, np.int64)
    for t in range(M):
        s = int(symt[t])
        x_pre = int(freq[s]) + (t - int(cum[s]))  # rANS C^{-1} state, in [f_s, 2 f_s)
        b = R - (x_pre.bit_length() - 1)          # renorm bits to lift into [M, 2M)
        nb[t] = b
        base[t] = x_pre << b                      # renorm base, in [M, 2M)
    enc_slot = None
    if build_enc:
        enc_slot = {s: np.empty(M, np.int64) for s in range(A) if freq[s] > 0}
        for t in range(M):
            s = int(symt[t])
            lo = int(base[t]) - M
            enc_slot[s][lo:lo + (1 << int(nb[t]))] = t
    return symt, nb, base, enc_slot


def _ans_encode_cats(cats, freq):
    """Reverse-order tANS encode of a category block. Returns (X0, packed bytes).
    State X stays in [M, 2M); bits are emitted LSB-first then the whole list is
    reversed once so the decoder can read them forward (ANS is LIFO)."""
    R, M = ANS_R, 1 << ANS_R
    _symt, nb, base, enc_slot = _ans_build(freq, R, build_enc=True)
    emit = []
    X = M                                     # canonical start = decoder's final state
    for s in reversed(cats.tolist()):
        t = int(enc_slot[s][X - M])
        b = X - int(base[t])                  # the nb[t] renorm bits (in [0, 2**nb[t]))
        for j in range(int(nb[t])):
            emit.append((b >> j) & 1)
        X = M + t
    X0 = X                                     # decoder's initial state
    packed = np.packbits(np.array(emit[::-1], np.uint8)).tobytes() if emit else b""
    return X0, packed


def _ans_decode_cats(X0, ans_bytes, n, freq):
    """Forward tANS decode of `n` categories from the (reversed) bitstream."""
    R, M = ANS_R, 1 << ANS_R
    symt, nb, base, _ = _ans_build(freq, R, build_enc=False)
    bits = (np.unpackbits(np.frombuffer(ans_bytes, np.uint8))
            if len(ans_bytes) else np.zeros(0, np.uint8))
    cats = np.empty(n, np.int64)
    X = int(X0)
    p = 0
    for i in range(n):
        t = X - M
        cats[i] = int(symt[t])
        val = 0
        for _ in range(int(nb[t])):           # MSB-first (reconciles the reversal)
            val = (val << 1) | int(bits[p]); p += 1
        X = int(base[t]) + val
    return cats


def _ans_encode_block(res_blk):
    """Encode one residual block: category tANS + raw mantissa bits + freq table."""
    u = ec.zigzag(res_blk.astype(np.int64))
    cats = _ans_bitlen(u)
    cmax = int(cats.max())
    widths = np.maximum(cats - 1, 0)                       # c-1 mantissa bits (0 for c<=1)
    base_val = np.where(cats >= 1, np.left_shift(np.int64(1), widths), np.int64(0))
    mant = u.astype(np.int64) - base_val                  # low bits of u
    total_bits = int(widths.sum())
    if total_bits:
        starts = np.concatenate(([0], np.cumsum(widths)[:-1])).astype(np.int64)
        mbits = np.zeros(total_bits, np.uint8)
        for j in range(int(widths.max())):                # LSB-first, vectorized
            sel = widths > j
            mbits[starts[sel] + j] = ((mant[sel] >> np.int64(j)) & 1).astype(np.uint8)
        mpacked = np.packbits(mbits).tobytes()
    else:
        mpacked = b""
    freq = _ans_normalize(np.bincount(cats, minlength=cmax + 1), ANS_R)
    X0, ans_packed = _ans_encode_cats(cats, freq)
    return (struct.pack("<B", cmax) + freq.astype("<u2").tobytes()
            + struct.pack("<H", X0)
            + struct.pack("<I", len(ans_packed)) + ans_packed
            + struct.pack("<I", len(mpacked)) + mpacked)


def _ans_decode_block(buf, off, n):
    (cmax,) = struct.unpack_from("<B", buf, off); off += 1
    freq = np.frombuffer(buf, "<u2", cmax + 1, off).astype(np.int64); off += 2 * (cmax + 1)
    (X0,) = struct.unpack_from("<H", buf, off); off += 2
    (ans_len,) = struct.unpack_from("<I", buf, off); off += 4
    ans_bytes = buf[off:off + ans_len]; off += ans_len
    (mant_len,) = struct.unpack_from("<I", buf, off); off += 4
    mant_bytes = buf[off:off + mant_len]; off += mant_len
    cats = _ans_decode_cats(X0, ans_bytes, n, freq)
    widths = np.maximum(cats - 1, 0)
    mant = np.zeros(n, np.int64)
    if int(widths.sum()):
        mbits = np.unpackbits(np.frombuffer(mant_bytes, np.uint8))
        starts = np.concatenate(([0], np.cumsum(widths)[:-1])).astype(np.int64)
        for j in range(int(widths.max())):
            sel = widths > j
            mant[sel] |= (mbits[starts[sel] + j].astype(np.int64) << np.int64(j))
    base_val = np.where(cats >= 1, np.left_shift(np.int64(1), widths), np.int64(0))
    u = (base_val + mant).astype(np.uint64)
    return ec.unzigzag(u), off


def _ans_encode_1d(res):
    """tANS entropy-code a 1-D residual channel, static freq table per ANS_BLOCK.
    Same call signature/role as ec.rice_encode_1d -> a drop-in back-end swap."""
    res = np.asarray(res, np.int64)
    n_total = res.size
    out = [struct.pack("<I", n_total)]
    for s in range(0, n_total, ANS_BLOCK):
        out.append(_ans_encode_block(res[s:s + ANS_BLOCK]))
    return b"".join(out)


def _ans_decode_1d(buf, off):
    (n_total,) = struct.unpack_from("<I", buf, off); off += 4
    res = np.empty(n_total, np.int64)
    pos = 0
    while pos < n_total:
        n = min(ANS_BLOCK, n_total - pos)
        blk, off = _ans_decode_block(buf, off, n)
        res[pos:pos + n] = blk
        pos += n
    return res, off


def ans_encode(x, cols=16):
    """LMS+xchan front-end IDENTICAL to the incumbent 'LMS+Rice+xchan'
    (ec.grid_parents/cross_betas/cross_forward + order-8 sign-sign LMS); only
    the per-channel entropy back-end is tANS instead of Rice."""
    x = np.asarray(x, np.int64)
    C, N = x.shape
    parent = ec.grid_parents(C, cols)
    betas = ec.cross_betas(x, parent)
    xt = ec.cross_forward(x, parent, betas)
    res = ec.lms_forward(xt)
    body = b"".join(_ans_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", ANS_MAGIC, cols, C, N)
    side = betas.astype("<i2").tobytes()          # same beta side-info as the incumbent
    return hdr + side + body


def ans_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == ANS_MAGIC, "bad tANS codec magic"
    off = 12
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = _ans_decode_1d(buf, off)
        res[c] = arr
    xt = ec.lms_inverse(res)
    x = ec.cross_inverse(xt, ec.grid_parents(C, cols), betas)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Adaptive Common Average Reference (ACAR) rank-1 common-mode
# front-end -- reversible-integer common-average removal + per-channel LMS + Rice.
# ---------------------------------------------------------------------------
# Every cross-channel front-end shipped so far removes a LOCAL, pairwise slice of
# the cross-channel redundancy: +xchan/xadapt/bestpartner subtract ONE grid
# neighbour with a gain; the (retired) iklt/iklt_adaptive rotate neighbour PAIRS.
# None of them can fully cancel the GLOBAL common-mode component -- the single
# signal shared by the WHOLE array (movement/EMG drive, power-line pickup,
# reference/electrode drift) -- because a neighbour-difference cancels common mode
# only to the extent the two neighbours share it, and leaves the array-wide DC
# drift and any far-field shared source. Common Average Reference (CAR) is the
# classic HD-EMG montage that removes exactly this: subtract the array mean from
# every channel. This is a genuinely DISTINCT slice of the cross-channel mutual
# information (INSIGHTS P1) from the neighbour subtracts -- a rank-1 GLOBAL lever,
# not a pairwise one -- and it is near-free: one running cross-channel sum per
# time sample plus one subtract, O(1)/sample-ch, RTL-trivial.
#
# Made lossless by a reversible-integer S-transform-style lift that codes the
# array TOTAL as a virtual channel (subtracting the same mean from all channels is
# rank-deficient -- it loses the array DC level -- so the lost degree of freedom
# is preserved by keeping the exact total). Per time slice, over an ON block:
#     S_t   = sum_c x[c,t]              (array total -- the virtual channel)
#     CAR_t = floor(S_t / C)            (integer common average = weighted mean)
#     y[0,t] = S_t                      (root slot carries the total, losslessly)
#     y[c,t] = x[c,t] - CAR_t   (c>=1)  (residual = channel - round(CAR))
# Inverse (exact): CAR_t = floor(y[0,t]/C); x[c,t]=y[c,t]+CAR_t (c>=1);
#     x[0,t] = y[0,t] - sum_{c>=1} x[c,t].  All integer, per-time-slice, no
# look-ahead. Channels 1..C-1 get TRUE mean-referenced CAR residuals (common mode
# removed, only ~1/C of the aggregate noise added back); the single root channel
# is inflated to the total -- the acknowledged rank-1 cost, paid on 1/C of the data.
#
# Gated per block, BACKWARD-ADAPTIVELY (INSIGHTS P4 -- zero side-info): block i is
# transformed only if the common-mode is material in the PREVIOUS reconstructed
# raw block, so the decoder recomputes the identical gate from already-restored
# data. The gate fires iff C*sum(CAR^2)/sum(x^2) exceeds a threshold set ABOVE the
# 1/C floor that independent per-channel noise produces just by array-averaging --
# so it fires only on a genuine shared component and cannot hurt low-common-mode
# segments (they pass through as identity). Block 0 bootstraps OFF (coded as-is),
# and the basis then adapts each block. Behind the front-end: the SAME order-8
# sign-sign LMS + adaptive Rice back-end as the whole family (only the spatial
# front-end differs). Distinct from cycle-1 xadapt (per-block single-neighbour
# beta) and cycle-2 bestpartner (a SELECTED neighbour): here the global array mean,
# not any one channel. Basis: Vaisman/Jordanic/Farina adaptive common-average
# filtering for HD-EMG (MBEC 2014, myocontrol/SNR benefit) -- unverified for
# compression here.
# ===========================================================================
ACAR_MAGIC = 0x4341          # 'CA'
ACAR_BLOCK = ec.BLOCK        # gate/adaptation block (aligns with the Rice block)
ACAR_GATE_NUM = 1            # gate ON iff C*sum(CAR^2)/sum(x^2) > ACAR_GATE_NUM/DEN
ACAR_GATE_DEN = 16           # threshold 1/16 ~ 2/C for C=32: above the noise floor


def _acar_gate(xprev, C):
    """Backward gate from the PREVIOUS raw block. ON iff the array common-mode is
    material enough that removing it (from C-1 channels) pays for inflating the
    root channel to the array total. Integer-only and deterministic, so encoder
    and decoder -- which both reconstruct the raw previous block exactly -- derive
    the identical decision. ON iff C*sum(CAR^2) * DEN > sum(x^2) * NUM, with
    CAR = floor(sum_c x / C). The threshold sits above the 1/C level that pure
    independent noise produces by channel-averaging, so it fires only on a genuine
    shared component. (Sums over <=256 samples of <=32 int16 -> |S|<2^21, CAR^2
    summed over the block < 2^50, times C*DEN < 2^60: inside int64.)"""
    xp = xprev.astype(np.int64)
    S = xp.sum(axis=0)                      # array total per time sample
    car = np.floor_divide(S, C)             # integer common average (floor)
    cm_pow = int((car * car).sum())
    tot_pow = int((xp * xp).sum())
    return cm_pow * C * ACAR_GATE_DEN > tot_pow * ACAR_GATE_NUM


def _acar_forward(x, cols, B=ACAR_BLOCK):
    """Reversible-integer common-average removal, per time-block. ON blocks put the
    array total in the root slot and channel-minus-CAR in the rest; OFF blocks pass
    through unchanged. Returns the transformed [C, N] int64 array. (cols is unused
    -- CAR spans the whole array, grid-agnostic -- but kept for interface parity.)"""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    nblocks = (N + B - 1) // B
    for i in range(nblocks):
        s, e = i * B, min((i + 1) * B, N)
        on = False if i == 0 else _acar_gate(x[:, (i - 1) * B:i * B], C)
        if not on:
            continue                        # identity: low-common-mode block
        blk = x[:, s:e]
        S = blk.sum(axis=0)                 # array total per time slice
        car = np.floor_divide(S, C)         # common average (floor)
        y[0, s:e] = S                       # root slot carries the virtual total
        y[1:, s:e] = blk[1:] - car          # residuals = channel - round(CAR)
    return y


def _acar_inverse(y, cols, B=ACAR_BLOCK):
    """Invert _acar_forward. Rebuilds raw x block-by-block in time order; before
    block i is inverted, raw block i-1 is already restored, so the same backward
    gate is recomputed and the lift is undone exactly."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    nblocks = (N + B - 1) // B
    for i in range(nblocks):
        s, e = i * B, min((i + 1) * B, N)
        on = False if i == 0 else _acar_gate(x[:, (i - 1) * B:i * B], C)
        if not on:
            continue
        S = y[0, s:e]
        car = np.floor_divide(S, C)
        x[1:, s:e] = y[1:, s:e] + car               # restore channels 1..C-1
        x[0, s:e] = S - x[1:, s:e].sum(axis=0)       # root = total - the rest
    return x


def acar_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _acar_forward(x, cols)
    res = ec.lms_forward(y)                  # order-8 sign-sign LMS (same as family)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", ACAR_MAGIC, cols, C, N)   # NO side-info (backward gate)
    return hdr + body


def acar_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == ACAR_MAGIC, "bad ACAR codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res)
    x = _acar_inverse(y, cols)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Order-4 LMS under the best-partner cross-channel front-end.
# ---------------------------------------------------------------------------
# This pairs two levers that were each proven separately but never together:
#   * the SPATIAL lever -- the already-shipped, non-dominated best-partner
#     front-end (`_bp_select`/`_bp_inverse`): each channel picks its best-of-4
#     causal grid neighbour + integer gain, tiny (parent,beta) side-info -- is
#     reused VERBATIM (identical selection, identical side-info, identical
#     inverse), so the spatial basis is unchanged.
#   * the TEMPORAL lever -- INSIGHTS P2 MEASURED on real Hyser/OTB that an
#     order-4 sign-sign LMS beats the order-8 one (deeper prediction fits noise
#     and RAISES coded entropy) at ~half the state/ops. Cycle-2's best-partner
#     was built on the over-provisioned order-8 predictor; here we simply
#     right-size it to order-4.
# So this codec is `LMS+Rice+xchan_bestpartner` with ec.lms_forward/inverse
# called at order=4 instead of the family default (8). No new mechanism, no new
# side-info: the encoder and decoder both run the SAME order-4 sign-sign LMS
# (backward-adaptive, zero side-info -- INSIGHTS P4) so they stay a matched pair.
# The intent (INSIGHTS open-frontier #1) is to dominate the incumbent on BOTH
# axes -- strictly cheaper (half the temporal state/ops) AND >= ratio.
# ===========================================================================
LMS4BP_MAGIC = 0x4C34   # 'L4'
LMS4_ORDER = 4          # right-sized temporal predictor (INSIGHTS P2), vs family's 8


def lms4bp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)          # best-partner front-end (verbatim)
    res = ec.lms_forward(xt, order=LMS4_ORDER)        # order-4 sign-sign LMS (P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", LMS4BP_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def lms4bp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == LMS4BP_MAGIC, "bad lms4bp codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = ec.lms_inverse(res, order=LMS4_ORDER)        # matched order-4 inverse
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Multi-parent backward-adaptive rank-1 subtract
# (LMS+Rice+xchan_multiparent).
# ---------------------------------------------------------------------------
# Every shipped cross-channel front-end that works here is the SAME rank-1
# lever: subtract ONE causal grid neighbour with a gain (+xchan whole-signal
# beta; xadapt/bestpartner variants). INSIGHTS P1-refinement measured that on
# EXTENDED arrays the shared content is spatially LOCAL, so a single neighbour
# leaves a further slice of local cross-channel mutual information uncaptured;
# INSIGHTS open-frontier #2 endorses adding a SECOND causal parent to reach it.
#
# Mechanism: replace the single grid-parent with TWO causal parents -- UP
# (g-cols) and LEFT (g-1), both grid index < g so decode still reconstructs in
# channel order -- each with its OWN backward-adaptive integer beta, and SUM
# their residual subtractions:
#     y[c,t] = x[c,t] - ((beta_up[c]*x[up,t]) >> s) - ((beta_left[c]*x[left,t]) >> s)
# This is a rank-2 LOCAL decorrelation realized as TWO independent asymmetric
# rank-1 subtracts (one per parent), NOT a joint 2x2 solve: each beta is the
# per-parent integer least-squares ratio <x_c,x_p>/<x_p,x_p> estimated
# independently from the PREVIOUS block's already-reconstructed RAW samples
# (block 0 -> beta=0). Both terms subtract the CLEAN raw parent and inject
# estimation noise only into the residual channel c -- the parent rows stay
# untouched -- which is exactly the robustness property INSIGHTS P3-refinement
# credits the rank-1 subtract with, and which the RETIRED energy-preserving
# rotation (iklt_adaptive, corrupts BOTH channels) lacks.
#
# Because both betas are recomputed by the decoder from bit-identical
# reconstructed history, NO beta is transmitted (zero side-info, backward-
# adaptive -- INSIGHTS P4), look-ahead 0. DISTINCT from the retired single-
# parent scalar xchan_adaptive: it adds a SECOND independent parent on a
# different topology (up vs left), the follow-up open-frontier #2 endorses --
# not a re-run of the dominated single-parent scalar. Behind the front-end: the
# SAME order-8 sign-sign LMS + adaptive Rice back-end as the whole family.
# Basis: MPEG-4 ALS multichannel / Choi et al. 2014 (paper-reported, unverified
# here). Gated hard on cost (each parent adds state + ops); neural budget
# verified.
# ===========================================================================
MP_MAGIC = 0x584D            # 'XM' (xchan multi-parent)
MP_BLOCK = ec.BLOCK          # backward-adaptation block (aligns with the Rice block)
MP_SHIFT = ec.CROSS_SHIFT    # fixed-point gain scale (matches the +xchan family)


def _mp_parents(C, cols):
    """Two causal grid parents per channel: (up, left). up = g-cols (row > 0),
    left = g-1 (col > 0); -1 where absent. Both indices < g so the decoder
    reconstructs in channel order and a channel with neither parent (grid
    origin) is coded as-is. Deterministic from (C, cols): identical on encode
    and decode."""
    up = np.full(C, -1, np.int64)
    left = np.full(C, -1, np.int64)
    for g in range(C):
        r, c = divmod(g, cols)
        if r > 0:
            up[g] = g - cols
        if c > 0:
            left[g] = g - 1
    return up, left


def _mp_forward(x, up, left, B=MP_BLOCK, shift=MP_SHIFT):
    """Two-parent cross-channel decorrelation with per-parent backward-adaptive
    gain. For each parent independently, beta[block i] is the integer
    least-squares ratio over the PREVIOUS block's raw samples (block 0 -> 0),
    and its rank-1 subtract of the CLEAN raw parent is SUMMED into the residual.
    Operates on the RAW signal (which the decoder rebuilds bit-exactly), so the
    betas match on both sides."""
    x = x.astype(np.int64)
    C, N = x.shape
    y = x.copy()
    nblocks = (N + B - 1) // B
    for c in range(C):
        pu, pl = int(up[c]), int(left[c])
        if pu < 0 and pl < 0:              # grid origin: no parent to subtract
            continue
        bu = bl = 0                        # block-0 bootstrap (coded as xchan-off)
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i > 0:
                ps, pe = (i - 1) * B, i * B
                if pu >= 0:
                    bu = _beta_from_block(x[c, ps:pe], x[pu, ps:pe], shift)
                if pl >= 0:
                    bl = _beta_from_block(x[c, ps:pe], x[pl, ps:pe], shift)
            r = x[c, s:e].copy()
            if pu >= 0:
                r = r - ((bu * x[pu, s:e]) >> shift)   # rank-1 subtract, parent 1
            if pl >= 0:
                r = r - ((bl * x[pl, s:e]) >> shift)   # rank-1 subtract, parent 2
            y[c, s:e] = r
    return y


def _mp_inverse(y, up, left, B=MP_BLOCK, shift=MP_SHIFT):
    """Invert _mp_forward. Both parents have index < c so their rows are fully
    reconstructed before channel c; within a channel, block i's per-parent betas
    are recomputed from the already-reconstructed block i-1 -- mirroring the
    encoder exactly, with the two subtracts added back in the same order."""
    y = y.astype(np.int64)
    C, N = y.shape
    x = y.copy()
    nblocks = (N + B - 1) // B
    for c in range(C):
        pu, pl = int(up[c]), int(left[c])
        if pu < 0 and pl < 0:
            continue
        bu = bl = 0
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i > 0:
                ps, pe = (i - 1) * B, i * B
                if pu >= 0:
                    bu = _beta_from_block(x[c, ps:pe], x[pu, ps:pe], shift)
                if pl >= 0:
                    bl = _beta_from_block(x[c, ps:pe], x[pl, ps:pe], shift)
            r = y[c, s:e].copy()
            if pu >= 0:
                r = r + ((bu * x[pu, s:e]) >> shift)
            if pl >= 0:
                r = r + ((bl * x[pl, s:e]) >> shift)
            x[c, s:e] = r
    return x


def mp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    up, left = _mp_parents(C, cols)
    y = _mp_forward(x, up, left)
    res = ec.lms_forward(y)                # order-8 sign-sign LMS (same as family)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", MP_MAGIC, cols, C, N)   # NO beta side-info
    return hdr + body


def mp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == MP_MAGIC, "bad xchan_multiparent magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res)
    up, left = _mp_parents(C, cols)
    x = _mp_inverse(y, up, left)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Cross-channel context-adaptive Rice (LMS+Rice+xctx).
# ---------------------------------------------------------------------------
# Every cycle so far moved the cross-channel FRONT-END (removing correlated
# MEANS: +xchan/xadapt/bestpartner subtract a neighbour, acar the array mean) or
# swapped the entropy engine (retired xchan_tans, P5). This candidate is on a
# DIFFERENT axis -- SECOND-ORDER / CONDITIONAL entropy -- untouched by any tried
# codec, and it keeps the Golomb-Rice engine (P5: Rice is already at the floor
# for the UNCONDITIONAL residual). It changes only how the Rice parameter k is
# SELECTED: per-sample, from a backward SPATIAL context.
#
# Mechanism (JPEG-LS/LOCO-I context modeling with a cross-channel context):
# every prior spatial front-end removes correlated first-order MEANS, but HD-EMG
# bursts (motor-unit action potentials) are spatially COHERENT, so the residual
# stays HETEROSCEDASTIC and its VARIANCE is correlated ACROSS channels even after
# mean decorrelation. A single per-block k per channel cannot track that. Here:
#   * The temporal residual is the SAME order-8 sign-sign LMS as the family
#     (res = ec.lms_forward(x)); the coder engine stays Golomb-Rice.
#   * For a channel c with causal grid parent p = grid_parents(c) (p < c, so the
#     decoder has p's full residual before it reaches c), a leaky integrator of
#     the NEIGHBOUR residual magnitude |res[p,t]| forms a running spatial-energy
#     estimate; its bit-length buckets that energy (log-energy context).
#   * Per context bucket we keep JPEG-LS statistics (A = sum of coded magnitudes,
#     N = count) and pick k as the smallest with (N<<k) >= A -- the standard
#     LOCO-I Golomb rule -- so k tracks the residual variance CONDITIONED on the
#     neighbour's current energy: high-neighbour-energy samples (spatially
#     coherent bursts) get a larger k, quiet samples a smaller one. This exploits
#     H(e_c | neighbour energy) < H(e_c): a conditional-entropy reduction a
#     per-block k structurally misses.
#   * The bucket and the per-bucket (A,N) stats are updated identically on both
#     sides from causally-available, bit-identical data, so ZERO side-info is
#     transmitted (no per-block k, no context table) -- backward-adaptive, P4.
#     Root channels (no parent) fall back to a single context (bucket 0), i.e.
#     plain per-channel JPEG-LS adaptive k with no spatial conditioning.
#
# Distinct from the RETIRED xchan_tans (P5): the entropy ENGINE stays Rice
# (already optimal for the unconditional residual); only its PARAMETER's context
# gains cross-channel information. Distinct from the spatial front-ends: nothing
# is subtracted across channels here -- the neighbour only CONDITIONS the coder.
# Borderline->embeddable: a leaky-energy add/shift + a small k lookup per sample,
# per-context (A,N) counters as state, RTL-trivial. Risk to MEASURE: if the
# per-block k already tracks local variance well, the spatial context may add
# little. Citations: JPEG-LS/LOCO-I (context-conditioned Golomb), US7580585B2
# (backward-adaptive Rice), Giurcaneanu/Tabus 2001 (context-based Golomb on
# audio) -- paper-reported, unverified here.
# ===========================================================================
XCTX_MAGIC = 0x5843     # 'XC'
XCTX_NBUCKETS = 12      # spatial-energy context buckets (log neighbour energy)
XCTX_DECAY = 2          # leaky-integrator decay for the neighbour-energy estimate
XCTX_RESET = 64         # JPEG-LS-style halving reset keeps per-context (A,N) local
XCTX_A_INIT = 4         # (A,N) seed -> initial k = 2 before any data
XCTX_N_INIT = 1


def _xctx_k(A, N):
    """LOCO-I/JPEG-LS Golomb parameter for context stats (A = accumulated coded
    magnitudes, N = count): the smallest k with (N << k) >= A. Integer-only and
    deterministic, so encode and decode derive the identical k from the identical
    (backward-updated) stats."""
    k = 0
    while (N << k) < A:
        k += 1
    return k


def _xctx_encode_channel(res, neigh):
    """Per-sample context-adaptive Rice encode of one residual channel. The
    context bucket is the bit-length of a leaky neighbour-energy integrator (a
    single bucket 0 when the channel has no parent); per-bucket JPEG-LS (A,N)
    stats pick the Rice k. Returns a length-prefixed packed-bit body. NO k or
    context is transmitted -- the decoder recomputes bucket + stats identically
    from the already-reconstructed neighbour residual."""
    u = ec.zigzag(np.asarray(res, np.int64))          # >= 0 mapped residual
    nmag = np.abs(np.asarray(neigh, np.int64)) if neigh is not None else None
    A = [XCTX_A_INIT] * XCTX_NBUCKETS
    Nc = [XCTX_N_INIT] * XCTX_NBUCKETS
    nrg = 0
    bits = []
    for t in range(u.size):
        if nmag is not None:
            nrg = nrg + int(nmag[t]) - (nrg >> XCTX_DECAY)   # leaky spatial energy
            b = nrg.bit_length()
            if b >= XCTX_NBUCKETS:
                b = XCTX_NBUCKETS - 1
        else:
            b = 0
        k = _xctx_k(A[b], Nc[b])
        ut = int(u[t])
        q = ut >> k
        bits.extend([0] * q)                          # unary quotient
        bits.append(1)                                # stop bit
        for j in range(k - 1, -1, -1):                # k remainder bits, MSB first
            bits.append((ut >> j) & 1)
        A[b] += ut
        Nc[b] += 1
        if Nc[b] >= XCTX_RESET:                       # halving reset -> local adapt
            A[b] >>= 1
            Nc[b] >>= 1
    packed = np.packbits(np.array(bits, np.uint8)).tobytes() if bits else b""
    return struct.pack("<I", len(packed)) + packed


def _xctx_decode_channel(buf, off, N, neigh):
    """Invert _xctx_encode_channel. Mirrors the encoder's bucket + per-context
    (A,N) update from the already-reconstructed neighbour residual, so it derives
    the identical per-sample k with no transmitted parameters."""
    (nbytes,) = struct.unpack_from("<I", buf, off); off += 4
    bits = (np.unpackbits(np.frombuffer(buf, np.uint8, nbytes, off))
            if nbytes else np.zeros(0, np.uint8))
    off += nbytes
    nmag = np.abs(np.asarray(neigh, np.int64)) if neigh is not None else None
    A = [XCTX_A_INIT] * XCTX_NBUCKETS
    Nc = [XCTX_N_INIT] * XCTX_NBUCKETS
    nrg = 0
    u = np.empty(N, np.int64)
    pos = 0
    for t in range(N):
        if nmag is not None:
            nrg = nrg + int(nmag[t]) - (nrg >> XCTX_DECAY)
            b = nrg.bit_length()
            if b >= XCTX_NBUCKETS:
                b = XCTX_NBUCKETS - 1
        else:
            b = 0
        k = _xctx_k(A[b], Nc[b])
        q = 0
        while bits[pos] == 0:                          # count unary zeros
            q += 1; pos += 1
        pos += 1                                        # skip stop bit
        r = 0
        for _ in range(k):                              # k remainder bits, MSB first
            r = (r << 1) | int(bits[pos]); pos += 1
        ut = (q << k) | r
        u[t] = ut
        A[b] += ut
        Nc[b] += 1
        if Nc[b] >= XCTX_RESET:
            A[b] >>= 1
            Nc[b] >>= 1
    return ec.unzigzag(u.astype(np.uint64)), off


def xctx_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    res = ec.lms_forward(x)                 # order-8 sign-sign LMS (same as family)
    parent = ec.grid_parents(C, cols)
    body = []
    for c in range(C):
        p = int(parent[c])
        neigh = res[p] if p >= 0 else None
        body.append(_xctx_encode_channel(res[c], neigh))
    hdr = struct.pack("<HHII", XCTX_MAGIC, cols, C, N)   # NO side-info
    return hdr + b"".join(body)


def xctx_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XCTX_MAGIC, "bad xctx magic"
    off = 12
    parent = ec.grid_parents(C, cols)
    res = np.empty((C, N), np.int64)
    for c in range(C):
        p = int(parent[c])
        neigh = res[p] if p >= 0 else None    # p < c so already reconstructed
        arr, off = _xctx_decode_channel(buf, off, N, neigh)
        res[c] = arr
    x = ec.lms_inverse(res)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: two-stage scale-matched spatial front-end -- GLOBAL adaptive
# CAR then LOCAL order-4 best-partner (acar+lms4bp).
# ---------------------------------------------------------------------------
# INSIGHTS P1-refinement MEASURED that the cross-channel mutual information splits
# into two distinct, NON-INTERCHANGEABLE slices and array size selects which one
# dominates: removing the GLOBAL rank-1 common-mode (`LMS+Rice+acar`, the array-mean
# lift) captured +14.4% on the small tightly-coupled 64-ch OTB array but collapsed
# to +0.8..2.5% on the larger 128-/320-ch Hyser/CEMHSEY arrays, where the LOCAL
# single-/best-neighbour subtract still got +10.8..13.1%. CAR removes exactly one
# eigenvector (DC-across-array); best-partner removes the local pairwise weight.
# Neither codec can reach the other's slice: a global mean does not cancel local
# pairwise redundancy, and a neighbour difference does not cancel the array-wide DC
# drift and far-field shared source.
#
# This candidate CASCADES the two already-verified primitives so it captures BOTH
# slices where both exist, in the order that keeps them orthogonal:
#   Stage 1 (GLOBAL): the ACAR reversible-integer S-transform lift (`_acar_forward`,
#     backward-gated, ZERO side-info) reused VERBATIM -- removes the global array
#     common-mode, leaving a CAR residual whose remaining cross-channel structure is
#     the LOCAL pairwise part.
#   Stage 2 (LOCAL): the promoted best-partner subtract (`_bp_select`, per-channel
#     best-of-4 causal grid neighbour + integer gain, tiny 2xint16/ch side-info)
#     reused VERBATIM, applied to the CAR RESIDUAL -- removes the local pairwise MI
#     that CAR left behind.
#   Back-end: the order-4 sign-sign LMS + adaptive Rice of the promoted best
#     `LMS4+Rice+xchan_bestpartner` (INSIGHTS P2: order-4 beats order-8).
#
# Why the two stages are ORTHOGONAL BY CONSTRUCTION (and so, unlike the RETIRED
# summed multi-parent, cannot double-count): stage 1 removes the array-mean
# component; the residual it leaves is mean-zero across the array by construction, so
# its local pairwise covariance is uncorrelated with the global mean stage 1 already
# took. The retired `xchan_multiparent` summed two CORRELATED local parents and
# over-subtracted their shared mode; here the two stages act on ORTHOGONAL subspaces
# (one global eigenvector vs the local-pairwise complement), so there is nothing to
# double-count.
#
# Losslessness of the cascade: both stages are exact integer inverses. Encode is
# x -> acar_forward -> bp_select -> LMS4 -> Rice; decode inverts in reverse order --
# Rice -> lms_inverse(order4) -> bp_inverse (the transmitted parents/betas restore the
# CAR residual exactly, parents[g]<g so each parent row is already rebuilt) ->
# acar_inverse (recomputes the SAME backward gate from the reconstructed raw previous
# block, block-by-block in time order). Channel 0 carries ACAR's virtual array total
# on ON blocks and has no best-partner candidate (grid origin), so it passes stage 2
# through unchanged -- the two stages compose cleanly. Cost is amortized O(1)/sample-ch
# for CAR on top of best-partner's per-sample subtract (INSIGHTS open-frontier #1).
# Risk (to MEASURE, not to pre-judge): on large arrays where redundancy is already
# local, CAR may not clear its per-block gate and add ~nothing -- the slices may be
# additive (both fire) or redundant after best-partner already took the local slice.
# ===========================================================================
ACARBP_MAGIC = 0x4143   # 'AC' (adaptive-CAR + best-partner cascade)


def acarbp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _acar_forward(x, cols)                      # stage 1: GLOBAL common-mode lift (verbatim)
    xt, parents, betas = _bp_select(y, cols)        # stage 2: LOCAL best-partner on the CAR residual
    res = ec.lms_forward(xt, order=LMS4_ORDER)      # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", ACARBP_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def acarbp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == ACARBP_MAGIC, "bad acar+bestpartner codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = ec.lms_inverse(res, order=LMS4_ORDER)      # matched order-4 inverse
    y = _bp_inverse(xt, parents, betas)             # undo stage 2 (LOCAL best-partner)
    x = _acar_inverse(y, cols)                      # undo stage 1 (GLOBAL CAR lift)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: SCALE-SELECTED two-stage spatial cascade
# (LMS4+Rice+acar_sel+bestpartner).
# ---------------------------------------------------------------------------
# The always-on two-stage cascade above (`LMS4+Rice+acar+bestpartner`) MEASURED a
# clean split by ARRAY SIZE (INSIGHTS P1-refinement, cycle-10 frontier #1): the
# CAR stage's isolated marginal gain over best-partner alone was +0.81% ratio on
# the tight 64-ch OTB array (a genuine non-dominated max-ratio corner) but NEGATIVE
# on the large 128-/320-ch Hyser/CEMHSEY arrays (-0.26 / -0.23 pp) -- because the
# two cross-channel MI slices are additive ONLY where the GLOBAL common-mode is a
# real eigenvector, which array size selects. On tight arrays the DC-across-array
# mode is physical and orthogonal to the local pairwise mode, so cascading captures
# both; on large arrays the shared content is spatially LOCAL, so once best-partner
# removes the local slice a fired CAR lift subtracts a MISMATCHED global basis and
# injects slightly more noise than it removes. The always-on cascade's per-block
# ACAR gate is a local-energy heuristic that still fires on the large arrays and
# nets negative there -- the regression this candidate removes.
#
# This is a META-GATE over the two ALREADY-VERIFIED primitives -- NOT a new
# mechanism. Per recording it SELECTS the spatial front-end from a decoder-derivable
# GLOBAL-vs-LOCAL coherence statistic:
#   * TIGHT array (global common-mode is a real eigenvector) -> the full cascade
#     `_acar_forward` (stage 1, backward-gated GLOBAL CAR lift) THEN `_bp_select`
#     (stage 2, LOCAL best-partner) -- identical to `LMS4+Rice+acar+bestpartner`.
#   * EXTENDED array (global mode is NOT a coherent eigenvector) -> best-partner
#     ONLY -- identical to the promoted `LMS4+Rice+xchan_bestpartner`, so the CAR
#     stage cannot inject its mismatched-basis noise.
# The scale statistic is the ARRAY CHANNEL COUNT C, which the decoder reads from the
# header BEFORE any reconstruction -- a deterministic integer comparison, ZERO
# side-info, ZERO circularity (unlike an energy ratio on reconstructed data, which
# a per-recording global CAR decision cannot use without knowing the decision it is
# trying to make). C is exactly the physical variable INSIGHTS P1-refinement names
# decisive: at C<=64 the array is tight enough that the array-mean is a coherent
# eigenvector (OTB 64-ch: CAR helps); at C>=128 the shared content is local (Hyser
# 128-ch, CEMHSEY 320-ch, CapgMyo 128-ch: CAR hurts or its gate never usefully
# fires). The threshold ACARSEL_MAX_CH=64 is the measured boundary between the two
# regimes -- inclusive of the 64-ch tight array, below the 128-ch extended arrays.
#
# Losslessness: both branches are exact-integer-invertible primitives reused
# VERBATIM; the header format is IDENTICAL across branches (magic, cols, C, N, then
# the best-partner parents/betas side-info, then Rice body), so the decoder derives
# the SAME branch from C and inverts the matching cascade. On C<=64 it undoes
# stage 2 then stage 1 (bp_inverse -> acar_inverse); on C>=128 it undoes stage 2
# only. Cost is the union of the branch it takes (never both) -- so it is Pareto-
# bounded by the more expensive branch (the cascade), with the CAR ops paid only on
# tight arrays. Intent: keep the OTB max-ratio corner WITHOUT the large-array
# regression -- a low-mechanism-risk, low-to-medium-payoff salvage of frontier #1.
# Basis: Vaisman/Jordanic/Farina adaptive-CAR (stage 1) + the shipped best-partner
# (stage 2); the meta-gate is novel here (unverified for compression).
# ===========================================================================
ACARSEL_MAGIC = 0x5353   # 'SS' (scale-selected cascade)
ACARSEL_MAX_CH = 64      # recording-level scale gate: CAR cascade only for C<=this
                         # (tight arrays where the global common-mode is a real
                         # eigenvector -- P1-refinement); best-partner-only above.


def _acarsel_use_car(C):
    """Decoder-derivable recording-level scale gate. Enable the GLOBAL adaptive-CAR
    stage iff the array is tight enough (C<=ACARSEL_MAX_CH) that the array-mean is a
    coherent eigenvector. Pure integer comparison on the channel count C, which the
    decoder reads from the header before any reconstruction -> deterministic,
    zero-circularity, zero side-info; encoder and decoder derive the identical
    decision from the identical C."""
    return C <= ACARSEL_MAX_CH


def acarsel_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    if _acarsel_use_car(C):
        y = _acar_forward(x, cols)                  # stage 1: GLOBAL CAR (tight arrays only)
    else:
        y = x                                        # extended array: skip stage 1
    xt, parents, betas = _bp_select(y, cols)        # stage 2: LOCAL best-partner (both branches)
    res = ec.lms_forward(xt, order=LMS4_ORDER)      # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", ACARSEL_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def acarsel_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == ACARSEL_MAGIC, "bad scale-selected cascade codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = ec.lms_inverse(res, order=LMS4_ORDER)      # matched order-4 inverse
    y = _bp_inverse(xt, parents, betas)             # undo stage 2 (LOCAL best-partner)
    if _acarsel_use_car(C):
        x = _acar_inverse(y, cols)                  # undo stage 1 only where it was applied
    else:
        x = y
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Joint asymmetric 2-parent adaptive sign-LMS spatial predictor
# (LMS+Rice+xchan_joint2).
# ---------------------------------------------------------------------------
# INSIGHTS open-frontier #2/#3 and the RETIRED `xchan_multiparent` post-mortem
# leave exactly ONE unspent second-parent escape: extending the spatial support to
# TWO causal parents pays only through a JOINT decorrelation that accounts for
# parent-parent covariance -- NOT a sum of two independent marginal rank-1
# subtracts (which double-counts the correlated parents' shared mode and
# over-subtracts). The retired multiparent estimated each beta_p = <x_c,x_p>/
# <x_p,x_p> as if its parent were the SOLE regressor, then SUMMED -- the classic
# marginal-vs-multiple regression gap under collinear predictors. INSIGHTS also
# names the naive joint fix (an energy-preserving 2x2 Givens rotation) a settled
# dead end, because a stale/noisy angle corrupts BOTH channels (iklt_adaptive).
#
# This candidate is the de-risked realization of that one open escape: a JOINT
# (not summed, not rotational) solve done as ONE backward-adaptive sign-sign LMS
# with TWO SPATIAL taps. Per channel c with causal parents up (g-cols) and left
# (g-1), a single joint predictor
#     pred[t] = (w_u * x[up,t] + w_l * x[left,t]) >> shift
#     e[t]    = x[c,t] - pred[t]                    (the coded cross-residual)
# and BOTH taps co-adapt against the SAME post-subtraction residual e[t]:
#     w_u += sign(e[t]) * sign(x[up,t])
#     w_l += sign(e[t]) * sign(x[left,t])
# Because both taps are driven by the shared residual AFTER both current taps have
# subtracted, w_u adapts to the correlation REMAINING once left's contribution is
# out (and vice-versa) -- exactly the multiple-regression coupling the summed
# marginal betas lacked. This is the LMS stochastic-gradient realization of the
# 2x2 normal-equations solve: the taps jointly descend the shared squared error,
# so the parent-parent covariance enters through the shared residual, never
# double-counting. It overcomes the multiparent failure WITHOUT a matrix inverse.
#
# ASYMMETRIC (rank-1 residual-only injection): the predictor only subtracts from
# channel c's coded residual; the raw parent rows x[up]/x[left] are used as inputs
# and left CLEAN, so estimation noise never touches the parents -- the robustness
# property INSIGHTS P3-refinement credits the rank-1 subtract with and the RETIRED
# energy-preserving rotation (iklt_adaptive, corrupts both channels) lacked. This
# overcomes the SECOND retired failure.
#
# Backward-adaptive & multiplierless in the family sense (sign-sign LMS: the tap
# update is +/-1, no multiply): w_u/w_l evolve per sample from data the decoder has
# bit-identically (both parents have grid index < c, so their rows are fully
# reconstructed before c, and e[t] IS the coded residual). No angle, no beta, NO
# side-info is transmitted; look-ahead 0. Behind the spatial front-end sits the
# order-4 sign-sign LMS temporal predictor (INSIGHTS P2: order-4 beats order-8 --
# "+1 spatial pair on the order-4 base") + adaptive Rice -- the promoted best's
# back-end. Grounded in MPEG-4 ALS RLS-LMS multichannel / multivariate-RLS
# (arXiv 1605.04418, paper-reported, unverified here). Gated hard on the neural
# 125-cyc budget (two extra taps only). INSIGHTS open-frontier #3.
# ===========================================================================
XJ2_MAGIC = 0x584A          # 'XJ' (xchan joint 2-parent)
XJ2_SHIFT = ec.CROSS_SHIFT  # fixed-point spatial-weight scale (matches +xchan family)
XJ2_ORDER = LMS4_ORDER      # order-4 temporal base behind the spatial front-end (P2)


def _xj2_parents(C, cols):
    """Two causal grid parents per channel: up=g-cols (row>0), left=g-1 (col>0);
    -1 where absent. Both idx<g so decode reconstructs in channel order and the
    grid origin (neither parent) is coded as-is. Deterministic from (C,cols) ->
    identical on encode and decode."""
    up = np.full(C, -1, np.int64)
    left = np.full(C, -1, np.int64)
    for g in range(C):
        r, c = divmod(g, cols)
        if r > 0:
            up[g] = g - cols
        if c > 0:
            left[g] = g - 1
    return up, left


def _xj2_forward(x, up, left, shift=XJ2_SHIFT):
    """Joint 2-parent spatial sign-sign LMS decorrelation. For each channel c with
    causal parents up/left, ONE joint predictor with two spatial taps (w_u,w_l)
    predicts x[c,t] from the SAME-slice raw parents; both taps co-adapt against the
    SHARED post-subtraction residual e (sign-sign LMS -> +/-1 tap update, no
    multiply). Only channel c's residual e is coded; the raw parent rows are left
    clean. Integer-only, per-sample, look-ahead 0. Returns the cross-residual
    [C,N] int64."""
    x = x.astype(np.int64)
    C, N = x.shape
    y = x.copy()
    for c in range(C):
        pu, pl = int(up[c]), int(left[c])
        if pu < 0 and pl < 0:
            continue                        # grid origin: coded as-is
        prow = x[pu] if pu >= 0 else None
        lrow = x[pl] if pl >= 0 else None
        xc = x[c]
        yc = y[c]
        wu = wl = 0
        for t in range(N):
            u = int(prow[t]) if prow is not None else 0
            l = int(lrow[t]) if lrow is not None else 0
            pred = (wu * u + wl * l) >> shift
            e = int(xc[t]) - pred
            yc[t] = e
            se = 1 if e > 0 else (-1 if e < 0 else 0)
            if prow is not None:
                wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
            if lrow is not None:
                wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return y


def _xj2_inverse(y, up, left, shift=XJ2_SHIFT):
    """Invert _xj2_forward. parents idx<c so their rows are fully reconstructed
    before channel c; within a channel the two taps are re-derived per sample from
    the shared residual e=y[c,t] (identical to the encoder's) and the reconstructed
    parents -- so pred, and hence x[c,t]=e+pred, match bit-for-bit."""
    y = y.astype(np.int64)
    C, N = y.shape
    x = y.copy()
    for c in range(C):
        pu, pl = int(up[c]), int(left[c])
        if pu < 0 and pl < 0:
            continue
        prow = x[pu] if pu >= 0 else None   # parent idx < c -> already reconstructed
        lrow = x[pl] if pl >= 0 else None
        yc = y[c]
        xc = x[c]
        wu = wl = 0
        for t in range(N):
            u = int(prow[t]) if prow is not None else 0
            l = int(lrow[t]) if lrow is not None else 0
            pred = (wu * u + wl * l) >> shift
            e = int(yc[t])
            xc[t] = e + pred
            se = 1 if e > 0 else (-1 if e < 0 else 0)
            if prow is not None:
                wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
            if lrow is not None:
                wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return x


def xj2_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    up, left = _xj2_parents(C, cols)
    y = _xj2_forward(x, up, left)
    res = ec.lms_forward(y, order=XJ2_ORDER)   # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", XJ2_MAGIC, cols, C, N)   # NO side-info (backward-adaptive)
    return hdr + body


def xj2_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XJ2_MAGIC, "bad xchan_joint2 magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=XJ2_ORDER)   # matched order-4 inverse
    up, left = _xj2_parents(C, cols)
    x = _xj2_inverse(y, up, left)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Backward-adaptive per-block best-partner RE-SELECTION
# (LMS4+Rice+xchan_bestpartner_adaptive).
# ---------------------------------------------------------------------------
# The PROMOTED best `LMS4+Rice+xchan_bestpartner` picks each channel's cross-
# partner (best-of-4 causal grid neighbour) AND its integer gain beta OFFLINE
# over the WHOLE recording, then ships the chosen (parent, beta) pair as a
# 2xint16/ch header. That whole-signal look-ahead + header side-info is its last
# non-embeddable caveat (INSIGHTS P4 / open-frontier #3): the on-node decoder
# cannot see the whole signal, and the header is real transmitted bits.
#
# Mechanism: re-select partner IDENTITY + integer beta PER BLOCK from the
# PREVIOUS already-reconstructed RAW block's 4-neighbourhood, decoder mirroring
# the identical selection -> ZERO side-info, look-ahead 0. For channel g, block i
# (i>0): over the previous block (i-1) of the RAW channels, for each causal
# neighbour candidate (left/up/up-left/up-right, all grid idx < g -- reused
# `_bp_candidates`) derive the integer least-squares gain (`_bp_opt_beta`) and
# score the resulting cross-residual's estimated Rice bits (`_bp_score`), also
# scoring the no-partner option; keep the min-bits (partner, beta). That pair is
# then applied to the CURRENT block: y[g,blk i] = x[g,blk i] - ((beta*x[p,blk i])
# >> shift). Because the reconstruction is lossless, the RAW previous block the
# decoder holds is bit-identical to the encoder's, and every candidate partner
# has grid idx < g so its row is fully reconstructed -- so the decoder recomputes
# the SAME (partner, beta) causally and NOTHING is transmitted. Block 0
# bootstraps to no-partner (coded as-is; no prior block exists), then the
# selection re-adapts each block.
#
# This is EXACTLY the promoted codec with its offline whole-signal partner/beta
# swapped for per-block backward-adaptive re-selection: same 4-candidate causal
# neighbourhood, same integer-LS beta, same Rice-bits scoring, same order-4
# sign-sign LMS + adaptive Rice back-end (INSIGHTS P2) -- only the ESTIMATION is
# now backward-adaptive (INSIGHTS P4), dropping both the look-ahead and the
# 2xint16/ch header. Distinct from the RETIRED `LMS+Rice+xchan_adaptive` (a
# single FIXED-grid-parent scalar beta, backward-adaptive gain but NO partner
# selection): here the partner IDENTITY itself is re-selected per block -- the
# exact port-caveat closure INSIGHTS open-frontier #3 endorses. Ratio risk to
# MEASURE: a stale partner across a burst boundary (the previous block may not
# predict the next one's best neighbour on non-stationary HD-sEMG); this is an
# embeddability/port lever (makes the shipped leaderboard best fully on-node),
# not a ratio play -- the question is whether it HOLDS the offline ratio.
# ===========================================================================
LMS4BPA_MAGIC = 0x4234        # 'B4' (order-4 backward-adaptive best-partner)
LMS4BPA_BLOCK = ec.BLOCK      # re-selection block (aligns with the Rice block)


def _bpa_select_block(xc_prev, x, cands, ps, pe):
    """Backward per-block partner+beta selection from the PREVIOUS raw block.
    Mirrors the offline best-partner selection (`_bp_opt_beta`/`_bp_score`) but
    restricted to block (i-1): return (partner, beta) with the fewest estimated
    Rice bits over that block, or (-1, 0) for the no-partner option. Integer-only
    and deterministic, so encode and decode -- which both hold the bit-identical
    reconstructed previous block -- derive the identical choice."""
    best_bits = _bp_score(xc_prev)            # option: no cross-channel subtract
    best_p, best_b = -1, 0
    for p in cands:
        b = _bp_opt_beta(xc_prev, x[p, ps:pe], BP_SHIFT)
        if b == 0:
            continue
        resid = xc_prev - ((b * x[p, ps:pe]) >> BP_SHIFT)
        bits = _bp_score(resid)
        if bits < best_bits:
            best_bits, best_p, best_b = bits, p, b
    return best_p, best_b


def _lms4bpa_forward(x, cols, B=LMS4BPA_BLOCK):
    """Cross-channel decorrelation with backward-adaptive per-block best-partner
    RE-SELECTION. Block i's (partner, beta) come from the PREVIOUS raw block
    (block 0 -> no partner); the chosen rank-1 subtract is applied to block i of
    the RAW signal. Returns the transformed [C, N] int64 array."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:                          # grid origin: no causal neighbour
            continue
        for i in range(1, nblocks):            # block 0 is coded as-is (no prior)
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, b = _bpa_select_block(x[g, ps:pe], x, cands, ps, pe)
            if p >= 0:
                y[g, s:e] = x[g, s:e] - ((b * x[p, s:e]) >> BP_SHIFT)
    return y


def _lms4bpa_inverse(y, cols, B=LMS4BPA_BLOCK):
    """Invert _lms4bpa_forward. Each candidate partner has grid idx < g so its row
    is fully reconstructed before g; within a channel we rebuild raw block-by-block
    in time order, so block i-1 is restored before block i and the SAME per-block
    (partner, beta) is recomputed from it -- mirroring the encoder exactly."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:
            continue
        for i in range(1, nblocks):
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, b = _bpa_select_block(x[g, ps:pe], x, cands, ps, pe)
            if p >= 0:
                x[g, s:e] = y[g, s:e] + ((b * x[p, s:e]) >> BP_SHIFT)
    return x


def lms4bpa_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _lms4bpa_forward(x, cols)                    # backward-adaptive per-block re-selection
    res = ec.lms_forward(y, order=LMS4_ORDER)        # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", LMS4BPA_MAGIC, cols, C, N)   # NO (parent,beta) side-info
    return hdr + body


def lms4bpa_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == LMS4BPA_MAGIC, "bad lms4bp_adaptive codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=LMS4_ORDER)        # matched order-4 inverse
    x = _lms4bpa_inverse(y, cols)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: Joint-solved SELECTED best pair -- selection x count fused
# (LMS4+Rice+xchan_jointbp2).
# ---------------------------------------------------------------------------
# INSIGHTS P1b PROVED the two spatial degrees of freedom -- *which* parent
# (best-partner SELECTION) and *how many* parents (joint COUNT) -- are used alone
# as SUBSTITUTES, and array geometry picks the winner: the joint 2-parent solve
# (`xchan_joint2`) took the highest Hyser cross-channel gain of any codec (+12.26%)
# via a second co-adapted parent but LOST the tight OTB array because it used a
# FIXED up+left pair where SELECTION matters; best-partner won tight OTB via
# selection but is SINGLE-parent. INSIGHTS open-frontier #1 (the highest-payoff
# live lever) names the one untried way to STACK them into a combined win on BOTH
# array scales: jointly solve the best *pair* of causal neighbours (co-adaptive
# sign-LMS, as in joint2) instead of a *fixed* up+left pair, with the pair chosen
# per channel like best-partner -- done backward-adaptively to stay zero-side-info.
#
# Mechanism = SELECTION (per block, backward) x COUNT (joint co-adaptive pair):
#   1. SELECT (per channel, per block i>0): over the PREVIOUS already-reconstructed
#      RAW block, scan the <=4 causal grid neighbours (left/up/up-left/up-right, all
#      grid idx<c -- reused `_bp_candidates`). Score, in estimated Rice bits, the
#      no-parent option, each single-parent option (integer-LS gain, reusing
#      `_bp_opt_beta`/`_bp_score` -- the best-partner path), AND every candidate
#      PAIR under a JOINT 2x2 integer least-squares solve (`_jbp2_pair_resid`, which
#      accounts for parent-parent covariance -- the marginal->multiple fix, NOT the
#      retired summed multiparent's double-count). Keep the min-bits option: a pair
#      (pu,pl), a single (pu,-1), or none (-1,-1). This fuses selection AND count --
#      count falls out of the same scored search, so a useless second parent is not
#      forced on tight arrays (the exact P1b tension).
#   2. PREDICT that block with ONE joint co-adaptive sign-sign LMS on the SELECTED
#      pair (structure verbatim from `xchan_joint2`): pred=(w_u*x[pu]+w_l*x[pl])>>s,
#      e=x[c]-pred, and BOTH taps co-adapt against the SHARED post-subtraction
#      residual (w_u+=sign(e)sign(x[pu]), w_l+=sign(e)sign(x[pl]) -- +/-1 update,
#      multiplierless). The taps descend the shared residual so each adapts to the
#      correlation REMAINING once the other parent's contribution is out -- the
#      stochastic-gradient 2x2 normal-equations solve. ASYMMETRIC rank-1
#      residual-only injection: only channel c's coded residual is modified; the raw
#      parent rows are inputs left CLEAN (robustness INSIGHTS P3-refinement credits
#      the rank-1 subtract with; the retired energy-preserving iklt_adaptive rotation
#      corrupted both channels). Taps PERSIST across blocks (the selected pair is
#      stable within a recording -- P4-refinement -- so warm taps rarely see a
#      pair-change transient); a slot whose parent is absent has zero input, so its
#      tap is frozen and contributes nothing.
#   3. BOOTSTRAP: block 0 (no previous block to select from) uses the fixed grid
#      (up,left) pair -- the joint2 pair -- so the taps warm from t=0; block 1 on
#      re-selects. ZERO side-info (both the selected pair AND the taps are recomputed
#      by the decoder from bit-identical reconstructed history), look-ahead 0.
#
# Distinct from every relative on the axis each names decisive:
#   - vs RETIRED `xchan_multiparent`: summed MARGINAL betas double-count the parents'
#     shared mode; here a JOINT gradient (and a JOINT 2x2 LS at selection time) cannot.
#   - vs RETIRED `iklt_adaptive`: energy-preserving rotation corrupts both channels;
#     here the predictor is asymmetric, rank-1 residual-only, parents left clean.
#   - vs KEPT `xchan_joint2`: FIXED up+left pair -> per-channel per-block SELECTED pair.
#   - vs PROMOTED `bestpartner`/`bestpartner_adaptive`: single selected parent ->
#     jointly-solved selected PAIR (adds the second co-adapted tap on top of selection).
# Behind the spatial front-end: the order-4 sign-sign LMS temporal predictor
# (INSIGHTS P2, the promoted best's back-end) + adaptive Rice. Embeddable: +1 spatial
# tap + per-block pair re-selection on the order-4 base, zero side-info; clears the
# tight 125-cyc neural budget. Grounded in MPEG-4 ALS multichannel prediction / Choi
# et al. Sensors 2014 correlation-sorted channel pairing (paper-reported, unverified
# here). INSIGHTS open-frontier #1.
# ===========================================================================
JBP2_MAGIC = 0x4A42          # 'JB' (jointly-solved best pair)
JBP2_SHIFT = ec.CROSS_SHIFT  # fixed-point spatial-tap scale (matches the +xchan family)
JBP2_ORDER = LMS4_ORDER      # order-4 temporal base behind the spatial front-end (P2)
JBP2_BLOCK = ec.BLOCK        # re-selection block (aligns with the Rice block)


def _round_div(num, den):
    """Symmetric rounded integer divide round(num/den) for den > 0, integer-only
    (Python big-ints, so the 2x2-solve intermediates never overflow). Identical on
    encode and decode -- used only to rank candidate pairs at SELECTION time."""
    if num >= 0:
        return (num + den // 2) // den
    return -(((-num) + den // 2) // den)


def _jbp2_pair_resid(xc, xp, xq, shift=JBP2_SHIFT):
    """Residual of channel block xc under a JOINT 2x2 integer least-squares fit on
    the pair (xp, xq) over one previous block -- the marginal->multiple fix at
    SELECTION time (accounts for parent-parent covariance, so it cannot double-count
    the parents' shared mode the way the retired summed multiparent did). Returns
    the residual 1-D array, or None if the pair is degenerate/collinear (det<=0)."""
    xc = xc.astype(np.int64); xp = xp.astype(np.int64); xq = xq.astype(np.int64)
    Spp = int((xp * xp).sum()); Sqq = int((xq * xq).sum()); Spq = int((xp * xq).sum())
    Scp = int((xc * xp).sum()); Scq = int((xc * xq).sum())
    det = Spp * Sqq - Spq * Spq
    if det <= 0:
        return None
    a = _round_div((Scp * Sqq - Scq * Spq) << shift, det)   # fixed-point joint gains
    b = _round_div((Scq * Spp - Scp * Spq) << shift, det)
    a = max(-32768, min(32767, a)); b = max(-32768, min(32767, b))
    pred = (a * xp + b * xq) >> np.int64(shift)
    return xc - pred


def _jbp2_select_block(xc_prev, x, cands, ps, pe):
    """Backward per-block SELECTION of the best pair/single/none from the PREVIOUS
    raw block, scored in estimated Rice bits. Returns (pu, pl): a jointly-solved
    pair (both >=0), a single best-partner (pu>=0, pl=-1), or none (-1,-1). Fuses
    selection AND count -- count falls out of the scored search, so a useless second
    parent is not forced. Integer-only and deterministic, so encode and decode --
    both holding the bit-identical reconstructed previous block -- pick identically."""
    best_bits = _bp_score(xc_prev)                # option: no cross-channel parent
    best_pu, best_pl = -1, -1
    for p in cands:                               # single-parent options (marginal LS)
        b = _bp_opt_beta(xc_prev, x[p, ps:pe], BP_SHIFT)
        if b == 0:
            continue
        bits = _bp_score(xc_prev - ((b * x[p, ps:pe]) >> BP_SHIFT))
        if bits < best_bits:
            best_bits, best_pu, best_pl = bits, p, -1
    L = len(cands)                                # joint pair options (2x2 LS)
    for ii in range(L):
        for jj in range(ii + 1, L):
            resid = _jbp2_pair_resid(xc_prev, x[cands[ii], ps:pe], x[cands[jj], ps:pe])
            if resid is None:
                continue
            bits = _bp_score(resid)
            if bits < best_bits:
                best_bits, best_pu, best_pl = bits, cands[ii], cands[jj]
    return best_pu, best_pl


def _jbp2_forward(x, cols, B=JBP2_BLOCK, shift=JBP2_SHIFT):
    """Joint-solved SELECTED-pair spatial sign-sign LMS decorrelation. Per channel
    c and block i: the pair (pu,pl) is re-selected from the previous raw block
    (block 0 -> fixed grid (up,left) bootstrap); ONE joint 2-tap sign-sign LMS
    predicts x[c] from that pair, both taps co-adapting against the shared residual,
    taps PERSISTING across blocks. Only channel c's residual is coded; the raw
    parent rows are left clean. Integer-only, per-sample, look-ahead 0. Returns the
    cross-residual [C,N] int64."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    up, left = _xj2_parents(C, cols)
    nblocks = (N + B - 1) // B
    for c in range(C):
        cands = _bp_candidates(c, cols, C)
        if not cands:
            continue                              # grid origin: coded as-is
        xc = x[c]; yc = y[c]
        wu = wl = 0
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i == 0:
                pu, pl = int(up[c]), int(left[c])          # fixed-pair bootstrap
            else:
                pu, pl = _jbp2_select_block(x[c, (i - 1) * B:i * B], x, cands,
                                            (i - 1) * B, i * B)
            prow = x[pu] if pu >= 0 else None
            lrow = x[pl] if pl >= 0 else None
            for t in range(s, e):
                u = int(prow[t]) if prow is not None else 0
                l = int(lrow[t]) if lrow is not None else 0
                pred = (wu * u + wl * l) >> shift
                ev = int(xc[t]) - pred
                yc[t] = ev
                se = 1 if ev > 0 else (-1 if ev < 0 else 0)
                if prow is not None:
                    wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
                if lrow is not None:
                    wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return y


def _jbp2_inverse(y, cols, B=JBP2_BLOCK, shift=JBP2_SHIFT):
    """Invert _jbp2_forward. Every candidate parent has grid idx < c so its row is
    fully reconstructed before c; within a channel we rebuild raw block-by-block in
    time order, so block i-1 is restored before block i and the SAME per-block pair
    is re-selected from it, with the SAME persistent taps re-derived per sample from
    the shared residual e=y[c,t] and reconstructed parents -- mirroring the encoder
    bit-for-bit."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    up, left = _xj2_parents(C, cols)
    nblocks = (N + B - 1) // B
    for c in range(C):
        cands = _bp_candidates(c, cols, C)
        if not cands:
            continue
        yc = y[c]; xc = x[c]
        wu = wl = 0
        for i in range(nblocks):
            s, e = i * B, min((i + 1) * B, N)
            if i == 0:
                pu, pl = int(up[c]), int(left[c])
            else:
                pu, pl = _jbp2_select_block(x[c, (i - 1) * B:i * B], x, cands,
                                            (i - 1) * B, i * B)
            prow = x[pu] if pu >= 0 else None    # parent idx < c -> already reconstructed
            lrow = x[pl] if pl >= 0 else None
            for t in range(s, e):
                u = int(prow[t]) if prow is not None else 0
                l = int(lrow[t]) if lrow is not None else 0
                pred = (wu * u + wl * l) >> shift
                ev = int(yc[t])
                xc[t] = ev + pred
                se = 1 if ev > 0 else (-1 if ev < 0 else 0)
                if prow is not None:
                    wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
                if lrow is not None:
                    wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return x


def jbp2_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _jbp2_forward(x, cols)
    res = ec.lms_forward(y, order=JBP2_ORDER)    # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", JBP2_MAGIC, cols, C, N)   # NO side-info (backward-adaptive)
    return hdr + body


def jbp2_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == JBP2_MAGIC, "bad xchan_jointbp2 magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=JBP2_ORDER)    # matched order-4 inverse
    x = _jbp2_inverse(y, cols)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: regime-switched (context-gated) order-4 temporal predictor
# behind the proven best-partner spatial front-end
# (LMS4rs+Rice+xchan_bestpartner).
# ---------------------------------------------------------------------------
# INSIGHTS open-frontier #2: with every SPATIAL lever within ~1% of a shared
# ceiling, the remaining bits live in the TEMPORAL residual's OWN entropy. P5
# proved the coder and the Rice-parameter context are dead, so the residual
# entropy is set UPSTREAM, by the predictor. HD-sEMG is strongly non-stationary
# and bursty (quiescent baseline vs MUAP bursts): a SINGLE adaptive sign-LMS
# under-fits the high-variance burst segments, where most residual bits live,
# because one coefficient set must compromise between the two regimes' very
# different local AR statistics.
#
# Mechanism (novel axis vs everything shipped): keep the promoted order-4
# best-partner spatial front-end verbatim (_bp_select / _bp_inverse), but
# replace the single order-4 sign-sign LMS with a small BANK of order-4 sign-LMS
# predictors, one SELECTED PER SAMPLE by a backward-derived ACTIVITY REGIME:
#   * Per channel we keep two leaky integer integrators of |residual|: a FAST one
#     (window ~2^RSW_WR samples, "recent activity") and a SLOW one (window
#     ~2^RSW_WL, "long-term level"). Both are updated AFTER each sample from the
#     residual magnitude, so at sample t they summarise only residuals < t.
#   * The regime is a quantized bucket of recent-vs-long-term activity (recent
#     level below / around / above the long-term level -> quiescent / normal /
#     burst). Using recent RELATIVE to a backward long-term reference makes the
#     split scale-free (no per-dataset threshold, no side-info).
#   * Only the SELECTED regime's order-4 weights predict and adapt this sample;
#     each regime therefore accumulates coefficients matched to its OWN local AR
#     statistics, lowering the conditional residual variance H(e|regime) < H(e).
#   * The regime at t depends only on causally-available reconstructed residuals,
#     which the decoder reproduces bit-for-bit (it reads e[t] from the stream),
#     so the decoder mirrors the SAME regime and the SAME per-regime updates ->
#     ZERO side-info, fully causal, look-ahead 0 (INSIGHTS P4). Order stays 4 per
#     P2; only the NUMBER of coefficient sets grows (RSW_NREG small = 3).
#
# Distinct from the RETIRED cross-channel-context Rice (`LMS+Rice+xctx`, P5):
# that conditioned the Rice PARAMETER k on a neighbour-energy context and left
# the residual itself unchanged (H(e|neighbour energy) ~= H(e) after LMS, so it
# lost). This conditions the PREDICTOR COEFFICIENTS on a TEMPORAL activity
# regime, reducing the residual UPSTREAM of the coder -- a different quantity on
# a different axis. NOT an entropy back-end swap (coder stays adaptive Rice).
# Grounded in adaptive switching linear prediction (Seemann & Tischer) and
# context-dependent MAE-minimizing prediction (Ulacha 2024) (paper-reported,
# unverified here).
# ===========================================================================
RSBP_MAGIC = 0x5253          # 'RS' (regime-switched best-partner)
RSW_ORDER = LMS4_ORDER       # order-4 temporal predictor (INSIGHTS P2), unchanged
RSW_SHIFT = ec.LMS_SHIFT     # fixed-point weight scale, same as the family LMS (8)
RSW_NREG = 3                 # predictor-bank size: quiescent / normal / burst (small, P2)
RSW_WR = 4                   # fast (recent) leaky-energy window ~2^4 samples
RSW_WL = 9                   # slow (long-term) leaky-energy window ~2^9 samples


def _rsw_regime(recent, long_):
    """Per-channel activity regime from the backward leaky energy integrators.
    Compares the recent level (recent >> RSW_WR) against the long-term level
    (long_ >> RSW_WL) via cross-multiplication so the test is exact integer
    arithmetic with no precision loss:
        recent/2^WR  <  3/4 * long_/2^WL   -> regime 0 (quiescent)
        recent/2^WR  >  3/2 * long_/2^WL   -> regime 2 (burst)
        otherwise                          -> regime 1 (normal)
    Both accumulators are >= 0 (they accumulate |e| and subtract a non-negative
    leak), so the shifts are floors on non-negative int64 -- deterministic and
    identical on encode and decode. Bootstrap (both 0) -> regime 1."""
    A = recent << np.int64(RSW_WL)          # recent level on the common 2^(WR+WL) scale
    B = long_ << np.int64(RSW_WR)           # long-term level on the same scale
    r = np.ones(recent.size, np.int64)      # default: normal
    r[4 * A < 3 * B] = 0                     # recent < 0.75 * long  -> quiescent
    r[2 * A > 3 * B] = 2                     # recent > 1.5  * long  -> burst
    return r


def _rsw_forward(x, order=RSW_ORDER, shift=RSW_SHIFT, nreg=RSW_NREG):
    """Regime-switched sign-sign LMS: a bank of `nreg` order-`order` predictors,
    one selected per sample-channel by the backward activity regime. Vectorized
    over channels; mirrors ec.lms_forward except for the per-sample bank pick."""
    C, N = x.shape
    x = x.astype(np.int64)
    w = np.zeros((C, nreg, order), np.int64)   # per-channel per-regime weights
    hist = np.zeros((C, order), np.int64)      # shared past reconstructed samples
    recent = np.zeros(C, np.int64)             # fast leaky |e| integrator
    long_ = np.zeros(C, np.int64)              # slow leaky |e| integrator
    res = np.empty((C, N), np.int64)
    ci = np.arange(C)
    for t in range(N):
        r = _rsw_regime(recent, long_)         # regime from residuals < t
        wsel = w[ci, r, :]                     # [C, order] selected bank
        pred = (wsel * hist).sum(axis=1) >> shift
        e = x[:, t] - pred
        res[:, t] = e
        # adapt ONLY the selected regime's weights (identical rule in decoder)
        w[ci, r, :] = wsel + np.sign(e)[:, None] * np.sign(hist)
        ae = np.abs(e)
        recent += ae - (recent >> np.int64(RSW_WR))
        long_ += ae - (long_ >> np.int64(RSW_WL))
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = x[:, t]
    return res


def _rsw_inverse(res, order=RSW_ORDER, shift=RSW_SHIFT, nreg=RSW_NREG):
    """Exact inverse of _rsw_forward. Reconstructs x[:, t] = pred + e where the
    regime, bank selection and per-regime update are recomputed from the SAME
    causally-available residuals the encoder used -> zero side-info."""
    C, N = res.shape
    res = res.astype(np.int64)
    w = np.zeros((C, nreg, order), np.int64)
    hist = np.zeros((C, order), np.int64)
    recent = np.zeros(C, np.int64)
    long_ = np.zeros(C, np.int64)
    x = np.empty((C, N), np.int64)
    ci = np.arange(C)
    for t in range(N):
        r = _rsw_regime(recent, long_)
        wsel = w[ci, r, :]
        pred = (wsel * hist).sum(axis=1) >> shift
        e = res[:, t]
        xt = pred + e
        x[:, t] = xt
        w[ci, r, :] = wsel + np.sign(e)[:, None] * np.sign(hist)
        ae = np.abs(e)
        recent += ae - (recent >> np.int64(RSW_WR))
        long_ += ae - (long_ >> np.int64(RSW_WL))
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = xt
    return x


def rsbp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)     # proven best-partner front-end
    res = _rsw_forward(xt)                        # regime-switched order-4 sign-LMS
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", RSBP_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def rsbp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == RSBP_MAGIC, "bad regime-switched bestpartner codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = _rsw_inverse(res)
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)


# ===========================================================================
# NEW candidate: max-MI (Chow-Liu) SPANNING-TREE channel topology
# (LMS4+Rice+xchan_mst).
# ---------------------------------------------------------------------------
# Every registered spatial front-end inherits the RASTER-CAUSAL parent set:
# `_bp_candidates` offers channel c only {left, up, up-left, up-right} -- the
# four 8-neighbours whose grid index is < c. That restriction exists purely so
# the decoder can walk channels in INDEX order; it is not a property of the
# array. Structurally it throws away exactly half the 8-neighbourhood (right,
# down, down-left, down-right), and the per-channel GREEDY pick under an
# arbitrary scan order is not the optimal parent structure even among the
# parents it can see. Row 0 has only `left`; column 0 has only up/up-right; and
# any channel whose strongest correlate happens to lie LATER in raster order is
# forced onto a strictly weaker parent. That loss is structural, not a tuning
# issue.
#
# Chow & Liu (IEEE Trans. IT, 1968) settle what the right structure is: among
# all tree factorizations of a joint distribution, the MAXIMUM-WEIGHT SPANNING
# TREE under pairwise-MUTUAL-INFORMATION edge weights is the one minimizing KL
# divergence to the true joint -- i.e. exactly the entropy-minimizing rank-1
# dependency structure the current front-end is greedily approximating. Under a
# Gaussian model the edge weight is -1/2 log(1-rho^2), so the MST maximizes the
# total REMOVABLE MI over all trees. This codec replaces the raster parent set
# with that tree.
#
# Mechanism (backward-adaptive, zero side-info -- INSIGHTS P4):
#   * CANDIDATE GRAPH: the undirected 8-neighbourhood of the electrode grid
#     (each adjacent pair once, diagonals included) -- ~4 edges per channel, a
#     bounded ~2x the incumbent's 4 raster candidates. NOT the complete graph:
#     embeddability caps the edge set (see cost_model.md).
#   * EDGE WEIGHT (integer, backward): over the PREVIOUS already-reconstructed
#     RAW block, for BOTH orientations of edge (u,v) derive the integer
#     least-squares gain (`_bp_opt_beta`, verbatim) and measure the CODED-BIT
#     SAVING in estimated Rice bits (`_bp_score`, verbatim):
#         w(u,v) = max(0, bits(u) - bits(u - b_uv*v)) + max(0, bits(v) - bits(v - b_vu*u))
#     A directional coded-bit saving is the operational estimate of N*I(u;v)
#     (bits actually removable by a rank-1 subtract); summing the two
#     orientations gives a SYMMETRIC estimator -- the integer stand-in for
#     Chow-Liu's symmetric MI -- and clamping each at 0 mirrors I >= 0. No
#     float, no division beyond the rounded integer LS ratio.
#   * TREE: Kruskal + union-find over those integer weights (descending weight,
#     ties broken by (u,v) index -- fully deterministic), giving the max-weight
#     spanning tree of the 8-neighbour graph. Root at the lowest-index node of
#     each component and orient edges away from the root by BFS (neighbours
#     visited in ascending index) -> a `parent[]` array plus a topological
#     channel ORDER. Rooting is free in Chow-Liu: any rooting of the same
#     undirected tree is the same factorization.
#   * SUBTRACT: one rank-1 adaptive subtract per TREE EDGE, applied to the
#     CURRENT block, y[c] = x[c] - ((beta_c * x[parent(c)]) >> shift), with
#     beta_c the same previous-block integer-LS gain already scored for that
#     orientation; if that orientation's saving was <= 0 the edge is coded with
#     beta = 0 (channel as-is), the tree structure being unchanged. Every
#     channel keeps EXACTLY ONE parent.
#   * CAUSALITY / ZERO SIDE-INFO: the tree is derived only from block i-1, which
#     the decoder holds bit-identically (lossless), so it rebuilds the IDENTICAL
#     tree and gains -- nothing is transmitted, look-ahead 0. Because a parent
#     may now have a HIGHER index than its child, the decoder inverts block i in
#     TREE ORDER (root -> leaves) instead of index order; each parent's block-i
#     raw samples are restored before its children read them. Block 0 bootstraps
#     to no parent (coded as-is), exactly like `bestpartner_adaptive`.
#
# NOT a re-proposal of anything registered or retired -- the new axis is the
# parent GRAPH (topology), not the gain, the count, or the time offset:
#   - vs PROMOTED `bestpartner` / `bestpartner_adaptive`: same rank-1 subtract,
#     same integer-LS gain, same Rice-bit scoring -- but the parent set is the
#     FULL 8-neighbourhood and the structure is globally optimal over trees
#     rather than greedy per channel under a raster order. Restricting the
#     candidate graph to the raster half-neighbourhood and forcing index-order
#     traversal would collapse this back toward `bestpartner_adaptive`.
#   - vs `xchan_lag` (this cycle): that moves the parent in TIME (lag d); this
#     moves it in the channel GRAPH. Orthogonal, both rank-1.
#   - vs `xchan_joint2` / `xchan_jointbp2` (HOW MANY parents): the subtract stays
#     strictly RANK-1 -- one parent, one gain per channel -- so this is NOT the
#     P3 multi-tap-transform dead end.
#   - vs RETIRED `xchan_multiparent` (summed marginal betas -> over-subtract):
#     each channel still has exactly ONE parent, so no shared mode is
#     double-counted (INSIGHTS P1b).
#   - vs RETIRED `iklt` / `iklt_adaptive`: no rotation; the subtract is
#     asymmetric, injecting estimation noise only into the child's residual
#     while the parent row stays clean (INSIGHTS P3 refinement).
#   - temporal back-end UNCHANGED: order-4 sign-sign LMS + adaptive Rice
#     (INSIGHTS P2/P5). Nothing is spent on the temporal or entropy axes.
#
# EMBEDDABILITY (cost_model.md): the edge set is the 8-neighbourhood, so the
# per-block backward scan is ~2x `bestpartner_adaptive`'s (~4 incident edges x 2
# orientations per channel vs 4 candidates); Kruskal/union-find over ~4C edges
# (~500 at 128 ch) is <0.05 ops/sample-ch amortised over a 256-sample block;
# all comparisons are integer bit-counts. Extra persistent state over the
# order-4 LMS base is parent id + traversal position + the int16 gain (~4 B/ch,
# ~0.5 KB at 128 ch). PORT NOTE (flagged, not hidden): decoding follows a tree
# traversal, so channel access is a PERMUTATION -- indirect BRAM addressing on
# the Spartan-7 (cheap, but no longer a linear channel sweep); the ENCODER, which
# is what runs on-node, still touches channels in any order it likes.
#
# FALSIFIABLE PREDICTIONS to measure: the gain should be largest where the
# raster restriction bites hardest -- boundary-heavy geometries and arrays whose
# dominant correlate is anisotropic (not aligned with the scan). If the raster
# half-neighbourhood already contains each channel's best correlate, the MST
# degenerates toward the greedy parent set and the gain is ~0 at ~2x selection
# cost, which would be a clean negative.
#
# CITATIONS (paper-reported, unverified here): Chow & Liu, "Approximating
# discrete probability distributions with dependence trees", IEEE Trans. IT
# 14(3):462-467, 1968; correlation-driven rather than geometry-driven channel
# grouping in biosignals -- "Efficient lossless multi-channel EEG compression
# based on channel clustering" (Biomed. Signal Process. Control, 2016) and
# "Low-complexity lossless multichannel ECG compression based on selective
# linear prediction" (2019), the latter being the single-parent-selection
# analogue already shipped here -- the tree is its global-optimality upgrade.
# ===========================================================================
XMST_MAGIC = 0x544D        # 'MT' (max-MI spanning-tree channel topology)
XMST_BLOCK = ec.BLOCK      # tree-rebuild block (aligns with the Rice block)
XMST_ORDER = LMS4_ORDER    # order-4 temporal base behind the spatial front-end (P2)


def _xmst_edges(C, cols):
    """Undirected 8-neighbour candidate edge set of the electrode grid, each
    adjacent pair listed exactly once (right, down-left, down, down-right from
    every channel). Bounded at ~4 edges/channel -- the embeddability cap that
    keeps this a Chow-Liu tree over a SPARSE graph, not the complete graph."""
    cols = max(1, int(cols))
    edges = []
    for g in range(C):
        r, c = divmod(g, cols)
        for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
            rr, cc = r + dr, c + dc
            if cc < 0 or cc >= cols:
                continue
            h = rr * cols + cc
            if h < C:
                edges.append((g, h))
    return edges


def _xmst_dir_gain(xc_prev, xp_prev, base_bits):
    """Directional (beta, coded-bit saving) for predicting channel c from parent
    p over the previous block: the integer least-squares gain (`_bp_opt_beta`)
    and how many estimated Rice bits the rank-1 subtract removes (`_bp_score`).
    The saving is the operational integer estimate of N*I(c;p) -- bits actually
    removable by a rank-1 subtract. Integer-only and deterministic."""
    b = _bp_opt_beta(xc_prev, xp_prev, BP_SHIFT)
    if b == 0:
        return 0, 0
    resid = xc_prev - ((b * xp_prev) >> BP_SHIFT)
    return b, base_bits - _bp_score(resid)


def _xmst_kruskal(C, wedges):
    """Maximum-weight spanning tree by Kruskal + union-find over integer edge
    weights. Edges are taken in descending weight with ties broken by (u, v)
    index, so the tree is a deterministic function of the previous block alone
    -- encoder and decoder, holding bit-identical history, build the same one.
    Returns the adjacency list of the chosen (undirected) tree edges."""
    par = list(range(C))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]        # path halving
            a = par[a]
        return a

    adj = [[] for _ in range(C)]
    for w, u, v in sorted(wedges, key=lambda t: (-t[0], t[1], t[2])):
        ru, rv = find(u), find(v)
        if ru != rv:
            par[ru] = rv
            adj[u].append(v)
            adj[v].append(u)
    return adj


def _xmst_root(adj, C):
    """Root the undirected tree and orient its edges away from the root: BFS
    from the lowest-index node of each component, neighbours visited in
    ascending index. Returns (parent[], order) where order lists every channel
    AFTER its parent -- the traversal the decoder inverts in. Rooting is free in
    Chow-Liu: any rooting of the same undirected tree is the same factorization
    (a disconnected candidate graph simply yields several roots)."""
    parent = np.full(C, -1, np.int64)
    order = []
    seen = [False] * C
    for root in range(C):
        if seen[root]:
            continue
        seen[root] = True
        order.append(root)
        queue = [root]
        qi = 0
        while qi < len(queue):
            u = queue[qi]
            qi += 1
            for v in sorted(adj[u]):
                if not seen[v]:
                    seen[v] = True
                    parent[v] = u
                    order.append(v)
                    queue.append(v)
    return parent, order


def _xmst_block_tree(x, ps, pe, edges, C):
    """Rebuild the Chow-Liu max-MI spanning tree for one block from the PREVIOUS
    already-reconstructed RAW block x[:, ps:pe]. Returns (parent, betas, order):
    parent[c] = tree parent (-1 for a root), betas[c] = the integer gain of that
    tree edge (0 if the subtract does not pay), order = root->leaf traversal.
    Integer-only and deterministic -> encoder and decoder derive it identically
    and NOTHING is transmitted."""
    prev = x[:, ps:pe]
    base = [_bp_score(prev[c]) for c in range(C)]
    dgain = {}
    wedges = []
    for (u, v) in edges:
        b_uv, s_uv = _xmst_dir_gain(prev[u], prev[v], base[u])   # u predicted from v
        b_vu, s_vu = _xmst_dir_gain(prev[v], prev[u], base[v])   # v predicted from u
        dgain[(u, v)] = (b_uv, s_uv)        # key = (child, parent)
        dgain[(v, u)] = (b_vu, s_vu)
        # symmetric integer MI proxy: both orientations' removable bits, clamped
        # at 0 (mutual information is non-negative; a negative saving is noise)
        wedges.append(((s_uv if s_uv > 0 else 0) + (s_vu if s_vu > 0 else 0), u, v))
    parent, order = _xmst_root(_xmst_kruskal(C, wedges), C)
    betas = np.zeros(C, np.int64)
    for c in range(C):
        p = int(parent[c])
        if p >= 0:
            b, s = dgain[(c, p)]
            if s > 0:                        # only subtract when it pays
                betas[c] = b
    return parent, betas, order


def _xmst_forward(x, cols, B=XMST_BLOCK):
    """Spanning-tree cross-channel decorrelation. Block i's tree + gains come
    from the PREVIOUS raw block (block 0 -> no parent, coded as-is); one rank-1
    subtract per tree edge is applied to block i of the RAW signal. The encoder
    reads only raw channels, so it needs no traversal order."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    if C < 2:
        return y
    edges = _xmst_edges(C, cols)
    nblocks = (N + B - 1) // B
    for i in range(1, nblocks):
        s, e = i * B, min((i + 1) * B, N)
        parent, betas, _ = _xmst_block_tree(x, (i - 1) * B, i * B, edges, C)
        for c in range(C):
            p, b = int(parent[c]), int(betas[c])
            if p >= 0 and b != 0:
                y[c, s:e] = x[c, s:e] - ((b * x[p, s:e]) >> BP_SHIFT)
    return y


def _xmst_inverse(y, cols, B=XMST_BLOCK):
    """Invert _xmst_forward. A tree parent may have a HIGHER index than its
    child, so blocks are rebuilt in TREE ORDER (root -> leaves) rather than
    channel order: each parent's block-i raw samples are restored before its
    children read them. Block i-1 is fully reconstructed for every channel
    before block i's tree is rebuilt from it, so the decoder derives the SAME
    tree and gains as the encoder."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    if C < 2:
        return x
    edges = _xmst_edges(C, cols)
    nblocks = (N + B - 1) // B
    for i in range(1, nblocks):
        s, e = i * B, min((i + 1) * B, N)
        parent, betas, order = _xmst_block_tree(x, (i - 1) * B, i * B, edges, C)
        for c in order:
            p, b = int(parent[c]), int(betas[c])
            if p >= 0 and b != 0:
                x[c, s:e] = y[c, s:e] + ((b * x[p, s:e]) >> BP_SHIFT)
    return x


def xmst_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _xmst_forward(x, cols)                       # Chow-Liu tree front-end
    res = ec.lms_forward(y, order=XMST_ORDER)        # order-4 sign-sign LMS (P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", XMST_MAGIC, cols, C, N)   # NO tree/beta side-info
    return hdr + body


def xmst_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XMST_MAGIC, "bad spanning-tree cross-channel codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=XMST_ORDER)        # matched order-4 inverse
    x = _xmst_inverse(y, cols)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: CONTEXT BIAS-CANCELLATION two-stage predictor
# (LMS4bc+Rice+xchan_bestpartner) -- a JPEG-LS/CALIC-style per-context running-mean
# corrector bolted onto the promoted order-4 sign-sign LMS.
# ---------------------------------------------------------------------------
# THE TEMPORAL LEVER (INSIGHTS frontier #2), deliberately a different axis from the
# spatial candidates in this cycle.
#
# WHY THERE IS ANYTHING LEFT. A linear predictor whitens only to SECOND order: it can
# zero E[e * x[t-i]] for its taps, but nothing forces the CONDITIONAL mean E[e | ctx]
# to vanish for a nonlinear function of the past. Worse, the shipped predictor is
# SIGN-SIGN LMS, which is not even MMSE-optimal -- it descends a sign-gradient
# (signed-error x signed-regressor) criterion whose fixed point is offset from the
# Wiener solution, and its constant +-1 weight steps never settle, leaving a
# persistent MISADJUSTMENT. Both effects leave the residual with a small but
# systematic CONTEXT-DEPENDENT DC term. Since H(e) >= H(e - E[e|ctx]) (subtracting a
# causally-known constant per context cannot raise entropy, and strictly lowers the
# second moment by E[mu_ctx^2]), removing that DC shortens the Rice code by about
# 1/2 * log2(1 + E[mu^2]/sigma^2) bits/sample. This is precisely the mechanism behind
# JPEG-LS's per-context bias corrector (Weinberger, Seroussi & Sapiro, LOCO-I) and
# CALIC's context error feedback (paper-reported, unverified here), which is where
# their measurable gain over the bare MED predictor comes from.
#
# MECHANISM (two stages, both backward-adaptive, zero side-info):
#   stage 1 - the incumbent order-4 sign-sign LMS, UNCHANGED: e[t] = x[t] - pred[t].
#   stage 2 - d[t] = e[t] - mu[c, ctx[t]], where mu is a per-(channel, context)
#             running mean of the raw stage-1 residual, held as a leaky integrator
#             S += e - (S >> BC_MU_W) and read back as mu = (S + half) >> BC_MU_W.
#             Shift-divide only: NO multiplies and NO divides in the corrector.
#   The Rice back-end codes d. The LMS adaptation and history still use the
#   PRE-correction e (the decoder recovers e = d + mu before updating), so stage 1 is
#   bit-identical to `LMS4+Rice+xchan_bestpartner`'s predictor and stage 2 is a pure
#   ADDITIVE second stage -- the predictor's FUNCTIONAL FORM gains a nonlinear
#   conditional-mean term, which is exactly the change P2 demands (not more taps, not
#   more coefficient sets).
#
# CONTEXT (30 buckets, <= 32): the quantized last two residuals plus one cross-channel
# sign bit -- q5(e[t-1]) x q3(e[t-2]) x sign(d[parent, t-1]). Quantizer thresholds are
# 0.5x and 1.5x the channel's backward leaky mean |e|, so the buckets are SCALE-FREE
# and stay meaningful across bursts and quiescence. The parent bit is taken at LAG 1
# (the parent's already-coded residual) so the per-sample update stays a single
# vectorized channel sweep with no intra-sample channel chain -- strictly causal on
# both sides.
#
# WHY THIS IS NOT A RETIRED LEVER (stated explicitly):
#   * `LMS+Rice+xctx` (retired, cycle 9) conditioned the RICE SCALE PARAMETER k on a
#     cross-channel energy context. It lost because adaptive-k already tracks scale
#     and the extra model is pure loss (P5). Here the CODER IS UNTOUCHED -- one
#     global adaptive-Rice back-end, no context-split frequency table, no k model.
#     What is conditioned is a FIRST MOMENT of the residual, upstream of the coder;
#     P5's finding was about the second moment / the code's parameter.
#   * `LMS4rs+Rice+xchan_bestpartner` (retired, cycle 14) forked WHOLE COEFFICIENT
#     SETS by activity regime. It lost because it fragments the adaptation and fits
#     noise (P2). Here there is exactly ONE global predictor and ONE weight set,
#     adapting on every sample as before; the context indexes a single scalar mean,
#     the cheapest possible statistic, which cannot fragment the predictor's learning.
#   * Not a spatial mechanism at all: the proven best-partner front-end (`_bp_select`
#     / `_bp_inverse`) is reused VERBATIM, identical side-info, identical inverse.
#
# EMBEDDABILITY (cost_model.md): one int32 accumulator per bucket (30 x 4 B = 120 B/ch,
# ~15 KB at 128 ch), a handful of compares to form the context, one gather, one
# shift-add to read mu, one add/shift/sub to update it. No multiplies, no divides, no
# look-ahead, ZERO side-info (the decoder rebuilds every table from reconstructed
# history), so it fits both the 2 kS/s and the tight 30 kHz budgets.
#
# HONEST RISK (recorded before measuring): P5 already found the post-LMS residual
# near-white, so E[mu^2]/sigma^2 may be tiny; the estimator itself injects variance
# ~sigma^2/(2^BC_MU_W) per bucket, which can EXCEED the bias it removes. The image-
# coding analogy suggests only ~1-2%. A clean negative here would be a genuine result:
# it would show the sign-sign misadjustment leaves no exploitable conditional mean.
# ===========================================================================
BC_MAGIC = 0x4342        # 'BC' (context bias-cancellation)
BC_ORDER = LMS4_ORDER    # order-4 temporal predictor (INSIGHTS P2), unchanged
BC_SHIFT = ec.LMS_SHIFT  # fixed-point weight scale, same as the family LMS (8)
BC_MU_W = 5              # leaky window (2^5 = 32 hits) of the per-context mean
BC_MU_RND = 1 << (BC_MU_W - 1)   # round-half-up constant for the mu read-back
BC_ABS_W = 6             # leaky window (2^6) of the per-channel mean-|e| scale
BC_NQ1 = 5               # quantizer levels for e[t-1]
BC_NQ2 = 3               # quantizer levels for e[t-2]
BC_NCTX = BC_NQ1 * BC_NQ2 * 2    # 30 context buckets (<= 32)


def _bc_context(e1, e2, sabs, dpar):
    """Context index in [0, BC_NCTX) from causally-available data only.

    Thresholds come from the channel's backward leaky mean |e| (T = sabs>>BC_ABS_W,
    always >= 0), so the quantizer is SCALE-FREE -- a residual counts as "large"
    relative to the channel's own current activity, not an absolute number:
        q1(e[t-1]) in 0..4  : < -1.5T, < -0.5T, |.| <= 0.5T, <= 1.5T, > 1.5T
        q2(e[t-2]) in 0..2  : < -0.5T, within, > 0.5T
        s          in 0..1  : sign of the PARENT channel's previous coded residual
    Bootstrap (T = 0) degenerates to plain signs, deterministically and identically
    on both sides. All integer compares -- no multiplies, no divides."""
    T = sabs >> np.int64(BC_ABS_W)
    t1 = T >> np.int64(1)            # 0.5 * mean|e|
    t2 = T + t1                      # 1.5 * mean|e|
    q1 = np.full(e1.size, 2, np.int64)
    q1[e1 < -t1] = 1
    q1[e1 < -t2] = 0
    q1[e1 > t1] = 3
    q1[e1 > t2] = 4
    q2 = np.ones(e2.size, np.int64)
    q2[e2 < -t1] = 0
    q2[e2 > t1] = 2
    s = (dpar < 0).astype(np.int64)
    return (q1 * BC_NQ2 + q2) * 2 + s


def _bc_forward(x, parents, order=BC_ORDER, shift=BC_SHIFT):
    """Order-4 sign-sign LMS (stage 1, verbatim rule) + per-context running-mean
    bias cancellation (stage 2). Returns the CORRECTED residual d that gets Rice-
    coded. Vectorized over channels; the corrector is a gather/scatter on one
    accumulator per (channel, context)."""
    C, N = x.shape
    x = x.astype(np.int64)
    par = np.asarray(parents, np.int64)
    has_par = par >= 0
    psrc = np.where(has_par, par, 0)           # safe gather index for root channels
    w = np.zeros((C, order), np.int64)
    hist = np.zeros((C, order), np.int64)      # past reconstructed samples
    S = np.zeros((C, BC_NCTX), np.int64)       # per-context leaky bias accumulators
    sabs = np.zeros(C, np.int64)               # leaky mean-|e| scale (context thresholds)
    e1 = np.zeros(C, np.int64)                 # raw residual e[t-1]
    e2 = np.zeros(C, np.int64)                 # raw residual e[t-2]
    dprev = np.zeros(C, np.int64)              # CODED residual d[t-1] (per channel)
    res = np.empty((C, N), np.int64)
    ci = np.arange(C)
    for t in range(N):
        pred = (w * hist).sum(axis=1) >> shift
        e = x[:, t] - pred                      # stage-1 (LMS) residual
        ctx = _bc_context(e1, e2, sabs, np.where(has_par, dprev[psrc], 0))
        acc = S[ci, ctx]
        mu = (acc + BC_MU_RND) >> np.int64(BC_MU_W)     # E[e|ctx], shift-divide
        d = e - mu                              # stage-2 (bias-cancelled) residual
        res[:, t] = d
        # running-mean update on the RAW residual -> mu tracks E[e|ctx] directly
        S[ci, ctx] = acc + e - (acc >> np.int64(BC_MU_W))
        # stage-1 adaptation is UNCHANGED: it sees the pre-correction e
        w += np.sign(e)[:, None] * np.sign(hist)
        sabs += np.abs(e) - (sabs >> np.int64(BC_ABS_W))
        e2 = e1
        e1 = e
        dprev = d
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = x[:, t]
    return res


def _bc_inverse(res, parents, order=BC_ORDER, shift=BC_SHIFT):
    """Exact inverse of _bc_forward. The decoder holds d[t] from the stream, forms
    the SAME context from data strictly before t, reads the SAME mu, and recovers
    e = d + mu -- so every table (weights, accumulators, scale) updates identically
    on both sides from causally-available data. Zero side-info."""
    C, N = res.shape
    res = res.astype(np.int64)
    par = np.asarray(parents, np.int64)
    has_par = par >= 0
    psrc = np.where(has_par, par, 0)
    w = np.zeros((C, order), np.int64)
    hist = np.zeros((C, order), np.int64)
    S = np.zeros((C, BC_NCTX), np.int64)
    sabs = np.zeros(C, np.int64)
    e1 = np.zeros(C, np.int64)
    e2 = np.zeros(C, np.int64)
    dprev = np.zeros(C, np.int64)
    x = np.empty((C, N), np.int64)
    ci = np.arange(C)
    for t in range(N):
        pred = (w * hist).sum(axis=1) >> shift
        ctx = _bc_context(e1, e2, sabs, np.where(has_par, dprev[psrc], 0))
        acc = S[ci, ctx]
        mu = (acc + BC_MU_RND) >> np.int64(BC_MU_W)
        d = res[:, t]
        e = d + mu                              # undo stage 2
        xt = pred + e                           # undo stage 1
        x[:, t] = xt
        S[ci, ctx] = acc + e - (acc >> np.int64(BC_MU_W))
        w += np.sign(e)[:, None] * np.sign(hist)
        sabs += np.abs(e) - (sabs >> np.int64(BC_ABS_W))
        e2 = e1
        e1 = e
        dprev = d
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = xt
    return x


def bcbp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)     # proven best-partner front-end (verbatim)
    res = _bc_forward(xt, parents)               # LMS4 + per-context bias cancellation
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", BC_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def bcbp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == BC_MAGIC, "bad context-bias-cancellation codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = _bc_inverse(res, parents)               # matched two-stage inverse
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: context-conditioned integer BIAS CANCELLATION on the prediction
# (LMS4bc+Rice+xchan_bestpartner) -- INSIGHTS open-frontier #2, the TEMPORAL lever.
# ---------------------------------------------------------------------------
# The incumbent LMS4+Rice+xchan_bestpartner whitens each channel with a LINEAR
# predictor (order-4 sign-sign LMS) after a rank-1 cross-channel subtract. A
# linear predictor can only zero LINEAR correlations: it drives E[e_t * h] -> 0
# for h in the span of its taps, but it says NOTHING about E[e_t | f(history)]
# for a NON-LINEAR f. Any surviving conditional mean is first-order-removable
# structure that no linear predictor of ANY order can represent (so P2's
# saturation result -- a statement about the linear class -- does not cover it),
# and by the law of total variance removing it lowers the residual variance by
# exactly Var(E[e|ctx]) => shorter Rice codes.
#
# Physical basis for expecting a non-zero conditional mean here: MUAPs are
# asymmetric biphasic waveforms and motor-unit firing is bursty, so residual
# SIGN RUNS are informative; and the NON-normalised sign-sign LMS update (a fixed
# +/-1 step per tap) lags during amplitude transients, leaving a context-dependent
# DC in the residual exactly when the signal is changing fast.
#
# MECHANISM (LOCO-I / JPEG-LS bias cancellation, Weinberger-Seroussi-Sapiro,
# IEEE TIP 2000, ported from the image raster to the electrode array x time):
# after the LMS prediction, subtract an integer correction B[ctx] learned by a
# running (sum, count) accumulator per context. Contexts are a tiny quantisation
# of the causal residual field:
#     ctx = (sgn e[g,t-1], sgn e[g,t-2], sgn e[parent(g), t])  -> 3*3*3 = 27
# i.e. the signs of the last two OWN-channel residuals x the sign of the
# co-located (same time slice) residual of the channel's already-selected
# best-partner parent. parent(g) < g by construction, so within a time slice the
# parent's residual is decoded before the child's -- causal and streaming-legal.
# Channels whose best-partner selection chose NO parent use sgn = 0 (9 live
# contexts). ZERO side-info: the decoder rebuilds every context and every
# accumulator from the residuals it has already reconstructed (INSIGHTS P4).
#
# The correction is tracked DIVISIONLESS, exactly as JPEG-LS does it: per context
# keep (B = running sum of coded residuals, N = count, C = the current integer
# correction). After each sample B += d, N += 1; at N == BIAS_RESET both are
# HALVED BY A SHIFT (this is the counter-halving that keeps the estimate local
# AND keeps the arithmetic to shifts -- no SDIV anywhere on the node), and C is
# nudged by +/-1 whenever the running sum leaves the band (-N, 0]. So C converges
# to round(mean residual | ctx) without ever dividing, and is bounded to int8.
#
# WHY THIS IS NOT A RETIRED MECHANISM (required disclosure):
#   * NOT LMS4rs (retired, cycle 14): that forked whole predictor COEFFICIENT
#     SETS per activity regime, splitting the adaptation data across 3 banks --
#     P2's named failure. Here the linear predictor stays SINGLE and adapts on
#     EVERY sample exactly as the incumbent does (the LMS pass is byte-identical
#     to LMS4+Rice+xchan_bestpartner's); only a scalar additive DC per context is
#     learned on top, and a scalar mean estimate needs orders of magnitude fewer
#     samples than a 4-tap filter.
#   * NOT xctx (retired, cycle 9): that conditioned the Rice PARAMETER k -- a
#     back-end lever P5 declared spent, leaving the residual itself untouched.
#     This changes the PREDICTION (the residual stream that reaches the coder is
#     genuinely different), which is the upstream place P5 directs spending.
#
# The spatial front-end (_bp_select/_bp_inverse) and the order-4 LMS are reused
# VERBATIM, so this is a clean A/B on the incumbent: the only difference is the
# bias-cancellation stage between the LMS and the Rice coder.
# ===========================================================================
BIAS_MAGIC = 0x4243     # 'BC'
BIAS_ORDER = LMS4_ORDER  # temporal predictor stays order-4 (INSIGHTS P2)
BIAS_NCTX = 27          # 3 (sgn e[t-1]) x 3 (sgn e[t-2]) x 3 (sgn parent e[t])
BIAS_RESET = 64         # JPEG-LS counter-halving threshold (shift, never a divide)
BIAS_CLAMP = 128        # correction bounded to int8: C in [-128, 127]


def _bias_new_state():
    """Per-channel bias state: (B = running residual sum, N = count, C = the
    integer prediction correction) per context. N starts at 1 (JPEG-LS) so the
    band test is well-defined from the first sample; C starts at 0 = identity."""
    return ([0] * BIAS_NCTX, [1] * BIAS_NCTX, [0] * BIAS_NCTX)


def _bias_update(st, q, d):
    """JPEG-LS divisionless bias update for context q given the CODED residual d
    (the error after the correction was applied). Run identically by encoder and
    decoder -- both have d -- so the two stay a matched pair. Only adds, compares
    and arithmetic shifts: no divide, no multiply."""
    B, Ncnt, Ccor = st
    b = B[q] + d
    n = Ncnt[q] + 1
    if n >= BIAS_RESET:                       # counter halving -> keeps the mean
        b = (b >> 1) if b >= 0 else -((1 - b) >> 1)   # local and the state small
        n >>= 1
    c = Ccor[q]
    if b <= -n:                               # running mean below the band -> C--
        if c > -BIAS_CLAMP:
            c -= 1
        b += n
        if b <= -n:
            b = -n + 1
    elif b > 0:                               # running mean above the band -> C++
        if c < BIAS_CLAMP - 1:
            c += 1
        b -= n
        if b > 0:
            b = 0
    B[q], Ncnt[q], Ccor[q] = b, n, c


def _bias_forward(e, parents):
    """Subtract the context-conditioned integer correction from the LMS residual
    field e [C, N]. Returns the coded residual d. Channel g's context uses its own
    two previous residuals and the same-slice residual of parents[g] (< g), all
    causally available to the decoder."""
    e = np.asarray(e, np.int64)
    C, N = e.shape
    d = np.empty_like(e)
    sg = np.sign(e)                            # -1 / 0 / +1, per sample-channel
    zero = np.zeros(N, np.int64)
    for g in range(C):
        p = int(parents[g])
        sp = sg[p] if p >= 0 else zero         # no parent -> neutral sign 0
        s1 = np.concatenate(([0], sg[g, :-1]))          # sgn e[g, t-1]
        s2 = np.concatenate(([0, 0], sg[g, :-2]))       # sgn e[g, t-2]
        ctx = (s1 + 1) * 9 + (s2 + 1) * 3 + (sp + 1)    # in [0, BIAS_NCTX)
        st = _bias_new_state()
        Ccor = st[2]
        eg, dg = e[g], d[g]
        for t in range(N):
            q = int(ctx[t])
            v = int(eg[t]) - Ccor[q]           # prediction := lms_pred + C[ctx]
            dg[t] = v
            _bias_update(st, q, v)
    return d


def _bias_inverse(d, parents):
    """Exact inverse of _bias_forward. Channels are walked in index order and
    parents[g] < g, so row parents[g] of the residual field is fully rebuilt
    before it is used as context; within a channel the own-signs are carried
    forward sample by sample from the residuals just reconstructed."""
    d = np.asarray(d, np.int64)
    C, N = d.shape
    e = np.empty_like(d)
    zero = np.zeros(N, np.int64)
    for g in range(C):
        p = int(parents[g])
        sp = np.sign(e[p]) if p >= 0 else zero          # p < g -> already restored
        st = _bias_new_state()
        Ccor = st[2]
        dg, eg = d[g], e[g]
        s1 = s2 = 0
        for t in range(N):
            q = (s1 + 1) * 9 + (s2 + 1) * 3 + (int(sp[t]) + 1)
            v = int(dg[t])
            val = v + Ccor[q]                  # undo the correction
            eg[t] = val
            _bias_update(st, q, v)             # identical update, same d
            s2 = s1
            s1 = 1 if val > 0 else (-1 if val < 0 else 0)
    return e


def biasbp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)          # best-partner front-end (verbatim)
    res = ec.lms_forward(xt, order=BIAS_ORDER)        # order-4 sign-sign LMS (verbatim)
    res = _bias_forward(res, parents)                 # context bias cancellation
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", BIAS_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def biasbp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == BIAS_MAGIC, "bad bias-cancellation codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    res = _bias_inverse(res, parents)                 # matched inverse of the bias stage
    xt = ec.lms_inverse(res, order=BIAS_ORDER)        # matched order-4 inverse
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: propagation-aware (TIME-LAGGED) cross-channel predictor
# (LMS4+Rice+xchan_xlag).
# ---------------------------------------------------------------------------
# EVERY spatial construction in the registry -- xchan, bestpartner(_adaptive),
# multiparent, joint2, jointbp2, iklt(_adaptive), acar -- evaluates the parent
# channel at time t ONLY. That is a modelling assumption, not a property of the
# data: HD-sEMG is a PROPAGATING field. Motor-unit action potentials travel along
# the muscle fibres at ~3-5 m/s; at an 8-10 mm inter-electrode distance that is
# ~1.6-3.3 ms = 3-7 samples at 2048 Hz. So the inter-channel cross-correlation
# does NOT peak at tau=0 -- it peaks at a non-zero lag tau*, and locating that
# peak is exactly how muscle-fibre conduction velocity is measured (the
# cross-correlogram peak displacement). For a jointly-Gaussian pair the reducible
# bits are ~ -0.5*log2(1-rho^2), monotone in |rho|, and rho(tau*) >= rho(0) BY
# DEFINITION of the peak; for a travelling wavefront rho(0) can be near zero or
# even negative once the delay approaches a half-cycle of the 60-120 Hz MUAP band,
# in which case a tau=0 subtract captures none of the available mutual information.
# This is a MI slice that is structurally invisible to every registered codec.
#
# Mechanism (rank-1 in SPACE -- the proven lever -- extended in TIME):
#   1. LAG SEARCH (per channel, per block i>0, backward): over the PREVIOUS
#      already-reconstructed RAW block, for each causal grid neighbour p
#      (left/up/up-left/up-right, all idx<c -- reused `_bp_candidates`), compute
#      the integer cross-correlogram S(tau) = <x_c, x_p(tau)> for tau in
#      [-L..+L] (L=XLAG_L=7, covering the full 3-7-sample propagation range in
#      both directions plus tau=0) and take tau*_p = argmax |S(tau)| -- the
#      CV-estimator peak. |S| (not S) because a half-cycle delay flips the sign;
#      the integer-LS gain that follows absorbs the sign.
#   2. SELECT (parent, lag): for each parent AT ITS OWN peak lag derive the
#      rounded integer least-squares gain (`_bp_opt_beta`, verbatim from the
#      best-partner path) and score the resulting rank-1 cross-residual's
#      estimated Rice bits (`_bp_score`); also score the no-parent option. Keep
#      the min-bits (parent, lag, gain). With tau*=0 forced this REDUCES EXACTLY
#      to `LMS4+Rice+xchan_bestpartner_adaptive`, so the lag search is a strict
#      superset of the promoted spatial front-end -- the measurement isolates the
#      time-shift and nothing else.
#   3. 3-TAP CROSS-PREDICTION FILTER (the MPEG-4 ALS MCC half): on the SELECTED
#      (parent, lag) only, solve a ridge-regularized 3x3 integer least-squares for
#      taps (b_-1, b_0, b_+1) applied at parent lags (tau-1, tau, tau+1) and keep
#      it only if it scores FEWER Rice bits than the single tap. A 3-tap FIR on
#      ONE parent interpolates a SUB-SAMPLE propagation delay (the true delay is
#      not an integer number of samples) and shapes the parent's spectrum to the
#      child's -- the two things a single scalar gain at an integer lag cannot do.
#      The ridge (lambda = trace>>XLAG_RIDGE_SHIFT) is required because three
#      consecutive samples of a band-limited parent are nearly collinear; without
#      it the 3x3 solve is ill-conditioned and the taps blow up. Gram/rhs are
#      normalized to <2^15 before an exact 3x3 Cramer solve so every intermediate
#      fits int64 on-node (no big-int, no float); a non-positive determinant or an
#      out-of-int16 tap deterministically falls back to the single tap.
#   4. APPLY to the CURRENT block: y[c,t] = x[c,t] - ((sum_m b_m * x[p, t-tau-m])
#      >> BP_SHIFT). Block 0 bootstraps to no-parent (no previous block exists).
#
# EMBEDDABILITY / LOOK-AHEAD: parents are always idx<c, so in a block-serial
# encoder the parent's WHOLE current block is already latched before channel c is
# coded -- a NEGATIVE lag (parent leads the child) therefore costs no look-ahead
# beyond the Rice block the coder already buffers. Parent indices are clamped to
# [0, block_end] on BOTH sides (`_xlag_shift_row`'s `hi`), so nothing outside the
# current block is ever touched and look-ahead stays 0. Per-sample encode work is
# unchanged in FORM (one shift-mul-subtract, three when the 3-tap wins); only the
# per-block SELECTION grows by x(2L+1) and amortises over the block. Both the
# (parent, lag) choice and the taps are recomputed by the decoder from
# bit-identical reconstructed history => ZERO side-info (INSIGHTS P4), and the
# temporal back-end stays order-4 sign-sign LMS + adaptive Rice (INSIGHTS P2/P5).
#
# Distinct from every relative on the axis each names decisive:
#   - vs PROMOTED bestpartner / bestpartner_adaptive: identical selection maths,
#     identical rank-1 subtract -- but the parent is evaluated at tau*, not at 0.
#   - vs RETIRED iklt/iklt_adaptive: those are zero-lag ENERGY-PRESERVING rotations
#     mixing several channels and corrupting both; this stays an ASYMMETRIC rank-1
#     residual-only subtract with the parent row left clean (INSIGHTS P3).
#   - vs RETIRED multiparent: that is a SUM of zero-lag rank-1 subtracts (double-
#     counts the shared mode); this is ONE parent, one lag -- no summed parents.
#   - vs KEPT joint2/jointbp2: those buy a second SPATIAL degree of freedom at
#     tau=0; this buys a TEMPORAL degree of freedom on one parent, so P1b/P3
#     (which are statements about spatial rank) do not cover it.
#   - the 3-tap filter is multi-tap in TIME on a single parent, i.e. still rank-1
#     in SPACE, which is precisely what P3 says the gain lives in.
# Citation: MPEG-4 ALS multichannel coding (MCC) selects a reference channel and
# applies a 3-tap cross-prediction filter plus a TIME SHIFT (paper-reported,
# unverified here). The bestpartner family already has the "selected reference"
# half; the time-shift half is what is missing and what this codec adds.
# PREDICTION: CapgMyo stays the honest negative control (differential montage
# cancels the travelling component, 1 kHz sampling makes the delay sub-sample) --
# a null there is the expected physics, not codec failure.
# ===========================================================================
XLAG_MAGIC = 0x474C          # 'LG' (lagged cross-channel predictor)
XLAG_BLOCK = ec.BLOCK        # re-selection block (aligns with the Rice block)
XLAG_L = 7                   # max |lag| searched (samples); covers 3-7 @2048 Hz
XLAG_RIDGE_SHIFT = 7         # 3x3 Gram ridge  lambda = max(1, trace >> 7)
XLAG_GRAM_BITS = 15          # normalize Gram/rhs below 2^15 -> int64-safe Cramer


def _xlag_shift_row(xp, s, e, lag, hi):
    """Parent segment aligned to output positions [s, e) at time-lag `lag`:
        v[j] = x_p[clamp(s + j - lag, 0, hi)]
    `hi` is the last parent index the block-serial pipeline has already latched
    (the current block's END), so even a NEGATIVE lag -- parent leading the child
    -- never reaches past the block the coder is already buffering: look-ahead
    stays 0. Clamping is deterministic integer index arithmetic, so encoder and
    decoder build the identical vector."""
    idx = np.arange(s, e, dtype=np.int64) - lag
    np.clip(idx, 0, hi, out=idx)
    return xp[idx]


def _xlag_peak_lag(xc_prev, xp, ps, pe):
    """Cross-correlogram peak: argmax over tau in [-L..L] of |<x_c, x_p(tau)>|,
    i.e. the muscle-fibre conduction-velocity estimator. Absolute value because a
    propagation delay near a half-cycle of the MUAP band flips the sign of the
    correlation -- the integer-LS gain derived afterwards absorbs that sign.
    Ties resolve to the smallest tau (scan order), so the choice is deterministic
    and identical on both sides. Integer macs only."""
    best_tau, best_mag = -XLAG_L, -1
    for tau in range(-XLAG_L, XLAG_L + 1):
        v = _xlag_shift_row(xp, ps, pe, tau, pe - 1)
        mag = abs(int((xc_prev * v).sum()))
        if mag > best_mag:
            best_mag, best_tau = mag, tau
    return best_tau


def _det3(m):
    """Exact 3x3 determinant of an integer matrix (entries pre-normalized to
    <2^15 by the caller, so |det| < 2^47 and an int64 accumulator suffices)."""
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _xlag_solve3(xc, vs, shift=BP_SHIFT):
    """Ridge-regularized 3x3 integer least-squares for the MPEG-4-ALS-style 3-tap
    cross-prediction filter: fixed-point taps b so that sum_m b_m*v_m ~ xc<<shift.

    Integer-only and int64-safe: the Gram matrix and rhs are right-shifted by a
    common amount until every entry is < 2^15, a ridge lambda = max(1, trace>>7)
    is added to the diagonal (three consecutive samples of a band-limited parent
    are nearly collinear -- without the ridge the solve is ill-conditioned and the
    taps explode), and the taps come from an exact 3x3 Cramer solve. Returns None
    (=> caller keeps the single tap) if the determinant is non-positive or a tap
    leaves the int16 fixed-point range. Fully deterministic, so encoder and
    decoder derive identical taps."""
    G = [[int((vs[a] * vs[b]).sum()) for b in range(3)] for a in range(3)]
    r = [int((xc * vs[a]).sum()) for a in range(3)]
    mx = max(max(abs(g) for row in G for g in row), max(abs(v) for v in r), 1)
    sh = max(0, mx.bit_length() - XLAG_GRAM_BITS)
    if sh:
        G = [[g >> sh for g in row] for row in G]
        r = [v >> sh for v in r]
    lam = max(1, (G[0][0] + G[1][1] + G[2][2]) >> XLAG_RIDGE_SHIFT)
    for a in range(3):
        G[a][a] += lam
    det = _det3(G)
    if det <= 0:
        return None
    taps = []
    for a in range(3):
        M = [row[:] for row in G]
        for i in range(3):
            M[i][a] = r[i]
        b = _round_div(_det3(M) << shift, det)
        if b < -32768 or b > 32767:
            return None
        taps.append(b)
    return taps


def _xlag_predict(xp, taps, tau, s, e, hi, shift=BP_SHIFT):
    """Fixed-point 3-tap (or single-tap, when only b_0 is non-zero) prediction of
    a block of channel c from parent row xp at lags (tau-1, tau, tau+1)."""
    acc = np.zeros(e - s, np.int64)
    for m, b in zip((-1, 0, 1), taps):
        if b:
            acc += b * _xlag_shift_row(xp, s, e, tau + m, hi)
    return acc >> shift


def _xlag_select_block(xc_prev, x, cands, ps, pe):
    """Backward per-block (parent, lag, taps) selection from the PREVIOUS raw
    block. Returns (-1, 0, None) for the no-parent option. Deterministic and
    integer-only, so encoder and decoder -- which both hold the bit-identical
    reconstructed previous block and the fully reconstructed parent rows -- derive
    the identical choice with NOTHING transmitted."""
    best_bits = _bp_score(xc_prev)              # option: no cross-channel subtract
    best = (-1, 0, None)
    for p in cands:
        tau = _xlag_peak_lag(xc_prev, x[p], ps, pe)     # CV-style correlogram peak
        v = _xlag_shift_row(x[p], ps, pe, tau, pe - 1)
        b = _bp_opt_beta(xc_prev, v, BP_SHIFT)          # integer LS gain at tau
        if b == 0:
            continue
        bits = _bp_score(xc_prev - ((b * v) >> BP_SHIFT))
        if bits < best_bits:
            best_bits, best = bits, (p, tau, [0, b, 0])
    p, tau, taps = best
    if p >= 0:                                  # MCC-style 3-tap refinement
        vs = [_xlag_shift_row(x[p], ps, pe, tau + m, pe - 1) for m in (-1, 0, 1)]
        t3 = _xlag_solve3(xc_prev, vs)
        if t3 is not None:
            pred = (t3[0] * vs[0] + t3[1] * vs[1] + t3[2] * vs[2]) >> BP_SHIFT
            bits = _bp_score(xc_prev - pred)
            if bits < best_bits:
                best_bits, best = bits, (p, tau, t3)
    return best


def _xlag_forward(x, cols, B=XLAG_BLOCK):
    """Propagation-aware rank-1 cross-channel decorrelation. Block i's (parent,
    lag, taps) come from the PREVIOUS raw block (block 0 -> no parent); the chosen
    lagged rank-1 subtract is applied to block i of the RAW signal."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:                          # grid origin: no causal neighbour
            continue
        for i in range(1, nblocks):            # block 0 is coded as-is (no prior)
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, tau, taps = _xlag_select_block(x[g, ps:pe], x, cands, ps, pe)
            if p >= 0:
                y[g, s:e] = x[g, s:e] - _xlag_predict(x[p], taps, tau, s, e, e - 1)
    return y


def _xlag_inverse(y, cols, B=XLAG_BLOCK):
    """Invert _xlag_forward. Every candidate parent has grid idx < g so its row is
    FULLY reconstructed (all time) before g is touched -- which is what makes lags
    of EITHER sign invertible; within a channel we rebuild raw block-by-block in
    time order, so block i-1 is restored before the block i whose parameters are
    derived from it. Mirrors the encoder exactly."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:
            continue
        for i in range(1, nblocks):
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, tau, taps = _xlag_select_block(x[g, ps:pe], x, cands, ps, pe)
            if p >= 0:
                x[g, s:e] = y[g, s:e] + _xlag_predict(x[p], taps, tau, s, e, e - 1)
    return x


def xlag_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _xlag_forward(x, cols)                       # lagged backward-adaptive rank-1
    res = ec.lms_forward(y, order=LMS4_ORDER)        # order-4 sign-sign LMS (P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", XLAG_MAGIC, cols, C, N)   # NO side-info at all
    return hdr + body


def xlag_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XLAG_MAGIC, "bad xlag codec magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=LMS4_ORDER)        # matched order-4 inverse
    x = _xlag_inverse(y, cols)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: per-channel backward-adaptive spatial model-ORDER gate --
# rank-1 (selected single parent) vs jointly-solved rank-2 pair
# (LMS4+Rice+xchan_bprank).
# ---------------------------------------------------------------------------
# INSIGHTS P1b settled the two spatial front-ends per ARRAY: a single SELECTED
# parent (rank-1, `bestpartner_adaptive`) wins tight arrays; the JOINTLY-SOLVED
# best PAIR (rank-2, `jointbp2`) took the highest Hyser cross-channel gain of any
# codec on the diffuse large array. Frontier #1 proposed choosing between them --
# but with a GLOBAL channel-count gate (C<=64 -> rank-1, C>=128 -> rank-2). That
# form is bounded by construction: it would route the 320-ch CEMHSEY recording
# wholesale into the rank-2 branch and inherit `jointbp2`'s regression there, and
# its ceiling is just max(two already-measured branches).
#
# The repair is granularity. Array geometry is NOT uniform WITHIN a grid: an edge
# or corner channel has 1-2 causal parents (rank-1 by construction), a channel
# sitting over an innervation zone or a second muscle sees ONE coherent local mode
# (rank-1 by physics), while an interior channel of a large diffuse array sees a
# genuinely rank>=2 local field. Cycles 12/13 measured the optimum flipping BETWEEN
# arrays; the same MI argument says it flips BETWEEN CHANNELS. So gate the spatial
# model ORDER per CHANNEL and per BLOCK, on measured code length, not per recording
# on a channel count.
#
# Mechanism (a MODEL-SELECTION gate over the union of the two proven hypothesis
# classes; all evidence from the PREVIOUS already-reconstructed RAW block):
#   H1 (rank-1): best of {no parent, each of the <=4 causal grid neighbours with its
#      rounded integer-LS gain} -- literally `bestpartner_adaptive`'s search
#      (`_bp_opt_beta`/`_bp_score`), keeping the winner's BIT COUNT `bits1`.
#   H2 (rank-2): the best PAIR of causal neighbours under a JOINT 2x2 integer
#      least-squares solve (`_jbp2_pair_resid` -- accounts for parent-parent
#      covariance, so it cannot double-count the shared mode the way the RETIRED
#      summed multiparent did), keeping its bit count `bits2`.
#   GATE: score(H1)=bits1, score(H2)=bits2 + MDL penalty, where the penalty is the
#      honest BIC form (1/2)*log2(B) bits for the ONE extra free real-valued gain
#      plus log2(#pairs)-log2(#singles) bits for the wider selection alphabet --
#      this is the O(log) selection-noise term the theory requires, charged in
#      integer bits. Mode changes only if the challenger beats the incumbent by more
#      than a HYSTERESIS band (incumbent score >> 7, ~0.8%), which suppresses
#      block-to-block dithering when the two hypotheses are statistically tied
#      (dithering is pure loss: it desynchronizes the rank-2 taps for no bit gain).
#   APPLY to the CURRENT block with the WINNING branch's own machinery, not a common
#      one -- rank-1 applies the closed-form integer-LS rank-1 subtract
#      y=x[c]-((beta*x[p])>>s) (`bestpartner_adaptive` verbatim); rank-2 applies the
#      joint co-adaptive 2-tap sign-sign LMS on the selected pair, pred=(w_u*x[pu]+
#      w_l*x[pl])>>s with BOTH taps descending the SHARED residual (`jointbp2`
#      verbatim). The rank-2 taps PERSIST across blocks and are simply FROZEN while
#      the channel is in rank-1 mode, so a channel that oscillates slowly does not
#      pay a re-convergence transient each time it returns.
#   Block 0 bootstraps to rank-1/no-parent (no prior block exists to score); the gate
#   starts adapting at block 1.
#
# Expected-code-length argument: selecting per channel-block by empirical code length
# over the UNION of two hypothesis classes has expected code length <= min of either
# FIXED class, up to the selection-noise term -- which is exactly what the MDL penalty
# and the hysteresis band are there to pay for. So this is the first construction whose
# ceiling is not bounded by max(bestpartner, jointbp2) per recording.
#
# ZERO side-info, look-ahead 0 (INSIGHTS P4): every input to the gate -- both
# hypotheses' scores, the penalty, the hysteresis state, and the selected parents --
# is computed from the bit-identical reconstructed previous block and from parent rows
# whose grid index is < c (hence fully reconstructed), so the DECODER REPEATS THE
# IDENTICAL TEST and nothing is transmitted. `acar_sel` already proved a
# decoder-observable gate is legal and bit-exact; this places the gate at the correct
# granularity (per channel-block, on measured code length) instead of per recording on
# a channel count. Integer/fixed-point only; order-4 sign-sign LMS + adaptive Rice
# back-end unchanged (INSIGHTS P2/P5).
#
# Distinct from its relatives on the axis each names decisive:
#   - vs `jointbp2`: jointbp2 scores none/single/pair in ONE flat argmin and then always
#     applies the LMS-tap predictor. Here the two hypothesis CLASSES are scored and
#     gated as model ORDERS -- with an MDL complexity charge and hysteresis jointbp2
#     has none of -- and the winner is applied with ITS OWN estimator (closed-form
#     per-block beta for rank-1, co-adaptive taps for rank-2).
#   - vs `bestpartner_adaptive`: adds the rank-2 hypothesis, but only where it pays for
#     its extra degree of freedom in measured bits.
#   - vs `acar_sel`: same zero-side-info gating PRINCIPLE, moved from a per-recording
#     channel count to a per-channel-block measured code length.
#   - NOT the naive global C-gate of the old survey row 1 (see above: bounded ceiling,
#     inherits the rank-2 regression on 320-ch CEMHSEY).
# Embeddability: both branches are already registered and verified integer/causal/
# zero-side-info; the increment over `jointbp2` is one extra per-block scoring compare,
# so the cost ceiling is ~jointbp2's. CAVEAT TO MEASURE: it must not merely pay
# jointbp2's scan price to arrive at bestpartner's answer -- if the gate lands in rank-1
# almost everywhere, ratio ~= bestpartner_adaptive at higher cost = Pareto-dominated.
# Basis: MDL/BIC model-order selection (Rissanen) applied to the spatial predictor
# order; the two branches are this registry's own measured constructions.
# ===========================================================================
BPRANK_MAGIC = 0x5252        # 'RR' (rank gate)
BPRANK_SHIFT = ec.CROSS_SHIFT   # fixed-point spatial-gain scale (the +xchan family's)
BPRANK_ORDER = LMS4_ORDER    # order-4 temporal base behind the spatial front-end (P2)
BPRANK_BLOCK = ec.BLOCK      # gate/re-selection block (aligns with the Rice block)
BPRANK_HYST_SHIFT = 7        # hysteresis band = incumbent score >> 7 (~0.8%)


def _bprank_ilog2(n):
    """floor(log2(n)) for n >= 1, integer-only (no float, no math.log)."""
    return int(n).bit_length() - 1


def _bprank_penalty(nsing, npair, B):
    """MDL/BIC complexity penalty (in BITS) charged to the rank-2 hypothesis:
      * (1/2)*log2(B) bits for the ONE extra free real-valued gain the pair model
        spends over the single-parent model (the standard BIC per-parameter cost on
        B observations), and
      * log2(#pairs) - log2(#singles) bits for the WIDER selection alphabet rank-2
        searches over (the model-selection/code-book term).
    Deliberately small -- this is the honest O(log) selection-noise term, not a
    tuning knob; the hysteresis band carries the rest of the switching control.
    Integer-only and derived from (B, candidate count), both of which the decoder
    knows exactly, so encoder and decoder charge the identical penalty."""
    pen = _bprank_ilog2(B) // 2
    if npair > 0 and nsing > 0:
        pen += max(0, _bprank_ilog2(npair) - _bprank_ilog2(nsing))
    return pen


def _bprank_best_single(xc_prev, x, cands, ps, pe, shift=BPRANK_SHIFT):
    """Hypothesis H1 (rank-1) scored on the PREVIOUS raw block: best of {no parent,
    each causal neighbour with its rounded integer-LS gain}, in estimated Rice bits.
    Returns (bits, parent, beta) with parent=-1 meaning 'code as-is'. This is
    `_bpa_select_block`'s search with the winning BIT COUNT kept so the model-order
    gate can compare hypothesis classes."""
    best_bits = _bp_score(xc_prev)                  # option: no cross-channel parent
    best_p, best_b = -1, 0
    for p in cands:
        b = _bp_opt_beta(xc_prev, x[p, ps:pe], shift)
        if b == 0:
            continue
        bits = _bp_score(xc_prev - ((b * x[p, ps:pe]) >> shift))
        if bits < best_bits:
            best_bits, best_p, best_b = bits, p, b
    return best_bits, best_p, best_b


def _bprank_best_pair(xc_prev, x, cands, ps, pe, shift=BPRANK_SHIFT):
    """Hypothesis H2 (rank-2) scored on the PREVIOUS raw block: the best PAIR of
    causal neighbours under a JOINT 2x2 integer least-squares solve
    (`_jbp2_pair_resid` -- parent-parent covariance included, so no double-count of
    the parents' shared mode). Returns (bits, pu, pl), or (None, -1, -1) when the
    channel has no non-degenerate pair (edge/corner channels: rank-1 by
    construction, and the gate then has nothing to switch to)."""
    best_bits, best_u, best_l = None, -1, -1
    L = len(cands)
    for ii in range(L):
        for jj in range(ii + 1, L):
            resid = _jbp2_pair_resid(xc_prev, x[cands[ii], ps:pe],
                                     x[cands[jj], ps:pe], shift)
            if resid is None:                       # degenerate/collinear pair
                continue
            bits = _bp_score(resid)
            if best_bits is None or bits < best_bits:
                best_bits, best_u, best_l = bits, cands[ii], cands[jj]
    return best_bits, best_u, best_l


def _bprank_gate(bits1, bits2, nsing, npair, B, mode_prev):
    """The per-channel per-block spatial model-ORDER gate. Compares the two
    hypotheses' MEASURED code cost on the previous block (bits1 vs bits2 + MDL
    penalty) and switches only if the challenger wins by more than a hysteresis band
    (incumbent score >> BPRANK_HYST_SHIFT, ~0.8%) -- so statistically tied blocks keep
    the incumbent order instead of dithering. Returns 1 (rank-1) or 2 (rank-2). Pure
    integer comparison on quantities both sides derive from bit-identical
    reconstructed history -> ZERO side-info."""
    if bits2 is None:                               # no admissible pair: rank-1 only
        return 1
    s1 = bits1
    s2 = bits2 + _bprank_penalty(nsing, npair, B)
    if mode_prev == 1:
        band = max(1, s1 >> BPRANK_HYST_SHIFT)
        return 2 if s2 + band < s1 else 1
    band = max(1, s2 >> BPRANK_HYST_SHIFT)
    return 1 if s1 + band < s2 else 2


def _bprank_forward(x, cols, B=BPRANK_BLOCK, shift=BPRANK_SHIFT):
    """Spatial front-end with a per-channel, per-block backward-adaptive model-ORDER
    gate. Per channel c and block i>0: score H1 (selected single parent, integer-LS
    gain) and H2 (jointly-solved best pair) on the PREVIOUS raw block, gate on
    measured bits + MDL penalty + hysteresis, then apply the WINNING branch's own
    estimator to the current block -- closed-form rank-1 subtract, or the joint
    co-adaptive 2-tap sign-sign LMS whose taps persist across blocks (frozen while in
    rank-1 mode). Block 0 is coded as-is. Returns the cross-residual [C,N] int64."""
    C, N = x.shape
    x = x.astype(np.int64)
    y = x.copy()
    nblocks = (N + B - 1) // B
    for c in range(C):
        cands = _bp_candidates(c, cols, C)
        if not cands:                               # grid origin: coded as-is
            continue
        nsing = len(cands) + 1                      # + the no-parent option
        npair = len(cands) * (len(cands) - 1) // 2
        xc = x[c]; yc = y[c]
        wu = wl = 0                                 # persistent rank-2 spatial taps
        mode = 1                                    # bootstrap: rank-1 (no prior block)
        for i in range(1, nblocks):
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            xprev = xc[ps:pe]
            bits1, p1, b1 = _bprank_best_single(xprev, x, cands, ps, pe, shift)
            bits2, pu, pl = _bprank_best_pair(xprev, x, cands, ps, pe, shift)
            mode = _bprank_gate(bits1, bits2, nsing, npair, pe - ps, mode)
            if mode == 1:
                if p1 >= 0:
                    yc[s:e] = xc[s:e] - ((b1 * x[p1, s:e]) >> shift)
            else:
                prow = x[pu]; lrow = x[pl]
                for t in range(s, e):
                    u = int(prow[t]); l = int(lrow[t])
                    pred = (wu * u + wl * l) >> shift
                    ev = int(xc[t]) - pred
                    yc[t] = ev
                    se = 1 if ev > 0 else (-1 if ev < 0 else 0)
                    wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
                    wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return y


def _bprank_inverse(y, cols, B=BPRANK_BLOCK, shift=BPRANK_SHIFT):
    """Invert _bprank_forward. Every candidate parent has grid idx < c so its row is
    fully reconstructed before c; within a channel we rebuild raw block-by-block in
    time order, so block i-1 is restored before block i and the SAME two hypotheses,
    the SAME MDL penalty and the SAME hysteresis state reproduce the encoder's mode
    decision exactly, with the rank-2 taps re-derived per sample from the shared
    residual e=y[c,t] -- mirroring the encoder bit-for-bit."""
    C, N = y.shape
    y = y.astype(np.int64)
    x = y.copy()
    nblocks = (N + B - 1) // B
    for c in range(C):
        cands = _bp_candidates(c, cols, C)
        if not cands:
            continue
        nsing = len(cands) + 1
        npair = len(cands) * (len(cands) - 1) // 2
        xc = x[c]; yc = y[c]
        wu = wl = 0
        mode = 1
        for i in range(1, nblocks):
            s, e = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            xprev = xc[ps:pe]                       # already reconstructed
            bits1, p1, b1 = _bprank_best_single(xprev, x, cands, ps, pe, shift)
            bits2, pu, pl = _bprank_best_pair(xprev, x, cands, ps, pe, shift)
            mode = _bprank_gate(bits1, bits2, nsing, npair, pe - ps, mode)
            if mode == 1:
                if p1 >= 0:
                    xc[s:e] = yc[s:e] + ((b1 * x[p1, s:e]) >> shift)
            else:
                prow = x[pu]; lrow = x[pl]
                for t in range(s, e):
                    u = int(prow[t]); l = int(lrow[t])
                    pred = (wu * u + wl * l) >> shift
                    ev = int(yc[t])
                    xc[t] = ev + pred
                    se = 1 if ev > 0 else (-1 if ev < 0 else 0)
                    wu += se * (1 if u > 0 else (-1 if u < 0 else 0))
                    wl += se * (1 if l > 0 else (-1 if l < 0 else 0))
    return x


def bprank_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    y = _bprank_forward(x, cols)                     # model-order-gated spatial front-end
    res = ec.lms_forward(y, order=BPRANK_ORDER)      # order-4 sign-sign LMS (INSIGHTS P2)
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", BPRANK_MAGIC, cols, C, N)   # NO side-info (gate is backward)
    return hdr + body


def bprank_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == BPRANK_MAGIC, "bad xchan_bprank magic"
    off = 12
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    y = ec.lms_inverse(res, order=BPRANK_ORDER)      # matched order-4 inverse
    x = _bprank_inverse(y, cols)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: VOLTERRA-LITE degree-2 temporal predictor
# (LMS4v2+Rice+xchan_bestpartner).
# ---------------------------------------------------------------------------
# INSIGHTS open-frontier #2 taken literally: P2 says the way to lower the
# temporal residual entropy is to change the predictor's FUNCTIONAL FORM, not
# its tap count (order 8 loses to order 4 across three cycles) and not its
# coefficient-SET count (the regime bank `LMS4rs`, retired). A linear predictor
# can only whiten a signal to SECOND ORDER: whatever compressibility survives an
# order-4 sign-LMS lives in higher-order structure. HD-sEMG is a non-Gaussian
# superposition of MUAPs seen through a nonlinear volume conductor, so the
# leading correction term of ANY analytic nonlinearity -- the degree-2 Volterra
# kernel -- is the principled first move.
#
# Mechanism: keep ONE order-4 sign-sign LMS coefficient set (order stays 4, P2)
# and ONE adaptation loop, but AUGMENT ITS REGRESSOR BASIS with V2_NQ = 3
# integer second-order products of the causal history:
#     q0 = x[t-1]*x[t-1],  q1 = x[t-1]*x[t-2],  q2 = x[t-2]*x[t-2]
# i.e. the complete degree-2 Volterra kernel truncated to quadratic memory 2,
# alongside the linear memory-4 kernel. Prediction is the single fixed-point sum
#     pred = ( sum_i wl_i*x[t-1-i] + sum_j wq_j*q_j ) >> V2_SHIFT
# and every tap -- linear and quadratic -- adapts in the SAME sign-sign update
# w += sign(e)*sign(regressor). There is NO gate, NO bank, NO second coefficient
# set: this is one predictor in a richer basis.
#
# The engineering risk the hypothesis flags is INTEGER SCALE: a product of two
# int16 samples is int32-wide and its natural scale is |x|^2, so a fixed shift
# either quantizes the term to zero on small signals or lets it dominate on
# large ones. A degree-2 Volterra coefficient physically has units 1/amplitude,
# so the fixed-point normalizer must TRACK the amplitude. We therefore normalize
# each product by a power of two derived from a backward leaky mean-|x|:
#     mag  += |x[t]| - (mag >> V2_MAGW)          (leaky, ~2^V2_MAGW window)
#     nbits = bitlength(mag >> V2_MAGW)          (refreshed every 16 samples)
#     q_j   = clamp( (x_a*x_b) >> nbits , +-32767 )
# so |q| ~ |x|^2 / mean|x| ~ |x|: the quadratic regressors sit on the SAME scale
# as the linear ones and the shared V2_SHIFT weight scale is meaningful for both.
# bitlength is a CLZ in hardware and the refresh is amortised 1/16 samples; the
# clamp bounds the datapath (int16-wide regressors) and caps how far a spike can
# amplify the quadratic term.
#
# LEAKAGE (the second guard the hypothesis calls for): quadratic regressors have
# much higher variance than linear ones, so an unleaked sign-sign tap can wander
# and inject prediction noise on an already-white residual. Every 16 samples the
# QUADRATIC taps only are leaked toward zero, wq -= sign(wq)*(|wq| >> V2_LEAK_L)
# (symmetric, integer, no drift), which both bounds |wq| (equilibrium ~2^L * 16,
# int16-safe) and makes the quadratic correction self-disabling when it does not
# earn its bits -- if the products carry no predictive information the sign-sign
# updates cancel, the leak pulls wq to 0, and the codec degenerates EXACTLY to
# the promoted LMS4+Rice+xchan_bestpartner. The linear taps are NOT leaked, so
# the proven linear behaviour is untouched.
#
# Everything is derived from causally-available reconstructed data (history,
# residual signs, and the |x| integrator), so the decoder recomputes the
# regressors, the normalizer exponent and the leak at the same instants and the
# pair stays matched with ZERO side-info (P4). The SPATIAL front-end is the
# promoted best-partner (`_bp_select`/`_bp_inverse`) reused VERBATIM, so this
# codec is a clean A/B against the current best: only the temporal predictor's
# functional form differs.
#
# Distinct from the RETIRED `LMS4rs+Rice+xchan_bestpartner` (cycle 14): that
# duplicated LINEAR coefficient SETS selected by an activity-regime gate, which
# fragmented adaptation (each bank saw ~1/3 the samples) and fit noise once the
# residual was white. Here there is a SINGLE coefficient set that sees EVERY
# sample -- no gate, no fragmentation -- and the added degrees of freedom are new
# BASIS FUNCTIONS, not copies of the old ones. Distinct from the RETIRED `xctx`
# (P5), which conditioned the entropy coder's Rice parameter and left the
# residual unchanged; here the residual itself is what changes and the coder is
# untouched adaptive Rice. Mechanism risk (stated before measurement): quadratic
# regressors are high-variance, so if the post-LMS residual really is white the
# term can only AMPLIFY noise -- exactly the failure mode P2 documents. A null
# result falsifies the degree-2 Volterra correction on HD-sEMG, which is itself
# the answer frontier #2 asks for.
# ===========================================================================
V2_MAGIC = 0x5632        # 'V2'
V2_ORDER = LMS4_ORDER    # linear memory stays 4 (INSIGHTS P2)
V2_NQ = 3                # quadratic regressors: x1*x1, x1*x2, x2*x2
V2_SHIFT = ec.LMS_SHIFT  # 8 -- same fixed-point weight scale as the family LMS
V2_MAGW = 5              # leaky mean-|x| integrator window ~2^5 samples
V2_NORM_MASK = 15        # refresh the normalizer exponent every 16 samples
V2_LEAK_L = 5            # quadratic-tap leak strength: wq -= |wq| >> 5 ...
V2_LEAK_MASK = 15        # ... applied every 16 samples
V2_QCLAMP = 32767        # saturate the quadratic regressors to int16 width


def _v2_bitlen(v):
    """Integer bit-length of a non-negative int64 array (a CLZ in hardware).
    Pure integer binary search -- no float, deterministic on both sides."""
    n = np.zeros(v.shape, np.int64)
    t = v.astype(np.int64).copy()
    for b in (32, 16, 8, 4, 2, 1):
        m = t >= (np.int64(1) << np.int64(b))
        n[m] += b
        t[m] >>= np.int64(b)
    n += (t > 0)
    return n


def _v2_regs(hist, nbits):
    """The V2_NQ degree-2 Volterra regressors, amplitude-normalized and
    saturated. hist[:, 0] = x[t-1], hist[:, 1] = x[t-2] (reconstructed, causal).
    The right shift by nbits is the fixed-point normalization by mean|x| so the
    quadratic regressors land on the same scale as the linear ones."""
    x1 = hist[:, 0]
    x2 = hist[:, 1]
    q = np.empty((hist.shape[0], V2_NQ), np.int64)
    q[:, 0] = (x1 * x1) >> nbits
    q[:, 1] = (x1 * x2) >> nbits
    q[:, 2] = (x2 * x2) >> nbits
    np.clip(q, -V2_QCLAMP, V2_QCLAMP, out=q)
    return q


def _v2_forward(x, order=V2_ORDER, shift=V2_SHIFT):
    """Volterra-lite sign-sign LMS: one coefficient set over an augmented
    [linear order-4 | degree-2 products] basis. Vectorized over channels."""
    C, N = x.shape
    x = x.astype(np.int64)
    wl = np.zeros((C, order), np.int64)      # linear taps (not leaked)
    wq = np.zeros((C, V2_NQ), np.int64)      # quadratic taps (leaky)
    hist = np.zeros((C, order), np.int64)    # past reconstructed samples
    mag = np.zeros(C, np.int64)              # leaky |x| integrator (~2^MAGW*mean|x|)
    nbits = np.zeros(C, np.int64)            # normalizer exponent
    res = np.empty((C, N), np.int64)
    for t in range(N):
        if (t & V2_NORM_MASK) == 0:          # amortised amplitude normalizer refresh
            nbits = _v2_bitlen(mag >> np.int64(V2_MAGW))
        q = _v2_regs(hist, nbits)
        pred = ((wl * hist).sum(axis=1) + (wq * q).sum(axis=1)) >> shift
        e = x[:, t] - pred
        res[:, t] = e
        se = np.sign(e)[:, None]             # ONE sign-sign update over both blocks
        wl += se * np.sign(hist)
        wq += se * np.sign(q)
        if (t & V2_LEAK_MASK) == 0:          # leak the quadratic taps only
            wq -= np.sign(wq) * (np.abs(wq) >> np.int64(V2_LEAK_L))
        mag += np.abs(x[:, t]) - (mag >> np.int64(V2_MAGW))
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = x[:, t]
    return res


def _v2_inverse(res, order=V2_ORDER, shift=V2_SHIFT):
    """Exact inverse of _v2_forward: the regressors, the normalizer exponent and
    the leak are recomputed from the SAME causal reconstructed history, so no
    side-info is needed and the pair is matched sample-for-sample."""
    C, N = res.shape
    res = res.astype(np.int64)
    wl = np.zeros((C, order), np.int64)
    wq = np.zeros((C, V2_NQ), np.int64)
    hist = np.zeros((C, order), np.int64)
    mag = np.zeros(C, np.int64)
    nbits = np.zeros(C, np.int64)
    x = np.empty((C, N), np.int64)
    for t in range(N):
        if (t & V2_NORM_MASK) == 0:
            nbits = _v2_bitlen(mag >> np.int64(V2_MAGW))
        q = _v2_regs(hist, nbits)
        pred = ((wl * hist).sum(axis=1) + (wq * q).sum(axis=1)) >> shift
        e = res[:, t]
        xt = pred + e
        x[:, t] = xt
        se = np.sign(e)[:, None]
        wl += se * np.sign(hist)
        wq += se * np.sign(q)
        if (t & V2_LEAK_MASK) == 0:
            wq -= np.sign(wq) * (np.abs(wq) >> np.int64(V2_LEAK_L))
        mag += np.abs(xt) - (mag >> np.int64(V2_MAGW))
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = xt
    return x


def v2bp_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    xt, parents, betas = _bp_select(x, cols)     # promoted best-partner front-end
    res = _v2_forward(xt)                        # Volterra-lite degree-2 predictor
    body = b"".join(ec.rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack("<HHII", V2_MAGIC, cols, C, N)
    side = parents.astype("<i2").tobytes() + betas.astype("<i2").tobytes()
    return hdr + side + body


def v2bp_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == V2_MAGIC, "bad volterra-lite bestpartner codec magic"
    off = 12
    parents = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    betas = np.frombuffer(buf, "<i2", C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        res[c] = arr
    xt = _v2_inverse(res)
    x = _bp_inverse(xt, parents, betas)
    return x.astype(np.int16)

# ===========================================================================
# NEW candidate: RESIDUAL-DOMAIN cross-channel prediction with a bit-matched
# selection criterion (LMS4+Rice+xchan_xres).
# ---------------------------------------------------------------------------
# STAGE-ORDER / DOMAIN axis. Every registered and retired cross-channel front-end
# (+xchan, xchan_adaptive, bestpartner, bestpartner_adaptive, iklt, itsklt, acar,
# joint2, jointbp2, xlag) applies its spatial stage to the RAW signal and only
# THEN runs the temporal predictor: `xt = <spatial>(x); res = ec.lms_forward(xt)`.
# This candidate REORDERS the pipeline -- and nothing else:
#
#     e = lms_forward(x, order=4)                 # temporal predictor FIRST, per channel
#     d[g, blk i] = e[g, blk i] - ((beta*e[p, blk i]) >> 8)   # rank-1 subtract of
#                                                 # a partner's temporal RESIDUAL
#     rice(d)
#
# TWO independent arguments, both stated BEFORE measurement:
#
# (i) DOMAIN. Volume conduction is instantaneous linear mixing of shared
#     motor-unit innovation trains. The channels' shared AUTOcorrelation (the
#     low-frequency, high-energy part) is removed by the per-channel temporal
#     predictor for free, so a beta fitted on RAW signals spends its single degree
#     of freedom on redundancy that dies downstream anyway. Fitting beta on the
#     INNOVATIONS targets the band where the coded bits actually live, and the
#     innovation mixing coefficient is more stationary than the raw broadband
#     cross-gain, so the backward (previous-block) estimate is less biased.
#
# (ii) CRITERION MISMATCH -- verified in this source. `_bp_score` ranks partners
#     by the Rice length of the PRE-LMS cross-residual, while the codecs EMIT the
#     POST-LMS one (`xt = _bp_select(x); res = ec.lms_forward(xt)`): the argmin is
#     taken over a PROXY, not over the objective. Moving the subtract into the
#     residual domain makes the scored quantity IDENTICAL to the coded quantity --
#     the selection is now bit-matched to what the Rice coder will actually spend.
#
# Everything else is held fixed against the incumbent
# `LMS4+Rice+xchan_bestpartner_adaptive`: the SAME <=4 causal grid-neighbour
# candidate set (`_bp_candidates`, all idx < g), the SAME integer least-squares
# gain (`_bp_opt_beta`), the SAME estimated-Rice-bits score (`_bp_score`), the
# SAME per-block backward re-selection from the PREVIOUS block (`_bpa_select_block`
# reused VERBATIM -- it is domain-agnostic), the SAME order-4 sign-sign LMS
# (INSIGHTS P2) and adaptive Rice back-end (P5). The ONLY variable is the DOMAIN
# the spatial stage and its scoring operate in: residual instead of raw.
#
# CAUSALITY / matched pair (INSIGHTS P4, zero side-info): lms_forward is
# per-channel, so e depends on x alone; the spatial stage then acts only across
# channels within a block. The decoder Rice-decodes d, walks channels in index
# order (every candidate partner has idx < g, hence e[p] is already fully
# recovered) and, within a channel, blocks in time order (block i's (partner,beta)
# is recomputed from the already-recovered RESIDUAL block i-1 of g and of each
# candidate) -- so it derives the identical (partner, beta) and NOTHING is
# transmitted. Block 0 bootstraps to no-partner. Finally `lms_inverse(e)` rebuilds
# x. Still per-sample causal, streaming, look-ahead 0, bounded block.
#
# EMBEDDABILITY: strictly the incumbent's cost -- identical op count, identical
# persistent per-channel state, no new buffers, integer/fixed-point throughout;
# only the pipeline order and the scoring domain change.
#
# HONEST FAILURE MODE: if the innovations' cross-correlation rho_e is materially
# below the raw rho_x, the residual-domain subtract recovers LESS shared energy
# than the raw-domain one; that is exactly what the measurement decides.
#
# CITATION: MPEG-4 ALS removes inter-channel redundancy by joint channel coding
# applied to the PREDICTION RESIDUAL signals, gating joint coding on the
# cross-correlation of residuals (Liebchen et al., MPEG-4 ALS; Sensors
# 14(9):17516, low-complexity joint coding for portable medical devices) --
# paper-reported, unverified here.
# ===========================================================================
XRES_MAGIC = 0x5852          # 'XR' (cross-channel in the RESidual domain)
XRES_BLOCK = ec.BLOCK        # re-selection block (aligns with the Rice block)
XRES_ORDER = LMS4_ORDER      # order-4 temporal predictor (INSIGHTS P2)


def _xres_forward(e, cols, B=XRES_BLOCK):
    """Residual-domain rank-1 cross-channel subtract with backward-adaptive
    per-block (partner, beta) re-selection. `e` is the [C, N] per-channel TEMPORAL
    RESIDUAL (post-LMS). Block i's pair is selected from the PREVIOUS residual
    block via `_bpa_select_block` (same integer-LS gain + Rice-bits score as the
    incumbent, now evaluated on the very quantity that gets coded); block 0 is
    passed through. Returns the [C, N] int64 coded residual d."""
    C, N = e.shape
    e = e.astype(np.int64)
    d = e.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:                          # grid origin: no causal neighbour
            continue
        for i in range(1, nblocks):            # block 0 coded as-is (no prior block)
            s, t = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, b = _bpa_select_block(e[g, ps:pe], e, cands, ps, pe)
            if p >= 0:
                d[g, s:t] = e[g, s:t] - ((b * e[p, s:t]) >> BP_SHIFT)
    return d


def _xres_inverse(d, cols, B=XRES_BLOCK):
    """Invert _xres_forward. Channels in index order (every candidate partner has
    grid idx < g, so its residual row is already fully recovered); within a channel
    blocks in time order, so residual block i-1 is recovered before block i and the
    SAME (partner, beta) is recomputed from it -- mirroring the encoder exactly."""
    C, N = d.shape
    d = d.astype(np.int64)
    e = d.copy()
    nblocks = (N + B - 1) // B
    for g in range(C):
        cands = _bp_candidates(g, cols, C)
        if not cands:
            continue
        for i in range(1, nblocks):
            s, t = i * B, min((i + 1) * B, N)
            ps, pe = (i - 1) * B, i * B
            p, b = _bpa_select_block(e[g, ps:pe], e, cands, ps, pe)
            if p >= 0:
                e[g, s:t] = d[g, s:t] + ((b * e[p, s:t]) >> BP_SHIFT)
    return e


def xres_encode(x, cols=16):
    x = np.asarray(x, np.int64)
    C, N = x.shape
    e = ec.lms_forward(x, order=XRES_ORDER)          # TEMPORAL predictor FIRST (P2)
    d = _xres_forward(e, cols)                       # then the residual-domain subtract
    body = b"".join(ec.rice_encode_1d(d[c]) for c in range(C))
    hdr = struct.pack("<HHII", XRES_MAGIC, cols, C, N)   # NO (parent,beta) side-info
    return hdr + body


def xres_decode(buf):
    magic, cols, C, N = struct.unpack_from("<HHII", buf, 0)
    assert magic == XRES_MAGIC, "bad residual-domain cross-channel codec magic"
    off = 12
    d = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = ec.rice_decode_1d(buf, off)
        d[c] = arr
    e = _xres_inverse(d, cols)                       # undo the residual-domain subtract
    x = ec.lms_inverse(e, order=XRES_ORDER)          # matched order-4 inverse
    return x.astype(np.int16)

# ===========================================================================
# Uniform codec objects + the registry
# ===========================================================================
class Codec:
    def __init__(self, name, encode, decode, meta, family="", desc="",
                 retired=False, retired_reason=""):
        self.name = name
        self.encode = encode
        self.decode = decode
        self.meta = meta
        self.family = family
        self.desc = desc
        self.cost = cost.score(meta)
        # `retired` marks a codec that has been conclusively verified
        # Pareto-dominated on REAL data (never for merely "not the best" --
        # a non-dominated but marginal codec, like a best-of-N Pareto corner,
        # stays active). Retired codecs are NEVER deleted -- the code and its
        # self-test coverage stay forever for reproducibility and so the
        # verdict can be re-checked -- they are just excluded from the default
        # bench.py/leaderboard sweep so they stop being re-benchmarked and
        # re-reported every cycle. Set `retired_reason` to the experiment
        # record / cycle that made the call.
        self.retired = retired
        self.retired_reason = retired_reason


def _wrap_embedded(predictor, cross):
    """Adapter: embedded_codec.encode/decode with fixed predictor+cross flags."""
    def enc(x, cols=16):
        return ec.encode(np.asarray(x, np.int64), predictor=predictor,
                         cross=cross, cols=cols)
    return enc, ec.decode


# --- op counts per sample-channel for the cost model (see cost_model.md) ---
# delta: 1 sub + zigzag(2) + rice pack(~6)          ~ 9
# LMS-8: 8 mac + 1 shift + 8-tap sign update(~16) + hist shift(8) + rice(~9) ~ 50
# xchan front-end adds: 1 mul + 1 shift + 1 sub      ~ 3   (per sample-channel)
# fixed:  4 candidate diffs(~12) + per-block argmin(amortised ~1) + rice(~9) ~ 22
_DELTA_OPS = 9
_LMS_OPS = 50
_XCHAN_OPS = 3
_FIXED_OPS = 22

# state bytes/ch: rice-k + small history. LMS keeps order-8 weights+history
# (16 x int16 = 32) + k; delta/fixed keep <=3 past samples + k.
_RICE_STATE = 4
_LMS_STATE = 40
_FIXED_STATE = 10
# xchan (block-adaptive realization): one int16 beta + the parent's current
# sample; the software impl computes beta over the whole array (offline) but the
# embeddable realization computes it per block -> bounded look-ahead = block.
_XCHAN_STATE = 6
_XCHAN_NOTE = ("software impl derives per-channel beta over the whole signal; "
               "embeddable realization computes beta per block (look-ahead=block)")

# xchan_adaptive (backward-adaptive realization): on top of the +xchan per-sample
# work (1 mul + 1 shift + 1 sub), each block-channel accumulates two running
# dot-products (<x_c,x_p> and <x_p,x_p>, ~2 macs/sample-ch) and does ONE rounded
# integer divide at the block boundary (amortised ~divide/BLOCK). The decoder
# RECOMPUTES the same beta (it is not transmitted), so dec_ops == enc_ops here.
_XADAPT_XTRA = 3   # 2 dot-product macs + amortised block divide, per sample-ch
# state/ch: order-8 LMS (40) + current beta int16 (2) + two int64 block
# accumulators for the running dot-products (16).
_XADAPT_STATE = _LMS_STATE + 18
_XADAPT_NOTE = (
    "backward-adaptive per-block cross-channel gain: beta[block i] is the "
    "integer least-squares ratio <x_c,x_p>/<x_p,x_p> over the PREVIOUS block's "
    "already-reconstructed samples (block 0 -> beta=0). Fully causal, "
    "lookahead=0, and NO beta side-info -- the decoder recomputes it. Replaces "
    "the whole-signal float beta + header side-info of the +xchan variants.")

REGISTRY = {}


def _register(c):
    REGISTRY[c.name] = c
    return c


# existing, already-verified codecs (wrapped, not rebuilt)
_e, _d = _wrap_embedded(ec.PRED_DELTA, False)
_register(Codec("delta+Rice", _e, _d, CodecMeta(
    integer_only=True, enc_ops=_DELTA_OPS, dec_ops=_DELTA_OPS,
    state_bytes_per_ch=_RICE_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK), family="temporal", desc="order-1 DPCM + adaptive Rice"))

_e, _d = _wrap_embedded(ec.PRED_LMS, False)
_register(Codec("LMS+Rice", _e, _d, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS, dec_ops=_LMS_OPS,
    state_bytes_per_ch=_LMS_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK), family="temporal", desc="sign-sign LMS order-8 + Rice"))

_e, _d = _wrap_embedded(ec.PRED_DELTA, True)
_register(Codec("delta+Rice+xchan", _e, _d, CodecMeta(
    integer_only=True, enc_ops=_DELTA_OPS + _XCHAN_OPS, dec_ops=_DELTA_OPS + _XCHAN_OPS,
    state_bytes_per_ch=_RICE_STATE + _XCHAN_STATE, causal=True,
    lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_XCHAN_NOTE),
    family="cross-channel", desc="delta + grid-neighbour decorrelation"))

_e, _d = _wrap_embedded(ec.PRED_LMS, True)
_register(Codec("LMS+Rice+xchan", _e, _d, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _XCHAN_OPS, dec_ops=_LMS_OPS + _XCHAN_OPS,
    state_bytes_per_ch=_LMS_STATE + _XCHAN_STATE, causal=True,
    lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_XCHAN_NOTE),
    family="cross-channel", desc="LMS + grid-neighbour decorrelation (current best)"))

# RETIRED (cycle 1, compression-cycle-2026-07-08): backward-adaptive per-block
# cross-channel beta -- no side-info, fully causal -> lookahead 0, unlike the
# whole-signal +xchan variants above. Kept registered (bit-exact, embedded_ok,
# double-verified) for reproducibility, but excluded from the default
# bench.py/leaderboard sweep: two independent verifiers confirmed it is
# Pareto-dominated by LMS+Rice+xchan on real otb_hdsemg_vl (2.13x/cost 0.065
# vs the incumbent's 2.14x/cost 0.057 -- worse ratio AND higher cost). See
# experiments/001_lms_rice_xchan_adaptive.md for the full record.
_register(Codec("LMS+Rice+xchan_adaptive", xadapt_encode, xadapt_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _XCHAN_OPS + _XADAPT_XTRA,
    dec_ops=_LMS_OPS + _XCHAN_OPS + _XADAPT_XTRA,
    state_bytes_per_ch=_XADAPT_STATE, causal=True, lookahead_samples=0,
    block_size=XADAPT_BLOCK, notes=_XADAPT_NOTE), family="cross-channel",
    desc="LMS + grid-neighbour decorrelation, backward-adaptive per-block gain",
    retired=True,
    retired_reason="Pareto-dominated by LMS+Rice+xchan on real otb_hdsemg_vl "
                    "(2.13x/0.065 vs 2.14x/0.057); double-verified PROMOTE on "
                    "correctness/embeddability only, never on ratio. "
                    "experiments/001_lms_rice_xchan_adaptive.md, cycle 2026-07-08."))

# NEW candidate: best-partner cross-channel selection (this cycle).
# Encode adds, on top of LMS+xchan, a per-channel scan over <=4 causal-neighbour
# candidates (each ~2 MACs/sample to accumulate <xg,xp> and <xp,xp>) to pick the
# best partner -> ~8 extra enc ops/sample-ch; the decoder does NOT search (it
# reads the chosen parent+beta side-info), so its op count matches plain xchan.
# State adds one parent-id byte/ch beyond the incumbent xchan state.
# integer-KLT front-end: a fixed reversible integer inter-channel transform
# applied per time-slice before LMS. The schedule has ~one horizontal + ~one
# vertical rotation per channel (~2 rotations/channel, each rotation touching 2
# channels -> ~1 rotation attributable per sample-ch on each axis). Each rotation
# is 3 lifting shears = 3 x (1 mul + 1 rounded shift + 1 add) ~ 12 ops; ~2
# rotations touch each channel -> ~24 ops/sample-ch. The transform is stateless
# in time (fixed global coefficients, zero look-ahead), so it adds NO persistent
# per-channel state on top of the LMS state. Decoder does the inverse rotations
# at the same cost, so dec_ops == enc_ops.
_IKLT_OPS = 24
_IKLT_NOTE = (
    "fixed multiplierless reversible integer inter-channel transform "
    "(integer-KLT via 3-step lifting/Givens rotations at theta=45deg -- the "
    "EXACT KLT of a stationary isotropic equal-variance neighbour pair for any "
    "correlation, so data-independent: no training, no eigendecomposition, no "
    "side-info). Applied per time-slice over a fixed grid-neighbour schedule "
    "(all horizontal then all vertical adjacent pairs, channel order); the "
    "cascade mixes each channel across a neighbourhood -> genuinely MULTI-TAP, "
    "distinct from the rank-1 single-neighbour subtract of +xchan/bestpartner. "
    "Transform is within a time-slice so temporal look-ahead=0; decoder applies "
    "the inverse rotations in reverse order. Then per-channel LMS+Rice as usual.")

_BP_SELECT_OPS = 8
_BP_STATE = _XCHAN_STATE + 1
_BP_NOTE = ("per-channel best-partner: encoder scans <=4 causal grid neighbours "
            "(left/up/up-left/up-right, all idx<g) and picks the min-Rice-bits "
            "partner + integer gain; chosen (parent,beta) carried as 2xint16/ch "
            "side-info. Selection derived offline over the whole signal (like the "
            "incumbent xchan beta); embeddable realization selects per block "
            "(look-ahead=block). Decoder is search-free.")
_register(Codec("LMS+Rice+xchan_bestpartner", bestpartner_encode, bestpartner_decode,
    CodecMeta(
        integer_only=True, enc_ops=_LMS_OPS + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS_OPS + _XCHAN_OPS,
        state_bytes_per_ch=_LMS_STATE + _BP_STATE, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_BP_NOTE),
    family="cross-channel",
    desc="LMS + best-of-4 causal-neighbour cross-channel selection + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated by its order-4 sibling "
                   "LMS4+Rice+xchan_bestpartner (promoted 2026-07-16): identical "
                   "best-partner front-end, predictor order 8->4 gives higher ratio at "
                   "LOWER cost (0.039 vs 0.063) on ALL 4 real sets (otb 2.162x vs 2.151x, "
                   "hyser 1.480x vs 1.478x, capgmyo 1.350x vs 1.349x, cemhsey 1.956x vs "
                   "1.955x) -- P2 (order-8 over-provisioned, deeper prediction fits noise). "
                   "experiments/006_lms4_rice_xchan_bestpartner.md, cycle 2026-07-16."))

# NEW candidate: fixed reversible integer-KLT (lifting) inter-channel transform
# (this cycle). Multi-tap spatial front-end; zero temporal look-ahead; no
# side-info. Encode and decode both run the transform (fwd / inverse rotations),
# so enc_ops == dec_ops. No persistent transform state beyond the LMS weights.
_register(Codec("LMS+Rice+iklt", iklt_encode, iklt_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _IKLT_OPS, dec_ops=_LMS_OPS + _IKLT_OPS,
    state_bytes_per_ch=_LMS_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK, notes=_IKLT_NOTE), family="cross-channel",
    desc="fixed reversible integer-KLT (lifting) inter-channel transform + LMS + Rice",
    retired=True,
    retired_reason="Pareto-dominated by LMS+Rice+xchan on real otb_hdsemg_vl "
                    "(iklt 2.07x/cost 0.068 vs incumbent 2.24x/cost 0.057 -- worse "
                    "ratio AND higher cost; also dominated by bestpartner 2.25x/0.063 "
                    "and delta+Rice+xchan 2.19x/0.013). Fixed 45deg integer-KLT captures "
                    "only +8.8% real xchan gain vs single-neighbour subtract's +18.0%. "
                    "experiments/002_lms_rice_iklt.md, cycle 2026-07-13."))

# NEW candidate (this cycle): DATA-DEPENDENT adaptive integer-lifting rotation
# cascade (backward-adaptive Givens angle). Same rotation cascade as the retired
# iklt (~24 ops/sample-ch of 3-lift shears), PLUS a backward angle estimate: per
# schedule pair, accumulate three running dot-products (saa,sbb,sab ~ 3 macs/
# sample-ch over the previous block) and, once per block, an argmin over the
# 31-entry angle table (amortised ~31/256 ~ 0.1 op/sample-ch). The decoder
# RECOMPUTES the same angle (it is not transmitted), so dec_ops == enc_ops.
# State adds, on top of the LMS weights, the three int64 covariance accumulators
# for the pair a channel is currently in (24 B) + the current angle index (~1 B).
_ITSKLT_XTRA = 4    # 3 covariance-accumulate macs + amortised per-block argmin
_ITSKLT_STATE = _LMS_STATE + 26
_ITSKLT_NOTE = (
    "backward-adaptive DATA-DEPENDENT integer-lifting Givens rotation cascade. "
    "Keeps the retired iklt's multiplierless reversible 3-lift shear butterfly "
    "(lossless for ANY integer lift coeffs) but the rotation ANGLE per grid-"
    "neighbour pair per time-block is chosen from the pair's 2x2 covariance over "
    "the PREVIOUS reconstructed RAW block: the tabulated (31 angles, -60..60deg) "
    "theta minimizing the post-rotation off-diagonal |0.5(sbb-saa)sin2t+sab cos2t|,"
    " via an integer sin/cos table (no atan, no eigendecomposition, no float in "
    "the codec path). theta[block i] uses only raw block i-1 which the decoder "
    "reconstructs before it reaches block i -> zero side-info, look-ahead 0, "
    "decoder recomputes the angle. Block 0 bootstraps to identity (theta=0). "
    "Cascaded over all horizontal then all vertical adjacent pairs (=_iklt_pairs) "
    "-> multi-tap, distinct from the rank-1 single-neighbour subtract. Then the "
    "unchanged order-8 sign-sign LMS + adaptive Rice back-end (only the spatial "
    "basis differs from the retired fixed-45deg iklt).")
_register(Codec("LMS+Rice+iklt_adaptive", itsklt_encode, itsklt_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _IKLT_OPS + _ITSKLT_XTRA,
    dec_ops=_LMS_OPS + _IKLT_OPS + _ITSKLT_XTRA,
    state_bytes_per_ch=_ITSKLT_STATE, causal=True, lookahead_samples=0,
    block_size=ITSKLT_BLOCK, notes=_ITSKLT_NOTE), family="cross-channel",
    desc="data-dependent backward-adaptive integer-KLT (lifted Givens angle) "
         "cascade + LMS + Rice",
    retired=True,
    retired_reason="Pareto-dominated by LMS+Rice+xchan on ALL 4 real sets "
    "(cycle 2026-07-14, results/cycle_bench.csv): otb 1.885x/0.083 vs 2.143x/"
    "0.057, hyser 1.352x vs 1.474x, capgmyo 1.326x vs 1.349x, cemhsey 1.761x vs "
    "1.955x -- worse ratio AND higher cost everywhere. Backward-adaptive rotation "
    "angle from the previous block is a stale/noisy estimate on non-stationary "
    "HD-sEMG and the rotation corrupts BOTH channels, so it captures only "
    "+1.7..+3.3% cross-channel gain (worse than even the retired fixed iklt). "
    "See experiments/003_lms_rice_iklt_adaptive.md."))

# NEW seeded candidate
_register(Codec("fixed0-3+Rice", fixed_encode, fixed_decode, CodecMeta(
    integer_only=True, enc_ops=_FIXED_OPS, dec_ops=_FIXED_OPS,
    state_bytes_per_ch=_FIXED_STATE, causal=True, lookahead_samples=ec.BLOCK,
    block_size=ec.BLOCK), family="temporal",
    desc="FLAC fixed predictors ord 0-3, best-per-block + Rice"))

# NEW candidate (this cycle): table-driven tANS entropy back-end vs Rice on the
# IDENTICAL LMS+xchan predictor/front-end (INSIGHTS P5, open-frontier #1). Over
# the incumbent LMS+xchan per-sample work, the tANS back-end adds, per sample-
# ch: category bit-length (~3 ops), mantissa split (~2), one tANS table lookup +
# a short variable-length bit renorm (~5), a category histogram accumulate (~1),
# and the amortised per-block table build (2*M table entries / ANS_BLOCK ~ 1
# op/sample-ch) -> ~+12 ops over Rice. Decode is symmetric (also table lookups +
# renorm, no per-symbol divide), so dec_ops == enc_ops. The runtime path is
# division-free; the only divides are in the once-per-block freq normalization
# and table build. Persistent state adds, on top of the LMS+xchan state, the
# per-block category frequency table (~90 B) and Rice-k-equivalent bookkeeping;
# the M-entry tANS lookup tables and the ANS_BLOCK reverse-encode symbol buffer
# are SHARED working memory (rebuilt per block, not multiplied per channel) --
# noted, not charged per-channel. Bounded look-ahead = one ANS_BLOCK.
_ANS_XTRA = 12
_ANS_STATE = _LMS_STATE + _XCHAN_STATE + 90     # + per-block freq table (side-info)
_ANS_NOTE = (
    "table-driven tANS (LOCO-ANS style) entropy back-end swapped in for adaptive "
    "Golomb-Rice on the IDENTICAL LMS+Rice+xchan predictor and cross-channel "
    "front-end (same grid-parent beta side-info) -- a clean head-to-head that "
    "isolates the back-end's marginal bits (INSIGHTS P5). Residual coder is a "
    "LOCO-ANS bucket+remainder split: zigzag u, entropy-code the category "
    "c=bit-length(u) with tANS, ship c-1 raw mantissa bits (bounds the ANS "
    "alphabet for any int16 input). Per ANS_BLOCK a STATIC integer-normalized "
    "category frequency table (sum=2**R, R=10) is built and shipped as tiny "
    "side-info; both sides build bit-identical tANS tables from it. tANS state "
    "normalized to [M,2M); transitions PRECOMPUTED from the bitwise-rANS map so "
    "the runtime coder is table lookups + a variable bit renorm with NO per-"
    "symbol divide (the FPGA-friendly property; divides live only in the once-"
    "per-block table build). Encoder runs the ANS pass in reverse over the block "
    "(reverse-order encode buffer), decoder reads forward. Look-ahead = one "
    "ANS_BLOCK; the incumbent's whole-signal float beta remains a port caveat "
    "(front-end unchanged). Payoff expected small/uncertain -- a back-end "
    "refinement to MEASURE on real data, not a headline lever (P5).")
_register(Codec("LMS+Rice+xchan_tans", ans_encode, ans_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _XCHAN_OPS + _ANS_XTRA,
    dec_ops=_LMS_OPS + _XCHAN_OPS + _ANS_XTRA,
    state_bytes_per_ch=_ANS_STATE, causal=True, lookahead_samples=ANS_BLOCK,
    block_size=ANS_BLOCK, notes=_ANS_NOTE), family="entropy-backend",
    desc="LMS + grid-neighbour decorrelation + table-driven tANS residual coder "
         "(vs Rice, same predictor)",
    retired=True,
    retired_reason="Pareto-dominated by LMS+Rice+xchan (same front-end, Rice "
    "back-end) on ALL 4 real sets (cycle 2026-07-14, results/cycle_bench.csv): "
    "tANS is 1.4..1.8% SMALLER ratio at ~2x cost (0.109 vs 0.057) -- otb 2.103x "
    "vs 2.143x, hyser 1.451x vs 1.474x, capgmyo 1.330x vs 1.349x, cemhsey 1.922x "
    "vs 1.955x. Real HD-sEMG residuals are near-geometric, so Golomb-Rice is "
    "already the near-optimal prefix code and the per-block category-freq table "
    "side-info costs more than the sub-Golomb bits recovered (confirms INSIGHTS "
    "P5). See experiments/004_lms_rice_xchan_tans.md."))

# NEW candidate (this cycle): Adaptive Common Average Reference (ACAR). Over the
# per-channel LMS+Rice work, the front-end adds, per sample-ch: one accumulate
# into the running array total (~1 op), one subtract of the shared CAR (~1 op),
# and an amortised floor-divide per time slice (1 divide / C ~ 0.03 op/sample-ch);
# the backward gate re-accumulates two energy sums over the previous block (~2
# macs/sample-ch) plus one comparison per block (amortised). ~4 extra ops over
# plain LMS. The decoder RECOMPUTES the gate (not transmitted) and runs the exact
# inverse lift, so dec_ops == enc_ops. The running array total and the two energy
# accumulators are O(1) SHARED working state (one per time slice / per block, NOT
# multiplied per channel) -- noted, not charged per-channel; per-channel state is
# just the LMS weights plus the current gate flag.
_ACAR_XTRA = 4     # accumulate-to-total + CAR subtract + amortised divide + gate macs
_ACAR_STATE = _LMS_STATE + 2   # LMS weights + gate flag (array-sum/energy accs shared)
_ACAR_NOTE = (
    "Adaptive Common Average Reference: a reversible-integer S-transform-style "
    "lift that removes the GLOBAL array common-mode (weighted mean across the "
    "whole array) before the temporal predictor -- a rank-1 GLOBAL spatial lever, "
    "distinct from the pairwise/single-neighbour subtracts of +xchan/xadapt/"
    "bestpartner (a different slice of the cross-channel mutual information, "
    "INSIGHTS P1). Per ON time-slice: S=sum_c x (array total), CAR=floor(S/C); the "
    "root channel slot carries S (the virtual total channel -- preserves the array "
    "DC that subtracting the mean from all channels would lose), every other "
    "channel becomes x-CAR (true mean-referenced residual: common mode removed, "
    "only ~1/C of the aggregate noise added). Inverse is exact and integer "
    "(CAR=floor(S/C); x_c=y_c+CAR; x_0=S-sum_{c>=1}x_c), per-time-slice, "
    "look-ahead 0. GATED per block BACKWARD-ADAPTIVELY: block i is transformed only "
    "if C*sum(CAR^2)/sum(x^2) over the PREVIOUS reconstructed raw block exceeds "
    "1/16 (~2/C, above the 1/C floor independent noise makes by array-averaging) -- "
    "so it fires only on a genuine shared component, cannot hurt low-common-mode "
    "blocks (identity pass-through), and ships ZERO side-info (the decoder "
    "recomputes the gate). Block 0 bootstraps OFF. Then the unchanged order-8 "
    "sign-sign LMS + adaptive Rice back-end (only the spatial front-end differs). "
    "Basis: Vaisman/Jordanic/Farina adaptive CAR filtering for HD-EMG (MBEC 2014), "
    "a myocontrol/SNR result -- unverified for compression here.")
_register(Codec("LMS+Rice+acar", acar_encode, acar_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _ACAR_XTRA, dec_ops=_LMS_OPS + _ACAR_XTRA,
    state_bytes_per_ch=_ACAR_STATE, causal=True, lookahead_samples=0,
    block_size=ACAR_BLOCK, notes=_ACAR_NOTE), family="cross-channel",
    desc="adaptive common-average reference (reversible-integer lift, backward-"
         "gated) + LMS + Rice"))

# NEW candidate (this cycle): Order-4 LMS under the best-partner front-end
# (INSIGHTS open-frontier #1). Identical to LMS+Rice+xchan_bestpartner but with
# the temporal predictor right-sized order-8 -> order-4 (INSIGHTS P2). Op/state
# accounting mirrors bestpartner with the LMS half-sized: order-4 sign-sign LMS
# is ~4 mac + 1 shift + 4-tap sign update(~8) + hist shift(4) + rice(~9) ~ 26 ops
# and 4 weights + 4 history = 8xint16 = 16 B + rice bookkeeping ~ 24 B state (vs
# the order-8 _LMS_OPS=50 / _LMS_STATE=40). Encoder adds the +xchan per-sample
# work and the best-partner neighbour scan (~8 ops); the decoder is search-free
# (reads the chosen parent+beta side-info), so dec_ops omits the scan.
_LMS4_OPS = 26
_LMS4_STATE = 24
_LMS4BP_NOTE = (
    "best-partner cross-channel front-end (per-channel best-of-4 causal grid "
    "neighbour + integer gain, 2xint16/ch side-info -- reused verbatim from "
    "LMS+Rice+xchan_bestpartner) with the temporal predictor right-sized from "
    "the family's order-8 to order-4 sign-sign LMS (INSIGHTS P2: order-4 beats "
    "order-8 on real Hyser/OTB -- deeper prediction fits noise and raises coded "
    "entropy -- at ~half the state/ops). Same backward-adaptive LMS on both "
    "sides (zero temporal side-info, INSIGHTS P4); only the predictor order "
    "differs from bestpartner. Selection derived offline over the whole signal "
    "like the incumbent xchan/bestpartner beta; embeddable realization selects "
    "per block (look-ahead=block). Decoder is search-free.")
_register(Codec("LMS4+Rice+xchan_bestpartner", lms4bp_encode, lms4bp_decode,
    CodecMeta(
        integer_only=True, enc_ops=_LMS4_OPS + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS4_OPS + _XCHAN_OPS,
        state_bytes_per_ch=_LMS4_STATE + _BP_STATE, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_LMS4BP_NOTE),
    family="cross-channel",
    desc="order-4 LMS + best-of-4 causal-neighbour cross-channel selection + Rice"))

# NEW candidate (this cycle): regime-switched (context-gated) order-4 temporal
# predictor under the promoted best-partner front-end (INSIGHTS open-frontier #2).
# Same spatial front-end + same order-4 sign-LMS math as LMS4+Rice+xchan_bestpartner,
# but the single temporal predictor becomes a BANK of RSW_NREG=3 order-4 sign-LMS
# predictors, one selected per sample-channel by a backward activity regime. Ops:
# on top of the order-4 LMS work (_LMS4_OPS) each sample adds two leaky-integrator
# updates (2 add + 2 shift ~4), one 3-way regime compare (~3), and a bank index
# (amortised ~1) -> ~8 extra ops/sample-ch; the per-regime update touches the SAME
# 4 taps, so the mac/adapt work is unchanged (only WHICH set). State: RSW_NREG=3
# weight banks of order-4 (3x4 int16 = 24 B) + order-4 history (8 B) + two int32
# energy accumulators (8 B) ~ 40 B, plus the best-partner side-info state (_BP_STATE).
# Backward-adaptive regime -> ZERO temporal side-info, look-ahead 0 (P4). Decoder
# mirrors the regime from reconstructed residuals, so dec_ops == enc_ops minus the
# best-partner neighbour scan (like bestpartner, decoder is selection-search-free).
_RSW_XTRA = 8
_RSW_STATE = 4 * RSW_NREG * 2 + RSW_ORDER * 2 + 8   # 3x4 weights + 4 hist + 2 acc (int16 units)
_RSBP_NOTE = (
    "regime-switched temporal predictor: keeps the promoted order-4 best-partner "
    "spatial front-end (best-of-4 causal grid neighbour + integer gain, 2xint16/ch "
    "side-info, reused verbatim) and replaces the single order-4 sign-sign LMS with "
    "a BANK of 3 order-4 sign-LMS predictors, one selected PER SAMPLE by a backward "
    "activity regime (recent vs long-term leaky |residual| energy, quiescent/normal/"
    "burst). Each regime adapts only on its own samples -> conditional residual "
    "variance H(e|regime) < H(e) on bursty HD-sEMG (INSIGHTS open-frontier #2: attack "
    "the temporal residual entropy, not the decorrelator). Regime derived from "
    "causally-reconstructed residuals only -> ZERO temporal side-info, look-ahead 0 "
    "(P4); order stays 4 (P2), only the number of coefficient sets grows. Distinct "
    "from the RETIRED xctx (P5): xctx conditioned the Rice PARAMETER on a cross-channel "
    "context leaving the residual unchanged; this conditions the PREDICTOR "
    "COEFFICIENTS on a temporal regime, reducing the residual upstream. Coder stays "
    "adaptive Rice (no back-end swap). Selection front-end derived offline like the "
    "incumbent bestpartner (embeddable realization selects per block, look-ahead=block).")
_register(Codec("LMS4rs+Rice+xchan_bestpartner", rsbp_encode, rsbp_decode,
    CodecMeta(
        integer_only=True, enc_ops=_LMS4_OPS + _RSW_XTRA + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS4_OPS + _RSW_XTRA + _XCHAN_OPS,
        state_bytes_per_ch=_RSW_STATE + _BP_STATE, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_RSBP_NOTE),
    family="cross-channel",
    desc="regime-switched (context-gated) order-4 LMS bank + best-partner + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated by LMS4+Rice+xchan_bestpartner on ALL "
                   "4 real sets (worse ratio AND higher cost 0.0524 vs 0.0394: otb 2.126x "
                   "vs 2.162x, hyser 1.476x vs 1.480x, capgmyo 1.340x vs 1.350x, cemhsey "
                   "1.954x vs 1.956x). Splitting the order-4 predictor into a 3-regime bank "
                   "did NOT lower H(e|regime) below H(e): after order-4 LMS the residual is "
                   "near-white (P2), 'burst' segments are higher-variance NOISE not distinct "
                   "linear dynamics, and per-regime banks each see ~1/3 the samples so they "
                   "adapt noisier -- fragmenting adaptation raised coded bits. Temporal "
                   "residual-entropy lever (frontier #2) spent NEGATIVE. "
                   "experiments/013_lms4rs_rice_xchan_bestpartner.md, cycle 2026-07-22."))

# NEW candidate (this cycle): two-stage scale-matched spatial front-end -- GLOBAL
# adaptive-CAR THEN LOCAL order-4 best-partner (INSIGHTS open-frontier #1). A pure
# CASCADE of two already-verified primitives, so its cost is the union of theirs:
# the ACAR lift's per-sample work (_ACAR_XTRA: accumulate-to-total + CAR subtract +
# amortised floor-divide + backward-gate macs) PLUS the best-partner front-end's
# per-sample subtract (_XCHAN_OPS) and its OFFLINE neighbour scan (_BP_SELECT_OPS,
# encoder only -- the decoder reads the chosen parent+beta side-info and is
# search-free) PLUS the right-sized order-4 LMS (_LMS4_OPS, INSIGHTS P2). The decoder
# RECOMPUTES the backward ACAR gate (not transmitted) and runs both exact inverse
# lifts, so dec_ops == enc_ops minus only the encoder-only best-partner scan. State
# is the order-4 LMS weights/history + best-partner bookkeeping (_BP_STATE) + the
# 1-byte ACAR gate flag; the ACAR array-total and energy accumulators are O(1)
# SHARED working state (one per time-slice/block, not per channel). ACAR ships ZERO
# side-info (backward gate, look-ahead 0); the best-partner (parent,beta) pair is the
# only side-info and, like the incumbent bestpartner, is derived offline over the
# whole signal -- embeddable realization selects per block (look-ahead=block).
_ACARBP_NOTE = (
    "two-stage scale-matched cross-channel front-end: GLOBAL adaptive-CAR (stage 1) "
    "THEN LOCAL best-partner (stage 2), both reused VERBATIM, behind order-4 LMS+Rice "
    "(the promoted best's back-end, INSIGHTS P2). Stage 1 is the ACAR reversible-"
    "integer S-transform lift (root slot carries the array total S; every other "
    "channel becomes x-floor(S/C)), backward-GATED per block (transformed only if "
    "C*sum(CAR^2)/sum(x^2) over the PREVIOUS reconstructed raw block exceeds 1/16 ~2/C, "
    "above the 1/C floor independent noise makes by array-averaging), block-0 OFF, "
    "ZERO side-info -- removes the GLOBAL rank-1 common-mode (one eigenvector, "
    "DC-across-array). Stage 2 is the best-of-4 causal grid neighbour + integer gain "
    "(2xint16/ch side-info) applied to the CAR RESIDUAL -- removes the LOCAL pairwise "
    "MI CAR leaves. The two slices are distinct and NON-INTERCHANGEABLE (INSIGHTS "
    "P1-refinement: CAR wins tight arrays +14.4% OTB, pairwise wins large Hyser/CEMHSEY "
    "+10.8..13.1%); cascading captures BOTH where both exist. ORTHOGONAL BY "
    "CONSTRUCTION -- stage 1 removes the array mean, leaving a residual whose local "
    "pairwise covariance is uncorrelated with the global mean it took, so unlike the "
    "RETIRED summed multi-parent (correlated parents -> over-subtract) the stages "
    "cannot double-count. Decode inverts in reverse (Rice -> lms_inverse(order4) -> "
    "bp_inverse -> acar_inverse), the ACAR gate recomputed from reconstructed raw "
    "history -- fully causal, bit-exact. Risk (to measure): on large arrays CAR may "
    "not clear its gate and add ~nothing after best-partner already took the local "
    "slice -- measure whether the slices are additive or redundant.")
_register(Codec("LMS4+Rice+acar+bestpartner", acarbp_encode, acarbp_decode,
    CodecMeta(
        integer_only=True,
        enc_ops=_LMS4_OPS + _ACAR_XTRA + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS4_OPS + _ACAR_XTRA + _XCHAN_OPS,
        state_bytes_per_ch=_LMS4_STATE + _BP_STATE + 2, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_ACARBP_NOTE),
    family="cross-channel",
    desc="two-stage spatial front-end: global adaptive-CAR lift THEN local order-4 "
         "best-partner subtract + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated (superseded) by its scale-selected "
                   "version LMS4+Rice+acar_sel+bestpartner at EQUAL cost 0.043: acar_sel "
                   "reproduces this codec's OTB max-ratio corner EXACTLY (2.1795x, "
                   "byte-identical body) but is strictly BETTER on the large arrays where "
                   "the always-on CAR lift injected mismatched-basis noise (hyser 1.4804x "
                   "vs 1.4770x, cemhsey 1.9555x vs 1.9515x; capgmyo tie 1.3505x). >= ratio "
                   "on every real set, strictly > on 2, at the same cost -> no remaining "
                   "trade-off. The scale gate makes always-on cascade obsolete. "
                   "experiments/014_lms4_rice_acar_sel_bestpartner.md, cycle 2026-07-22."))

# NEW candidate (this cycle): SCALE-SELECTED two-stage cascade (INSIGHTS
# open-frontier #3, salvage of frontier #1). A META-GATE over two already-verified
# primitives: per recording it picks the CAR+best-partner cascade
# (LMS4+Rice+acar+bestpartner) for TIGHT arrays vs best-partner-only
# (LMS4+Rice+xchan_bestpartner) for EXTENDED arrays, from the decoder-derivable
# array channel count C. Cost is the union of the branch it takes (never both), so
# it is Pareto-bounded by the cascade branch and reduces to best-partner's cost on
# large arrays; ops/state below quote the worst case (the cascade branch, C<=64),
# identical to LMS4+Rice+acar+bestpartner. The scale gate is a pure integer compare
# on C -- ZERO side-info, ZERO circularity (the decoder reads C from the header
# before reconstructing) -- so dec_ops mirrors the always-on cascade's.
_ACARSEL_NOTE = (
    "SCALE-SELECTED two-stage cross-channel cascade -- a META-GATE over two "
    "already-verified primitives (NOT a new mechanism). Per recording, from the "
    "decoder-derivable ARRAY CHANNEL COUNT C, it selects the spatial front-end: "
    "C<=64 (TIGHT array, the array-mean is a coherent eigenvector -- INSIGHTS "
    "P1-refinement) -> the full cascade (GLOBAL backward-gated adaptive-CAR lift "
    "_acar_forward THEN LOCAL best-partner _bp_select, identical to "
    "LMS4+Rice+acar+bestpartner); C>=128 (EXTENDED array, shared content is spatially "
    "LOCAL) -> best-partner ONLY (identical to the promoted LMS4+Rice+xchan_bestpartner), "
    "so the CAR stage cannot subtract its mismatched global basis and inject noise. "
    "The gate is a pure integer compare on C, which the decoder reads from the header "
    "BEFORE any reconstruction -> deterministic, ZERO circularity, ZERO side-info "
    "beyond best-partner's own (parent,beta) pair. Threshold ACARSEL_MAX_CH=64 is the "
    "measured regime boundary: CAR helped +0.81% on the 64-ch OTB array but was "
    "-0.23..-0.26 pp on the 128-/320-ch Hyser/CEMHSEY arrays (the two MI slices are "
    "additive only where the global mode is a real eigenvector). Keeps the OTB "
    "max-ratio corner WITHOUT the large-array regression the always-on cascade paid. "
    "Both branches are exact-integer-invertible verified primitives, identical header "
    "format; decode derives the SAME branch from C and inverts the matching cascade "
    "(bp_inverse then, only for C<=64, acar_inverse). Behind both: order-4 sign-sign "
    "LMS + adaptive Rice (INSIGHTS P2). Cost/state quoted for the worst case (cascade "
    "branch); best-partner-only on large arrays is strictly cheaper. Basis: "
    "Vaisman/Farina adaptive-CAR + the shipped best-partner; meta-gate novel here.")
_register(Codec("LMS4+Rice+acar_sel+bestpartner", acarsel_encode, acarsel_decode,
    CodecMeta(
        integer_only=True,
        enc_ops=_LMS4_OPS + _ACAR_XTRA + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS4_OPS + _ACAR_XTRA + _XCHAN_OPS,
        state_bytes_per_ch=_LMS4_STATE + _BP_STATE + 2, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_ACARSEL_NOTE),
    family="cross-channel",
    desc="scale-selected spatial cascade: per-recording gate (by channel count) "
         "between global adaptive-CAR+best-partner and best-partner-only + Rice"))

# NEW candidate (this cycle): Multi-parent backward-adaptive rank-1 subtract
# (INSIGHTS open-frontier #2). Extends the single grid-parent to TWO causal
# parents (up + left), each with its OWN backward-adaptive integer beta, the two
# rank-1 residual subtracts SUMMED. Over the incumbent +xchan per-sample work,
# each parent contributes: the rank-1 subtract itself (1 mul + 1 shift + 1 sub ~
# _XCHAN_OPS) PLUS a backward beta estimate (two running dot-products <x_c,x_p>,
# <x_p,x_p> ~ 2 macs + an amortised block divide ~ _XADAPT_XTRA). Two parents ->
# 2*(_XCHAN_OPS + _XADAPT_XTRA) extra ops over plain LMS. The decoder RECOMPUTES
# both betas (nothing transmitted), so dec_ops == enc_ops. State adds, on top of
# the order-8 LMS weights, two int16 betas (4 B) + two int64 covariance
# accumulators per parent (2 parents x 2 x 8 = 32 B) = 36 B. Backward-adaptive
# so look-ahead 0 and ZERO side-info (INSIGHTS P4).
_MP_XTRA = 2 * (_XCHAN_OPS + _XADAPT_XTRA)   # two parents: subtract + backward beta each
_MP_STATE = _LMS_STATE + 36                  # LMS + 2 betas + 2x2 int64 accumulators
_MP_NOTE = (
    "multi-parent backward-adaptive rank-1 cross-channel subtract: TWO causal "
    "grid parents per channel -- up (g-cols) and left (g-1), both idx<g -- each "
    "with its OWN backward-adaptive integer gain beta = <x_c,x_p>/<x_p,x_p> "
    "(fixed-point) estimated from the PREVIOUS block's already-reconstructed RAW "
    "samples (block 0 -> beta=0), the two rank-1 residual subtracts SUMMED: "
    "y[c]=x[c]-((bu*x[up])>>s)-((bl*x[left])>>s). A rank-2 LOCAL decorrelation as "
    "TWO independent asymmetric rank-1 subtracts (not a joint 2x2 solve); each "
    "subtracts the CLEAN raw parent and injects estimation noise only into "
    "residual channel c, leaving both parent rows untouched -- the robustness "
    "property INSIGHTS P3-refinement credits the rank-1 subtract with (unlike the "
    "retired energy-preserving iklt_adaptive rotation that corrupts both "
    "channels). Both betas recomputed by the decoder from bit-identical "
    "reconstructed history -> zero side-info, look-ahead 0, backward-adaptive "
    "(INSIGHTS P4). Targets the residual LOCAL spatial MI one parent leaves on "
    "extended high-|corr| arrays (INSIGHTS P1-refinement, open-frontier #2); "
    "distinct from the retired single-parent scalar xchan_adaptive by adding a "
    "second independent parent on a different topology. Then the unchanged "
    "order-8 sign-sign LMS + adaptive Rice back-end. Basis: MPEG-4 ALS "
    "multichannel / Choi et al. 2014 (paper-reported, unverified here).")
_register(Codec("LMS+Rice+xchan_multiparent", mp_encode, mp_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _MP_XTRA, dec_ops=_LMS_OPS + _MP_XTRA,
    state_bytes_per_ch=_MP_STATE, causal=True, lookahead_samples=0,
    block_size=MP_BLOCK, notes=_MP_NOTE), family="cross-channel",
    desc="LMS + two-parent (up+left) backward-adaptive rank-1 cross-channel "
         "decorrelation + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated by LMS+Rice+xchan on ALL 4 real "
                   "sets (worse ratio AND higher cost 0.078 vs 0.057: otb 1.971x vs "
                   "2.143x, hyser 1.398x vs 1.474x, capgmyo 1.347x vs 1.349x, cemhsey "
                   "1.872x vs 1.955x). Summing two INDEPENDENT marginal rank-1 subtracts "
                   "over-subtracts the up/left parents' shared common mode (Cov(up,left)>0 "
                   "ignored) -- captures only ~half the single-parent xchan gain. "
                   "experiments/007_lms_rice_xchan_multiparent.md, cycle 2026-07-16."))

# NEW candidate (this cycle): Cross-channel context-adaptive Rice (SECOND-ORDER /
# CONDITIONAL entropy axis, untouched by any tried codec). Keeps the order-8
# sign-sign LMS residual and the Golomb-Rice ENGINE, but selects the per-sample
# Rice k from a backward SPATIAL context (JPEG-LS/LOCO-I context modeling). Over
# the plain LMS+Rice per-sample work, the xctx back-end adds, per sample-ch: a
# leaky neighbour-energy update (1 add + 1 shift + 1 sub ~3), a bit-length bucket
# (~1), the LOCO-I k lookup (a short while-loop, amortised ~2), and the
# per-context (A,N) accumulate + occasional halving (~1) -> ~+8 ops over Rice.
# Decode mirrors the identical bucket + stats update (also no per-symbol divide),
# so dec_ops == enc_ops. Persistent state adds, on top of the order-8 LMS
# weights, XCTX_NBUCKETS per-context stat pairs (A int32 + N int16 ~ 6 B each ->
# ~72 B) + the leaky-energy accumulator (~4 B). Backward-adaptive: ZERO side-info
# (no k, no context table transmitted), look-ahead 0 -- the decoder recomputes
# every k from the already-reconstructed neighbour residual.
_XCTX_XTRA = 8
_XCTX_STATE = _LMS_STATE + XCTX_NBUCKETS * 6 + 4   # LMS + per-context (A,N) + nrg
_XCTX_NOTE = (
    "cross-channel context-adaptive Golomb-Rice: same order-8 sign-sign LMS "
    "residual and the SAME Rice engine as the family (P5 -- Rice is at the floor "
    "for the unconditional residual), but the per-sample Rice k is selected from "
    "a backward SPATIAL context (JPEG-LS/LOCO-I context modeling on a "
    "cross-channel context). For channel c with causal grid parent p (p<c, so "
    "the decoder has p's full residual first), a leaky integrator of |res[p,t]| "
    "estimates the neighbour spatial energy; its bit-length buckets that energy "
    "(XCTX_NBUCKETS log-energy buckets). Per bucket, JPEG-LS stats (A=sum coded "
    "magnitudes, N=count, halving-reset at 64) pick k = smallest with (N<<k)>=A, "
    "so k tracks the residual variance CONDITIONED on the neighbour's current "
    "energy -- exploiting H(e_c|neighbour energy) < H(e_c), the across-channel "
    "HETEROSCEDASTICITY a single per-block k misses (spatially coherent MUAP "
    "bursts stay variance-correlated across channels even after mean "
    "decorrelation). Bucket + (A,N) updated identically on both sides from "
    "bit-identical causal data -> ZERO side-info (no per-block k, no context "
    "table), backward-adaptive (P4), look-ahead 0. Root channels (no parent) "
    "fall back to a single context = plain per-channel JPEG-LS adaptive k. "
    "Distinct from the RETIRED xchan_tans (P5): the entropy ENGINE stays Rice; "
    "only its PARAMETER's context gains cross-channel information. Nothing is "
    "subtracted across channels -- the neighbour only CONDITIONS the coder. "
    "Basis: JPEG-LS/LOCO-I context-conditioned Golomb, US7580585B2 "
    "(backward-adaptive Rice), Giurcaneanu/Tabus 2001 -- unverified here.")
_register(Codec("LMS+Rice+xctx", xctx_encode, xctx_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS_OPS + _XCTX_XTRA, dec_ops=_LMS_OPS + _XCTX_XTRA,
    state_bytes_per_ch=_XCTX_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK, notes=_XCTX_NOTE), family="entropy-backend",
    desc="LMS + cross-channel context-adaptive Rice k (JPEG-LS-style spatial "
         "context, zero side-info)",
    retired=True,
    retired_reason="Conclusively Pareto-dominated even by plain LMS+Rice (no xchan) on "
                   "ALL 4 real sets (worse ratio AND far higher cost 0.095 vs 0.052: otb "
                   "1.783x vs 1.825x, hyser 1.293x vs 1.330x, capgmyo 1.297x vs 1.332x, "
                   "cemhsey 1.682x vs 1.729x). After LMS whitening the residual is not "
                   "cross-channel heteroscedastic enough: H(e_c|neighbour energy) ~= "
                   "H(e_c), so the 12-bucket context split's model cost dominates any "
                   "conditional-entropy gain -- confirms/extends P5. "
                   "experiments/008_lms_rice_xctx.md, cycle 2026-07-16."))

# NEW candidate (this cycle): Joint asymmetric 2-parent adaptive sign-LMS spatial
# predictor (INSIGHTS open-frontier #3 -- the de-risked JOINT second-parent
# escape). Over the order-4 LMS+Rice per-sample work, the spatial front-end adds,
# per sample-ch: a 2-tap prediction (2 mul + 1 add + 1 shift ~4), the residual
# subtract (1), and the two sign-sign tap updates (2 signs + 2 signs + 2 adds ~4)
# -> ~+9 ops over the order-4 temporal LMS. Backward-adaptive (both taps re-derived
# from the shared residual + reconstructed parents), so the decoder does the
# IDENTICAL work: dec_ops == enc_ops. State adds, on top of the order-4 LMS
# weights/history, just the two int16 spatial taps (4 B) per channel; NO side-info
# is transmitted (zero header, look-ahead 0 -- INSIGHTS P4). Two extra taps only,
# so it clears the tight neural 125-cyc budget.
_XJ2_XTRA = 9      # 2-tap spatial predict (mac+shift) + subtract + two sign-sign updates
_XJ2_STATE = _LMS4_STATE + 4   # order-4 LMS state + two int16 spatial taps (w_u,w_l)
_XJ2_NOTE = (
    "joint asymmetric 2-parent spatial sign-sign LMS: predicts channel c from BOTH "
    "causal grid parents up (g-cols) and left (g-1) with ONE joint predictor "
    "pred=(w_u*x[up]+w_l*x[left])>>shift, and BOTH taps co-adapt against the SAME "
    "post-subtraction residual e=x[c]-pred via sign-sign LMS (w_u+=sign(e)sign(x[up]), "
    "w_l+=sign(e)sign(x[left]) -- +/-1 tap update, multiplierless). Because the taps "
    "descend the SHARED residual after both current taps subtract, each adapts to the "
    "correlation REMAINING once the other parent's contribution is out -- the "
    "stochastic-gradient realization of the 2x2 normal-equations (multiple-regression) "
    "solve that accounts for parent-parent covariance. This is the ONLY unspent "
    "second-parent escape INSIGHTS leaves: a JOINT solve, NOT the retired "
    "xchan_multiparent's SUM of two independent MARGINAL rank-1 betas (which "
    "double-counts the correlated parents' shared mode -> over-subtracts). ASYMMETRIC "
    "rank-1 residual-only injection: only channel c's coded residual is modified; the "
    "raw parent rows are inputs left CLEAN, so estimation noise never touches the "
    "parents -- unlike the retired energy-preserving iklt_adaptive rotation that "
    "corrupts both channels (INSIGHTS P3-refinement robustness). Both taps re-derived "
    "by the decoder from bit-identical reconstructed parents (idx<c) and the coded "
    "residual e -> ZERO side-info, look-ahead 0, backward-adaptive (INSIGHTS P4). "
    "Behind the spatial front-end: the order-4 sign-sign LMS temporal predictor "
    "(INSIGHTS P2, the promoted best's back-end) + adaptive Rice. Basis: MPEG-4 ALS "
    "RLS-LMS multichannel / multivariate-RLS (arXiv 1605.04418, paper-reported, "
    "unverified here).")
_register(Codec("LMS+Rice+xchan_joint2", xj2_encode, xj2_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _XJ2_XTRA, dec_ops=_LMS4_OPS + _XJ2_XTRA,
    state_bytes_per_ch=_XJ2_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK, notes=_XJ2_NOTE), family="cross-channel",
    desc="order-4 LMS + joint 2-parent (up+left) backward-adaptive sign-sign LMS "
         "spatial predictor (zero side-info) + Rice"))

# NEW candidate (this cycle): Backward-adaptive per-block best-partner RE-SELECTION
# (INSIGHTS open-frontier #3 -- the port-caveat closure for the PROMOTED best).
# Identical to LMS4+Rice+xchan_bestpartner but the (partner, beta) pair is re-
# selected PER BLOCK from the PREVIOUS reconstructed raw block instead of derived
# offline over the whole signal -- so BOTH the whole-signal look-ahead AND the
# 2xint16/ch header are removed. Over the order-4 LMS+Rice per-sample work, the
# front-end adds the per-block re-selection scan: for each of <=4 causal
# candidates, two running dot-products <x_c,x_p>/<x_p,x_p> over the previous block
# (~2 macs/sample-ch each) + the residual Rice-bits estimate, then an amortised
# per-block argmin, PLUS the chosen rank-1 subtract on the current block
# (_XCHAN_OPS). Unlike the offline bestpartner (decoder search-free), the decoder
# here RECOMPUTES the same selection from bit-identical reconstructed history, so
# dec_ops == enc_ops. Persistent per-channel state is the order-4 LMS
# weights/history + the current (partner id, beta) (~3 B); the <=4-candidate
# covariance accumulators are O(1) SHARED working state (reused per channel-block,
# not multiplied per channel) -- noted, not charged per-channel. Backward-adaptive
# so look-ahead 0 and ZERO side-info (INSIGHTS P4) -- the embeddability win over
# the promoted best.
_LMS4BPA_SELECT = 10   # <=4-candidate backward scan (2 macs each) + amortised argmin
_LMS4BPA_STATE = _LMS4_STATE + 3   # order-4 LMS + current (partner byte, int16 beta)
_LMS4BPA_NOTE = (
    "backward-adaptive per-block best-partner RE-SELECTION: the PROMOTED best "
    "LMS4+Rice+xchan_bestpartner with its offline whole-signal (partner, beta) "
    "swapped for per-block backward re-selection. For channel g, block i>0: over "
    "the PREVIOUS already-reconstructed RAW block, scan the <=4 causal grid "
    "neighbours (left/up/up-left/up-right, all idx<g -- same _bp_candidates), "
    "derive each candidate's integer least-squares gain (_bp_opt_beta) and score "
    "the resulting cross-residual's estimated Rice bits (_bp_score), also scoring "
    "the no-partner option, and keep the min-bits (partner, beta). That pair is "
    "applied as a rank-1 subtract to the CURRENT block: y[g]=x[g]-((beta*x[p])>>s). "
    "Because reconstruction is lossless the decoder holds the bit-identical raw "
    "previous block and every candidate partner (idx<g) is already reconstructed, "
    "so it recomputes the SAME (partner, beta) causally -> ZERO side-info (no "
    "2xint16/ch header), look-ahead 0. Block 0 bootstraps to no-partner (coded "
    "as-is). Same 4-candidate neighbourhood, integer-LS beta, Rice-bits scoring, "
    "and order-4 sign-sign LMS + adaptive Rice back-end as the promoted best "
    "(INSIGHTS P2); only the ESTIMATION is now backward-adaptive (INSIGHTS P4), "
    "closing the promoted codec's last port caveat (offline partner/beta + header). "
    "Distinct from the RETIRED LMS+Rice+xchan_adaptive (single FIXED-grid-parent "
    "scalar beta, NO partner selection): here the partner IDENTITY itself is "
    "re-selected per block. Ratio risk to MEASURE: a stale partner across a burst "
    "boundary on non-stationary HD-sEMG -- an embeddability/port lever, not a ratio "
    "play; the question is whether it HOLDS the promoted offline ratio.")
_register(Codec("LMS4+Rice+xchan_bestpartner_adaptive", lms4bpa_encode, lms4bpa_decode,
    CodecMeta(
        integer_only=True, enc_ops=_LMS4_OPS + _XCHAN_OPS + _LMS4BPA_SELECT,
        dec_ops=_LMS4_OPS + _XCHAN_OPS + _LMS4BPA_SELECT,
        state_bytes_per_ch=_LMS4BPA_STATE, causal=True, lookahead_samples=0,
        block_size=LMS4BPA_BLOCK, notes=_LMS4BPA_NOTE), family="cross-channel",
    desc="order-4 LMS + backward-adaptive per-block best-of-4 partner RE-SELECTION "
         "(zero side-info) + Rice"))

# NEW candidate (this cycle): Joint-solved SELECTED best pair -- selection x count
# fused (INSIGHTS open-frontier #1, the highest-payoff live lever). Stacks the two
# proven-but-substitute spatial degrees of freedom: per-block backward best-PAIR
# SELECTION (like bestpartner_adaptive, but choosing a pair) THEN a joint co-adaptive
# 2-tap sign-sign LMS on that pair (like joint2, but on the selected pair, not a fixed
# up+left one). Over the order-4 LMS+Rice per-sample work, the front-end adds: the
# joint 2-tap predict + subtract + two sign-sign tap updates (~_XJ2_XTRA) PLUS the
# per-block backward re-selection scan (<=4 single-candidate marginal dot-products +
# <=6 candidate-pair 2x2 LS solves over the previous block, amortised over the block
# ~_JBP2_SELECT). Backward-adaptive: both the selected pair AND the two taps are
# recomputed by the decoder from bit-identical reconstructed history, so the decoder
# does the IDENTICAL work -> dec_ops == enc_ops, ZERO side-info, look-ahead 0
# (INSIGHTS P4). Persistent per-channel state is the order-4 LMS weights/history + the
# two int16 spatial taps (w_u,w_l, 4 B) + the current selected (pu,pl) ids (~2 B); the
# <=6-pair covariance accumulators are O(1) SHARED working state (reused per
# channel-block, not multiplied per channel) -- noted, not charged per-channel. Two
# extra taps + a bounded per-block scan on the order-4 base -> clears the tight neural
# 125-cyc budget.
_JBP2_SELECT = 14   # <=4 single (2 macs each) + <=6 pair 2x2-LS scans, amortised/block
_JBP2_STATE = _LMS4_STATE + 6   # order-4 LMS + two int16 taps (4 B) + (pu,pl) ids (2 B)
_JBP2_NOTE = (
    "joint-solved SELECTED best pair -- selection x COUNT fused (INSIGHTS P1b + "
    "open-frontier #1): stacks the two spatial degrees of freedom P1b proved are used "
    "alone as substitutes. STAGE 1 SELECTION (per channel, per block i>0, backward): "
    "over the PREVIOUS already-reconstructed RAW block, score in estimated Rice bits "
    "the no-parent option, each single-parent option (integer-LS gain, reusing "
    "_bp_opt_beta/_bp_score -- the best-partner path), AND every causal-neighbour PAIR "
    "under a JOINT 2x2 integer least-squares solve (_jbp2_pair_resid: fixed-point gains "
    "from the pair's covariance, accounting for parent-parent covariance -- the "
    "marginal->multiple fix, so it CANNOT double-count the shared mode the RETIRED "
    "summed multiparent did); keep the min-bits pair (pu,pl>=0) / single (pu>=0,pl=-1) "
    "/ none (-1,-1). Candidates = <=4 causal grid neighbours (left/up/up-left/up-right, "
    "all idx<c, reused _bp_candidates). COUNT falls out of the same scored search, so a "
    "useless second parent is not forced on tight arrays (the exact P1b tension). "
    "STAGE 2 PREDICT: ONE joint co-adaptive sign-sign LMS on the SELECTED pair "
    "(structure verbatim from xchan_joint2) -- pred=(w_u*x[pu]+w_l*x[pl])>>shift, "
    "e=x[c]-pred, BOTH taps co-adapt against the SHARED post-subtraction residual "
    "(w_u+=sign(e)sign(x[pu]), w_l+=sign(e)sign(x[pl]), +/-1 update, multiplierless); "
    "each tap adapts to the correlation REMAINING once the other's contribution is out "
    "(stochastic-gradient 2x2 normal-equations solve). ASYMMETRIC rank-1 residual-only "
    "injection: only channel c's coded residual is modified; raw parent rows are inputs "
    "left CLEAN (robustness INSIGHTS P3-refinement; the retired energy-preserving "
    "iklt_adaptive rotation corrupted both channels). Taps PERSIST across blocks (the "
    "selected pair is stable within a recording, P4-refinement); a slot whose parent is "
    "absent has zero input so its tap is frozen. Block 0 bootstraps to the fixed grid "
    "(up,left) pair (taps warm from t=0); block 1 on re-selects. Both the selected pair "
    "AND the taps are recomputed by the decoder from bit-identical reconstructed "
    "history (all candidate parents idx<c fully reconstructed) -> ZERO side-info, "
    "look-ahead 0, backward-adaptive (INSIGHTS P4). Behind the front-end: order-4 "
    "sign-sign LMS temporal predictor (INSIGHTS P2) + adaptive Rice -- the promoted "
    "best's back-end. Distinct from RETIRED multiparent (summed marginal betas "
    "double-count -> joint 2x2/gradient cannot), RETIRED iklt_adaptive (rotation "
    "corrupts both channels -> asymmetric rank-1 residual-only, parents clean), KEPT "
    "joint2 (fixed pair -> selected pair), PROMOTED bestpartner (single parent -> "
    "jointly-solved pair). The one untried way to STACK selection AND count into a win "
    "on BOTH array scales. Basis: MPEG-4 ALS multichannel prediction / Choi et al. "
    "Sensors 2014 correlation-sorted channel pairing (paper-reported, unverified here).")
_register(Codec("LMS4+Rice+xchan_jointbp2", jbp2_encode, jbp2_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _XJ2_XTRA + _JBP2_SELECT,
    dec_ops=_LMS4_OPS + _XJ2_XTRA + _JBP2_SELECT,
    state_bytes_per_ch=_JBP2_STATE, causal=True, lookahead_samples=0,
    block_size=JBP2_BLOCK, notes=_JBP2_NOTE), family="cross-channel",
    desc="order-4 LMS + backward-adaptive per-block best-PAIR selection + joint "
         "co-adaptive 2-tap sign-sign LMS spatial predictor (zero side-info) + Rice"))


# NEW candidate (this cycle): max-MI (CHOW-LIU) SPANNING-TREE channel topology --
# the same dominant spatial lever (INSIGHTS P1), but changing the parent GRAPH
# instead of the gain, the parent count, or the time offset. Per sample-channel the
# subtract costs exactly what any rank-1 front-end costs (1 mul + 1 shift + 1 sub =
# _XCHAN_OPS) on top of the order-4 LMS+Rice base (_LMS4_OPS); what grows is the
# per-block backward SCAN: the 8-neighbour edge set gives ~4 incident edges per
# channel scored in BOTH orientations (~8 scored candidates) vs bestpartner_adaptive's
# 4 -- so ~2x _LMS4BPA_SELECT -- plus Kruskal/union-find over ~4C edges (~500 at
# 128 ch), which is <0.05 ops/sample-ch once amortised over the 256-sample block.
# All weights are integer Rice bit-counts; no float, no division past the rounded
# integer-LS gain. The decoder repeats the identical search, so dec_ops == enc_ops and
# NOTHING is transmitted. Persistent state: order-4 LMS (24 B) + parent id + traversal
# position + the int16 gain (4 B) = 28 B/ch (~3.6 KB at 128 ch). PORT NOTE: the DECODER
# walks channels in tree order (a permutation -> indirect BRAM addressing on the
# Spartan-7, cheap but not a linear sweep); the on-node ENCODER is unaffected.
_XMST_SELECT = 21   # ~4 incident edges x 2 orientations (2 macs + bit-scoring each),
                    # + Kruskal/union-find over ~4C edges, amortised per block
_XMST_STATE = _LMS4_STATE + 4   # order-4 LMS + (parent byte, order byte, int16 gain)
_XMST_NOTE = (
    "max-MI (Chow-Liu) SPANNING-TREE channel topology: every other registered "
    "front-end inherits the RASTER-CAUSAL parent set (_bp_candidates offers channel c "
    "only left/up/up-left/up-right, i.e. the 8-neighbours with index<c) -- a "
    "restriction that exists only so the decoder can walk channels in INDEX order. It "
    "discards exactly HALF the 8-neighbourhood (right/down/down-left/down-right), and "
    "the per-channel GREEDY pick under an arbitrary scan order is not the optimal "
    "parent structure even among the parents it can see: row 0 has only 'left', column "
    "0 only up/up-right, and any channel whose strongest correlate lies later in raster "
    "order is forced onto a strictly weaker parent -- a STRUCTURAL loss, not a tuning "
    "issue. Chow & Liu (IEEE Trans. IT 14(3):462-467, 1968) prove the maximum-weight "
    "spanning tree under pairwise-MI edge weights is the tree factorization minimizing "
    "KL divergence to the true joint -- exactly the entropy-minimizing rank-1 dependency "
    "structure the current front-end greedily approximates (Gaussian edge weight "
    "-1/2 log(1-rho^2), so the MST maximizes total removable MI over all trees). "
    "MECHANISM (backward, zero side-info): candidate graph = the undirected 8-"
    "neighbourhood of the grid (~4 edges/ch, a bounded ~2x the incumbent's 4 raster "
    "candidates -- NOT the complete graph; embeddability caps the edge set). For each "
    "edge, over the PREVIOUS already-reconstructed RAW block, BOTH orientations get the "
    "integer least-squares gain (_bp_opt_beta, verbatim) and the coded-bit saving in "
    "estimated Rice bits (_bp_score, verbatim); w(u,v) = max(0,save(u|v)) + "
    "max(0,save(v|u)) -- a directional coded-bit saving is the operational estimate of "
    "N*I(u;v), and summing the orientations gives the SYMMETRIC integer stand-in for "
    "Chow-Liu's MI (clamped at 0, since I>=0). Kruskal + union-find over those integer "
    "weights (descending weight, ties by (u,v) index) builds the max-weight spanning "
    "tree; BFS from the lowest-index node of each component roots it and orients edges "
    "away from the root (rooting is free in Chow-Liu -- any rooting of the same "
    "undirected tree is the same factorization). One rank-1 subtract per TREE EDGE is "
    "then applied to the CURRENT block, y[c]=x[c]-((beta*x[parent(c)])>>shift), with "
    "beta the same previous-block integer-LS gain already scored for that orientation "
    "(beta=0, channel as-is, when that orientation's saving was <=0; the tree structure "
    "is unchanged). CAUSALITY: the tree comes only from block i-1, which the decoder "
    "holds bit-identically (lossless), so it rebuilds the IDENTICAL tree and gains -- "
    "ZERO side-info, look-ahead 0 (INSIGHTS P4); block 0 bootstraps to no parent, as in "
    "bestpartner_adaptive. Because a parent may now have a HIGHER index than its child, "
    "the decoder inverts block i in TREE ORDER (root->leaves), each parent's block-i raw "
    "samples restored before its children read them. NEW AXIS = the parent GRAPH: vs "
    "PROMOTED bestpartner(_adaptive) same rank-1 subtract, same integer-LS gain, same "
    "Rice-bit scoring, but the FULL 8-neighbourhood and a structure globally optimal "
    "over trees instead of greedy-per-channel under a raster order (restricting the "
    "graph to the raster half-neighbourhood and forcing index-order traversal collapses "
    "this back toward bestpartner_adaptive); vs xchan_lag (same cycle) that moves the "
    "parent in TIME, this moves it in the channel GRAPH -- orthogonal, both rank-1; vs "
    "joint2/jointbp2 (HOW MANY parents) the subtract stays strictly RANK-1, one parent "
    "and one gain per channel, so NOT the P3 multi-tap dead end; vs RETIRED "
    "xchan_multiparent each channel still has exactly ONE parent, so no shared mode is "
    "double-counted (P1b); vs RETIRED iklt/iklt_adaptive there is no rotation -- the "
    "subtract is asymmetric, injecting estimation noise only into the child's residual "
    "while the parent row stays clean (P3 refinement). Temporal back-end UNCHANGED: "
    "order-4 sign-sign LMS + adaptive Rice (P2/P5). EMBEDDABILITY: ~2x the incumbent's "
    "per-block selection cost, Kruskal over ~4C edges <0.05 ops/sample-ch amortised, "
    "integer bit-count comparisons only, ~4 B/ch extra state. PORT NOTE (flagged): "
    "DECODE follows a tree traversal, so channel access is a PERMUTATION -- indirect "
    "BRAM addressing on the Spartan-7 (cheap, but not a linear channel sweep); the "
    "on-node ENCODER is unaffected. FALSIFIABLE: the gain should be largest where the "
    "raster restriction bites hardest (boundary-heavy geometries, anisotropic "
    "correlation not aligned with the scan); if each channel's best correlate is already "
    "inside the raster half-neighbourhood the MST degenerates to the greedy parent set "
    "and the result is ~0 gain at ~2x selection cost -- a clean negative. Bases "
    "(paper-reported, unverified here): Chow & Liu 1968; correlation-driven rather than "
    "geometry-driven channel grouping in biosignals -- 'Efficient lossless multi-channel "
    "EEG compression based on channel clustering' (Biomed. Signal Process. Control, "
    "2016) and 'Low-complexity lossless multichannel ECG compression based on selective "
    "linear prediction' (2019), the latter being the single-parent-selection analogue "
    "already shipped here, of which the tree is the global-optimality upgrade.")
_register(Codec("LMS4+Rice+xchan_mst", xmst_encode, xmst_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _XCHAN_OPS + _XMST_SELECT,
    dec_ops=_LMS4_OPS + _XCHAN_OPS + _XMST_SELECT,
    state_bytes_per_ch=_XMST_STATE, causal=True, lookahead_samples=0,
    block_size=XMST_BLOCK, notes=_XMST_NOTE), family="cross-channel",
    desc="order-4 LMS + backward-adaptive per-block max-MI (Chow-Liu) SPANNING-TREE "
         "channel topology, one rank-1 subtract per tree edge (zero side-info) + Rice"))


# NEW candidate (this cycle): CONTEXT BIAS-CANCELLATION -- the TEMPORAL lever
# (INSIGHTS frontier #2), changing the predictor's FUNCTIONAL FORM by an additive
# conditional-mean term rather than its tap count or its coefficient-set count (P2).
# Per sample-channel, on top of the order-4 LMS + rank-1 subtract base
# (_LMS4_OPS + _XCHAN_OPS) and the incumbent's offline best-partner scan
# (_BP_SELECT_OPS, unchanged and amortised), stage 2 costs: ~3 shifts/adds for the
# scale thresholds, ~6 compares to quantize the last two residuals, ~1 to pick up the
# parent's residual sign, ~3 to combine them into a bucket index (small-constant
# shifts/adds, NO multiply), 1 table gather, 2 for the rounded shift-divide read of mu,
# 1 subtract to apply it, 3 to update the accumulator (shift, sub, add) + 1 store, and
# 3 for the mean-|e| leaky integrator ~= 22 ops. NO multiplies and NO divides anywhere
# in the corrector -- everything is a shift-divide, which is what makes it cheap in
# both firmware and RTL. Decoder does the identical work (dec_ops == enc_ops minus the
# encoder-only partner scan), and NOTHING extra is transmitted: the mu tables are
# rebuilt from reconstructed history (P4). Persistent state: order-4 LMS (24 B) +
# 30 int32 context accumulators (120 B) + the mean-|e| accumulator (4 B) + e[t-1],
# e[t-2] (8 B as int32) + this channel's own d[t-1] (4 B) = 160 B/ch on top of the
# best-partner bookkeeping (_BP_STATE) -> ~21 KB at 128 ch, ~8% of the SRAM budget.
_BC_XTRA = 22          # context formation + mu read/apply/update, shift-divide only
_BC_STATE = _LMS4_STATE + BC_NCTX * 4 + 4 + 8 + 4   # LMS4 + mu tables + scale + e1/e2/d
_BC_NOTE = (
    "TWO-STAGE PREDICTOR: stage 1 is the promoted order-4 sign-sign LMS, bit-identical "
    "to LMS4+Rice+xchan_bestpartner (same taps, same +-1 sign-sign update, fed the "
    "PRE-correction residual e on both sides); stage 2 subtracts a per-context running "
    "mean mu[c,ctx] of e before Rice-coding, d = e - mu. THEORY: a linear predictor "
    "whitens only to second order, and sign-sign LMS is not even MMSE-optimal -- it "
    "descends a sign-gradient criterion whose fixed point is offset from the Wiener "
    "solution and whose constant +-1 steps never settle, so the residual retains a "
    "persistent context-dependent NON-ZERO CONDITIONAL MEAN. H(e) >= H(e - E[e|ctx]) "
    "and the second moment drops by E[mu_ctx^2], shortening the Rice code by about "
    "1/2*log2(1 + E[mu^2]/sigma^2) bits/sample -- the same mechanism that gives "
    "JPEG-LS/LOCO-I its measurable gain over bare MED, and CALIC its context error "
    "feedback (Weinberger, Seroussi & Sapiro; Wu & Memon -- paper-reported, unverified "
    "here). CONTEXT (30 buckets <= 32): q5(e[t-1]) x q3(e[t-2]) x sign(d[parent,t-1]), "
    "with quantizer thresholds at 0.5x and 1.5x the channel's BACKWARD leaky mean |e| "
    "so the buckets are scale-free across bursts and quiescence; the parent bit is at "
    "LAG 1 so the sample update stays one vectorized channel sweep with no intra-sample "
    "channel chain. ESTIMATOR: leaky integrator S += e - (S>>5), mu = (S+16)>>5 -- "
    "shift-divide only, no multiply, no divide, no counter reset. NOT A RETIRED LEVER: "
    "vs RETIRED xctx (cycle 9), which conditioned the RICE PARAMETER k on a "
    "cross-channel energy context and lost because adaptive-k already tracks scale and "
    "the model is pure loss (P5) -- here the CODER IS UNTOUCHED (one global adaptive-"
    "Rice back-end, no context-split tables, no k model) and what is conditioned is a "
    "FIRST MOMENT of the residual UPSTREAM of the coder; vs RETIRED LMS4rs (cycle 14), "
    "which forked WHOLE COEFFICIENT SETS by activity regime and lost by fragmenting "
    "adaptation and fitting noise (P2) -- here there is exactly ONE global predictor "
    "and ONE weight set adapting on every sample, the context indexing only a single "
    "scalar mean, the cheapest statistic there is. SPATIAL FRONT-END UNCHANGED: "
    "_bp_select/_bp_inverse reused verbatim, identical (parent,beta) side-info. "
    "HONEST RISK: P5 measured the post-LMS residual near-white, so E[mu^2]/sigma^2 may "
    "be tiny while the estimator itself injects ~sigma^2/2^5 of variance per bucket -- "
    "a null or small negative is a real possible outcome and would show the sign-sign "
    "misadjustment leaves no exploitable conditional mean.")
_register(Codec("LMS4bc+Rice+xchan_bestpartner", bcbp_encode, bcbp_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _BC_XTRA + _XCHAN_OPS + _BP_SELECT_OPS,
    dec_ops=_LMS4_OPS + _BC_XTRA + _XCHAN_OPS,
    state_bytes_per_ch=_BC_STATE + _BP_STATE, causal=True, lookahead_samples=0,
    block_size=ec.BLOCK, notes=_BC_NOTE), family="temporal",
    desc="order-4 LMS + JPEG-LS-style per-context running-mean bias cancellation "
         "(30 buckets, zero side-info) + Rice, under the best-partner front-end"))

# NEW candidate (this cycle): context-conditioned integer BIAS CANCELLATION on the
# prediction (INSIGHTS open-frontier #2 -- change the predictor's FUNCTIONAL FORM,
# not its tap/set count). Everything of LMS4+Rice+xchan_bestpartner is reused
# verbatim (same best-partner selection + side-info, same order-4 sign-sign LMS,
# same Rice), so the increment is exactly the bias stage. Ops/sample-ch on top of
# _LMS4_OPS + _XCHAN_OPS: sign of the current residual (1), context index assembly
# from three cached signs (2 shifted adds), correction table load (1), correction
# subtract (1), accumulator add + count increment (2), and the band compare +
# +/-1 nudge with its amortised halving shift (~1) ~ 8 ops. NO divide and NO
# multiply anywhere in the stage (that is the point of the JPEG-LS counter-halving
# form). The decoder runs the byte-identical update on the same coded residual, so
# the stage costs the same on both sides; dec_ops omits only the encoder-side
# best-partner neighbour scan, exactly as in LMS4+Rice+xchan_bestpartner.
# State/ch: 27 contexts x (B int16 + N uint8 + C int8) = 108 B, plus the two cached
# own-sign registers (2 B) = 110 B, on top of the order-4 LMS + best-partner state
# -> ~150 B/ch, i.e. ~19 KB at 128 ch, far inside the 256 KiB SRAM budget.
_BIAS_XTRA = 8
_BIAS_STATE = BIAS_NCTX * 4 + 2      # (sum,count,correction)/ctx + 2 sign registers
_BIAS_NOTE = (
    "context-conditioned integer bias cancellation on the PREDICTION (LOCO-I / "
    "JPEG-LS, Weinberger-Seroussi-Sapiro IEEE TIP 2000 -- paper-reported to recover "
    "most of the gap to context-arithmetic coding at near-zero cost, unverified here), "
    "ported from the image raster to the electrode-array x time field. After the "
    "verbatim best-partner cross-channel subtract and the verbatim order-4 sign-sign "
    "LMS, subtract an integer correction B[ctx] learned per channel by a running "
    "(sum, count) accumulator. ctx = (sgn e[g,t-1], sgn e[g,t-2], sgn e[parent(g),t]) "
    "-> 3x3x3 = 27 contexts (9 live where best-partner selected NO parent); the "
    "parent is the channel's already-selected best partner and parent<g, so its "
    "same-slice residual is decoded before the child's -- causal, streaming-legal, "
    "look-ahead 0, ZERO side-info (the decoder rebuilds every context and every "
    "accumulator from residuals it has already reconstructed; INSIGHTS P4). The "
    "correction is tracked DIVISIONLESS exactly as JPEG-LS does: B += d, N += 1, both "
    "HALVED BY A SHIFT at N=64 (counter halving -> keeps the estimate local and keeps "
    "the node free of any SDIV), and C nudged +/-1 whenever the running sum leaves the "
    "band (-N, 0], so C converges to round(E[e|ctx]) and stays int8-bounded. THEORY: a "
    "linear predictor zeroes only LINEAR correlations -- it drives E[e*h]->0 for h in "
    "its tap span but says nothing about E[e | f(history)] for non-linear f, so any "
    "surviving conditional mean is first-order-removable structure NO linear predictor "
    "of any order can represent, and by the law of total variance removing it lowers "
    "residual variance by exactly Var(E[e|ctx]). P2's saturation result bounds the "
    "LINEAR class and does not cover this. Physical basis: MUAPs are asymmetric "
    "biphasic and firing is bursty, so residual sign-runs carry a non-zero conditional "
    "mean, and the non-normalised sign-sign LMS update lags during amplitude "
    "transients, leaving a context-dependent DC. DISTINCT FROM THE RETIRED "
    "MECHANISMS: not LMS4rs (that forked whole predictor COEFFICIENT SETS per regime "
    "and fragmented adaptation -- P2's named failure; here the linear predictor stays "
    "SINGLE and adapts on EVERY sample, the LMS pass being identical to the "
    "incumbent's, and only a scalar DC per context is added -- a mean estimate needs "
    "orders of magnitude fewer samples than a 4-tap filter); not xctx (that "
    "conditioned the Rice PARAMETER, the spent back-end lever of P5, leaving the "
    "residual untouched -- this changes the residual stream itself, the upstream place "
    "P5 directs spending). Best-partner selection is derived offline over the whole "
    "signal like the incumbent (embeddable realization selects per block, "
    "look-ahead=block); the bias stage itself is pure streaming. RISK TO MEASURE: the "
    "whole bet is whether Var(E[e|ctx]) is non-trivial AFTER order-4 LMS at all -- if "
    "the residual's conditional mean is already ~0 the +/-1 nudges are pure dither and "
    "the ratio moves down, not up.")
_register(Codec("LMS4bc_lite+Rice+xchan_bestpartner", biasbp_encode, biasbp_decode,
    CodecMeta(
        integer_only=True,
        enc_ops=_LMS4_OPS + _XCHAN_OPS + _BP_SELECT_OPS + _BIAS_XTRA,
        dec_ops=_LMS4_OPS + _XCHAN_OPS + _BIAS_XTRA,
        state_bytes_per_ch=_LMS4_STATE + _BP_STATE + _BIAS_STATE, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_BIAS_NOTE),
    family="temporal",
    desc="order-4 LMS + best-partner cross-channel subtract + JPEG-LS-style "
         "context-conditioned integer bias cancellation on the prediction "
         "(27 sign contexts, divisionless, zero side-info) + Rice"))

# NEW candidate (this cycle): propagation-aware (TIME-LAGGED) cross-channel
# predictor. Ops/sample-ch on top of the order-4 LMS base (_LMS4_OPS), all counted
# per sample-channel with the per-block work amortised over B=256:
#   * LAG SCAN (_XLAG_SCAN): <=4 causal parents x (2*XLAG_L+1)=15 lags, ONE mac per
#     lag for the cross-correlogram S(tau)=<x_c,x_p(tau)> (60) + one parent-energy
#     mac each (4) + the 15-way argmax compares amortised (~6) ~ 70. This is the
#     dominant added cost and the honest price of the mechanism: it scans every lag
#     exactly. (A shipping encoder can subsample the correlogram window ~4x -- the
#     peak of a smooth correlogram is robust -- but the model does NOT, so the cost
#     below is an upper bound, not a best case.)
#   * SELECT (_XLAG_SELECT): integer-LS gain + Rice-bit score for each parent AT ITS
#     PEAK LAG plus the no-parent option (~10), same convention as _LMS4BPA_SELECT.
#   * 3-TAP SOLVE (_XLAG_TAP3): 6 Gram + 3 rhs dot-products on the ONE selected
#     parent (9) + the 3x3 Cramer solve amortised over the block (~1) + scoring the
#     3-tap residual (~3) ~ 13.
#   * APPLY (_XLAG_APPLY): 3 muls + 2 adds + 1 shift + 1 sub + index arithmetic ~ 9
#     per sample-ch (3 when the single-tap option wins; 3-tap is the upper bound).
# Backward-adaptive with ZERO side-info, so the decoder repeats the identical
# search -> dec_ops == enc_ops. State/ch: order-4 LMS (_LMS4_STATE) + parent id (1)
# + lag (1) + three int16 taps (6) + an XLAG_L-deep parent ring buffer (14 B) so a
# positive lag can reach across the block boundary = _LMS4_STATE + 22. Look-ahead 0:
# parent indices are clamped to the current block's end, and parents are idx<c so
# their block is already latched when channel c is coded.
_XLAG_SCAN = 70
_XLAG_SELECT = 10
_XLAG_TAP3 = 13
_XLAG_APPLY = 9
_XLAG_STATE = _LMS4_STATE + 22
_XLAG_NOTE = (
    "propagation-aware TIME-LAGGED rank-1 cross-channel predictor. Every other "
    "spatial front-end in this registry evaluates the parent at time t only; "
    "HD-sEMG MUAPs PROPAGATE at ~3-5 m/s, so at 8-10 mm IED the inter-channel "
    "cross-correlation peaks at a NON-ZERO lag tau* (3-7 samples at 2048 Hz) and a "
    "tau=0 subtract can miss most of the available mutual information (rho(0) can "
    "even be near zero or negative when the delay nears a half-cycle of the 60-120 "
    "Hz MUAP band; rho(tau*)>=rho(0) by definition of the peak, and reducible bits "
    "~ -0.5*log2(1-rho^2) is monotone in |rho|). Per channel per block i>0, over the "
    "PREVIOUS already-reconstructed RAW block: (1) for each of <=4 causal grid "
    "neighbours (left/up/up-left/up-right, idx<c, reused _bp_candidates) take the "
    "cross-correlogram peak tau*_p = argmax_|tau|<=7 |<x_c, x_p(tau)>| -- literally "
    "the muscle-fibre conduction-velocity estimator, |.| because a half-cycle delay "
    "flips the correlation sign; (2) at each parent's own peak lag derive the rounded "
    "integer-LS gain (_bp_opt_beta) and score estimated Rice bits (_bp_score), also "
    "scoring the no-parent option, keep the minimum; (3) on the SELECTED (parent,lag) "
    "only, try an MPEG-4-ALS-MCC-style 3-tap cross-prediction filter at lags "
    "(tau-1,tau,tau+1) from a ridge-regularized 3x3 integer least-squares (Gram/rhs "
    "normalized below 2^15 then an exact int64 Cramer solve; ridge lambda=max(1,"
    "trace>>7) because three consecutive samples of a band-limited parent are nearly "
    "collinear), keeping it ONLY if it costs fewer Rice bits -- this interpolates the "
    "SUB-SAMPLE part of the propagation delay and shapes the parent's spectrum to the "
    "child's; a non-positive determinant or an out-of-int16 tap falls back to the "
    "single tap. Apply to the CURRENT block: y[c,t]=x[c,t]-((sum_m b_m*x[p,t-tau-m])"
    ">>8). Block 0 bootstraps to no-parent. With tau forced to 0 this REDUCES EXACTLY "
    "to LMS4+Rice+xchan_bestpartner_adaptive, so the measurement isolates the time "
    "shift and nothing else. ZERO side-info and look-ahead 0 (INSIGHTS P4): both the "
    "(parent,lag) choice and the taps are recomputed by the decoder from bit-identical "
    "reconstructed history, parents are idx<c so their whole block is already latched "
    "in a block-serial encoder (a NEGATIVE lag costs no look-ahead beyond the Rice "
    "block already buffered), and parent indices are clamped to the current block's "
    "end on both sides so nothing outside it is touched. Integer/fixed-point only, "
    "order-4 sign-sign LMS + adaptive Rice back-end unchanged (INSIGHTS P2/P5). "
    "Rank-1 in SPACE -- multi-tap in TIME on ONE parent -- so it is neither the "
    "RETIRED iklt (zero-lag energy-preserving multi-channel rotation that corrupts "
    "both channels) nor the RETIRED multiparent (a SUM of zero-lag rank-1 subtracts "
    "that double-counts the shared mode), and P1b/P3 (statements about spatial rank) "
    "do not cover it. Cost driver is the lag scan (x15 candidate evaluations per "
    "block-channel); it amortises over the 256-sample block but is counted here in "
    "full, unsubsampled. Basis: MPEG-4 ALS multichannel coding (MCC) -- selected "
    "reference channel + 3-tap cross-prediction filter + TIME SHIFT (paper-reported, "
    "unverified here); the bestpartner family already has the selected-reference half. "
    "PREDICTION: CapgMyo stays the honest negative control (differential montage "
    "cancels the travelling component; 1 kHz sampling makes the delay sub-sample).")
_register(Codec("LMS4+Rice+xchan_xlag", xlag_encode, xlag_decode, CodecMeta(
    integer_only=True,
    enc_ops=_LMS4_OPS + _XLAG_APPLY + _XLAG_SCAN + _XLAG_SELECT + _XLAG_TAP3,
    dec_ops=_LMS4_OPS + _XLAG_APPLY + _XLAG_SCAN + _XLAG_SELECT + _XLAG_TAP3,
    state_bytes_per_ch=_XLAG_STATE, causal=True, lookahead_samples=0,
    block_size=XLAG_BLOCK, notes=_XLAG_NOTE), family="cross-channel",
    desc="order-4 LMS + backward-adaptive per-block (parent, LAG) selection with an "
         "MPEG-4-ALS-style 3-tap cross-prediction filter (zero side-info) + Rice"))

# NEW candidate (this cycle): per-channel backward-adaptive spatial model-ORDER gate
# (rank-1 selected parent vs jointly-solved rank-2 pair). Ops/sample-ch on top of the
# order-4 LMS base (_LMS4_OPS), per-block work amortised over B=256:
#   * SCORE both hypotheses (_BPRANK_SCORE): the <=4 single-parent marginal scans
#     (2 macs each, as _LMS4BPA_SELECT) PLUS the <=6 candidate-pair 2x2 LS solves
#     (as _JBP2_SELECT) -- the same two-hypothesis scan jointbp2 already performs, so
#     the increment over jointbp2 is only the gate itself: ONE penalty add and one or
#     two compares per block-channel (~1 amortised), plus a 1-bit mode + hysteresis
#     state. This is why the cost ceiling is ~jointbp2's.
#   * APPLY (_BPRANK_APPLY): charged at the EXPENSIVE branch's rate -- the rank-2
#     joint 2-tap predict + subtract + two sign-sign tap updates (_XJ2_XTRA=9). The
#     rank-1 branch costs only _XCHAN_OPS=3 (mul+shift+sub), so a channel-block that
#     gates to rank-1 is CHEAPER than this; the model charges the upper bound.
# Backward-adaptive with ZERO side-info -> the decoder repeats the identical scan and
# gate, so dec_ops == enc_ops. State/ch: order-4 LMS (_LMS4_STATE) + two int16 rank-2
# taps (4) + rank-1 beta int16 (2) + selected parent ids (2) + mode/hysteresis bit (1)
# = _LMS4_STATE + 9. The <=6 pair covariance accumulators are O(1) SHARED working
# state (reused per channel-block, not multiplied per channel) -- noted, not charged
# per channel. Look-ahead 0: all evidence is the PREVIOUS block of rows idx<c.
_BPRANK_SCORE = _LMS4BPA_SELECT + _JBP2_SELECT + 1   # both hypotheses + the gate compare
_BPRANK_APPLY = _XJ2_XTRA        # upper bound: the rank-2 branch (rank-1 costs 3)
_BPRANK_STATE = _LMS4_STATE + 9
_BPRANK_NOTE = (
    "per-channel, per-block backward-adaptive spatial model-ORDER gate: rank-1 (a "
    "SELECTED single parent) vs jointly-solved rank-2 (the best PAIR). INSIGHTS P1b "
    "settled these two front-ends per ARRAY (rank-1 wins tight arrays, the joint pair "
    "took the highest Hyser cross-channel gain of any codec), and frontier #1 proposed "
    "gating them on the recording's CHANNEL COUNT -- a form bounded by construction "
    "(it routes all 320 CEMHSEY channels into the rank-2 branch and inherits jointbp2's "
    "regression there; ceiling = max of two already-measured branches). Here the gate "
    "is moved to the granularity the physics actually varies at: WITHIN an array, edge/"
    "corner channels have 1-2 causal parents (rank-1 by construction), channels over an "
    "innervation zone or a second muscle carry ONE coherent local mode, while interior "
    "channels of a large diffuse array are rank>=2. Per channel c, per block i>0, ALL "
    "evidence taken from the PREVIOUS already-reconstructed RAW block: H1 = best of "
    "{no parent, each of the <=4 causal grid neighbours (left/up/up-left/up-right, all "
    "idx<c, reused _bp_candidates) with its rounded integer-LS gain}, scored in "
    "estimated Rice bits (_bp_opt_beta/_bp_score -- bestpartner_adaptive's search); "
    "H2 = best candidate PAIR under a JOINT 2x2 integer least-squares solve "
    "(_jbp2_pair_resid, parent-parent covariance included, so it cannot double-count "
    "the shared mode the RETIRED summed multiparent did). GATE: score(H1)=bits1 vs "
    "score(H2)=bits2 + an MDL/BIC complexity penalty of (1/2)log2(B) bits for the one "
    "extra free gain plus log2(#pairs)-log2(#singles) bits for the wider selection "
    "alphabet -- the honest O(log) selection-noise term, integer-only -- and the mode "
    "changes only if the challenger wins by more than a HYSTERESIS band (incumbent "
    "score >>7, ~0.8%), so statistically tied blocks keep the incumbent order instead "
    "of dithering (dithering desynchronizes the rank-2 taps for no bit gain). APPLY "
    "with the WINNING branch's OWN estimator, not a shared one: rank-1 -> the "
    "closed-form per-block integer-LS subtract y=x[c]-((beta*x[p])>>8) "
    "(bestpartner_adaptive verbatim); rank-2 -> the joint co-adaptive 2-tap sign-sign "
    "LMS on the selected pair, pred=(w_u*x[pu]+w_l*x[pl])>>8 with both taps descending "
    "the SHARED residual (jointbp2 verbatim), taps PERSISTING across blocks and simply "
    "FROZEN while the channel is in rank-1 mode so a slowly oscillating channel pays no "
    "re-convergence transient. Block 0 bootstraps to rank-1/no-parent. Selecting per "
    "channel-block by empirical code length over the UNION of the two hypothesis "
    "classes has expected code length <= min of either FIXED class up to that "
    "selection-noise term, so unlike the channel-count gate its ceiling is NOT "
    "max(bestpartner, jointbp2). ZERO side-info, look-ahead 0 (INSIGHTS P4): both "
    "hypotheses' scores, the penalty, the hysteresis state and the selected parents are "
    "recomputed by the decoder from bit-identical reconstructed history (all candidate "
    "parents idx<c fully reconstructed), so it REPEATS THE IDENTICAL TEST and nothing "
    "is transmitted -- the same legality acar_sel proved for a decoder-observable gate, "
    "at the correct granularity. Integer/fixed-point only; order-4 sign-sign LMS + "
    "adaptive Rice back-end unchanged (INSIGHTS P2/P5). Distinct from KEPT jointbp2 "
    "(ONE flat argmin over none/single/pair then always the LMS-tap predictor; no MDL "
    "charge, no hysteresis, no per-branch estimator), from bestpartner_adaptive (adds "
    "the rank-2 hypothesis, but only where it pays for its extra degree of freedom in "
    "measured bits), and from acar_sel (same gating principle, moved from a "
    "per-recording channel count to a per-channel-block measured code length). CAVEAT "
    "TO MEASURE: it must not merely pay jointbp2's scan price to arrive at "
    "bestpartner's answer -- if the gate lands in rank-1 nearly everywhere, the ratio "
    "collapses to bestpartner_adaptive's at a higher cost = Pareto-dominated. Basis: "
    "MDL/BIC model-order selection (Rissanen) applied to the SPATIAL predictor order; "
    "both branches are this registry's own measured constructions.")
_register(Codec("LMS4+Rice+xchan_bprank", bprank_encode, bprank_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _BPRANK_APPLY + _BPRANK_SCORE,
    dec_ops=_LMS4_OPS + _BPRANK_APPLY + _BPRANK_SCORE,
    state_bytes_per_ch=_BPRANK_STATE, causal=True, lookahead_samples=0,
    block_size=BPRANK_BLOCK, notes=_BPRANK_NOTE), family="cross-channel",
    desc="order-4 LMS + per-channel/per-block backward-adaptive spatial model-ORDER "
         "gate (rank-1 selected parent vs jointly-solved rank-2 pair, MDL penalty + "
         "hysteresis, zero side-info) + Rice"))


# NEW candidate (this cycle): VOLTERRA-LITE degree-2 temporal predictor under the
# promoted best-partner front-end (INSIGHTS open-frontier #2 / P2's "change the
# FUNCTIONAL FORM"). Same spatial front-end and same SINGLE order-4 sign-sign LMS
# coefficient set as LMS4+Rice+xchan_bestpartner; the only change is that the
# regressor basis gains V2_NQ=3 amplitude-normalized second-order products.
# Ops on top of the order-4 LMS work (_LMS4_OPS): 3 int16xint16 products + 3
# normalizing shifts + 3 saturating clamps (~9), 3 extra macs in the prediction
# sum (~3), 3 extra sign-sign tap updates (~6), the leaky |x| integrator (2), the
# amortised bit-length/CLZ normalizer refresh (~6 ops every 16 samples ~ 0.5) and
# the amortised quadratic leak (~3 ops every 16 samples ~ 0.2) -> ~22 extra
# ops/sample-ch. State: order-4 weights + 4-sample history (_LMS4_STATE) + 3
# quadratic int16 weights (6 B) + the int32 |x| accumulator and the 1-byte
# exponent (5 B) -> ~35 B/ch, plus the best-partner side-info state (_BP_STATE).
# Fully backward-adaptive -> ZERO temporal side-info, look-ahead 0 (P4); the only
# side-info is the best-partner (parent,beta) pair, derived offline exactly like
# the incumbent (embeddable realization re-selects per block, look-ahead=block).
# Decoder mirrors every update, so dec_ops == enc_ops minus the encoder-only
# neighbour scan.
_V2_XTRA = 22
_V2_STATE = _LMS4_STATE + V2_NQ * 2 + 5
_V2BP_NOTE = (
    "Volterra-lite degree-2 temporal predictor: keeps the promoted order-4 "
    "best-partner spatial front-end (best-of-4 causal grid neighbour + integer "
    "gain, 2xint16/ch side-info, reused VERBATIM) and keeps ONE order-4 sign-sign "
    "LMS coefficient set in ONE adaptation loop, but AUGMENTS its regressor basis "
    "with 3 integer second-order products of the causal history (x[t-1]^2, "
    "x[t-1]x[t-2], x[t-2]^2) -- the degree-2 Volterra kernel truncated to "
    "quadratic memory 2. Theory (INSIGHTS frontier #2 / P2): a linear predictor "
    "whitens only to SECOND order, so any residual compressibility left after "
    "order-4 LMS is higher-order, and the degree-2 kernel is the leading term of "
    "any analytic nonlinearity -- HD-sEMG being a non-Gaussian MUAP superposition "
    "through a nonlinear volume conductor. This is a change of FUNCTIONAL FORM, "
    "which is what P2 demands: NOT more taps (order 8 loses to order 4) and NOT "
    "more coefficient sets (the retired regime bank LMS4rs -- here a SINGLE set "
    "sees EVERY sample, no gate, no fragmented adaptation). Integer-scale "
    "handling: each product is normalized by 2^bitlength(leaky mean|x|) "
    "(refreshed every 16 samples, a CLZ in hardware) so |q| ~ |x| and the shared "
    "fixed-point weight scale is meaningful for both blocks, then saturated to "
    "int16 width -- bounding the datapath and capping spike amplification. The "
    "quadratic taps (only) are leaked every 16 samples, wq -= sign(wq)*(|wq|>>5), "
    "which bounds |wq| to int16 and makes the correction SELF-DISABLING: if the "
    "products carry no information the taps decay to 0 and the codec degenerates "
    "exactly to LMS4+Rice+xchan_bestpartner. Regressors, normalizer exponent and "
    "leak are all recomputed by the decoder from causally-reconstructed history "
    "-> ZERO temporal side-info, look-ahead 0 (P4). Coder untouched adaptive Rice "
    "(NOT an entropy back-end or Rice-context play, cf. retired xctx, P5). Stated "
    "risk before measurement: quadratic regressors are high-variance, so on an "
    "already-white residual they can only AMPLIFY noise -- the failure mode P2 "
    "documents; a null result falsifies the degree-2 Volterra correction itself, "
    "not its normalization. Selection front-end derived offline like the incumbent "
    "bestpartner (embeddable realization selects per block, look-ahead=block).")
_register(Codec("LMS4v2+Rice+xchan_bestpartner", v2bp_encode, v2bp_decode,
    CodecMeta(
        integer_only=True, enc_ops=_LMS4_OPS + _V2_XTRA + _XCHAN_OPS + _BP_SELECT_OPS,
        dec_ops=_LMS4_OPS + _V2_XTRA + _XCHAN_OPS,
        state_bytes_per_ch=_V2_STATE + _BP_STATE, causal=True,
        lookahead_samples=ec.BLOCK, block_size=ec.BLOCK, notes=_V2BP_NOTE),
    family="temporal",
    desc="Volterra-lite degree-2 (quadratic-augmented basis) order-4 sign-LMS "
         "+ best-partner + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated by LMS4+Rice+xchan_bestpartner on ALL 4 "
                   "real sets (worse ratio AND higher cost 0.0592 vs 0.0394: otb 2.1431x "
                   "vs 2.1619x, hyser 1.4758x vs 1.4804x, capgmyo 1.3468x vs 1.3505x, "
                   "cemhsey 1.9521x vs 1.9555x) -- identical spatial front-end, so the "
                   "loss is attributable to the temporal basis alone. Adding degree-2 "
                   "Volterra regressors to the SAME sign-sign LMS loop realises exactly "
                   "the P2 failure mode: after order-4 linear prediction the HD-sEMG "
                   "residual is white to second order AND the surface-EMG generation model "
                   "(a linear volume-conductor filtering of MU action potentials) is itself "
                   "linear, so E[e_t * x_{t-i}x_{t-j}] ~ 0 -- the quadratic taps have no "
                   "signal to lock onto and their O(x^2) variance leaks into the residual, "
                   "raising coded entropy. The leak term correctly bounds the damage to "
                   "-0.2..-0.9% instead of diverging. Confirms P2's stronger form: the "
                   "temporal lever is exhausted by FORM as well as by ORDER. "
                   "experiments/017_lms4v2_rice_xchan_bestpartner.md, cycle 2026-08-07."))

# NEW candidate (this cycle): RESIDUAL-DOMAIN cross-channel prediction with a
# bit-matched selection criterion. Cost is IDENTICAL to the incumbent
# `LMS4+Rice+xchan_bestpartner_adaptive` by construction -- the same order-4 LMS
# (_LMS4_OPS), the same applied rank-1 subtract (1 mul + 1 shift + 1 sub =
# _XCHAN_OPS), the same <=4-candidate backward scan with an amortised argmin
# (_LMS4BPA_SELECT), and the same persistent per-channel state (_LMS4BPA_STATE:
# order-4 LMS weights/history + the current partner byte and int16 beta). Only
# the ORDER of the two stages and the DOMAIN the selection is scored in change,
# so no new buffers and no new state. The decoder repeats the identical backward
# selection (nothing is transmitted) -> dec_ops == enc_ops.
_XRES_NOTE = (
    "RESIDUAL-DOMAIN cross-channel prediction with a BIT-MATCHED selection "
    "criterion. Pipeline REORDER (the one variable vs bestpartner_adaptive): run "
    "the order-4 sign-sign LMS per channel FIRST, then apply the rank-1 subtract "
    "between TEMPORAL RESIDUALS, d[g]=e[g]-((beta*e[p])>>8), with (partner,beta) "
    "RE-SELECTED per 256-sample block from the PREVIOUS already-recovered RESIDUAL "
    "block -- ZERO side-info, look-ahead 0 (INSIGHTS P4), same <=4 causal grid "
    "neighbours (_bp_candidates), same integer-LS gain (_bp_opt_beta), same "
    "Rice-bits score (_bp_score), same per-block scan (_bpa_select_block reused "
    "verbatim). THEORY (i) DOMAIN: volume conduction is instantaneous linear "
    "mixing of shared motor-unit innovation trains; the channels' shared "
    "AUTOcorrelation is already removed by the per-channel temporal predictor, so "
    "a beta fitted on RAW signals spends its single degree of freedom on "
    "redundancy that dies downstream, while a beta fitted on the INNOVATIONS "
    "targets the band where the coded bits live -- and the innovation mixing "
    "coefficient is more stationary than the raw broadband cross-gain, so the "
    "backward estimate is less biased. (ii) CRITERION MISMATCH, verified in this "
    "source: _bp_score ranks partners by the Rice length of the PRE-LMS residual "
    "while every raw-domain codec emits the POST-LMS one (xt=_bp_select(x); "
    "res=lms_forward(xt)) -- an argmin over a proxy, not over the objective. In "
    "the residual domain the scored quantity IS the coded quantity. UNTRIED: "
    "every registered/retired cross-channel front-end applies its spatial stage "
    "BEFORE lms_forward. CAUSALITY: lms_forward is per-channel so e depends on x "
    "alone; the decoder walks channels in index order (every partner idx<g, so "
    "e[p] is fully recovered) and blocks in time order (block i's pair recomputed "
    "from the recovered residual block i-1), then lms_inverse(e) rebuilds x -- a "
    "matched pair from causally-available data only. Block 0 bootstraps to "
    "no-partner. EMBEDDABILITY: identical op count and persistent state to the "
    "incumbent, no new buffers, integer/fixed throughout. HONEST FAILURE MODE: if "
    "the innovations' rho_e is materially below the raw rho_x the residual-domain "
    "subtract recovers less -- that is what the measurement decides. Bases: "
    "MPEG-4 ALS removes inter-channel redundancy by joint channel coding of the "
    "PREDICTION RESIDUAL signals, gated on the cross-correlation of residuals "
    "(Liebchen et al.; Sensors 14(9):17516) -- paper-reported, unverified here.")
_register(Codec("LMS4+Rice+xchan_xres", xres_encode, xres_decode, CodecMeta(
    integer_only=True, enc_ops=_LMS4_OPS + _XCHAN_OPS + _LMS4BPA_SELECT,
    dec_ops=_LMS4_OPS + _XCHAN_OPS + _LMS4BPA_SELECT,
    state_bytes_per_ch=_LMS4BPA_STATE, causal=True, lookahead_samples=0,
    block_size=XRES_BLOCK, notes=_XRES_NOTE), family="cross-channel",
    desc="order-4 LMS FIRST, then backward-adaptive per-block best-partner rank-1 "
         "subtract between TEMPORAL RESIDUALS, scored on the coded (post-LMS) "
         "bits (zero side-info) + Rice",
    retired=True,
    retired_reason="Conclusively Pareto-dominated by LMS4+Rice+xchan_bestpartner_adaptive "
                   "at IDENTICAL cost 0.038743 (same enc/dec_ops 39, same state 27 B/ch) on "
                   "ALL 4 real sets (cycle 2026-08-16, results/cycle_bench.csv): otb 2.0975x "
                   "vs 2.1531x, hyser 1.4686x vs 1.4770x, cemhsey 1.9407x vs 1.9539x, capgmyo "
                   "1.3500x vs 1.3529x -- strictly worse ratio everywhere, no cost trade-off "
                   "left. Isolated xchan gain is LOWER in the residual domain on every real "
                   "set (otb +14.32% vs +17.36%, hyser +10.25% vs +10.88%): the per-channel "
                   "temporal LMS is a high-pass that destroys the shared low-frequency "
                   "volume-conduction mode carrying most of the inter-channel MI before the "
                   "spatial stage can subtract it. Stage ORDER dominates the (correct) "
                   "scored-quantity==coded-quantity refinement."))



def list_codecs(include_retired=False):
    """Codecs for the default bench.py/search.py sweep and the leaderboard.
    Retired codecs (Pareto-dominated on real data, per a verifier's audit) are
    excluded by default so they stop being re-benchmarked and re-reported every
    cycle -- pass include_retired=True to re-check one explicitly (e.g. to
    reproduce an old verdict, or re-audit after a shared primitive changes)."""
    return [c for c in REGISTRY.values() if include_retired or not c.retired]


def list_retired():
    return [c for c in REGISTRY.values() if c.retired]


# ===========================================================================
def _selftest():
    rng = np.random.default_rng(0)
    # A realistic-ish int16 field: correlated noise floor + spikes + a shared
    # common-mode, on an 8x16 grid, so cross-channel codecs are exercised too.
    C, N, cols = 32, 2500, 8
    base = rng.normal(0, 12, (C, N))
    common = rng.normal(0, 6, N)                       # shared common-mode
    x = (base + 0.5 * common).round().astype(np.int16)
    x[5, 800:820] += 500                               # a spike burst
    x[6, 800:820] += 300

    # Bit-exactness is checked for EVERY codec ever registered, retired or not
    # -- retirement means "excluded from the default bench/leaderboard sweep",
    # never "excused from correctness." Nothing is deleted or untested.
    all_codecs = list_codecs(include_retired=True)
    n_retired = len(list_retired())
    print(f"registry self-test on random int16 [{C} x {N}], {len(all_codecs)} codecs"
          f" ({n_retired} retired, excluded from the default sweep)\n")
    print(f"{'codec':<20}{'ratio':>7}{'round-trip':>12}{'emb_ok':>8}"
          f"{'neural':>8}{'cost':>8}  status")
    print("-" * 71)
    all_ok = True
    for c in all_codecs:
        blob = c.encode(x, cols=cols)
        y = c.decode(blob)
        ok = np.array_equal(x, y)
        all_ok &= ok
        ratio = x.nbytes / len(blob)
        status = "RETIRED" if c.retired else ""
        print(f"{c.name:<20}{ratio:>6.2f}x{('OK' if ok else 'FAIL!'):>12}"
              f"{('OK' if c.cost.embedded_ok else 'no'):>8}"
              f"{('OK' if c.cost.neural_ok else '-'):>8}{c.cost.cost:>8.3f}  {status}")
        assert ok, f"round-trip mismatch for {c.name}"
    assert all_ok
    print("\nregistry self-test: ALL round-trips bit-exact")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    # default action is the self-test (the verifier hook invokes with --selftest)
    _selftest()
