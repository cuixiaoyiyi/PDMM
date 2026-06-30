#!/usr/bin/env bash
# RQ3 on the 20 real-world apps (F-Droid + Google Play): bigger entry sets ->
# real dynamic range to expose the param-count -> taint-cost relationship.
set -u
cd "$(dirname "$0")" || exit 1
J8="/c/Program Files/Java/jdk1.8.0_121"
PLAT="datasets/android-platforms-min"
CP="pdmm/lib_DMMPP.jar;pdmm/build"
SS="rq3/SourcesAndSinks.txt"
OUT="results/rq3_flowdroid_real.csv"
LOG="results/rq3_real.log"
rm -f "$OUT" "$LOG"

run() {
  local apk="$1" label="$2"
  [ -f "$apk" ] || { echo "MISSING $apk" >>"$LOG"; return; }
  timeout 900 "$J8/bin/java.exe" -Xmx12g -cp "$CP" cn.ac.ios.pdmm.TaintRunner \
      "$PLAT" "$apk" "$SS" "$OUT" "$label" >>"$LOG" 2>&1
  local rc=$?
  if [ $rc -eq 124 ]; then echo "$label,-1,900.00,0.0,TIMEOUT" >> "$OUT"; echo "TIMEOUT $label" >>"$LOG"; fi
}

for apk in DMMPP/apks/f-Droid/*.apk; do
  run "$apk" "fDroid:$(basename "$apk" .apk)"
done
for apk in DMMPP/apks/GooglePlay/*.apk; do
  run "$apk" "GooglePlay:$(basename "$apk" .apk)"
done
echo "DONE rq3_real rows: $(($(wc -l < "$OUT") - 1))"
