# Experiment data

`experiments/data/manifest.json` records the size, row count, and SHA-256 of each data file. Empty numeric cells represent unavailable observations. Failed and incomplete runs retain their status and do not contribute invented zeros.

| File | Rows | Unit |
|---|---:|---|
| `taint_instances.csv` | 1,160 | APK × configuration: 180 FragBench, 940 DroidBench, 40 selected-application instances |
| `taint_flows.csv.gz` | 1,002 | Reported source/sink record, retaining duplicate reports |
| `gen8_instances.csv` | 1,830 | APK × lifecycle × argument policy: 1,266 main-inventory and 564 expanded-inventory instances |
| `gen8_components.csv.gz` | 40,110 | Exported component record, including standalone and spliced components |
| `cost_instances.csv` | 500 | Application × configuration × repetition |
| `dynamic_cases.csv` | 36 | API 29 dynamic benchmark case |

The CSV files preserve recorded values and link them to source files through hashes and input fingerprints. Machine-specific directory names and unrelated process records are omitted from the public projection. Original source-file hashes refer to the original file bytes, so a normalized CSV projection has its own separate checksum.

## Populations

The main parameter inventory contains 211 APKs: 188 DroidBench cases, 20 selected applications, and AntennaPod, K-9 Mail, and Nextcloud. Nextcloud has no complete six-configuration output, leaving 210 paired APKs. Three paired APKs have zero PerArg parameters; parameter-reduction means and medians therefore use 207 positive baselines. Application reduction counts use all 210.

The expanded inventory contains 94 APKs with at least five recognized Fragment classes. There are 510 complete exports and 54 incomplete or failed exports. Requiring a complete output in all six configurations gives 64 paired APKs. Selection metadata, original download addresses, and APK hashes are in `experiments/corpus94.csv`; main-inventory identities are in `experiments/main211.csv`.

FragBench has 29 positive and seven negative dynamic labels. Static scoring uses the configured benchmark sink. DroidBench has 181 available truth labels among 188 planned APKs, with a common trusted panel of 179 APKs. The 20-application taint comparison has 12 paired outputs; the other eight applications remain unresolved.

## Measures

Data-formal slots are the sum of data inputs in generated component dummy-main signatures. The additional Boolean control array is excluded. Parameters for ordinary callbacks and constructors are included. A reused formal counts once within its generated method.

DroidBench scores use a count proxy: `match = min(reported, expected)`, `excess = max(reported - expected, 0)`, and `miss = max(expected - reported, 0)`. These excess counts have not been adjudicated as semantic false positives. ActivityEventSequence3 and ActivitySavedState1 illustrate the distinction: the sink list includes the intermediate `Bundle.putString` write, and Alias adds a path to the benchmark's documented SMS or Log sink. Both records are retained.

Cost statistics use the median of five repetitions for each application/configuration. Each paired comparison therefore has 20 application observations. Process Working Set, sampled process-tree Working Set, and heap occupancy after a confirmed GC are separate fields. A blank natural major-GC peak means that no such event was observed; the confirmed final collection is recorded separately.

The cost measurements use the recorded controlled-background environment. Their wall times characterize that environment and the specified path budget. The reported tests establish no wall-time improvement.
