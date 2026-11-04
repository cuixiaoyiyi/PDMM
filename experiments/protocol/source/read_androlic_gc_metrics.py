"""Reference function used to check the measured-run GC parser.
Extracted from the recorded measurement runner; source SHA-256: 1a742fca89b9892eedf06f2632b41fff1e3c1fba27cbd5d51847e8c4d29c509e
"""

def read_androlic_gc_metrics(folder, label=None, config=None, rep=None):
    metric, events = gc_paths(folder)
    raw = metric.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("Androlic GC JSON is truncated")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("GC metrics must be a JSON object")
    required = {"schema_version", "measurement_variant", "metric_scope", "androlic_status", "generation_solve_complete",
        "original_generation_solve_seconds", "before_forced_gc_ids", "generation_solve_start_gc_ids", "generation_solve_end_gc_ids",
        "generation_solve_gc_notification_count", "generation_solve_major_gc_notification_count", "notification_count", "event_rows_dropped",
        "forced_gc_requested", "forced_gc_notification_confirmed", "forced_major_gc_notification_confirmed", "forced_gc_after_heap_bytes",
        "forced_gc_missing_reason", "forced_gc_call_seconds", "forced_gc_notification_wait_seconds", "forced_gc_total_overhead_seconds",
        "legacy_reported_live_any_mb", "legacy_reported_live_major_mb", "legacy_reported_major_gcs", "legacy_reported_policy",
        "legacy_tracker_tail_outside_stage", "generation_component_failures", "solve_component_failures", "label", "config", "repetition"}
    if not required <= data.keys() or type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["measurement_variant"] != VARIANT or data["metric_scope"] != SCOPE:
        raise ValueError("Androlic GC measurement schema / scope mismatch")
    for flag in ("generation_solve_complete", "legacy_tracker_tail_outside_stage", "forced_gc_requested",
                 "forced_gc_notification_confirmed", "forced_major_gc_notification_confirmed"):
        if type(data[flag]) is not bool:
            raise ValueError("GC confirmation / scope flag is not Boolean: " + flag)
    if data["legacy_tracker_tail_outside_stage"] is not True:
        raise ValueError("legacy tracker tail must be outside generation+solve timing")
    for field in ("generation_component_failures", "solve_component_failures"):
        if type(data[field]) is not int or data[field] < 0:
            raise ValueError("invalid component failure count: " + field)
    if data["generation_solve_complete"] and (data["generation_component_failures"] or data["solve_component_failures"]):
        raise ValueError("completed generation+solve has component failures")
    if label is not None and (data["label"], data["config"], str(data["repetition"])) != (label, config, str(rep)):
        raise ValueError("Androlic GC sidecar identity mismatch")
    if not events.read_bytes().endswith(b"\n"):
        raise ValueError("Androlic GC event CSV is truncated")
    columns = ["ordinal", "collector", "cause", "action", "gc_id", "start_uptime_ms", "end_uptime_ms", "duration_ms",
        "heap_used_after_gc_bytes", "major_action", "in_generation_solve_window", "matches_probe_gc_request"]
    with events.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        if reader.fieldnames != columns:
            raise ValueError("GC CSV header has wrong scope / incomplete fields")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("malformed GC event row")
    for field in ("notification_count", "event_rows_dropped", "generation_solve_gc_notification_count", "generation_solve_major_gc_notification_count"):
        if type(data[field]) is not int or data[field] < 0:
            raise ValueError("invalid GC event count")
    if not 0 <= data["generation_solve_major_gc_notification_count"] <= data["generation_solve_gc_notification_count"] <= data["notification_count"]:
        raise ValueError("GC stage event count ordering is inconsistent")
    if len(rows) + data["event_rows_dropped"] != data["notification_count"]:
        raise ValueError("GC event count disagrees with coverage")
    for field in ("original_generation_solve_seconds", "forced_gc_call_seconds", "forced_gc_notification_wait_seconds", "forced_gc_total_overhead_seconds"):
        if type(data[field]) not in (int, float) or not math.isfinite(data[field]) or data[field] < 0:
            raise ValueError("missing / invalid stage or forced-GC duration")
    if abs(data["forced_gc_call_seconds"] + data["forced_gc_notification_wait_seconds"] - data["forced_gc_total_overhead_seconds"]) > 1e-8:
        raise ValueError("forced-GC overhead components disagree with total")
    for value, reason in (("generation_solve_peak_after_any_gc_bytes", "generation_solve_any_gc_missing_reason"),
                         ("generation_solve_peak_after_major_gc_bytes", "generation_solve_major_gc_missing_reason"),
                         ("forced_gc_after_heap_bytes", "forced_gc_missing_reason")):
        if data.get(value) is None:
            if not data.get(reason):
                raise ValueError("unexplained missing GC observation: " + value)
        elif type(data[value]) is not int or data[value] < 0:
            raise ValueError("invalid after-GC heap observation")
    for field in ("overall_observed_peak_after_any_gc_bytes", "overall_observed_peak_after_major_gc_bytes"):
        if field not in data or (data[field] is not None and (type(data[field]) is not int or data[field] < 0)):
            raise ValueError("invalid overall observed GC heap peak")
    for field in ("legacy_reported_live_any_mb", "legacy_reported_live_major_mb", "legacy_reported_major_gcs"):
        if type(data[field]) is not int or data[field] < 0:
            raise ValueError("invalid preserved reported metric")
    if data["forced_major_gc_notification_confirmed"] and not data["forced_gc_notification_confirmed"]:
        raise ValueError("major confirmation requires a matching GC notification")
    if data["forced_gc_notification_confirmed"] and not data["forced_gc_requested"]:
        raise ValueError("GC confirmation cannot precede an absent request")
    parsed_rows = []
    for ordinal, row in enumerate(rows, 1):
        values = {}
        for name in ("ordinal", "gc_id", "start_uptime_ms", "end_uptime_ms", "duration_ms", "heap_used_after_gc_bytes"):
            if not re.fullmatch(r"(?:0|[1-9][0-9]*)", row[name]):
                raise ValueError("GC event numeric field is malformed")
            values[name] = int(row[name])
        if values["ordinal"] != ordinal or values["gc_id"] < 1 or values["end_uptime_ms"] - values["start_uptime_ms"] != values["duration_ms"]:
            raise ValueError("GC event ordinal / timing / ID inconsistency")
        for name in ("major_action", "in_generation_solve_window", "matches_probe_gc_request"):
            if row[name] not in {"true", "false"}:
                raise ValueError("GC event Boolean field is malformed")
            values[name] = row[name] == "true"
        if values["major_action"] != ("major" in row["action"].lower()):
            raise ValueError("GC major classification disagrees with reported action")
        for name in ("generation_solve_start_gc_ids", "generation_solve_end_gc_ids", "before_forced_gc_ids"):
            mapping = data[name]
            if not isinstance(mapping, dict) or any(type(value) is not int or value < -1 for value in mapping.values()):
                raise ValueError("GC ID window map is malformed")
        lower = data["generation_solve_start_gc_ids"].get(row["collector"])
        upper = data["generation_solve_end_gc_ids"].get(row["collector"])
        in_stage = lower is not None and lower >= 0 and values["gc_id"] > lower and (upper is None or values["gc_id"] <= upper)
        if values["in_generation_solve_window"] != in_stage:
            raise ValueError("GC event generation+solve window disagrees with GC IDs")
        before = data["before_forced_gc_ids"].get(row["collector"])
        matches = data["forced_gc_requested"] and before is not None and before >= 0 and values["gc_id"] > before and "System.gc" in row["cause"]
        if values["matches_probe_gc_request"] != matches:
            raise ValueError("GC event request match disagrees with GC IDs / cause")
        parsed_rows.append(values)
    stage = [r for r in parsed_rows if r["in_generation_solve_window"]]
    stage_major = [r for r in stage if r["major_action"]]
    all_major = [r for r in parsed_rows if r["major_action"]]
    matched_major = [r for r in parsed_rows if r["matches_probe_gc_request"] and r["major_action"]]
    if len({(r["collector"], r["gc_id"]) for r in rows}) != len(rows):
        raise ValueError("duplicate per-collector GC event ID")
    dropped = data["event_rows_dropped"]
    for group, field in ((stage, "generation_solve_gc_notification_count"), (stage_major, "generation_solve_major_gc_notification_count")):
        if not len(group) <= data[field] <= len(group) + dropped:
            raise ValueError("GC stage count disagrees with recorded events")
    for group, field in ((stage, "generation_solve_peak_after_any_gc_bytes"), (stage_major, "generation_solve_peak_after_major_gc_bytes"),
                         (parsed_rows, "overall_observed_peak_after_any_gc_bytes"), (all_major, "overall_observed_peak_after_major_gc_bytes")):
        observed = max((r["heap_used_after_gc_bytes"] for r in group), default=None)
        if not dropped and data[field] != observed:
            raise ValueError("GC peak disagrees with complete event history")
        if dropped and observed is not None and (data[field] is None or data[field] < observed):
            raise ValueError("GC aggregate peak is smaller than recorded observations")
    if data["forced_major_gc_notification_confirmed"]:
        if data["forced_gc_after_heap_bytes"] is None:
            raise ValueError("confirmed final GC lacks after-GC occupancy")
        if not data["event_rows_dropped"] and not any(r["matches_probe_gc_request"] == "true" and r["major_action"] == "true" for r in rows):
            raise ValueError("forced final GC confirmation has no corresponding event")
        if not dropped and data["forced_gc_after_heap_bytes"] != matched_major[-1]["heap_used_after_gc_bytes"]:
            raise ValueError("confirmed final heap disagrees with the last matching major event")
    elif data["forced_gc_after_heap_bytes"] is not None:
        raise ValueError("unconfirmed GC request cannot provide confirmed live-heap data")
    return validate_gc_core(data, rows, "generation_solve")
