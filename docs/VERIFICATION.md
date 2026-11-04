# Verification record

Checked on November 4, 2026 against the saved experiment outputs and the current manuscript.

## Data and statistics

The checked data cover all 180 FragBench, 940 DroidBench, and 40 selected-application taint instances. Input fingerprints, source/sink CSVs, status records, and saved hashes agree. The 181 available DroidBench leak counts agree with the original benchmark annotations. Dynamic labels were checked against the recorded sink markers for all 36 cases.

The parameter checks covered all 1,830 planned export records and recalculated complete-panel statistics from saved summary and component files. Invalid or failed outputs retain unknown values. The main and expanded APK hash sets are disjoint.

For the cost study, 4,500 source artifacts were checked. All 1,700 application/configuration/metric aggregates, 68 exact paired tests, and Holm-adjusted probabilities were independently recomputed. The public CSV analysis was then compared with the saved results through 9,087 checks; all passed.

No mismatch was found in the audited headline numbers. These checks establish consistency and traceability of the saved records. They do not reconstruct every historical runtime event or establish semantic truth for every real-application difference.

## References

All 47 bibliography entries were corroborated: 42 scholarly publications and five official online resources. All 37 DOI values already supplied in the bibliography resolve to the intended works. Publisher-deposited Crossref/DataCite records and official conference, DBLP, and publication pages supplied the checks. The per-entry sources are in `reference-audit.json`.

No invented publication, incorrect supplied DOI, or required bibliographic correction was found. Two existing publications also have optional missing DOI fields: DroidSafe, `10.14722/ndss.2015.23089`, and the 1996 IDE paper, `10.1016/0304-3975(96)00072-2`.

## Code and reproduction

The construction and analysis algorithms have executable implementations. The method audit mapped 22 implementation claims to source code and checked parameter selection, lifecycle placement, transaction capture, role propagation, exact signed-rank tests, and Holm adjustment.

The packaging addresses hardcoded build paths with parameterized entry points, and the FragBench collector requires both a successful build and 36 fresh unique outputs. Actual isolated compilation produced 26 Gen8 classes, 31 FlowDroid classes, four measured-exporter classes, and four measured-Androlic classes. Failure-path checks cover old-output rejection, incomplete output rejection, solver failure, invalid GC records, process launch failure, and timeouts. These checks did not rerun the scientific APK or performance campaigns.

The implementation retains its documented scope: state bindings and some transaction holders are class-associated; host extraction uses recognized code/layout patterns; ordinary callback and constructor inputs are generally fresh under Rules. Saved measurements and the source support selective parameter reduction, with no established wall-time improvement in the repeated cost study.
