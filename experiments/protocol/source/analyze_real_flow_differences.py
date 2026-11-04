"""Whole-inventory real-app outcome audit and exact reported-flow differences.

Run only after the functional batch finishes. No APK execution, no accuracy
claim, and no normalization of generated method names or statement text.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

from annotate_taint_outcomes import completed_batch, InputVerifier, csv_rows, snapshot
from resource_monitor import utc_now
from run_static import atomic_csv, atomic_json

BASELINE, CANDIDATE = "native", "hsm_tx_alias"


def compare_reported_flows(baseline, candidate):
    """Preserve duplicate reported records; unavailable output stays unknown."""
    if baseline is None or candidate is None:
        return {"comparison_available": False, "reason": "one or both configurations lack trusted complete output",
                "shared": None, "baseline_only": None, "candidate_only": None}
    a, b = Counter(tuple(row) for row in baseline), Counter(tuple(row) for row in candidate)
    def records(values):
        return [{"source_method": key[0], "source_statement": key[1],
                 "sink_method": key[2], "sink_statement": key[3], "reported_multiplicity": count,
                 "manual_validation": "pending"} for key, count in sorted(values.items())]
    return {"comparison_available": True, "reason": None, "shared": records(a & b),
            "baseline_only": records(a - b), "candidate_only": records(b - a),
            "baseline_reported_records": sum(a.values()), "candidate_reported_records": sum(b.values()),
            "exact_key_policy": "all four original source/sink method/statement strings; no normalization"}


def analyze(annotation, expected_apps=20):
    if (annotation.get("scope") != "complete_planned_batch" or annotation.get("whole_batch_complete") is not True
            or annotation.get("prediction_target") != "all"
            or annotation.get("annotated") != expected_apps * 2 or annotation.get("expected") != expected_apps * 2):
        raise ValueError("full real-app inventory and both configurations are required")
    verifier = InputVerifier()
    verifier.verify(annotation["raw_batch_state"])
    state = json.loads(Path(annotation["raw_batch_state"]["path"]).read_text(encoding="utf-8"))
    planned = state.get("instances", {})
    if (state.get("finished") is not True or state.get("expected") != expected_apps * 2
            or state.get("processed") != expected_apps * 2 or len(planned) != expected_apps * 2):
        raise ValueError("the verified batch state lacks the full planned inventory")
    grouped = {}
    seen = set()
    for row in annotation["outcomes"]:
        key = row.get("planned_key")
        if key not in planned or key in seen:
            raise ValueError("annotation has an absent or duplicate planned identity")
        seen.add(key)
        identity = planned[key]
        label, config, rep = identity["label"], identity["config"], identity["rep"]
        # A corrupt/missing attempt JSON can produce an unknown before annotate
        # has read its identity. Use the verified inventory only for that row's
        # planned identity; it supplies no prediction or missing resource value.
        for field, expected in (("label",label), ("config",config), ("repetition",rep)):
            if field in row and row[field] != expected:
                raise ValueError("outcome identity conflicts with verified plan")
        if rep != 1 or config not in {BASELINE, CANDIDATE} or config in grouped.setdefault(label, {}):
            raise ValueError("duplicate or out-of-protocol real-app instance")
        for artifact in row["raw_artifacts"]:
            verifier.verify(artifact)
        flows, apk = None, row.get("apk_integrity")
        if row.get("score_eligible") is True:
            if any(field not in row for field in ("label", "config", "repetition")):
                raise ValueError("trusted output lacks its own verified identity")
            if row.get("classification") not in {"completed_taint_output", "completed_lookup_empty"} or not apk:
                raise ValueError("trusted output lacks complete classification or APK binding")
            verifier.verify(apk)
            path = (Path(row["attempt"]) / (label + "." + config + ".flows.csv")).resolve()
            bindings = [item for item in row["raw_artifacts"] if Path(item["path"]).resolve() == path]
            if len(bindings) != 1:
                raise ValueError("flow CSV lacks exactly one verified artifact binding")
            verifier.verify(bindings[0])
            raw = path.read_bytes()
            parsed = csv_rows(raw, 6)
            if any(r[:2] != [label, config] for r in parsed) or len(parsed) != row["flow_count_all"]:
                raise ValueError("flow identity/count differs from complete annotation")
            flows = [r[2:] for r in parsed]
        grouped[label][config] = {"outcome": row, "planned_identity":{"key":key,"label":label,"config":config,"repetition":rep},
                                 "flows": flows, "apk": apk}
    if seen != set(planned):
        raise ValueError("some planned outcomes were omitted")
    unknown = sum(row.get("score_eligible") is not True for row in annotation["outcomes"])
    if annotation.get("unknown_predictions") != unknown:
        raise ValueError("unknown coverage count differs from outcomes")
    if len(grouped) != expected_apps or any(set(rows) != {BASELINE, CANDIDATE} for rows in grouped.values()):
        raise ValueError("missing real-app/configuration combinations")
    comparisons = []
    for label, rows in sorted(grouped.items()):
        a, b = rows[BASELINE], rows[CANDIDATE]
        if a["apk"] and b["apk"] and a["apk"]["sha256"] != b["apk"]["sha256"]:
            raise ValueError("comparison uses different APK bytes: " + label)
        compared = compare_reported_flows(a["flows"], b["flows"])
        compared.update(label=label, baseline=BASELINE, candidate=CANDIDATE,
                        apk_sha256=(a["apk"] or b["apk"] or {}).get("sha256"),
                        baseline_outcome=a["outcome"], candidate_outcome=b["outcome"],
                        baseline_planned_identity=a["planned_identity"], candidate_planned_identity=b["planned_identity"])
        comparisons.append(compared)
    verifier.stable()
    return {"schema_version": 1, "scope": "complete real-app functional reported-flow differences",
            "planned_applications": expected_apps, "planned_instances": expected_apps * 2,
            "comparison_available_applications": sum(row["comparison_available"] for row in comparisons),
            "unknown_predictions": unknown, "accuracy_metrics": None,
            "accuracy_missing_reason": "no independent real-app ground truth supplied",
            "whole_batch_complete": True, "annotation": annotation, "comparisons": comparisons,
            "limitations": ["exact strings and multiplicities are reported records, not independently validated semantic source/sink pairs",
                            "methodOf can report '?'; generated method naming or statement differences can affect set identity",
                            "every added/removed record requires manual path/alias/lifecycle validation; pending records imply no proven improvement",
                            "functional wall and memory observations are affected by concurrent load and are not formal repeated performance measurements"],
            "changes_original_artifacts": False, "manual_flow_validation_complete": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", required=True, type=Path)
    parser.add_argument("--apk-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root, apks, output = args.batch_root.resolve(), args.apk_dir.resolve(), args.output_dir.resolve()
    if output.exists() or output == root or output.is_relative_to(root) or output.is_relative_to(apks):
        raise ValueError("a new separate immutable output directory is required")
    if len(list(apks.glob("*.apk"))) != 20:
        raise ValueError("the declared real-app corpus must contain exactly 20 APKs")
    started_at, started = utc_now(), time.perf_counter()
    annotation = completed_batch(root, apks, [BASELINE, CANDIDATE], 1, "all")
    result = analyze(annotation)
    result.update(started_at=started_at, ended_at=utc_now(), analysis_wall_seconds=time.perf_counter()-started,
                  analyzer=snapshot(__file__)[1], fixture_only=False)
    output.mkdir(parents=True)
    atomic_json(output / "differences.json", result)
    columns = ["label", "direction", "source_method", "source_statement", "sink_method", "sink_statement", "reported_multiplicity", "manual_validation"]
    rows = [columns]
    for application in result["comparisons"]:
        if application["comparison_available"]:
            for direction in ("baseline_only", "candidate_only"):
                rows += [[application["label"], direction, *[r[k] for k in columns[2:]]] for r in application[direction]]
    atomic_csv(output / "manual_review_queue.csv", rows)
    print(json.dumps({"output":str(output), "planned_instances":result["planned_instances"],
                      "comparison_available_applications":result["comparison_available_applications"],
                      "unknown_predictions":result["unknown_predictions"], "manual_review_records":len(rows)-1,
                      "accuracy_metrics":None}))


if __name__ == "__main__":
    main()
