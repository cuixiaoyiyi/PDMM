# PDMM: Hierarchical Lifecycle Modeling for Android Dummy Main Methods

PDMM is a static analysis tool that constructs precise dummy main methods for Android applications. It addresses two key limitations in existing approaches: **parameter bloat** and **imprecise Activity-Fragment lifecycle modeling**. By generating a more accurate synthetic entry point, PreciseDMM significantly improves the scalability and precision of downstream static analyses such as taint tracking.

This tool is the implementation of the paper:  
*"Constructing Precise Dummy Main Methods for Android via Hierarchical Lifecycle Modeling"* (to appear).

---

## Features

- **Alias-Aware Parameter Reduction**  
  Merges redundant callback parameters (e.g., `Bundle`, `Intent`, `View`) using type-based equivalence partitioning, reducing the number of formal parameters in the dummy main method by up to 65%.

- **Hierarchical State Machine (HSM) for Lifecycles**  
  Models Activity‑Fragment interactions with path‑sensitive predicates, ensuring that only valid callback sequences are included. This eliminates infeasible paths caused by asynchronous transactions (`commit` vs. `commitNow`).

- **Seamless Integration with FlowDroid**  
  The generated dummy main method can be directly used as input to FlowDroid’s taint analysis engine, improving both performance (time, memory) and precision (F1‑score).

- **Lightweight Pre‑processing**  
  The dummy main construction adds less than 1.5% overhead to the total analysis time, even for large apps (e.g., Telegram).

---

## Requirements

- Java 8 or higher
- [Soot](https://github.com/soot-oss/soot) (included in the build)
- [FlowDroid](https://github.com/secure-software-engineering/FlowDroid) (optional, for downstream analysis)
- Apache Maven (for building)

---

## Installation

Clone the repository and build with Maven:

```bash
git clone https://github.com/cuixiaoyiyi/PDMM.git
cd PDMM
mvn clean package
