#!/usr/bin/env python3
"""Recompute the paper's results from portable CSV/gzip data using Python's standard library.

Example: python scripts/reproduce_results.py --data experiments/data --output reproduced
No Android/JVM analysis, network access, or external package is required.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
from pathlib import Path
import statistics


TAINT_CONFIGS = ("native", "hsm", "hsm_tx", "hsm_tx_alias", "hsm_tx_alias_mand")
REAL_CONFIGS = ("native", "hsm_tx_alias")
LIFECYCLES = ("fixed", "hsm")
POLICIES = ("perarg", "pertype", "rules")
COST_BASELINE = "fixed/perarg"
COST_CANDIDATES = ("fixed/pertype", "fixed/rules", "hsm/perarg", "hsm/rules")
METRIC_UNITS = {
    "external_wall_seconds": "seconds",
    "forced_gc_after_heap_bytes": "bytes",
    "forced_gc_call_seconds": "seconds",
    "forced_gc_notification_wait_seconds": "seconds",
    "forced_gc_total_overhead_seconds": "seconds",
    "forced_major_gc_confirmed_count": "count",
    "formals": "count",
    "generation_solve_gc_notification_count": "count",
    "generation_solve_major_gc_notification_count": "count",
    "generation_solve_peak_after_any_gc_bytes": "bytes",
    "java_analysis_seconds": "seconds",
    "reported_live_any_mib": "MiB",
    "reported_live_major_or_final_mib": "MiB",
    "reported_major_gc_count": "count",
    "root_working_set_bytes": "bytes",
    "symbolic_paths": "count",
    "tree_sampled_working_set_bytes": "bytes",
}
INPUT_FILES = (
    "taint_instances.csv", "taint_flows.csv.gz", "gen8_instances.csv",
    "gen8_components.csv.gz", "cost_instances.csv", "dynamic_cases.csv",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def integer(text):
    return None if text == "" else int(text)


def truthy(text):
    require(text in ("True", "False"), "Invalid Boolean field: " + repr(text))
    return text == "True"


def write_csv(path, records, fields=None):
    fields = fields or list(records[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def safe_ratio(a, b):
    return a / b if b else None


def taint_results(instances, flows):
    indexed = {}
    by_dataset = defaultdict(list)
    flow_rows = defaultdict(list)
    for row in flows:
        key = (row["dataset"], row["label"], row["config"], int(row["rep"]))
        flow_rows[key].append(row)
    for row in instances:
        key = (row["dataset"], row["label"], row["config"], int(row["rep"]))
        require(key not in indexed, "Duplicate taint identity: " + repr(key))
        indexed[key] = row
        by_dataset[row["dataset"]].append(row)
        if truthy(row["score_eligible"]):
            actual = flow_rows[key]
            require(len(actual) == integer(row["flow_count_all"]), "Flow count mismatch: " + repr(key))
            configured = sum("FBSINK" in item["sink_statement"] for item in actual)
            require(configured == integer(row["flow_count_configured_fbsink"]), "Configured-sink count mismatch: " + repr(key))
        else:
            require(row["prediction"] == "", "Unknown prediction must remain missing: " + repr(key))

    results = {}
    for dataset in ("FragBench", "DroidBench"):
        data = by_dataset[dataset]
        labels = sorted({r["label"] for r in data})
        expected = {}
        for row in data:
            value = integer(row["expected_leaks"])
            if row["label"] in expected:
                require(expected[row["label"]] == value, "Inconsistent expected count")
            expected[row["label"]] = value
        common = [label for label in labels if expected[label] is not None and all(
            (dataset, label, cfg, 1) in indexed and truthy(indexed[dataset, label, cfg, 1]["score_eligible"])
            for cfg in TAINT_CONFIGS)]
        scores = []
        for cfg in TAINT_CONFIGS:
            matched = excess = missed = 0
            for label in common:
                key = (dataset, label, cfg, 1)
                actual = flow_rows[key]
                count = int(any("FBSINK" in item["sink_statement"] for item in actual)) if dataset == "FragBench" else len(actual)
                matched += min(count, expected[label])
                excess += max(0, count - expected[label])
                missed += max(0, expected[label] - count)
            scores.append({"config": cfg, "common_APKs": len(common), "match_or_TP": matched,
                "excess_or_FP": excess, "miss_or_FN": missed,
                "precision": safe_ratio(matched, matched + excess),
                "recall": safe_ratio(matched, matched + missed),
                "F1": safe_ratio(2 * matched, 2 * matched + excess + missed)})
        results[dataset] = {
            "planned_instances": len(data), "APKs": len(labels), "configs": len({r["config"] for r in data}),
            "trusted_instances": sum(truthy(r["score_eligible"]) for r in data),
            "unknown_instances": sum(not truthy(r["score_eligible"]) for r in data),
            "truth_labelled_APKs": sum(value is not None for value in expected.values()),
            "truth_positive_APKs": sum(value is not None and value > 0 for value in expected.values()),
            "truth_negative_APKs": sum(value == 0 for value in expected.values()),
            "common_trusted_truth_APKs": len(common), "scores": scores,
        }

    real = by_dataset["Real"]
    comparisons = []
    for label in sorted({r["label"] for r in real}):
        keys = [("Real", label, cfg, 1) for cfg in REAL_CONFIGS]
        if not all(key in indexed and truthy(indexed[key]["score_eligible"]) for key in keys):
            continue
        records = [flow_rows[key] for key in keys]
        keysets = [{(r["source_method"], r["source_statement"], r["sink_method"], r["sink_statement"]) for r in group} for group in records]
        native, candidate = keysets
        comparisons.append({"label": label, "native_records": len(records[0]), "candidate_records": len(records[1]),
            "native_unique": len(native), "candidate_unique": len(candidate), "shared": len(native & candidate),
            "native_only": len(native - candidate), "candidate_only": len(candidate - native),
            "symmetric_difference": len(native ^ candidate),
            "native_only_keys": sorted(native - candidate), "candidate_only_keys": sorted(candidate - native)})
    results["Real"] = {"planned_instances": len(real), "APKs": len({r["label"] for r in real}),
        "trusted_instances": sum(truthy(r["score_eligible"]) for r in real),
        "unknown_instances": sum(not truthy(r["score_eligible"]) for r in real),
        "paired_APKs": len(comparisons), "identical_key_sets": sum(r["symmetric_difference"] == 0 for r in comparisons),
        "raw_exact_key_symmetric_difference": sum(r["symmetric_difference"] for r in comparisons), "comparisons": comparisons}
    return results


def parameter_results(instances, components):
    indexed = {}
    comp_sums = defaultdict(int)
    comp_counts = Counter()
    for row in components:
        if row["status"] == "OK":
            key = (row["panel"], row["label"], row["lifecycle"], row["policy"], int(row["rep"]))
            comp_sums[key] += int(row["data_formals"])
            comp_counts[key] += 1
    for row in instances:
        key = (row["panel"], row["label"], row["lifecycle"], row["policy"], int(row["rep"]))
        require(key not in indexed, "Duplicate parameter-export identity")
        indexed[key] = row
        if truthy(row["trusted_complete"]):
            require(comp_sums[key] == int(row["data_formal_slots"]), "Component/formal total mismatch: " + repr(key))
            require(comp_counts[key] == int(row["generated"]), "Generated-method count mismatch: " + repr(key))
        else:
            require(row["data_formal_slots"] == "", "Incomplete export must not become zero")
    coverage = {}
    panels = []
    for panel in sorted({r["panel"] for r in instances}):
        group = [r for r in instances if r["panel"] == panel]
        labels = sorted({r["label"] for r in group})
        paired = [label for label in labels if all((panel, label, life, policy, 1) in indexed and
            truthy(indexed[panel, label, life, policy, 1]["trusted_complete"])
            for life in LIFECYCLES for policy in POLICIES)]
        coverage[panel] = {"planned_instances": len(group), "APKs": len(labels),
            "trusted_complete_instances": sum(truthy(r["trusted_complete"]) for r in group),
            "unknown_instances": sum(not truthy(r["trusted_complete"]) for r in group), "paired_APKs": len(paired)}
        for life in LIFECYCLES:
            apps = [{"label": label, **{policy: int(indexed[panel, label, life, policy, 1]["data_formal_slots"]) for policy in POLICIES}} for label in paired]
            sums = {policy: sum(app[policy] for app in apps) for policy in POLICIES}
            percentages = [100 * (app["perarg"] - app["rules"]) / app["perarg"] for app in apps if app["perarg"] > 0]
            cohorts = []
            for cohort in sorted({app["label"].split("__", 1)[0] for app in apps}):
                subset = [app for app in apps if app["label"].split("__", 1)[0] == cohort]
                baseline = sum(app["perarg"] for app in subset)
                rules = sum(app["rules"] for app in subset)
                cohorts.append({"cohort": cohort, "APKs": len(subset), "perarg": baseline, "rules": rules,
                    "baseline_share_percent": 100 * safe_ratio(baseline, sums["perarg"]) if sums["perarg"] else None,
                    "aggregate_reduction_percent": 100 * safe_ratio(baseline - rules, baseline) if baseline else None})
            largest = sorted(apps, key=lambda app: (-app["perarg"], app["label"]))
            panels.append({"panel": panel, "lifecycle": life, "APKs": len(apps), "positive_baselines": len(percentages),
                **sums, "aggregate_reduction_percent": 100 * safe_ratio(sums["perarg"] - sums["rules"], sums["perarg"]) if sums["perarg"] else None,
                "mean_application_reduction_percent": statistics.mean(percentages) if percentages else None,
                "median_application_reduction_percent": statistics.median(percentages) if percentages else None,
                "reduced_APKs": sum(app["rules"] < app["perarg"] for app in apps),
                "cohorts": cohorts, "top_three_baseline_share_percent": 100 * safe_ratio(sum(app["perarg"] for app in largest[:3]), sums["perarg"]) if sums["perarg"] else None,
                "largest_inventories": largest[:3]})
    return {"coverage": coverage, "panels": panels}


def exact_signed_rank(differences):
    """Two-sided sign randomization, using integer twice-average ranks and subset-sum DP."""
    nz = [value for value in differences if value]
    n = len(nz)
    if not n:
        return {"n_pairs": len(differences), "n_nonzero": 0, "n_zero": len(differences), "statistic": 0.0,
            "w_positive": 0.0, "w_negative": 0.0, "p_two_sided": "1", "rank_biserial": 0.0}
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0] * n
    start = 0
    while start < n:
        stop = start + 1
        while stop < n and abs(nz[order[stop]]) == abs(nz[order[start]]):
            stop += 1
        for index in order[start:stop]:
            ranks[index] = start + 1 + stop
        start = stop
    total = sum(ranks)
    positive = sum(rank for rank, value in zip(ranks, nz) if value > 0)
    tail = min(positive, total - positive)
    distribution = Counter({0: 1})
    for rank in ranks:
        following = Counter(distribution)
        for value, count in distribution.items():
            following[value + rank] += count
        distribution = following
    extreme = sum(count for value, count in distribution.items() if min(value, total - value) <= tail)
    p = Decimal(extreme) / Decimal(2 ** n)
    return {"n_pairs": len(differences), "n_nonzero": n, "n_zero": len(differences) - n,
        "statistic": tail / 2, "w_positive": positive / 2, "w_negative": (total - positive) / 2,
        "p_two_sided": str(p), "rank_biserial": (2 * positive - total) / total}


def cost_results(instances, output):
    identities = set()
    values = defaultdict(list)
    reps = defaultdict(set)
    status = Counter()
    for row in instances:
        key = (row["label"], row["config"], int(row["rep"]))
        require(key not in identities, "Duplicate cost identity")
        identities.add(key)
        status[row["status"]] += 1
        if row["status"] != "ok":
            continue
        reps[key[:2]].add(key[2])
        for metric in METRIC_UNITS:
            if row[metric] != "":
                values[key[0], key[1], metric].append(float(row[metric]))
    require(all(cfg == COST_BASELINE or cfg in COST_CANDIDATES for _, cfg, _ in identities), "Unexpected cost configuration")
    labels = sorted({key[0] for key in identities})
    configs = (COST_BASELINE,) + COST_CANDIDATES
    expected_repetitions = {key[2] for key in identities}
    aggregates = []
    medians = {}
    for (label, cfg, metric), observations in sorted(values.items()):
        # A missing metric is excluded from this app/config rather than filled with zero.
        if reps[label, cfg] != expected_repetitions or len(observations) != len(expected_repetitions):
            continue
        median = statistics.median(observations)
        q1, _, q3 = statistics.quantiles(observations, n=4, method="inclusive") if len(observations) > 1 else [median] * 3
        medians[label, cfg, metric] = median
        aggregates.append({"label": label, "config": cfg, "metric": metric, "unit": METRIC_UNITS[metric],
            "n": len(observations), "median": median, "q1": q1, "q3": q3, "iqr": q3 - q1})
    comparisons = []
    for candidate in COST_CANDIDATES:
        for metric, unit in sorted(METRIC_UNITS.items()):
            paired = [label for label in labels if (label, COST_BASELINE, metric) in medians and (label, candidate, metric) in medians]
            if not paired:
                continue
            quantum = Decimal(1).scaleb(-6 if unit == "seconds" else -3 if unit == "MiB" else 0)
            differences = [(Decimal(str(medians[label, candidate, metric])) - Decimal(str(medians[label, COST_BASELINE, metric]))).quantize(quantum, rounding=ROUND_HALF_EVEN) for label in paired]
            comparisons.append({"baseline": COST_BASELINE, "candidate": candidate, "metric": metric, "unit": unit,
                **exact_signed_rank(differences)})
    adjusted = [None] * len(comparisons)
    running = Decimal(0)
    order = sorted(range(len(comparisons)), key=lambda i: Decimal(comparisons[i]["p_two_sided"]))
    for rank, index in enumerate(order):
        running = max(running, Decimal(comparisons[index]["p_two_sided"]) * (len(comparisons) - rank))
        adjusted[index] = min(Decimal(1), running)
    for row, p in zip(comparisons, adjusted):
        row["p_holm_fwer"] = str(p)
        row["holm_reject_at_0_05"] = p <= Decimal("0.05")
    configuration_medians = {}
    paired_ratios = {}
    for cfg in configs:
        configuration_medians[cfg] = {}
        paired_ratios[cfg] = {}
        for metric in METRIC_UNITS:
            observed = [medians[label, cfg, metric] for label in labels if (label, cfg, metric) in medians]
            pairs = [label for label in labels if (label, cfg, metric) in medians and (label, COST_BASELINE, metric) in medians and medians[label, COST_BASELINE, metric] != 0]
            configuration_medians[cfg][metric] = statistics.median(observed) if observed else None
            ratios = [medians[label, cfg, metric] / medians[label, COST_BASELINE, metric] for label in pairs]
            paired_ratios[cfg][metric] = statistics.median(ratios) if ratios else None
    write_csv(output / "cost_application_medians.csv", aggregates)
    write_csv(output / "cost_comparisons.csv", comparisons)
    return {"planned_instances": len(instances), "unique_instance_identities": len(identities), "APKs": len(labels),
        "configs": len({key[1] for key in identities}), "repeat_numbers": sorted({key[2] for key in identities}),
        "status": dict(status), "application_median_rows": len(aggregates),
        "paired_unit": "one application median of its repetitions", "comparison_family_size": len(comparisons),
        "Holm_significant_count": sum(row["holm_reject_at_0_05"] for row in comparisons),
        "missing_generation_major_GC_peak": sum(row["generation_solve_peak_after_major_gc_bytes"] == "" for row in instances),
        "configuration_medians": configuration_medians, "median_paired_ratios": paired_ratios, "comparisons": comparisons}


def dynamic_results(instances):
    labels = [row["id"] for row in instances]
    require(len(labels) == len(set(labels)), "Duplicate dynamic case identity")
    observed = {}
    for row in instances:
        require(row["status"] == "completed" and int(row["case_exit_code"]) == 0, "Incomplete dynamic case")
        positive = int(row["sink_tainted"]) > 0
        require(positive == (row["observed"] == "leak"), "Dynamic observation does not match tainted-sink count")
        observed[row["id"]] = int(positive)
    return {"unique_cases": len(observed), "positive": sum(observed.values()), "negative": len(observed) - sum(observed.values()),
        "sink_calls": sum(int(row["sink_calls"]) for row in instances), "case_labels": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[1] / "experiments" / "data", help="Portable CSV/gzip data directory")
    parser.add_argument("--output", type=Path, required=True, help="Directory for new JSON/CSV results")
    args = parser.parse_args()
    require(args.data.is_dir(), "Data directory does not exist")
    require(args.data.resolve() != args.output.resolve(), "Output must differ from the data directory")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.data / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    data = {}
    hashes = {}
    for name in INPUT_FILES:
        path = args.data / name
        hashes[name] = sha256(path)
        if manifest is not None:
            require(hashes[name] == manifest["files"][name]["sha256"], "Manifest SHA mismatch: " + name)
        data[name] = read_csv(path)
        if manifest is not None:
            require(len(data[name]) == manifest["files"][name]["rows"], "Manifest row-count mismatch: " + name)
    taint = taint_results(data["taint_instances.csv"], data["taint_flows.csv.gz"])
    dynamic = dynamic_results(data["dynamic_cases.csv"])
    fb_truth = {row["label"]: integer(row["expected_leaks"]) for row in data["taint_instances.csv"] if row["dataset"] == "FragBench"}
    require(fb_truth == dynamic["case_labels"], "Dynamic labels and static benchmark truth differ")
    results = {"metadata": {"schema": "portable-study-reproduction-v1", "script_sha256": sha256(Path(__file__)),
        "data_files_sha256": hashes, "missing_values": "Empty fields remain missing; unknown instances do not become zero predictions.",
        "DroidBench_scoring": "Per-APK count proxy: min(reported, expected) matches; excess and misses are count differences.",
        "real_comparison": "Exact source/sink statement keys; differences are not semantic vulnerability labels.",
        "parameter_metric": "Data-formal slots exclude the control-choice array; percentages exclude zero baselines, counts retain all paired APKs.",
        "cost_scope": "Controlled-background measurements; app medians are paired units. The metric family receives post-hoc Holm correction.",
        "signed_rank": "Two-sided exact conditional sign randomization, zero differences omitted, average ranks for ties; differences rounded half-even to 6 decimals for seconds, 3 for MiB, integer for bytes/counts."},
        "taint": taint, "parameters": parameter_results(data["gen8_instances.csv"], data["gen8_components.csv.gz"]),
        "cost": cost_results(data["cost_instances.csv"], args.output), "dynamic": dynamic}
    output_path = args.output / "results.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print("Recomputed results.json, cost_application_medians.csv, and cost_comparisons.csv")


if __name__ == "__main__":
    main()
