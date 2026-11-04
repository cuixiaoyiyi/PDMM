#!/usr/bin/env python3
"""Turns the FragBench traces of one emulator run into
  (1) the observed transition relation between lifecycle events (the dynamic oracle for E2),
  (2) argument-identity facts for the parameter-merging rules (E1),
  (3) the verdict table.
Usage: analyze_dyn.py <api>
Reads  C:\\pdmm_work2\\fragbench\\dyn\\api<api>\\*.log ; writes results/fragbench_dyn_api<api>_*.csv
"""
import csv
import os
import re
import sys
from collections import Counter, defaultdict

W = r"C:\pdmm_work2\fragbench\dyn"
RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

TRACE = re.compile(r"D/FBTRACE\s*\(\s*(\d+)\): (\w+) (\d+) (\S+) this=(\S+)((?: a\d+=\S+)*) t=(\d+)")
STEP = re.compile(r"I/FBSTEP\s*\(\s*\d+\): (.*)")

LIFECYCLE = {"onCreate", "onStart", "onRestoreInstanceState", "onPostCreate", "onResume", "onPostResume", "onPause",
             "onSaveInstanceState", "onStop", "onRestart", "onDestroy", "onNewIntent", "onActivityResult",
             "onAttachFragment", "onAttach", "onAttachContext", "onCreateView", "onViewCreated", "onActivityCreated",
             "onViewStateRestored", "onDestroyView", "onDetach"}


def parse(path):
    events = []
    step = "start"
    for line in open(path, encoding="utf-8", errors="replace"):
        m = STEP.search(line)
        if m:
            step = m.group(1).strip()
            continue
        m = TRACE.search(line)
        if not m:
            continue
        pid, cid, seq, ev, this, args, tid = m.groups()
        argd = {}
        for a in args.split():
            k, v = a.split("=", 1)
            argd[k] = v
        cls, name = ev.split(".", 1)
        events.append(dict(pid=pid, seq=int(seq), cls=cls, name=name, this=this, args=argd, step=step, tid=tid))
    return events


def label(e):
    kind = "ACT" if e["cls"] in ("A", "Second") else "FRAG"
    return kind + "." + e["name"]


def main():
    api = sys.argv[1]
    d = os.path.join(W, "api" + api)
    os.makedirs(RES, exist_ok=True)
    trans = Counter()
    trans_apps = defaultdict(set)
    alias = Counter()
    per_app = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".log"):
            continue
        cid = f[:-4]
        ev = parse(os.path.join(d, f))
        per_app[cid] = ev
        # (1) transitions: consecutive events within one process, lifecycle events only
        # (clicks and other callbacks are kept as their own labels)
        prev = None
        for e in ev:
            if prev is not None and prev["pid"] == e["pid"]:
                key = (label(prev), label(e))
                trans[key] += 1
                trans_apps[key].add(cid)
            prev = e
        # (2) argument identity
        by_instance = defaultdict(list)
        for e in ev:
            by_instance[(e["pid"], e["this"])].append(e)
        # activity: onCreate / onRestoreInstanceState / onPostCreate bundles of one instance
        for (pid, inst), es in by_instance.items():
            first = {}
            for e in es:
                if e["cls"] != "A":
                    continue
                if e["name"] in ("onCreate", "onRestoreInstanceState", "onPostCreate") and e["name"] not in first:
                    first[e["name"]] = e["args"].get("a0")
            for a, b in (("onCreate", "onRestoreInstanceState"), ("onCreate", "onPostCreate")):
                if a in first and b in first and first[a] != "null" and first[b] != "null":
                    alias[("A." + a + ".a0", "A." + b + ".a0", "same" if first[a] == first[b] else "different")] += 1
            # fragment: onCreate / onViewCreated(a1) / onActivityCreated / onViewStateRestored bundles
            if es and es[0]["cls"] in ("F", "G", "C"):
                fb = {}
                for e in es:
                    a = e["args"].get("a1") if e["name"] == "onViewCreated" else e["args"].get("a0")
                    if e["name"] in ("onCreate", "onViewCreated", "onActivityCreated", "onViewStateRestored") and e["name"] not in fb:
                        fb[e["name"]] = a
                for b in ("onViewCreated", "onActivityCreated", "onViewStateRestored"):
                    if "onCreate" in fb and b in fb and fb["onCreate"] != "null" and fb[b] != "null":
                        alias[("F.onCreate.a0", "F." + b + ".a0", "same" if fb["onCreate"] == fb[b] else "different")] += 1
        # activity onSaveInstanceState -> next activity instance onCreate (same process)
        saved = None
        for e in ev:
            if e["cls"] == "A" and e["name"] == "onSaveInstanceState":
                saved = (e["pid"], e["args"].get("a0"))
            elif e["cls"] == "A" and e["name"] == "onCreate" and saved is not None:
                b = e["args"].get("a0")
                if b != "null":
                    same_proc = saved[0] == e["pid"]
                    alias[("A.onSaveInstanceState.a0", "A.onCreate(next instance).a0",
                           ("same" if saved[1] == b else "different") + (" (same process)" if same_proc else " (after process kill)"))] += 1
                saved = None
        # activity bundle vs fragment bundle in the same re-creation
        act_b = None
        for e in ev:
            if e["cls"] == "A" and e["name"] == "onCreate" and e["args"].get("a0") != "null":
                act_b = (e["pid"], e["args"]["a0"])
            if e["cls"] in ("F", "G", "C") and e["name"] == "onCreate" and e["args"].get("a0") != "null" and act_b and act_b[0] == e["pid"]:
                alias[("A.onCreate.a0", "F.onCreate.a0", "same" if act_b[1] == e["args"]["a0"] else "different")] += 1
        # fragment onSaveInstanceState -> next fragment onCreate
        fsaved = None
        for e in ev:
            if e["cls"] in ("F", "G", "C") and e["name"] == "onSaveInstanceState":
                fsaved = (e["pid"], e["args"].get("a0"))
            elif e["cls"] in ("F", "G", "C") and e["name"] == "onCreate" and fsaved and e["args"].get("a0") != "null":
                alias[("F.onSaveInstanceState.a0", "F.onCreate(next instance).a0",
                       ("same" if fsaved[1] == e["args"]["a0"] else "different") + (" (same process)" if fsaved[0] == e["pid"] else " (after process kill)"))] += 1
                fsaved = None
        # onAttach argument is the host activity
        hosts = set(e["this"] for e in ev if e["cls"] == "A")
        for e in ev:
            if e["cls"] in ("F", "G", "C") and e["name"] in ("onAttach", "onAttachContext"):
                alias[("F." + e["name"] + ".a0", "host activity", "same" if e["args"].get("a0") in hosts else "different")] += 1
        # onViewCreated view is the fragment's button (the one its click listener reports)
        views = defaultdict(set)
        for e in ev:
            if e["cls"] in ("F", "G", "C") and e["name"] == "viewClick":
                views[e["this"]].add(e["args"].get("a0"))
        for e in ev:
            if e["cls"] in ("F", "G", "C") and e["name"] == "onViewCreated" and views.get(e["this"]):
                alias[("F.onViewCreated.a0", "view of the fragment's click listener", "same" if e["args"].get("a0") in views[e["this"]] else "different")] += 1
        # onClick view is the button of the activity (same object across clicks)
        clicks = [e["args"].get("a0") for e in ev if e["cls"] == "A" and e["name"] == "onClick"]
        if len(clicks) > 1:
            alias[("A.onClick.a0 (1st)", "A.onClick.a0 (later, same instance)", "same" if len(set(clicks)) == 1 else "different")] += 1

    with open(os.path.join(RES, "fragbench_dyn_api%s_transitions.csv" % api), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["from", "to", "count", "apps"])
        for (a, b), n in sorted(trans.items(), key=lambda kv: -kv[1]):
            w.writerow([a, b, n, len(trans_apps[(a, b)])])
    with open(os.path.join(RES, "fragbench_dyn_api%s_alias.csv" % api), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["a", "b", "relation", "observations"])
        for (a, b, r), n in sorted(alias.items()):
            w.writerow([a, b, r, n])
    print("apps:", len(per_app), " transitions:", len(trans), " total events:", sum(len(v) for v in per_app.values()))
    print("\nlifecycle transitions between activity and fragment events (top 40 by count):")
    for (a, b), n in sorted(trans.items(), key=lambda kv: -kv[1])[:40]:
        print("   %-28s -> %-28s %5d  apps=%d" % (a, b, n, len(trans_apps[(a, b)])))
    print("\nargument identity:")
    for (a, b, r), n in sorted(alias.items()):
        print("   %-34s vs %-40s %-30s %d" % (a, b, r, n))


if __name__ == "__main__":
    main()
