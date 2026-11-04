#!/usr/bin/env python3
"""Read-only taint outcome annotation; never changes frozen runner artifacts.

FlowDroid 2.15.1's PerformanceData uses -1 for unrecorded metrics. A complete
Java OK/exit-zero output with empty reachable source/sink lookup is a zero tool
prediction, not evidence that the Android program cannot leak. Nullable metrics
remain missing; phase execution is inferred only for the documented lookup
early-return profile. Failed/truncated/terminated runs retain unknown prediction.

Single-attempt mode cannot establish batch completion. Batch mode requires an
explicit planned APK/config/repetition inventory and a stable finished manifest;
all planned instances remain in the output, including failures. Headline scoring
is not declared ready while unknown predictions exist.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

HERE = Path(__file__).resolve().parent
FLOWDROID_SHA256 = "51dadead47a173c494c2fa4855b1e8bd3b54e702a2c4b5ed58e60153009ae218"
COLS = ["label", "config", "status", "flows", "sources", "sinks", "cg_s", "taint_s", "path_s", "total_s", "fd_max_mb",
        "wall_s", "live_any_mb", "live_major_mb", "major_gcs", "edge_prop", "infoflow_prop", "alias_prop", "cg_edges",
        "reachable", "dmm_methods", "dmm_sites", "dmm_edges", "pdmm"]
SENTINELS = {"sources", "sinks", "cg_s", "taint_s", "path_s", "total_s", "fd_max_mb", "edge_prop", "infoflow_prop", "alias_prop"}
LOOKUP = {"source": "No sources found, aborting analysis", "sink": "No sinks found, aborting analysis"}


def digest(value, ensure_ascii=True):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_ascii).encode()).hexdigest()


def snapshot(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return raw, {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def csv_rows(raw, width):
    if raw and not raw.endswith(b"\n"):
        raise ValueError("CSV is truncated: missing final newline")
    result = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True))
    if any(len(row) != width for row in result):
        raise ValueError("CSV field count mismatch")
    return result


class InputVerifier:
    """Hash shared immutable inputs once, invalidate the cache on stat change."""
    def __init__(self):
        self.cache = {}

    def verify(self, item):
        p = Path(item["path"]).resolve()
        st = p.stat()
        key = (str(p), item["sha256"], item.get("size"))
        signature = (st.st_size, st.st_mtime_ns)
        cached = self.cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        if item.get("size") is not None and st.st_size != item["size"]:
            raise ValueError("input size changed: " + str(p))
        with p.open("rb") as fh:
            value = hashlib.file_digest(fh, "sha256").hexdigest()
        after = p.stat()
        if signature != (after.st_size, after.st_mtime_ns) or value != item["sha256"]:
            raise ValueError("input hash changed or unstable: " + str(p))
        proof = {"path": str(p), "size": after.st_size, "sha256": value}
        self.cache[key] = (signature, proof)
        return proof

    def stable(self):
        for (path, _, _), (signature, _) in self.cache.items():
            st = Path(path).stat()
            if signature != (st.st_size, st.st_mtime_ns):
                raise ValueError("input changed during annotation: " + path)


def annotate(attempt, *, expected=None, planned_apk=None, prediction_target="all", verifier=None):
    attempt = Path(attempt).resolve()
    verifier = verifier or InputVerifier()
    report = {"attempt": str(attempt), "classification": "untrusted_or_failed", "prediction": None,
              "prediction_all_flows": None, "prediction_fbsink": None, "score_eligible": False,
              "prediction_target": prediction_target, "raw_artifacts": [], "reasons": [],
              "original_result_status": None, "fingerprint": None, "whole_batch_complete": False}
    artifacts, raw_bytes = {}, {}

    def read(name, is_json=False):
        if name not in raw_bytes:
            raw, info = snapshot(attempt / name)
            artifacts[name], raw_bytes[name] = info, raw
        raw = raw_bytes[name]
        return json.loads(raw.decode("utf-8-sig")) if is_json else raw

    try:
        inputs, saved, resource = read("inputs.json", True), read("result.json", True), read("resource.json", True)
        params = inputs["parameters"]
        label, config, rep = saved["label"], saved["config"], saved["rep"]
        report.update(label=label, config=config, repetition=rep, fingerprint=saved["fingerprint"],
                      original_result_status=saved["status"], original_validation_error=saved.get("validation_error"),
                      original_exit_code=resource.get("exit_code"), external_wall_seconds=resource.get("wall_seconds"),
                      external_peak_root_working_set_bytes=resource.get("peak_root_working_set_bytes"),
                      external_peak_tree_sampled_working_set_bytes=resource.get("peak_tree_sampled_working_set_bytes"),
                      external_memory_missing_reason=resource.get("memory_missing_reason"),
                      sample_interval_s=resource.get("sample_interval_s"), concurrency=resource.get("metadata", {}))
        fingerprint = digest(params)
        meta = resource.get("metadata", {})
        if (inputs["fingerprint"] != fingerprint or saved["fingerprint"] != fingerprint
                or meta.get("fingerprint") != fingerprint or saved.get("kind") != "taint"
                or params["config"] != config or params["rep"] != rep
                or meta.get("label") != label or meta.get("config") != config or meta.get("repetition") != rep
                or Path(params["apk"]).stem != label):
            raise ValueError("attempt identity/fingerprint mismatch")
        if planned_apk is not None and Path(params["apk"]).resolve() != Path(planned_apk).resolve():
            raise ValueError("attempt APK differs from the explicit planned APK inventory")
        if expected is not None:
            if (expected.get("fingerprint") != fingerprint or expected.get("label") != label
                    or expected.get("config") != config or expected.get("rep") != rep
                    or expected.get("status") != saved["status"]
                    or Path(expected["attempt"]).resolve() != attempt):
                raise ValueError("batch manifest and selected attempt disagree")
        # Hash preserved partial logs/CSVs too, but never interpret their flows
        # as valid predictions merely because files happen to exist.
        for name in (label+"."+config+".run.csv", label+"."+config+".flows.csv", "process.log"):
            path = (attempt / name).resolve()
            if not path.is_relative_to(attempt):
                raise ValueError("artifact path escaped its attempt directory")
            if path.exists():
                read(name)
        # Preserve every failed attempt as a failed/unknown tool outcome. No
        # marker in a partial log can turn a failed JVM into prediction zero.
        if resource.get("status") != "ok" or resource.get("exit_code") != 0 or resource.get("cleanup_error"):
            report["classification"] = "execution_failed"
            raise ValueError("resource status/exit is not a clean completed run")
        if saved["status"] not in {"ok", "invalid_output"}:
            raise ValueError("original runner failure is not the documented sentinel validation case")
        if saved["status"] == "invalid_output" and "invalid nonnegative numeric value: '-1'" != saved.get("validation_error"):
            raise ValueError("original invalid output has another cause; preserve failure")
        wall = resource.get("wall_seconds")
        if (not resource.get("started_at") or not resource.get("ended_at")
                or type(wall) not in {int, float} or not math.isfinite(wall) or wall < 0):
            raise ValueError("external timing is incomplete")
        report["input_integrity"] = [verifier.verify(item) for item in params["inputs"]]
        report["apk_integrity"] = verifier.verify({"path": params["apk"], "sha256": params["apk_sha256"]})
        if not any(item["sha256"] == FLOWDROID_SHA256 for item in params["inputs"]):
            raise ValueError("FlowDroid version is outside this sentinel interpretation")
        command = resource.get("command", [])
        command_hash = hashlib.sha256(json.dumps(command, ensure_ascii=False).encode()).hexdigest()
        if command_hash != resource.get("command_sha256") or "rev.TaintRun" not in command:
            raise ValueError("resource command integrity/main class mismatch")
        args = command[command.index("rev.TaintRun")+1:]
        if (len(args) != 8 or Path(args[1]).resolve() != Path(params["apk"]).resolve()
                or Path(args[3]).resolve() != attempt or args[4:6] != [label, config]
                or args[6] != params["cg"] or args[7] != str(params["timeout"])):
            raise ValueError("TaintRun command arguments disagree with recorded parameters")
        run_name, flow_name = label+"."+config+".run.csv", label+"."+config+".flows.csv"
        run_rows = csv_rows(read(run_name), 24)
        if len(run_rows) != 1 or run_rows[0][:3] != [label, config, "OK"] or not run_rows[0][23]:
            raise ValueError("Java output is not one complete exact-OK run row")
        raw_row = dict(zip(COLS, run_rows[0]))
        normalized, missing = {}, []
        for field in COLS[3:23]:
            value = float(raw_row[field])
            if not math.isfinite(value) or (field != "wall_s" and int(value) != value):
                raise ValueError("invalid numeric metric: " + field)
            if value == -1 and field in SENTINELS:
                normalized[field] = None
                missing.append(field)
            elif value < 0:
                raise ValueError("unsupported negative metric: " + field)
            else:
                normalized[field] = value if field == "wall_s" else int(value)
        flows = csv_rows(read(flow_name), 6)
        if any(row[:2] != [label, config] for row in flows) or len(flows) != normalized["flows"]:
            raise ValueError("flow row identity/count mismatch")
        if saved["status"] == "ok":
            actual_outputs = [artifacts[run_name], artifacts[flow_name]]
            if saved.get("outputs") != actual_outputs:
                raise ValueError("formerly validated output artifact hash changed")
        log = read("process.log").decode("utf-8", errors="replace")
        ending = f"[TAINT] {label} {config} OK flows={len(flows)} "
        if not any(line.startswith(ending) for line in log.splitlines()):
            raise ValueError("final TaintRun completion log record missing")
        lookup_markers = [kind for kind, marker in LOOKUP.items() if marker in log]
        if re.search(r"^Exception in thread", log, re.M):
            raise ValueError("uncaught exception reported despite the apparent OK row")
        lookup_only = (bool(lookup_markers) and len(flows) == 0
                       and all(normalized[k] is None for k in ("sources", "sinks", "taint_s", "path_s", "edge_prop", "infoflow_prop", "alias_prop")))
        if saved["status"] == "invalid_output" and not missing:
            raise ValueError("claimed sentinel validation failure contains no legitimate sentinel")
        fbsink = sum("FBSINK" in row[5] for row in flows)
        report.update(classification="completed_lookup_empty" if lookup_only else "completed_taint_output",
                      prediction=int((fbsink if prediction_target == "fbsink" else len(flows)) > 0),
                      prediction_all_flows=int(bool(flows)), prediction_fbsink=int(fbsink > 0), score_eligible=True,
                      flow_count_all=len(flows), flow_count_fbsink=fbsink, java_status="OK",
                      raw_java_metrics=raw_row, nullable_java_metrics=normalized,
                      missing_metric_fields=missing,
                      missing_metric_basis="FlowDroid PerformanceData -1 means unrecorded; original CSV values retained",
                      source_sink_lookup_markers=lookup_markers,
                      stages={"callgraph": "timing_recorded" if normalized["cg_s"] is not None else "not_recorded",
                              "taint_propagation": "not_executed_after_empty_lookup" if lookup_only else
                                                   ("timing_recorded" if normalized["taint_s"] is not None else "execution_not_determined_from_missing_timing"),
                              "path_reconstruction": "not_executed_after_empty_lookup" if lookup_only else
                                                     ("timing_recorded" if normalized["path_s"] is not None else "execution_not_determined_from_missing_timing")},
                      accuracy_interpretation="Zero is the tool prediction, not runtime no-leak truth; positive ground truth must count it as a false negative")
        verifier.stable()
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        if report["score_eligible"]:
            report.update(classification="untrusted_or_failed", prediction=None,
                          prediction_all_flows=None, prediction_fbsink=None, score_eligible=False)
        report["reasons"].append(str(exc))
    finally:
        # Include every raw artifact actually inspected, even when malformed.
        report["raw_artifacts"] = list(artifacts.values())
    return report


def completed_batch(root, apk_dir, configs, reps, prediction_target):
    root, apk_dir = Path(root).resolve(), Path(apk_dir).resolve()
    if reps < 1 or not configs or len(configs) != len(set(configs)):
        raise ValueError("explicit nonempty unique planned configurations and positive repetitions required")
    apks = sorted(apk_dir.glob("*.apk"))
    if not apks:
        raise ValueError("planned APK inventory is empty")
    expected = {p.stem+"."+cfg+".rep"+str(rep): (p, cfg, rep)
                for p in apks for cfg in configs for rep in range(1, reps+1)}
    raw_state, state_info = snapshot(root / "state.json")
    state = json.loads(raw_state.decode("utf-8-sig"))
    if (state.get("kind") != "taint" or state.get("finished") is not True
            or state.get("expected") != len(expected) or state.get("processed") != len(expected)
            or set(state.get("instances", {})) != set(expected)):
        raise ValueError("unfinished/mismatched batch: use attempt mode until every planned instance is terminal")
    if digest({key: item["fingerprint"] for key, item in state["instances"].items()}) != state.get("batch_fingerprint"):
        raise ValueError("completed batch fingerprint does not authenticate the selected instance inventory")
    verifier, annotated = InputVerifier(), []
    for key, (apk, cfg, rep) in sorted(expected.items()):
        instance = state["instances"][key]
        if instance.get("label") != apk.stem or instance.get("config") != cfg or instance.get("rep") != rep:
            raise ValueError("batch key/identity mismatch: " + key)
        outcome = annotate(instance["attempt"], expected=instance, planned_apk=apk,
                           prediction_target=prediction_target, verifier=verifier)
        outcome["planned_key"] = key
        outcome["whole_batch_complete"] = True
        annotated.append(outcome)
    after, _ = snapshot(root / "state.json")
    if after != raw_state:
        raise ValueError("batch manifest changed during annotation")
    verifier.stable()
    unknown = sum(row["prediction"] is None for row in annotated)
    return {"scope": "complete_planned_batch", "whole_batch_complete": True, "raw_batch_state": state_info,
            "batch_root": str(root), "expected": len(expected), "annotated": len(annotated),
            "prediction_target": prediction_target, "unknown_predictions": unknown,
            "classification_counts": dict(Counter(row["classification"] for row in annotated)),
            "headline_accuracy_ready": unknown == 0, "outcomes": annotated,
            "coverage_policy": "Every planned row retained. Do not silently exclude failures from accuracy denominators; unknown outcomes require explicit failure coverage and bounds or deferred headline scores."}


def load_truth(path, kind, *, planned_labels):
    """Load observed FragBench truth or predeclared DroidBench annotations."""
    raw, artifact = snapshot(path)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    truth, exclusions, mappings, seen = {}, {}, {}, set()
    for row in reader:
        original = row["id"] if kind == "fragbench" else row["label"]
        candidates = {original}
        if kind == "droidbench":
            candidates.add(original.removeprefix("droidbench__"))
            candidates.add("droidbench__"+original)
        matching = candidates.intersection(planned_labels)
        if len(matching) != 1:
            raise ValueError("truth label absent or ambiguous in the predeclared plan: " + original)
        label = next(iter(matching))
        if label in seen:
            raise ValueError("duplicate normalized truth label: " + label)
        seen.add(label)
        mappings[original] = label
        if kind == "fragbench":
            if (row.get("status", "completed") != "completed" or row["observed"] not in {"leak", "noleak"}
                    or row.get("crashed", "0") != "0" or row.get("case_exit_code", "0") != "0"):
                raise ValueError("dynamic truth is incomplete/crashed: " + label)
            truth[label] = int(row["observed"] == "leak")
        elif kind == "droidbench":
            if row["status"] == "ok":
                value = int(row["expected_leaks"])
                if value < 0:
                    raise ValueError("negative expected leak annotation")
                truth[label] = value
            else:
                exclusions[label] = "Predeclared DroidBench truth status="+row["status"]+"; "+row.get("note", "")
        else:
            raise ValueError("unknown truth kind")
    if kind == "fragbench" and (len(truth) != 36 or set(truth) != set(planned_labels)):
        raise ValueError("FragBench requires all 36 observed truth rows for the complete planned label inventory")
    for label in planned_labels-set(truth)-set(exclusions):
        exclusions[label] = "APK absent from predeclared DroidBench ground-truth annotations"
    return {"truth": truth, "predeclared_exclusions": exclusions, "source_artifact": artifact,
            "kind": kind, "eligible_cases": len(truth), "excluded_cases": len(exclusions), "label_mapping": mappings,
            "exclusions_independent_of_taint_success_or_failure": True,
            "positive_cases": sum(value > 0 for value in truth.values()), "negative_cases": sum(value == 0 for value in truth.values())}


def score_full_coverage(report, truth, *, count_mode=False, truth_exclusions=None):
    """Score complete planned annotations, retaining failures and unknown truth.

truth maps exact APK labels to nonnegative expected leak counts. FragBench uses
count_mode=False with FBSINK predictions; DroidBench count_mode=True reproduces
the legacy min(reported flows, expected leaks) count proxy, not source/sink-pair
matching. It requires manual flow-difference validation for pair-level claims.
Full metrics remain null when any planned outcome or truth
is unknown. Known counts and a labelled sensitivity bound are diagnostic only.
"""
    if report.get("scope") != "complete_planned_batch" or report.get("whole_batch_complete") is not True:
        raise ValueError("single-attempt/partial annotations cannot publish batch accuracy")
    outcomes = report["outcomes"]
    if not outcomes or report.get("expected") != len(outcomes):
        raise ValueError("planned coverage does not match annotation rows")
    groups, identities = {}, set()
    truth_exclusions = truth_exclusions or {}
    for outcome in outcomes:
        label, config, rep = outcome["label"], outcome["config"], outcome["repetition"]
        identity = (label, config, rep)
        if identity in identities:
            raise ValueError("duplicate planned scoring identity")
        identities.add(identity)
        key = (config, rep)
        group = groups.setdefault(key, {"config": config, "repetition": rep, "planned_instances": 0,
                                       "known_output_tp": 0, "known_output_fp": 0, "known_output_fn": 0,
                                       "unknown_predictions": 0, "missing_truth": 0,
                                       "predeclared_truth_exclusions": 0, "unknown_predictions_with_known_truth": 0,
                                       "positive_truth_with_unknown_prediction": 0,
                                       "expected_positive_leaks_in_unknown_predictions": 0,
                                       "total_expected_leaks_with_known_truth": 0, "rows": []})
        group["planned_instances"] += 1
        prediction = outcome.get("prediction")
        if prediction not in {None, 0, 1} or (prediction is not None and outcome.get("score_eligible") is not True):
            raise ValueError("inconsistent prediction validity")
        if prediction is None:
            group["unknown_predictions"] += 1
        expected = truth.get(label)
        if expected is not None and (type(expected) is not int or expected < 0 or (not count_mode and expected not in {0, 1})):
            raise ValueError("truth is not a valid expected leak count")
        row = {"label": label, "classification": outcome["classification"], "prediction": prediction,
               "expected_leaks": expected, "attempt": outcome["attempt"], "fingerprint": outcome["fingerprint"]}
        group["rows"].append(row)
        if expected is None:
            group["missing_truth"] += 1
            row["excluded_reason"] = truth_exclusions.get(label, "Ground truth unavailable; not an analysis-dependent exclusion")
            row["predeclared_truth_exclusion"] = label in truth_exclusions
            group["predeclared_truth_exclusions"] += int(label in truth_exclusions)
            continue
        group["total_expected_leaks_with_known_truth"] += expected
        if prediction is None:
            group["unknown_predictions_with_known_truth"] += 1
            group["positive_truth_with_unknown_prediction"] += int(expected > 0)
            group["expected_positive_leaks_in_unknown_predictions"] += expected
            continue
        count = outcome["flow_count_all"] if count_mode else prediction
        if type(count) is not int or count < 0:
            raise ValueError("reported leak count is invalid")
        group["known_output_tp"] += min(count, expected)
        group["known_output_fp"] += max(0, count-expected)
        group["known_output_fn"] += max(0, expected-count)
    summaries = []
    for _, group in sorted(groups.items()):
        tp, fp, fn = (group[k] for k in ("known_output_tp", "known_output_fp", "known_output_fn"))
        complete = group["unknown_predictions"] == 0 and group["missing_truth"] == 0
        subset_complete = (group["unknown_predictions_with_known_truth"] == 0
                           and group["missing_truth"] == group["predeclared_truth_exclusions"]
                           and group["planned_instances"] > group["missing_truth"])
        metrics = None
        if subset_complete:
            precision = tp/(tp+fp) if tp+fp else 0.0
            recall = tp/(tp+fn) if tp+fn else 0.0
            metrics = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
                       "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.0}
        denominator = group["total_expected_leaks_with_known_truth"]
        group.update(full_coverage_metrics=metrics if complete else None, full_coverage_metrics_ready=complete,
                     metrics_on_predeclared_truth_subset=metrics, declared_truth_subset_metrics_ready=subset_complete,
                     recall_lower_bound_on_truth_known_planned_rows=tp/denominator if denominator else None,
                     fn_if_unknown_predictions_are_missed=fn+group["expected_positive_leaks_in_unknown_predictions"],
                     diagnostic_counts_are_not_complete_case_headline_scores=True)
        summaries.append(group)
    return {"scope": "full_planned_coverage_score", "count_mode": count_mode, "summaries": summaries,
            "metric_basis": "legacy leak-count proxy; TP=min(reported flows, expected leaks), not validated source/sink pairs" if count_mode else "application-level binary detection of the configured FBSINK",
            "source_sink_pair_level_validation": False,
            "manual_flow_difference_validation_required_for_pair_level_claims": True,
            "headline_accuracy_ready": all(g["full_coverage_metrics_ready"] for g in summaries),
            "declared_truth_subset_accuracy_ready": all(g["declared_truth_subset_metrics_ready"] for g in summaries),
            "policy": "Failed/unknown rows remain unknown. Complete accuracy is withheld when any planned prediction or truth is unavailable; sensitivity bound treats unresolved known positives as missed without inventing their predictions."}


def source_provenance():
    paths = [HERE / "src/rev/TaintRun.java", HERE / "lib/fd_core_src/soot/jimple/infoflow/results/InfoflowPerformanceData.java",
             HERE / "lib/fd_core_src/soot/jimple/infoflow/AbstractInfoflow.java"]
    return [snapshot(p)[1] for p in paths if p.exists()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    one = sub.add_parser("attempt")
    one.add_argument("--attempt", required=True)
    batch = sub.add_parser("batch")
    batch.add_argument("--batch-root", required=True)
    batch.add_argument("--apk-dir", required=True)
    batch.add_argument("--configs", nargs="+", required=True)
    batch.add_argument("--reps", type=int, default=1)
    score = sub.add_parser("score")
    score.add_argument("--annotations", required=True)
    score.add_argument("--truth", required=True)
    score.add_argument("--truth-kind", choices=("fragbench", "droidbench"), required=True)
    for p in (one, batch, score):
        p.add_argument("--prediction-target", choices=("all", "fbsink"), default="all")
        p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError("annotation output exists; choose a new immutable sidecar path")
    started = time.perf_counter()
    if args.mode == "attempt":
        outcome = annotate(args.attempt, prediction_target=args.prediction_target)
        report = {"scope": "single_attempt_audit", "whole_batch_complete": False,
                  "headline_accuracy_ready": False, "outcomes": [outcome]}
    elif args.mode == "batch":
        report = completed_batch(args.batch_root, args.apk_dir, args.configs, args.reps, args.prediction_target)
    else:
        raw, annotation_info = snapshot(args.annotations)
        annotation = json.loads(raw.decode("utf-8-sig"))
        required_target = "fbsink" if args.truth_kind == "fragbench" else "all"
        if annotation.get("prediction_target") != required_target:
            raise ValueError("annotation prediction target does not match this benchmark scoring protocol")
        verifier = InputVerifier()
        verifier.verify(annotation["raw_batch_state"])
        for outcome in annotation["outcomes"]:
            for artifact in outcome["raw_artifacts"]:
                verifier.verify(artifact)
        labels = {row["label"] for row in annotation["outcomes"]}
        declared_truth = load_truth(args.truth, args.truth_kind, planned_labels=labels)
        report = score_full_coverage(annotation, declared_truth["truth"], count_mode=args.truth_kind == "droidbench",
                                     truth_exclusions=declared_truth["predeclared_exclusions"])
        report.update(annotation_artifact=annotation_info, truth_provenance=declared_truth,
                      whole_batch_complete=True, outcomes=annotation["outcomes"])
        verifier.stable()
    report.update(annotation_schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                  annotator=snapshot(__file__)[1], source_provenance=source_provenance(),
                  audit_wall_seconds=time.perf_counter()-started,
                  changes_original_artifacts=False, substitutes_missing_metrics_with_zero=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, allow_nan=False)
        fh.write("\n")
    print(json.dumps({"output": str(output), "scope": report["scope"], "whole_batch_complete": report["whole_batch_complete"],
                      "classification_counts": dict(Counter(row["classification"] for row in report["outcomes"]))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
