"""Read-only shared integrity checks for the frozen GC probe's sidecar format."""
import math
import re

def validate_gc_core(data, rows, prefix):
    """Validate delivered observations; missing confirmation is legal, contradictory data is not."""
    if not isinstance(data, dict):
        raise ValueError("GC metrics must be a JSON object")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("GC schema version is invalid")
    for field in (prefix + "_complete", "forced_gc_requested", "forced_gc_notification_confirmed", "forced_major_gc_notification_confirmed"):
        if type(data.get(field)) is not bool:
            raise ValueError("GC flag must be a JSON Boolean: " + field)
    status = data.get("androlic_status", data.get("export_status"))
    if data[prefix + "_complete"] and status != "OK":
        raise ValueError("completed GC window has unsuccessful analysis status")
    if data["forced_gc_requested"] != (data[prefix + "_complete"] and status == "OK"):
        raise ValueError("final GC request conflicts with successful complete analysis")
    count_any, count_major = prefix + "_gc_notification_count", prefix + "_major_gc_notification_count"
    for field in ("notification_count", "event_rows_dropped", count_any, count_major):
        if type(data.get(field)) is not int or data[field] < 0:
            raise ValueError("GC count must be an integer, not Boolean or negative: " + field)
    if not 0 <= data[count_major] <= data[count_any] <= data["notification_count"]:
        raise ValueError("GC count ordering is inconsistent")
    dropped = data["event_rows_dropped"]
    if len(rows) + dropped != data["notification_count"]:
        raise ValueError("GC event count differs from recorded/dropped history")
    capacity = data.get("event_storage_capacity")
    if type(capacity) is not int or capacity < 0 or len(rows) != min(capacity, data["notification_count"]):
        raise ValueError("GC stored history conflicts with storage capacity")
    for field in ("original_" + prefix + "_seconds", "forced_gc_call_seconds", "forced_gc_notification_wait_seconds", "forced_gc_total_overhead_seconds"):
        if type(data.get(field)) not in (int, float) or not math.isfinite(data[field]) or data[field] < 0:
            raise ValueError("GC/stage duration is missing, nonfinite, Boolean or negative: " + field)
    if abs(data["forced_gc_call_seconds"] + data["forced_gc_notification_wait_seconds"] - data["forced_gc_total_overhead_seconds"]) > 1e-8:
        raise ValueError("GC overhead total differs from its measured components")
    for field in ("observer_setup_seconds", "observer_unregister_seconds", "observer_callback_elapsed_sum_seconds"):
        if type(data.get(field)) not in (int, float) or not math.isfinite(data[field]) or data[field] < 0:
            raise ValueError("GC observer duration is invalid: " + field)
    peaks = [(prefix + "_peak_after_any_gc_bytes", prefix + "_any_gc_missing_reason"),
             (prefix + "_peak_after_major_gc_bytes", prefix + "_major_gc_missing_reason"),
             ("forced_gc_after_heap_bytes", "forced_gc_missing_reason"),
             ("overall_observed_peak_after_any_gc_bytes", None), ("overall_observed_peak_after_major_gc_bytes", None)]
    for field, reason in peaks:
        if field not in data or (data[field] is not None and (type(data[field]) is not int or data[field] < 0)):
            raise ValueError("GC heap bytes must be a nonnegative integer or explained null: " + field)
        if data[field] is None and reason and (not isinstance(data.get(reason), str) or not data[reason].strip()):
            raise ValueError("missing GC metric has no textual reason: " + field)
    maps = [prefix + "_start_gc_ids", prefix + "_end_gc_ids", "before_forced_gc_ids"]
    for field in maps:
        mapping = data.get(field)
        if not isinstance(mapping, dict) or any(not isinstance(key, str) or type(value) is not int or value < -1 for key, value in mapping.items()):
            raise ValueError("per-collector GC-ID boundary map is invalid")
    if not data["forced_gc_requested"] and data["before_forced_gc_ids"]:
        raise ValueError("unrequested final GC has request boundary IDs")
    if set(data[maps[0]]) != set(data[maps[1]]) or (data["forced_gc_requested"] and set(data[maps[2]]) != set(data[maps[1]])):
        raise ValueError("GC boundary collector sets disagree")
    for collector in set().union(*(data[field] for field in maps)):
        start, end, before = (data[field].get(collector) for field in maps)
        if start is not None and end is not None and start >= 0 and end >= 0 and end < start:
            raise ValueError("GC stage ID boundaries run backwards")
        if end is not None and before is not None and end >= 0 and before >= 0 and before < end:
            raise ValueError("final GC request ID precedes stage end")
    parsed = []
    identities = set()
    for ordinal, row in enumerate(rows, 1):
        event = {}
        if not row.get("collector") or not row.get("action") or not row.get("cause"):
            raise ValueError("GC event identity/action/cause missing")
        for field in ("ordinal", "gc_id", "start_uptime_ms", "end_uptime_ms", "duration_ms", "heap_used_after_gc_bytes"):
            if not isinstance(row.get(field), str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)", row[field]):
                raise ValueError("GC event numeric value is malformed")
            event[field] = int(row[field])
        if event["ordinal"] != ordinal or event["gc_id"] < 1 or event["end_uptime_ms"] - event["start_uptime_ms"] != event["duration_ms"]:
            raise ValueError("GC event ID/ordinal/duration invalid")
        identity = (row["collector"], event["gc_id"])
        if identity in identities:
            raise ValueError("duplicate per-collector GC-ID event")
        identities.add(identity)
        window_flag = "in_" + prefix + "_window"
        for field in ("major_action", window_flag, "matches_probe_gc_request"):
            if row.get(field) not in {"true", "false"}:
                raise ValueError("GC event flag must be true/false")
            event[field] = row[field] == "true"
        if event["major_action"] != ("major" in row["action"].lower()):
            raise ValueError("GC event major classification conflicts with action")
        lower = data[maps[0]].get(row["collector"])
        upper = data[maps[1]].get(row["collector"])
        inside = lower is not None and lower >= 0 and event["gc_id"] > lower and (upper is None or event["gc_id"] <= upper)
        if event[window_flag] != inside:
            raise ValueError("GC event window conflicts with ID boundaries")
        before = data["before_forced_gc_ids"].get(row["collector"])
        matching = data["forced_gc_requested"] and before is not None and before >= 0 and event["gc_id"] > before and "System.gc" in row["cause"]
        if event["matches_probe_gc_request"] != matching:
            raise ValueError("GC request-match event conflicts with ID/cause")
        parsed.append(event)
    stage = [event for event in parsed if event["in_" + prefix + "_window"]]
    stage_major = [event for event in stage if event["major_action"]]
    overall_major = [event for event in parsed if event["major_action"]]
    matching = [event for event in parsed if event["matches_probe_gc_request"]]
    matching_major = [event for event in matching if event["major_action"]]
    for group, count in ((stage, count_any), (stage_major, count_major)):
        if not len(group) <= data[count] <= len(group) + dropped:
            raise ValueError("GC phase count conflicts with delivered event history")
    for group, field in ((stage, peaks[0][0]), (stage_major, peaks[1][0]), (parsed, peaks[3][0]), (overall_major, peaks[4][0])):
        maximum = max((event["heap_used_after_gc_bytes"] for event in group), default=None)
        if not dropped and data[field] != maximum:
            raise ValueError("GC aggregate peak conflicts with complete event history")
        if dropped and maximum is not None and (data[field] is None or data[field] < maximum):
            raise ValueError("GC aggregate peak is below a delivered observation")
    for count, peak in ((count_any, peaks[0][0]), (count_major, peaks[1][0]), ("notification_count", peaks[3][0])):
        if (data[count] == 0) != (data[peak] is None):
            raise ValueError("GC aggregate count and peak nullness disagree")
    for smaller, larger in ((peaks[1][0], peaks[0][0]), (peaks[0][0], peaks[3][0]),
                            (peaks[1][0], peaks[4][0]), (peaks[4][0], peaks[3][0])):
        if data[smaller] is not None and (data[larger] is None or data[smaller] > data[larger]):
            raise ValueError("GC aggregate peaks violate observation containment")
    if data["forced_major_gc_notification_confirmed"] and not data["forced_gc_notification_confirmed"]:
        raise ValueError("major confirmation without any confirmation")
    if data["forced_gc_notification_confirmed"] and not data["forced_gc_requested"]:
        raise ValueError("GC confirmed although not requested")
    for group, flag in ((matching, "forced_gc_notification_confirmed"), (matching_major, "forced_major_gc_notification_confirmed")):
        if group and data[flag] is not True:
            raise ValueError("observed matching event contradicts false confirmation")
        if not dropped and data[flag] != bool(group):
            raise ValueError("confirmation conflicts with complete matching-event history")
    if data["forced_major_gc_notification_confirmed"]:
        if data["forced_gc_after_heap_bytes"] is None:
            raise ValueError("confirmed final major GC lacks after-GC occupancy")
        if not dropped and data["forced_gc_after_heap_bytes"] != matching_major[-1]["heap_used_after_gc_bytes"]:
            raise ValueError("confirmed heap differs from last matching major event")
    elif data["forced_gc_after_heap_bytes"] is not None:
        raise ValueError("unconfirmed final GC cannot supply a confirmed heap value")
    return data
