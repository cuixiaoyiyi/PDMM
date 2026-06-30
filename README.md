# PDMM: Hierarchical Lifecycle Modeling for Android Dummy Main Methods

PDMM is a static analysis tool that constructs precise dummy main methods for Android applications. It addresses two key limitations in existing approaches: **parameter bloat** and **imprecise Activity-Fragment lifecycle modeling**. By generating a more accurate synthetic entry point, PreciseDMM significantly improves the scalability and precision of downstream static analyses such as taint tracking.

Implementation and measurements for *"Lightweight and Lifecycle-Synchronized Dummy Main Construction for Android Static Analysis"*, built on top of **DMMPP**
(Cui et al., ISSTA 2024) and the FlowDroid/Soot stack.

### Datasets (real)
- [**DroidBench 3.0**](https://github.com/secure-software-engineering/DroidBench/tree/master/apk) — 188 APKs (all categories), incl. `FragmentLifecycle1/2`.
- **Real-world** — the 20 APKs shipped with DMMPP: [10 F-Droid + 10 Google Play](https://github.com/cuixiaoyiyi/DMMPP/tree/main/apks).
- **Android platforms** — `android.jar` API 25/29/30.

## Requirements

- Java 8 or higher
- [Soot](https://github.com/soot-oss/soot) (included in the build)
- [FlowDroid](https://github.com/secure-software-engineering/FlowDroid) (optional, for downstream analysis)
- Apache Maven (for building)

