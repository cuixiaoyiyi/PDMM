"""Five-repeat serial performance summaries; functional batches are rejected.

APK medians are the paired sampling unit, never the five repeats pooled as
independent applications. The signed-rank p-value is an exact conditional sign
permutation distribution of average ranks (including ties, discarding zeros).
It is not SciPy's untied-rank 'exact' shortcut. Inputs/outputs are validated
before statistics; failed or missing repetitions are reported and excluded.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
import json
import math
from pathlib import Path
import statistics

from run_static import (ANDRO_COLS, RUN_COLS, atomic_csv, atomic_json, completed_attempt,
                        digest, resource_valid, sha256)
from resource_monitor import utc_now

SOURCES = ["https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html",
           "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html",
           "https://journals.sagepub.com/doi/10.2466/11.IT.3.1"]


def signed_rank(differences):
    differences = [Decimal(str(d)) for d in differences]
    if any(not d.is_finite() for d in differences):
        raise ValueError("nonfinite paired difference")
    ordered = sorted((abs(d), i, d) for i, d in enumerate(differences) if d)
    ranks = []
    ties, i = 0, 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        # Twice average rank is integral, including tied groups.
        rank2 = i + 1 + j
        ranks.extend((rank2, d > 0) for _, _, d in ordered[i:j])
        ties += int(j-i > 1)
        i = j
    total = sum(rank for rank, _ in ranks)
    positive = sum(rank for rank, sign in ranks if sign)
    negative = total-positive
    counts, upper = [1] + [0]*total, 0
    for rank, _ in ranks:
        for value in range(upper, -1, -1):
            if counts[value]:
                counts[value+rank] += counts[value]
        upper += rank
    observed = min(positive, negative)
    extreme = sum(count for value, count in enumerate(counts) if min(value, total-value) <= observed)
    permutations = 1 << len(ranks)
    return {"n_pairs": len(differences), "n_nonzero": len(ranks), "n_zero": len(differences)-len(ranks),
            "tied_absolute_rank_groups": ties, "w_positive": positive/2, "w_negative": negative/2,
            "statistic": observed/2, "p_two_sided": extreme/permutations,
            "exact_extreme_assignments": str(extreme), "exact_assignments": str(permutations),
            "rank_biserial": (positive-negative)/total if total else 0.0,
            "method": "exact conditional sign permutation of average signed ranks; zero_method=wilcox",
            "direction": "candidate minus baseline; positive effect indicates larger candidate values",
            "null_assumption": "independent application-level differences symmetric about zero"}


def quartiles(values):
    if not values or any(not math.isfinite(float(x)) for x in values):
        raise ValueError("empty/nonfinite observations")
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else [values[0]]*3
    return {"n": len(values), "median": statistics.median(values), "q1": q1, "q3": q3, "iqr": q3-q1}


def rounded_difference(candidate, baseline, unit, seconds_digits):
    quantum = Decimal(1).scaleb(-seconds_digits if unit == "seconds" else -3 if unit == "MiB" else 0)
    return (Decimal(str(candidate))-Decimal(str(baseline))).quantize(quantum, rounding=ROUND_HALF_EVEN)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metrics(resource, valid, kind):
    java = dict(zip(RUN_COLS if kind == "taint" else ANDRO_COLS, valid["run_row"]))
    result = {"external_wall_seconds": (resource["wall_seconds"], "seconds"),
              "root_working_set_bytes": (resource.get("peak_root_working_set_bytes"), "bytes"),
              "tree_sampled_working_set_bytes": (resource.get("peak_tree_sampled_working_set_bytes"), "bytes")}
    for output, key, unit in (("reported_live_any_mib", "live_any_mb", "MiB"),
                              ("reported_live_major_or_final_mib", "live_major_mb", "MiB"),
                              ("reported_major_gc_count", "major_gcs", "count")):
        result[output] = (float(java[key]), unit)
    if kind == "taint":
        for output, key in (("callgraph_seconds", "cg_s"), ("taint_seconds", "taint_s"),
                            ("path_reconstruction_seconds", "path_s"), ("java_internal_wall_seconds", "wall_s")):
            result[output] = (float(java[key]), "seconds")
        for key in ("cg_edges", "reachable", "edge_prop", "infoflow_prop", "alias_prop"):
            result[key] = (float(java[key]), "count")
    else:
        result["java_analysis_seconds"] = (float(java["time_s"]), "seconds")
        result["symbolic_paths"] = (float(java["total_paths"]), "count")
        result["formals"] = (float(java["formals"]), "count")
    gc = valid.get("gc_metrics")
    if gc is not None:
        for key in ("generation_solve_peak_after_any_gc_bytes", "generation_solve_peak_after_major_gc_bytes",
                    "forced_gc_after_heap_bytes"):
            result[key] = (gc[key], "bytes")
        for key in ("generation_solve_gc_notification_count", "generation_solve_major_gc_notification_count"):
            result[key] = (gc[key], "count")
        for key in ("forced_gc_call_seconds", "forced_gc_notification_wait_seconds", "forced_gc_total_overhead_seconds"):
            result[key] = (gc[key], "seconds")
        if type(gc["forced_major_gc_notification_confirmed"]) is not bool:
            raise ValueError("invalid final-GC confirmation flag")
        result["forced_major_gc_confirmed_count"] = (int(gc["forced_major_gc_notification_confirmed"]), "count")
    for value, _ in result.values():
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("invalid successful measurement")
    return result


def analyze_batch(root, baseline=None, seconds_digits=6):
    root = Path(root).resolve()
    state, inputs = load(root / "state.json"), load(root / "inputs.json")
    batch = inputs["batch"]
    if (not state.get("finished") or state.get("expected") != state.get("processed")
            or len(state.get("instances", {})) != state.get("expected")):
        raise ValueError("batch is not fully processed: " + str(root))
    if (state.get("mode") != "performance" or batch.get("mode") != "performance"
            or batch.get("parallel") != 1 or batch.get("reps") != 5 or batch.get("timeout") != 1800
            or batch.get("seed") != 20260930):
        raise ValueError("requires serial five-repeat seeded 1800s formal protocol; functional/legacy batches rejected")
    kind = batch["kind"]
    if kind not in {"taint", "androlic"}:
        raise ValueError("unsupported performance kind")
    variant = batch.get("measurement_variant")
    measured = variant is not None
    environment = "exclusive_v1"
    if measured:
        from run_androlic_measured import VARIANT, SCOPE, validate_measured_outputs, validate_context_metadata, BACKGROUND_ENVIRONMENT, BACKGROUND_NAME, BACKGROUND_PRODUCER
        if kind != "androlic" or variant != VARIANT or batch.get("gc_scope") != SCOPE:
            raise ValueError("unknown measurement variant or GC scope")
        if any(record.get("measurement_variant") != VARIANT or record.get("gc_scope") != SCOPE
               for record in (state, inputs)):
            raise ValueError("mixed measured/legacy batch metadata")
        environment = validate_context_metadata((batch, state, inputs))
        if environment != BACKGROUND_ENVIRONMENT:
            raise ValueError("active measured statistics require the fast observer; use frozen analyzers for exclusive v1 or the v2 pilot")
        if environment == BACKGROUND_ENVIRONMENT:
            if batch.get("name") != BACKGROUND_NAME or root.name != BACKGROUND_NAME:
                raise ValueError("controlled background statistics require the exact v2 batch name")
            link = batch["controlled_background_baseline"]
            expected = {str(Path(link["path"]).resolve()): link["sha256"],
                        str(BACKGROUND_PRODUCER.resolve()): batch["controlled_background_proofproducer_source_sha256"]}
            shared = {str(Path(item["path"]).resolve()): item["sha256"] for item in inputs["shared_inputs"]}
            if any(shared.get(path) != sha for path, sha in expected.items()):
                raise ValueError("background/source fingerprint evidence absent from shared inputs")
    elif any(record.get("measurement_variant") is not None or record.get("gc_scope") is not None
             for record in (state, inputs)):
        raise ValueError("unmarked measurement variant")
    if environment == "exclusive_v1" and state.get("time_load_affected") is not False:
        raise ValueError("legacy/exclusive performance cannot claim controlled background")
    selected_policy = batch.get("formal_exclusivity_policy")
    base = baseline or ("native" if kind == "taint" else "fixed/perarg")
    if digest({k:r["fingerprint"] for k,r in state["instances"].items()}) != state["batch_fingerprint"]:
        raise ValueError("batch fingerprint mismatch")
    groups, failures, source_files, gc_observations, exclusivity_observations = defaultdict(dict), [], [], [], []
    synthetic_fixture = False
    for key, instance in state["instances"].items():
        rep = instance["rep"]
        pair = (instance["label"], instance["config"])
        if rep not in range(1, 6) or rep in groups[pair]:
            raise ValueError("duplicate/out-of-protocol repetition")
        folder = Path(instance["attempt"])
        params = load(folder / "inputs.json")["parameters"]
        saved, resource = load(folder / "result.json"), load(folder / "resource.json")
        if (digest(params) != instance["fingerprint"] or params["inputs"] != inputs["shared_inputs"]
                or saved["fingerprint"] != instance["fingerprint"] or saved["status"] != instance["status"]
                or (saved.get("label"), saved.get("config"), saved.get("rep")) != (pair[0], pair[1], rep)
                or params["rep"] != rep or params["config"] != pair[1]
                or resource.get("metadata", {}).get("fingerprint") != instance["fingerprint"]
                or resource.get("metadata", {}).get("mode") != "performance"
                or resource["metadata"].get("max_observed_concurrency") != 1):
            raise ValueError("instance identity/protocol mismatch: " + key)
        if measured and any(record.get("measurement_variant") != VARIANT or record.get("gc_scope") != SCOPE
                            for record in (instance, saved, params, resource["metadata"])):
            raise ValueError("mixed measured/legacy instance metadata: " + key)
        if measured:
            validate_context_metadata((batch, instance, saved, params, resource["metadata"]))
        synthetic_fixture |= params.get("synthetic") is True or resource["metadata"].get("fixture_only") is True
        if not measured and any(record.get("measurement_variant") is not None or record.get("gc_scope") is not None
                                for record in (instance, saved, params, resource["metadata"])):
            raise ValueError("unmarked measured instance: " + key)
        if any(params.get(k) != batch.get(k) for k in ("mode","parallel","reps","timeout","cg","maxpaths","xmx","seed","sample_interval")):
            raise ValueError("repetition belongs to a different protocol: " + key)
        for name in ("inputs.json", "result.json", "resource.json"):
            p = folder / name
            source_files.append({"path": str(p), "sha256": sha256(p)})
        if instance["status"] == "ok":
            if measured:
                validated = validate_measured_outputs(kind, folder, pair[0], pair[1], rep, require_exclusivity=True)
                if saved.get("outputs") != validated["files"] or instance.get("outputs") != validated["files"]:
                    raise ValueError("measured output hash mismatch: " + key)
            else:
                valid = completed_attempt(kind, folder, instance["fingerprint"], pair[0], pair[1], rep)
                validated = valid["validated"] if valid else None
            if not validated or not resource_valid(resource) or resource.get("cleanup_error"):
                raise ValueError("successful output integrity failure: " + key)
            if resource.get("sample_interval_s") != batch.get("sample_interval"):
                raise ValueError("resource sampling protocol mismatch: " + key)
            groups[pair][rep] = metrics(resource, validated, kind)
            source_files += validated["files"]
            if measured:
                gc_observations.append({"key":key, "label":pair[0], "config":pair[1], "rep":rep,
                                        "metrics":validated["gc_metrics"]})
                exclusivity_observations.append({"key":key, "proof":validated["formal_exclusivity"]})
                synthetic_fixture |= validated["formal_exclusivity"].get("synthetic_guard_fixture") is True
        else:
            if measured:
                from formal_exclusivity import validate_exclusivity
                failed_proof = validate_exclusivity(resource, folder)
                exclusivity_observations.append({"key": key, "proof": failed_proof})
                synthetic_fixture |= failed_proof.get("synthetic_guard_fixture") is True
            if (not resource.get("ended_at") or not isinstance(resource.get("wall_seconds"), (int, float))
                    or not math.isfinite(resource["wall_seconds"]) or resource["wall_seconds"] < 0
                    or instance["status"] in {"running", "interrupted"}):
                raise ValueError("nonterminal/unmeasured failure: " + key)
            rs, exit_code = resource.get("status"), resource.get("exit_code")
            terminal = ((instance["status"] in {"failed","timeout"} and rs == instance["status"] and isinstance(exit_code,int))
                        or (instance["status"] == "invalid_output" and rs == "ok" and exit_code == 0)
                        or (instance["status"] == "launch_error" and rs == "launch_error" and resource.get("pid") is None))
            if not terminal or resource.get("cleanup_error"):
                raise ValueError("failed process termination unverified: " + key)
            groups[pair][rep] = None
            failures.append({"key": key, "label": pair[0], "config": pair[1], "rep": rep,
                             "status": instance["status"], "exit_code": resource.get("exit_code"),
                             "actual_wall_seconds": resource["wall_seconds"], "resource": str(folder / "resource.json")})
    configs = sorted({c for _,c in groups})
    labels = sorted({a for a,_ in groups})
    if base not in configs or set(groups) != {(a,c) for a in labels for c in configs}:
        raise ValueError("missing baseline or app/config combinations")
    aggregates, complete, excluded = [], {}, []
    for (label, config), repeats in sorted(groups.items()):
        if set(repeats) != set(range(1,6)):
            raise ValueError("missing expected repetition")
        good = [r for r in repeats.values() if r is not None]
        if len(good) != 5:
            excluded.append({"label": label, "config": config, "reason": "one or more unsuccessful repeats", "ok_repeats": len(good)})
            continue
        for metric in sorted(good[0]):
            values = [r[metric][0] for r in good]
            unit = good[0][metric][1]
            if any(v is None for v in values):
                excluded.append({"label": label, "config": config, "metric": metric, "reason": "missing measured values"})
                continue
            summary = quartiles(values)
            aggregates.append({"label":label,"config":config,"metric":metric,"unit":unit,**summary})
            complete[(label, config, metric)] = summary["median"]
    comparisons = []
    metric_units = {r["metric"]:r["unit"] for r in aggregates}
    for candidate in configs:
        if candidate == base:
            continue
        for metric,unit in sorted(metric_units.items()):
            matched = [a for a in labels if (a,base,metric) in complete and (a,candidate,metric) in complete]
            differences = [rounded_difference(complete[(a,candidate,metric)], complete[(a,base,metric)], unit, seconds_digits) for a in matched]
            row = {"baseline":base,"candidate":candidate,"metric":metric,"unit":unit,
                   "paired_applications":matched,"excluded_applications":sorted(set(labels)-set(matched))}
            row.update(signed_rank(differences) if matched else {"n_pairs":0,"p_two_sided":None,"rank_biserial":None,"missing_reason":"no complete paired applications"})
            comparisons.append(row)
    return {"batch":str(root),"name":batch["name"],"kind":kind,"baseline":base,
            "measurement_variant":variant, "gc_scope":batch.get("gc_scope"), "gc_observations":gc_observations,
            "formal_exclusivity_policy":batch.get("formal_exclusivity_policy"), "exclusivity_observations":exclusivity_observations,
            "measurement_environment":environment, "sterile_exclusive":environment == "exclusive_v1",
            "background_load_present":environment == "controlled_background_v2_fast",
            "controlled_background_binding_sha256":batch.get("controlled_background_binding_sha256"),
            "controlled_background_baseline":batch.get("controlled_background_baseline"),
            "time_load_affected":state.get("time_load_affected"),
            "synthetic_fixture":synthetic_fixture, "counts_are_experiment_statistics":not synthetic_fixture,
            "callgraph_metadata_role":("passed to TaintRun" if kind == "taint" else
                                       "shared runner bookkeeping; cg is not passed to the Androlic Java command or config file; internal algorithm not established here"),
            "protocol":{k:batch.get(k) for k in ("mode","parallel","reps","timeout","seed","cg","xmx","maxpaths","sample_interval")},
            "shared_inputs_sha256":digest(inputs["shared_inputs"]),"source_files":source_files,
            "instance_status_counts":dict(Counter(r["status"] for r in state["instances"].values())),
            "aggregates":aggregates,"comparisons":comparisons,"failures":failures,"exclusions":excluded,
            "quartile_method":"inclusive linear interpolation (statistics.quantiles)",
            "difference_rounding":{"seconds_digits":seconds_digits,"MiB_digits":3,"bytes_and_counts_digits":0},
            "paired_unit":"one application median of five verified successful repeats",
            "multiplicity":"raw two-sided p-values; no claim of significance from unadjusted multiple comparisons",
            "limitations":[("controlled-background v2 fast observer retains exactly pinned background services and their measured load under fixed budgets; these are not sterile exclusive timings and must not be pooled with v1 or the slow v2 pilot" if environment == "controlled_background_v2_fast" else "exclusive v1 uses no admitted background JVMs"),
                           "fresh admission plus sampled Windows/WSL/state monitoring rejects observed unadmitted collisions; finite sampling can miss short-lived work and observer cost is retained, not subtracted",
                           "legacy LiveSetTracker.finish holds notification lock during request/wait and does not confirm final GC; reported heap values retained as reported, not a verified major-GC maximum",
                           "internal Java durations exclude final tracker.finish; external wall includes process launch and forced-GC overhead",
                           "measured Androlic GC observations cover generation+solve; final confirmed occupancy and forced call/wait overhead are separate; delivered notifications do not establish an absolute peak live set",
                           "failed repeats excluded rather than replaced by timeout constant or zero memory"],"method_sources":SOURCES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", action="append", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--baseline")
    parser.add_argument("--seconds-digits", type=int, default=6)
    args = parser.parse_args()
    if not 0 <= args.seconds_digits <= 9:
        parser.error("seconds-digits must be 0..9")
    roots = [p.resolve() for p in args.batch]
    output = args.out_dir.resolve()
    if len(roots) != len(set(roots)) or any(output == p or output.is_relative_to(p) for p in roots):
        raise ValueError("separate output directory and unique batches required")
    batches = [analyze_batch(p,args.baseline,args.seconds_digits) for p in roots]
    if len({b["measurement_environment"] for b in batches}) != 1:
        raise ValueError("exclusive v1 and controlled-background v2 statistics must use separate output requests")
    if any(b["synthetic_fixture"] for b in batches):
        raise ValueError("synthetic validation fixtures cannot be published as formal research statistics")
    result = {"schema":"formal-performance-v2-controlled-background-fast" if batches[0]["measurement_environment"] == "controlled_background_v2_fast" else "formal-performance-v1","checked_at":utc_now(),"batches":batches,
              "pooling":"batches/callgraphs are analyzed separately, never pooled"}
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "summary.json", result)
    aggregate_cols = ["batch","label","config","metric","unit","n","median","q1","q3","iqr"]
    aggregate_rows = [[b["name"]]+[r[k] for k in aggregate_cols[1:]] for b in batches for r in b["aggregates"]]
    atomic_csv(output / "five_repeat_metrics.csv", [aggregate_cols]+aggregate_rows)
    comparison_cols = ["batch","baseline","candidate","metric","unit","n_pairs","p_two_sided","rank_biserial"]
    comparison_rows = [[b["name"]]+[r.get(k) for k in comparison_cols[1:]] for b in batches for r in b["comparisons"]]
    atomic_csv(output / "paired_signed_rank.csv", [comparison_cols]+comparison_rows)
    print(json.dumps({"batches":len(batches),"metrics":len(aggregate_rows),"comparisons":len(comparison_rows),
                      "failures":sum(len(b["failures"]) for b in batches),"output":str(output)}))


if __name__ == "__main__":
    main()
