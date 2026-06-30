#!/usr/bin/env bash
# RQ3: run the real FlowDroid taint engine over DroidBench (baseline downstream
# cost + detected leaks). cwd-relative paths only (native java.exe).
set -u
cd "$(dirname "$0")" || exit 1
J8="/c/Program Files/Java/jdk1.8.0_121"
PLAT="datasets/android-platforms-min"
CP="pdmm/lib_DMMPP.jar;pdmm/build"
SS="rq3/SourcesAndSinks.txt"
OUT="results/rq3_flowdroid.csv"
LOG="results/rq3.log"
rm -f "$OUT" "$LOG"

run() {
  local apk="$1" label="$2"
  [ -f "$apk" ] || { echo "MISSING $apk" >>"$LOG"; return; }
  timeout 180 "$J8/bin/java.exe" -Xmx8g -cp "$CP" cn.ac.ios.pdmm.TaintRunner \
      "$PLAT" "$apk" "$SS" "$OUT" "$label" >>"$LOG" 2>&1
  local rc=$?
  if [ $rc -eq 124 ]; then echo "$label,-1,180.00,0.0,TIMEOUT" >> "$OUT"; echo "TIMEOUT $label" >>"$LOG"; fi
}

# Focus on the lifecycle-/callback-/dataflow-bearing categories most relevant to
# this paper; these are the apps with deterministic ground-truth leaks.
CATS="Lifecycle Callbacks Aliasing FieldAndObjectSensitivity AndroidSpecific GeneralJava ImplicitFlows InterComponentCommunication"
for cat in $CATS; do
  for apk in datasets/DroidBench/apk/$cat/*.apk; do
    [ -f "$apk" ] || continue
    run "$apk" "${cat}_$(basename "$apk" .apk)"
  done
done
echo "DONE rq3 rows: $(($(wc -l < "$OUT") - 1))"
