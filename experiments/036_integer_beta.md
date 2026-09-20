# 036 — Integer cross-channel beta (half away from zero) for the whole +xchan family

- **Date:** 2026-09-19
- **Branch:** `main` (direct commit; consumer: hdemg-bench S1, design D13 / ruling R1)
- **Scope:** `host_tools/embedded_codec.py` (`int_beta`, `cross_betas`), `research/registry.py` (`_int_beta`, `_bp_opt_beta` delegate)

## Hypothesis

Replacing the float least-squares gain `round(num/den * 256)` in `cross_betas` with the exact-rational
integer rule already used by the registry's adaptive and best-partner betas changes every `+xchan` ratio
by less than 0.01 % on all four real datasets, and changes no other codec at all.

## Implementation

`int_beta(num, den, shift)`: `0` when `den <= 0`; otherwise `((|num| << shift) + den // 2) // den`, sign
restored, clipped to int16. One integer division per channel per block, no float. Known-answer tests
(ties, negatives, den = 0, clipping, 2000 random dot-product-sized pairs vs the float formula).

Self-test: `PYTHONPATH=host_tools:research python3 host_tools/embedded_codec.py` →
`embedded_codec self-test: ALL round-trips bit-exact`. `registry.py --selftest` and `--audit` pass.

## Measurement

`research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 --max-samples 15000`
before (`results/s1_int_beta_before.csv`, at 963b1c9) and after (`results/s1_int_beta_after.csv`), compared by
`research/compare_int_beta.py`:

```
dataset             codec                                 before     after   delta %
capgmyo_dba_s1      LMS+Rice+xchan                       1.34930   1.34930   +0.0000
capgmyo_dba_s1      LMS+Rice+xchan_joint2                1.35044   1.35044   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_bestpartner          1.35048   1.35048   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_bestpartner_adaptive   1.35287   1.35287   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_bprank               1.35146   1.35146   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_jointbp2             1.35029   1.35029   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_mst                  1.35273   1.35273   +0.0000
capgmyo_dba_s1      LMS4+Rice+xchan_xlag                 1.36385   1.36385   +0.0000
capgmyo_dba_s1      LMS4bc+Rice+xchan_bestpartner        1.35315   1.35315   +0.0000
capgmyo_dba_s1      LMS4bc_lite+Rice+xchan_bestpartner   1.35378   1.35378   +0.0000
capgmyo_dba_s1      LMS4bcpool+Rice+xchan_bestpartner    1.35062   1.35062   +0.0000
capgmyo_dba_s1      LMS4bcxm+Rice+xchan_bestpartner      1.35134   1.35134   +0.0000
capgmyo_dba_s1      LMS4bcxs+Rice+xchan_bestpartner      1.35316   1.35316   +0.0000
capgmyo_dba_s1      delta+Rice+xchan                     1.29003   1.29003   +0.0000
cemhsey_s1_d1t1     LMS+Rice+xchan                       1.95511   1.95511   +0.0000
cemhsey_s1_d1t1     LMS+Rice+xchan_joint2                1.95427   1.95427   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_bestpartner          1.95555   1.95555   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_bestpartner_adaptive   1.95395   1.95395   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_bprank               1.95210   1.95210   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_jointbp2             1.95226   1.95226   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_mst                  1.95312   1.95312   +0.0000
cemhsey_s1_d1t1     LMS4+Rice+xchan_xlag                 1.95234   1.95234   +0.0000
cemhsey_s1_d1t1     LMS4bc+Rice+xchan_bestpartner        1.95525   1.95525   +0.0000
cemhsey_s1_d1t1     LMS4bc_lite+Rice+xchan_bestpartner   1.96999   1.96999   +0.0000
cemhsey_s1_d1t1     LMS4bcpool+Rice+xchan_bestpartner    1.95568   1.95568   +0.0000
cemhsey_s1_d1t1     LMS4bcxm+Rice+xchan_bestpartner      1.95502   1.95502   +0.0000
cemhsey_s1_d1t1     LMS4bcxs+Rice+xchan_bestpartner      1.97162   1.97162   +0.0000
cemhsey_s1_d1t1     delta+Rice+xchan                     1.88237   1.88237   +0.0000
hyser_1dof_f1_s1    LMS+Rice+xchan                       1.47382   1.47382   +0.0000
hyser_1dof_f1_s1    LMS+Rice+xchan_joint2                1.49300   1.49300   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_bestpartner          1.48038   1.48038   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_bestpartner_adaptive   1.47702   1.47702   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_bprank               1.49523   1.49523   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_jointbp2             1.49692   1.49692   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_mst                  1.48232   1.48232   +0.0000
hyser_1dof_f1_s1    LMS4+Rice+xchan_xlag                 1.46845   1.46845   +0.0000
hyser_1dof_f1_s1    LMS4bc+Rice+xchan_bestpartner        1.48508   1.48508   +0.0000
hyser_1dof_f1_s1    LMS4bc_lite+Rice+xchan_bestpartner   1.48353   1.48353   +0.0000
hyser_1dof_f1_s1    LMS4bcpool+Rice+xchan_bestpartner    1.48597   1.48597   +0.0000
hyser_1dof_f1_s1    LMS4bcxm+Rice+xchan_bestpartner      1.48466   1.48466   +0.0000
hyser_1dof_f1_s1    LMS4bcxs+Rice+xchan_bestpartner      1.48487   1.48487   +0.0000
hyser_1dof_f1_s1    delta+Rice+xchan                     1.45155   1.45155   +0.0000
otb_hdsemg_vl       LMS+Rice+xchan                       2.14262   2.14262   +0.0000
otb_hdsemg_vl       LMS+Rice+xchan_joint2                2.14968   2.14968   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_bestpartner          2.16194   2.16194   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_bestpartner_adaptive   2.15311   2.15311   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_bprank               2.14959   2.14959   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_jointbp2             2.15224   2.15224   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_mst                  2.17017   2.17017   +0.0000
otb_hdsemg_vl       LMS4+Rice+xchan_xlag                 2.02939   2.02939   +0.0000
otb_hdsemg_vl       LMS4bc+Rice+xchan_bestpartner        2.19344   2.19344   +0.0000
otb_hdsemg_vl       LMS4bc_lite+Rice+xchan_bestpartner   2.18040   2.18040   +0.0000
otb_hdsemg_vl       LMS4bcpool+Rice+xchan_bestpartner    2.19478   2.19478   +0.0000
otb_hdsemg_vl       LMS4bcxm+Rice+xchan_bestpartner      2.19159   2.19159   +0.0000
otb_hdsemg_vl       LMS4bcxs+Rice+xchan_bestpartner      2.18186   2.18186   +0.0000
otb_hdsemg_vl       delta+Rice+xchan                     2.04096   2.04096   +0.0000
RESULT: PASS
```

## Verification

Only rows whose codec calls `embedded_codec.cross_betas` moved; every other row is identical. Largest
absolute delta: 0.0000 %.

## Outcome

Adopted as the family-wide beta rule. The leaderboard's `+xchan` numbers are within 0.01 % of the
published snapshot and are not re-run. hdemg-bench pins this commit and regenerates its C-port vectors.
