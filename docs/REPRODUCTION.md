# Reproduction

## Saved-data analysis

```sh
python scripts/reproduce_results.py --output reproduced
```

The analysis uses only the Python standard library and verifies the data-file manifest before reading measurements. Use a fresh output directory. It recomputes all three research-question summaries, application-level medians, exact paired signed-rank probabilities, and the post-hoc Holm correction over 68 comparisons.

## Dependencies and compilation

The portable scripts were checked with Python 3.13, psutil 7.2.2, JDK 8, and JDK 17 on Windows. The JDK 8 adapter uses the original DMMPP and Androlic dependency JARs. The JDK 17 adapter uses the Maven Central FlowDroid 2.15.1 command-line assembly. Downloads are version-pinned and checked against the actual experiment JAR hashes.

```sh
python -m pip install -r requirements.txt
python scripts/fetch_dependencies.py
python scripts/build.py --src src --deps dependencies/jars --helpers scripts/helpers --build-dir build/classes --backend all --jdk8 /path/to/jdk8 --jdk17 /path/to/jdk17 --with-probes --instrumentation instrumentation
```

The compiled Gen8 classes are written to `build/classes/gen8`, FlowDroid classes to `build/classes/taint`, the measured exporter to `build/classes/gen8-probe`, and the measured Androlic adapter to `build/classes/cost-probe`. The measured classes precede Gen8 and their dependency JAR on the runtime classpath; the FlowDroid overrides precede the original FlowDroid JAR when running the taint adapter.

## Export a component model

```sh
python scripts/run_export.py --apk /path/to/application.apk --platforms /path/to/android-platforms --lifecycle hsm --policy rules --output runs/application-hsm-rules --label application --jdk8 /path/to/jdk8 --deps dependencies/jars --build-dir build/classes/gen8 --probe-build build/classes/gen8-probe --helpers scripts/helpers
```

Lifecycle choices are `fixed` and `hsm`; parameter choices are `perarg`, `pertype`, and `rules`. The six combinations form the parameter experiment. Fixed uses predefined standalone component schedules. HSM embeds hosted Fragment phases at Activity transitions. PerArg supplies an input per argument position, PerType shares by exact declared type, and Rules uses host/state/view roles.

The export command rejects old nonempty output directories. It records command inputs and hashes, process status, wall time, root and process-tree memory, and a validation result. The validator checks complete component coverage, the serialized data-formal total, and generated bodies. Timeouts and failures retain terminal records. These single-APK exports provide functional evidence; the saved cost experiment has its own five-repeat measurement protocol.

## FragBench

`benchmarks/fragbench/project` contains the generated AndroidX project used for the 36-case experiment. The project pins Android Gradle Plugin 8.5.0. Use Gradle 8.7, JDK 17, and an Android SDK with the required platform/build tools.

```sh
python scripts/build_fragbench.py --project benchmarks/fragbench/project --gradle-home /path/to/gradle-8.7 --jdk17 /path/to/jdk17 --sdk /path/to/android-sdk --helpers scripts/helpers --output build/fragbench
```

The build copies clean sources to a new directory, checks the actual Gradle exit status, and accepts one fresh debug APK for each of the 36 unique case IDs. Project outputs, Java/Android user directories, Gradle caches, and logs are placed under the chosen output directory. Install the SDK platform and build tools beforehand. The earlier pipeline could mask Gradle failure behind a shell pipe and collect existing APKs; this entry checks both process success and complete fresh outputs. The portable build was checked through compilation and failure-path fixtures; rebuilding and executing all 36 Android applications is a separate experiment.

The original generators and dynamic measurement code are retained in `benchmarks/fragbench/original`. They document the recorded experiment and require adapting their original local work-root settings before a new emulator campaign. The included dynamic-case data can be inspected without an emulator.

## Experiment designs

The detection ablation uses Native, HSM, HSM+Tx, HSM+Tx+Alias, and Full in FlowDroid. Tx retains transaction-supplied Fragment receivers and adds supported synchronous-completion callbacks. Alias connects host, state, and returned-view values. Full removes optional skips around inserted phase groups.

The cost experiment selects Fixed/PerArg, Fixed/PerType, Fixed/Rules, HSM/PerArg, and HSM/Rules. Runs are serial, with seed 20260930, five repetitions, a 12 GiB Java heap, a 1,800-second timeout, a 500-path budget per component, and nominal 0.5-second process-resource sampling. This repository includes the measured rows and original analysis/scoring sources. A new execution should record its machine and background load as a new dataset; reproducing the statistical calculation uses the existing CSVs.

To collect a new serial five-configuration measurement for one APK:

```sh
python scripts/run_cost.py --apk /path/to/application.apk --platforms /path/to/android-platforms --jdk8 /path/to/jdk8 --deps dependencies/jars --build-dir build/classes/gen8 --probe-build build/classes/cost-probe --helpers scripts/helpers --output runs/application-cost
```

The launcher records each of the 25 scheduled instances separately. Component solver failures, invalid GC records, launch errors, and timeouts remain failed outcomes. Five validated repetitions are required for a configuration median, and unavailable metrics remain null. These per-APK summaries are descriptive; the paper's paired tests use 20 application-level observations. The launcher and validators were compiled and checked through software fixtures and a saved measurement; no new application analysis was used to replace the recorded paper data.
