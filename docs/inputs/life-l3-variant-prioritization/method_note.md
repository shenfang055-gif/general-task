# Synthetic trio prioritization rule

The affected proband is `P1`; parents `F1` and `M1` are unaffected.

Keep only variants with proband `DP >= 12`, proband `GQ >= 30`, population allele frequency `< 0.01`, and consequence in `stop_gained`, `frameshift`, `splice_acceptor`, `splice_donor`, or `missense_damaging`.

For a gene marked `AD_de_novo`, retain a heterozygous proband variant only when both parents are reference. For a gene marked `AR_compound_het`, retain the gene only when the proband has at least two qualifying heterozygous variants, with at least one inherited from each different parent. This synthetic task does not require phasing beyond parental origin.

The legacy script contains scientific logic bugs. Repair it or replace it, but save a rerunnable implementation to `output/prioritize.py`.

