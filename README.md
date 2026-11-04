# PDMM

Code and experiment data for **Lifecycle-Synchronized Dummy Main Construction for Android Program Analysis**.

PDMM constructs Android analysis entry points that coordinate Activity and Fragment callbacks. The implementation has a FlowDroid backend for taint analysis and a parameterized Jimple backend for DMMPP/Androlic. The experiments examine lifecycle interactions, generated data parameters, and analysis cost.

## Reproduce the reported results

Python 3.10 or later is sufficient for the saved-data analysis:

```sh
python scripts/reproduce_results.py --output reproduced
```

This command reads the per-run records in `experiments/data`, verifies their checksums, and produces:

- `results.json`: benchmark scores, real-application differences, parameter distributions, dynamic-case counts, and cost summaries;
- `cost_application_medians.csv`: the 1,700 application/configuration/metric aggregates;
- `cost_comparisons.csv`: 68 paired tests and their Holm-adjusted probabilities.

See [Results](docs/RESULTS.md) for the main values and [Data](docs/DATA.md) for fields, populations, and missing outcomes.

## Build the analysis adapters

The symbolic backend uses JDK 8. The FlowDroid backend uses JDK 17. Dependency versions and hashes are recorded in `dependencies/manifest.json`.

```sh
python -m pip install -r requirements.txt
python scripts/fetch_dependencies.py
python scripts/build.py --src src --deps dependencies/jars --helpers scripts/helpers --build-dir build/classes --backend all --jdk8 /path/to/jdk8 --jdk17 /path/to/jdk17 --with-probes --instrumentation instrumentation
```

Supply the JDK paths installed on your system. The build writes only to the chosen build directory and rejects existing nonempty output directories. Both Java adapters and the GC exporter have been compiled with the recorded dependency versions.

Single-APK generation, serial cost measurements, and benchmark build instructions are in [Reproduction](docs/REPRODUCTION.md). Saved-data recomputation requires no Android SDK or dependency downloads.

## Repository contents

| Directory | Contents |
|---|---|
| `src` | Gen8 construction, hosting extraction, FlowDroid adapters and entry-point overrides |
| `instrumentation` | External-run GC instrumentation sources |
| `scripts` | Portable build/export tools and saved-data analysis |
| `benchmarks/fragbench` | The 36-case AndroidX benchmark project and its original generators |
| `experiments/data` | Per-run measurements, per-component exports, and reported flows |
| `experiments/protocol` | Source/sink definitions and statistical/scoring scripts used for the recorded experiments |
| `docs` | Reproduction instructions, result definitions, and verification records |
| `legacy` | Earlier source and experiment artifacts retained from the repository |

The current analysis reads `experiments/data`. Earlier material is documented in `legacy/README.md`.

## Verification

The November 4, 2026 checks reproduced the reported numerical results from saved experiment files and verified all 47 bibliography entries. The data checks cover 1,160 taint-analysis instances, 1,830 parameter-export instances, 500 cost measurements, and 36 dynamic benchmark cases. Details and remaining measurement limits are in [Verification](docs/VERIFICATION.md).

Third-party source and dependency information is in [NOTICE](NOTICE.md).
