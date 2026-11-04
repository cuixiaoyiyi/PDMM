"""Generate isolated measured exporter copies and compile only new build dirs.

Original Java sources, build8/build17, E5 outputs and active runners are untouched.
The transformation preserves the original generation timer and CSV statements.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from resource_monitor import run_command
from run_static import atomic_json, sha256

def transform(source, kind):
    original = "DumpGen8" if kind == "gen8" else "DumpFlowDroidDMM"
    measured = original + "Measured"
    text = re.sub(r"\b" + original + r"\b", measured, source)
    timer = "long t0 = System.nanoTime();"
    ending = "double secs = (System.nanoTime() - t0) / 1e9;"
    exit_line = "System.exit(0);"
    for marker in (timer, ending, exit_line):
        if text.count(marker) != 1:
            raise ValueError("original exporter layout changed: " + marker)
    text = text.replace(timer, "rev.measure.ExportGcProbe probe = rev.measure.ExportGcProbe.start();\n        " + timer + "\n        probe.generationStarted();")
    text = text.replace(ending, ending + "\n        probe.generationEnded(secs);")
    metric_name = 'label + "." + cfg + ".gc.metrics.json"' if kind == "gen8" else 'label + ".gc.metrics.json"'
    complete = '"OK".equals(status) && failed == 0' if kind == "gen8" else '"OK".equals(status)'
    text = text.replace(exit_line, "probe.finish(new File(outDir, " + metric_name + "), status, " + complete + ");\n        " + exit_line)
    return text

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-root", default=r"C:\pdmm_work2")
    p.add_argument("--tag", default="20261008")
    args = p.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", args.tag):
        raise ValueError("invalid build tag")
    work = Path(args.work_root).resolve()
    source_dir = HERE / "work" / ("export_probe_sources_" + args.tag)
    record_dir = HERE / "work" / ("export_probe_build_" + args.tag)
    record_dir.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": 1, "tag": args.tag, "builds": {}, "original_timer_preserved": True,
               "original_sources_unchanged": True, "legacy_builds_not_modified": True}
    common = [HERE / "instrumentation/rev/measure/ExportGcProbe.java", HERE / "instrumentation/rev/measure/ProbeSmoke.java"]
    for kind, version, package, basename in (("gen8", "8", "rev8", "DumpGen8"), ("fd", "17", "rev", "DumpFlowDroidDMM")):
        original = HERE / "src" / package / (basename + ".java")
        prior_hash = sha256(original)
        measured = source_dir / package / (basename + "Measured.java")
        measured.parent.mkdir(parents=True, exist_ok=True)
        measured.write_text(transform(original.read_text(encoding="utf-8"), kind), encoding="utf-8", newline="\n")
        build = (work / ("build_export_probe" + version + "_" + args.tag)).resolve()
        if not build.is_relative_to(work) or build in {work / "build8", work / "build17"}:
            raise ValueError("new build directory escaped controlled work root")
        build.mkdir(parents=True, exist_ok=True)
        jdk = Path(r"C:\Program Files\Java\jdk1.8.0_121" if version == "8" else r"C:\Program Files\Java\jdk-17.0.1")
        cp = str(work / ("build8" if version == "8" else "build17")) + ";" + str(work / ("lib/DMMPP.jar" if version == "8" else "lib/flowdroid-2.15.1.jar"))
        command = [str(jdk / "bin/javac.exe"), "-J-Xmx256m", "-encoding", "UTF-8", "-cp", cp, "-d", str(build)] + [str(path) for path in common + [measured]]
        resource = run_command(command, cwd=str(HERE), log_path=str(record_dir / (kind + ".compile.log")),
            record_path=str(record_dir / (kind + ".compile.resource.json")), timeout_s=120,
            metadata={"kind": "infrastructure_compilation", "dataset": "none; no APK experiment", "generation_exporter": kind}, sample_interval_s=.25)
        if sha256(original) != prior_hash:
            raise ValueError("original source changed during isolated compilation")
        if resource["status"] != "ok":
            raise RuntimeError("isolated compile failed: " + str(record_dir / (kind + ".compile.log")))
        summary["builds"][kind] = {"path": str(build), "java": str(jdk / "bin/java.exe"),
            "main_class": package + "." + basename + "Measured", "original_source": str(original), "original_sha256": prior_hash,
            "generated_source": str(measured), "generated_sha256": sha256(measured),
            "classes": [{"path": str(path), "sha256": sha256(path), "size": path.stat().st_size} for path in sorted(build.rglob("*.class"))],
            "compile_resource": str(record_dir / (kind + ".compile.resource.json"))}
    atomic_json(record_dir / "manifest.json", summary)
    print(json.dumps({kind: row["path"] for kind, row in summary["builds"].items()}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
