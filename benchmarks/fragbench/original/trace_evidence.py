#!/usr/bin/env python3
"""Independent checkpoint/alias evidence from preserved dynamic logs.

Never runs adb or mutates experiment outputs. Identity comparisons use the
identity component after '@', in a single inferred process generation only.
Current T.tag uses identityHashCode, so equality is a token observation, not
proof of a collision-free object ID. Without supplied, sourced automata, true
trace acceptance and specification legality remain explicitly unmeasured.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import re

TRACE = re.compile(r"^(\w+) (\d+) (\S+) this=(\S+)((?: a\d+=\S+)*) t=(\d+)$")
TIME_TAG = re.compile(r"([VDIWE])/(FBTRACE|FBSINK|FBSTEP|FBSESSION)\s*\(\s*(\d+)\):\s*(.*)")
THREAD_TAG = re.compile(r"^\S+\s+\S+\s+(\d+)\s+\d+\s+([VDIWE])\s+(FBTRACE|FBSINK|FBSTEP|FBSESSION)\s*:\s*(.*)")
LIFECYCLE = {"onCreate", "onStart", "onRestoreInstanceState", "onPostCreate", "onResume", "onPostResume",
             "onPause", "onSaveInstanceState", "onStop", "onRestart", "onDestroy", "onNewIntent", "onActivityResult",
             "onAttachFragment", "onAttach", "onAttachContext", "onCreateView", "onViewCreated", "onActivityCreated",
             "onViewStateRestored", "onDestroyView", "onDetach"}


def sha256(path):
    with Path(path).open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def identity(token):
    """Declared types may differ for the same underlying object."""
    if token is None or token == "null" or "@" not in token:
        return None
    return token.split("@", 1)[1]


def declared_type(token):
    return token.split("@", 1)[0] if token and "@" in token else None


def formal_index(event, slot):
    if slot == "this":
        return None
    # gen.py logs only data Intent for onActivityResult: trace a0 is formal 2.
    return 2 if event["callback"] == "onActivityResult" and slot == "a0" else int(slot[1:])


def parse_lines(lines, cid, source):
    events, sinks, warnings = [], [], []
    last_seq, generations, cycles, created = {}, defaultdict(int), defaultdict(lambda: 1), set()
    step = "unmarked"
    for line_no, line in enumerate(lines, 1):
        m = TIME_TAG.search(line)
        if m:
            _, tag, pid, payload = m.groups()
        else:
            m = THREAD_TAG.search(line)
            if not m:
                continue
            pid, _, tag, payload = m.groups()
        if tag == "FBSTEP":
            step = payload
            continue
        if tag == "FBSINK":
            if payload.startswith(cid + " "):
                sinks.append({"case": cid, "source": source, "line_no": line_no, "pid": int(pid),
                              "step": step, "payload": payload[len(cid) + 1:], "tainted": "TAINT#" in payload})
            continue
        if tag != "FBTRACE":
            continue
        t = TRACE.match(payload)
        if not t or t.group(1) != cid:
            warnings.append({"line_no": line_no, "reason": "malformed or different-case FBTRACE"})
            continue
        _, seq, event, receiver, args, thread = t.groups()
        if "." not in event:
            warnings.append({"line_no": line_no, "reason": "event lacks class/callback separator"})
            continue
        seq, pid = int(seq), int(pid)
        if pid in last_seq and seq <= last_seq[pid]:
            generations[pid] += 1
            warnings.append({"line_no": line_no, "reason": "PID sequence reset/regression; inferred a new process generation"})
        last_seq[pid] = seq
        cls, callback = event.split(".", 1)
        scope = (pid, generations[pid])
        key = (*scope, cls, identity(receiver))
        if callback == "onCreate":
            if key in created:
                cycles[key] += 1
            created.add(key)
        event_row = {"case": cid, "source": source, "line_no": line_no, "pid": pid,
                     "process_generation": generations[pid], "seq": seq, "thread_id": int(thread),
                     "class": cls, "callback": callback, "event": event,
                     "label": ("ACT" if cls in ("A", "Second") else "FRAG") + "." + callback,
                     "receiver_token": receiver, "receiver_identity_token": identity(receiver),
                     "receiver_creation_cycle": cycles[key], "step": step,
                     "args": dict(a.split("=", 1) for a in args.split()),
                     "checkpoint_basis": "entry before body" if callback in ("onCreateView", "onClick", "viewClick") else "after super call; callback exit is unobserved"}
        events.append(event_row)
    return events, sinks, warnings


def process_scope(event):
    return event["source"], event["case"], event["pid"], event["process_generation"]


def receiver_scope(event):
    return (*process_scope(event), event["class"], event["receiver_identity_token"], event["receiver_creation_cycle"])


def alias_pairs(events):
    pairs, skipped = [], Counter()
    by_receiver, by_process = defaultdict(list), defaultdict(list)
    for event in events:
        by_receiver[receiver_scope(event)].append(event)
        by_process[process_scope(event)].append(event)

    def pair(rule, a, slot_a, b, slot_b):
        va = a["receiver_token"] if slot_a == "this" else a["args"].get(slot_a)
        vb = b["receiver_token"] if slot_b == "this" else b["args"].get(slot_b)
        ia, ib = identity(va), identity(vb)
        if ia is None or ib is None:
            skipped[rule + ":null_or_missing"] += 1
            return
        if process_scope(a) != process_scope(b):
            skipped[rule + ":cross_process_generation"] += 1
            return
        pairs.append({"rule": rule, "case": a["case"], "source": a["source"], "pid": a["pid"],
                      "process_generation": a["process_generation"], "lhs": a["event"] + "." + slot_a,
                      "rhs": b["event"] + "." + slot_b, "lhs_line": a["line_no"], "rhs_line": b["line_no"],
                      "lhs_token": va, "rhs_token": vb, "lhs_declared_type": declared_type(va),
                      "rhs_declared_type": declared_type(vb), "relation": "same_token" if ia == ib else "different_token",
                      "lhs_formal_parameter_index": formal_index(a, slot_a), "rhs_formal_parameter_index": formal_index(b, slot_b),
                      "basis": "identity component after @, within this inferred process generation; hash equality can collide",
                      "lhs_receiver": a["receiver_token"], "rhs_receiver": b["receiver_token"],
                      "lhs_creation_cycle": a["receiver_creation_cycle"], "rhs_creation_cycle": b["receiver_creation_cycle"]})

    for es in by_receiver.values():
        first = {}
        for e in es:
            first.setdefault(e["callback"], e)
        cls = es[0]["class"]
        if cls in ("A", "Second"):
            if "onCreate" in first:
                for other in ("onRestoreInstanceState", "onPostCreate"):
                    if other in first:
                        pair("R-stateA", first["onCreate"], "a0", first[other], "a0")
            clicks = [e for e in es if e["callback"] == "onClick"]
            for click in clicks[1:]:
                pair("R-click-same-A-instance", clicks[0], "a0", click, "a0")
            new_intents = [e for e in es if e["callback"] == "onNewIntent"]
            if new_intents:
                for result in [e for e in es if e["callback"] == "onActivityResult"]:
                    pair("R-distinct-intent-mechanisms", new_intents[0], "a0", result, "a0")
        else:
            state_slots = (("onCreate", "a0"), ("onCreateView", "a2"), ("onViewCreated", "a1"),
                           ("onActivityCreated", "a0"), ("onViewStateRestored", "a0"))
            present = [(first[name], slot) for name, slot in state_slots if name in first]
            for (a, sa), (b, sb) in itertools.combinations(present, 2):
                pair("R-stateF", a, sa, b, sb)
            if "onViewCreated" in first:
                for click in [e for e in es if e["callback"] == "viewClick"]:
                    pair("R-view-created-to-click", first["onViewCreated"], "a0", click, "a0")

    pending_save = {}
    for e in events:
        if e["class"] != "A":
            continue
        key = process_scope(e)
        if e["callback"] == "onSaveInstanceState":
            pending_save[key] = e
        elif e["callback"] == "onCreate" and key in pending_save:
            pair("R-savedA-same-process", pending_save.pop(key), "a0", e, "a0")

    for es in by_process.values():
        acts = [e for e in es if e["class"] in ("A", "Second")]
        host_ids = {}
        for e in es:
            if e["class"] in ("A", "Second") or e["callback"] not in ("onAttach", "onAttachContext"):
                continue
            arg = identity(e["args"].get("a0"))
            # A checkpoint can follow Fragment.onAttach because super.onCreate already
            # dispatches Fragment callbacks; matching all recorded receivers avoids
            # accidentally assigning the previous Activity instance during rotation.
            candidates = [a for a in acts if arg is not None and a["receiver_identity_token"] == arg]
            if candidates:
                host = min(candidates, key=lambda a: abs(a["line_no"] - e["line_no"]))
                pair("R-host-recorded-receiver", e, "a0", host, "this")
                host_ids[receiver_scope(e)] = arg
            else:
                skipped["R-host:host_receiver_unobserved_or_nonmatching"] += 1
        for e in es:
            if e["class"] in ("A", "Second") or e["callback"] != "onCreate":
                continue
            host_id = host_ids.get(receiver_scope(e))
            creates = [a for a in acts if a["callback"] == "onCreate" and a["receiver_identity_token"] == host_id]
            if creates:
                host = min(creates, key=lambda a: abs(a["line_no"] - e["line_no"]))
                pair("R-stateF-vs-host-stateA", host, "a0", e, "a0")
            else:
                skipped["R-stateF-vs-host-stateA:host_creation_unobserved"] += 1
    return pairs, dict(skipped)


def checkpoint_edges(events):
    grouped = defaultdict(list)
    for event in events:
        if event["callback"] in LIFECYCLE:
            grouped[process_scope(event)].append(event)
    edges = []
    for sequence in grouped.values():
        for a, b in zip(sequence, sequence[1:]):
            edges.append({"case": a["case"], "source": a["source"], "pid": a["pid"],
                          "process_generation": a["process_generation"], "from": a["label"], "to": b["label"],
                          "from_line": a["line_no"], "to_line": b["line_no"], "step": b["step"],
                          "basis": "consecutive recorded lifecycle checkpoints in one process generation; not callback returns"})
    return edges, list(grouped.values())


def transaction_observations(events, sinks):
    # These labels come from cases.py source snippets; traces contain no TX begin/
    # return marker or callback exit, so causal synchrony is deliberately unmeasured.
    scenarios = {"c1": ("commitNow", "A.onCreate", "F"), "c2": ("commit", "A.onCreate", "F"),
                 "c3": ("commitNow", "A.onClick", "G"), "c4": ("commit", "A.onClick", "G"),
                 "c5": ("commit+executePendingTransactions", "A.onCreate", "F"),
                 "c6": ("commit", "A.onClick", "G")}
    rows = []
    for sink in sinks:
        if sink["case"] not in scenarios:
            continue
        api, trigger_label, target = scenarios[sink["case"]]
        preceding = [e for e in events if e["source"] == sink["source"] and e["pid"] == sink["pid"] and e["line_no"] < sink["line_no"]]
        triggers = [e for e in preceding if e["event"] == trigger_label]
        if not triggers:
            continue
        trigger = triggers[-1]
        between = [e["event"] for e in preceding if e["line_no"] > trigger["line_no"]
                   and e["process_generation"] == trigger["process_generation"] and e["class"] == target]
        rows.append({"case": sink["case"], "source": sink["source"], "transaction_api_from_case_source": api,
                     "trigger_checkpoint": trigger_label, "trigger_line": trigger["line_no"], "sink_line": sink["line_no"],
                     "observed_callbacks_before_sink": between, "sink_tainted": sink["tainted"],
                     "transaction_return_observed": False, "callback_exit_observed": False,
                     "causal_synchrony": None, "basis": "source-labeled observed checkpoint ordering, not transaction causality"})
    return rows


class SourcedNfa:
    """External automaton only; never construct a model from the scored traces."""
    def __init__(self, path, kind):
        self.path = Path(path).resolve()
        self.model = json.loads(self.path.read_text(encoding="utf-8"))
        m = self.model
        if m.get("schema") != "trace-nfa-v1" or m.get("kind") != kind:
            raise ValueError("NFA schema/kind mismatch")
        if not m.get("source_artifacts") or not m.get("label_basis") or m.get("trace_semantics") not in ("prefix", "complete"):
            raise ValueError("NFA requires source hashes, checkpoint label basis and trace semantics")
        for artifact in m["source_artifacts"]:
            src = (self.path.parent / artifact["path"]).resolve()
            if sha256(src) != artifact["sha256"]:
                raise ValueError("NFA provenance source hash mismatch")
        self.edges = defaultdict(list)
        states = set(m["states"])
        self.initial, self.accepting = set(m["initial_states"]), set(m["accepting_states"])
        if not self.initial or not self.accepting or not (self.initial | self.accepting).issubset(states):
            raise ValueError("invalid NFA states")
        for edge in m["transitions"]:
            if edge["from"] not in states or edge["to"] not in states:
                raise ValueError("NFA edge state missing")
            self.edges[edge["from"]].append((edge.get("label"), edge["to"]))
        self.projection = set(m["projection_labels"]) if m.get("projection_labels") else None

    def closure(self, states):
        found, todo = set(states), list(states)
        while todo:
            for label, dest in self.edges[todo.pop()]:
                if label is None and dest not in found:
                    found.add(dest)
                    todo.append(dest)
        return found

    def advance(self, states, label):
        return self.closure({dest for state in self.closure(states) for event, dest in self.edges[state] if event == label})

    def accepts(self, labels):
        states = self.closure(self.initial)
        for label in labels:
            states = self.advance(states, label)
            if not states:
                return False
        if self.model["trace_semantics"] == "complete":
            return bool(states & self.accepting)
        # Prefix must extend to some accepting state; a dead state is not enough.
        reachable, todo = set(states), list(states)
        while todo:
            state = todo.pop()
            if state in self.accepting:
                return True
            for _, dest in self.edges[state]:
                if dest not in reachable:
                    reachable.add(dest)
                    todo.append(dest)
        return False

    def legal_pair(self, a, b):
        reachable, todo = set(self.initial), list(self.initial)
        while todo:
            for _, dest in self.edges[todo.pop()]:
                if dest not in reachable:
                    reachable.add(dest)
                    todo.append(dest)
        return bool(self.advance(self.advance(reachable, a), b))


def model_metrics(model, sequences):
    if model is None:
        return {"trace_acceptance_rate": None, "edge_legal_rate": None,
                "missing_reason": "no independent sourced checkpoint automaton provided; edge tables alone cannot establish full trace acceptance"}
    accepted, traces, legal, count, excluded = 0, 0, 0, 0, 0
    for sequence in sequences:
        labels = [e["label"] for e in sequence]
        projected = [v for v in labels if model.projection is None or v in model.projection]
        excluded += len(labels) - len(projected)
        if not projected:
            continue
        traces += 1
        accepted += model.accepts(projected)
        for a, b in zip(projected, projected[1:]):
            count += 1
            legal += model.legal_pair(a, b)
    constraints = model.model.get("constraints_modelled") is True
    return {"model_path": str(model.path), "model_sha256": sha256(model.path), "trace_semantics": model.model["trace_semantics"],
            "label_basis": model.model["label_basis"], "projected_out_events": excluded, "trace_count": traces,
            "accepted_traces": accepted, "edge_count": count, "legal_edges": legal,
            "syntactic_trace_acceptance_rate": accepted / traces if traces else None,
            "syntactic_edge_legal_rate": legal / count if count else None,
            "trace_acceptance_rate": accepted / traces if traces and constraints else None,
            "edge_legal_rate": legal / count if count and constraints else None,
            "missing_reason": None if constraints else "model does not assert encoded predicate/framework constraints; only syntactic metrics are available"}


def jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def analyze(run_dir, out_dir, *, legacy=False, case_ids=None, dmm_model=None, spec_model=None):
    run_dir, out_dir = Path(run_dir).resolve(), Path(out_dir).resolve()
    if out_dir == run_dir or out_dir.is_relative_to(run_dir):
        raise ValueError("analysis output must be separate from immutable experiment output")
    if not legacy:
        from check_dynamic_complete import evaluate
        report = evaluate(run_dir)
        if not report["complete"]:
            raise ValueError("dynamic run is not complete; analysis cannot establish missing evidence")
    events, sinks, warnings, inputs = [], [], [], []
    paths = sorted(run_dir.glob("*.log"))
    if case_ids:
        paths = [p for p in paths if p.stem in set(case_ids)]
    for path in paths:
        if not re.fullmatch(r"[abcdep]\d+", path.stem):
            continue
        inputs.append({"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size})
        e, s, w = parse_lines(path.read_text(encoding="utf-8", errors="replace").splitlines(), path.stem, str(path))
        events.extend(e)
        sinks.extend(s)
        warnings.extend({"case": path.stem, "source": str(path), **v} for v in w)
    if not inputs:
        raise ValueError("no requested case logs found")
    pairs, skipped = alias_pairs(events)
    edges, sequences = checkpoint_edges(events)
    tx = transaction_observations(events, sinks)
    alias_counts = Counter((r["rule"], r["relation"]) for r in pairs)
    summary = {"schema": "fragbench-trace-evidence-v1", "inputs": inputs, "legacy_input": legacy,
               "external_metrics_for_legacy_runs": None if legacy else "per-case resource artifacts retained by dynamic runner",
               "legacy_metrics_missing_reason": "old dynamic runs have no new external resource measurements; separately monitoring this analyzer does not measure those past runs" if legacy else None,
               "formal_slot_mapping": {"A.onActivityResult.trace_a0": "formal parameter index 2, Intent data; primitive request/result parameters are unlogged"},
               "event_count": len(events), "case_count": len(inputs), "inferred_process_generations": len({process_scope(e) for e in events}),
               "alias_counts": [{"rule": rule, "relation": relation, "count": count} for (rule, relation), count in sorted(alias_counts.items())],
               "alias_skips": skipped, "checkpoint_edge_count": len(edges), "transaction_observation_count": len(tx),
               "dmm": model_metrics(dmm_model, sequences), "specification": model_metrics(spec_model, sequences),
               "limitations": ["existing T.tag uses identityHashCode, not a collision-free ID; comparisons do not cross process generations",
                               "receiver cycles separate re-creation; inferred generations use PID and sequence regression, not an explicit process-start nonce",
                               "after-super checkpoints cannot directly measure callback entry/return or transaction completion",
                               "R-host matches recorded receiver identity component within one generation; no missing receiver is counted as different",
                               "onCreateView return value and transactional begin/return are not currently logged"],
               "warnings": warnings}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("events", events), ("alias_pairs", pairs), ("edges", edges), ("transaction_observations", tx)):
        jsonl(out_dir / (name + ".jsonl"), rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--legacy", action="store_true", help="explicitly allow old logs without new completion/resources, marking legacy missingness")
    p.add_argument("--cases", nargs="+")
    p.add_argument("--dmm-model", type=Path)
    p.add_argument("--spec-model", type=Path)
    args = p.parse_args()
    dmm = SourcedNfa(args.dmm_model, "generated_dmm") if args.dmm_model else None
    spec = SourcedNfa(args.spec_model, "framework_specification") if args.spec_model else None
    summary = analyze(args.run_dir, args.out_dir, legacy=args.legacy, case_ids=args.cases, dmm_model=dmm, spec_model=spec)
    print(json.dumps({k: summary[k] for k in ("event_count", "case_count", "alias_counts", "alias_skips", "dmm", "specification")}, indent=2))


if __name__ == "__main__":
    main()
