#!/usr/bin/env bash
# RQ3 "Ours" column: run the real DMMPP downstream analyzer (Androlic /
# jymbolic SymbolicEngine) on each app, baseline (full params) vs ours
# (de-bloated). Same engine + same path bounds; only the dummy-main parameter
# count differs. Runs entirely under an ASCII path (the jar mis-reads CJK paths).
set -u
J8="/c/Program Files/Java/jdk1.8.0_121"
CPWIN='C:\pdmm_work\androlic.jar;C:\pdmm_work\build'
OUTWIN='C:\pdmm_work\results\rq3_androlic.csv'
OUT='/c/pdmm_work/results/rq3_androlic.csv'
LOG='/c/pdmm_work/results/androlic.log'
CFGDIR='/c/pdmm_work/cfg'
rm -f "$OUT" "$LOG"

write_cfg() {  # $1 = cfg basename, $2 = apk name
  {
    echo 'androidPath C:\pdmm_work\platforms'
    echo 'apkBasePath C:\pdmm_work\apks'
    echo "apkName $2"
    echo 'outputBasePath C:\pdmm_work\out'
    echo 'javaHome C:\Program Files\Java\jdk1.8.0_121'
    echo 'maxRunningTime 100000'
    echo 'maxPathNumber 500'
    echo 'maxPathLength 10000'
    echo 'maxContextDepth 4'
    echo 'maxRecursiveInvocationLevel 3'
    echo 'maxLoopUnrollNumber 2'
    echo 'debugMode 0'
    echo 'isJimpleOutput 0'
    echo 'entryMethod DMMPP'
  } > "$CFGDIR/$1.txt"
}

run() {  # $1 = mode, $2 = cfg basename, $3 = label
  local cfgwin="C:\\pdmm_work\\cfg\\$2.txt"
  timeout 360 "$J8/bin/java.exe" -Xmx12g -cp "$CPWIN" cn.ac.ios.pdmm.AndrolicRQ3 \
      "$1" "$cfgwin" "$OUTWIN" "$3" >>"$LOG" 2>&1
  if [ $? -eq 124 ]; then echo "$3,$1,-1,-1,-1,360.00,0.0" >> "$OUT"; fi
}

APPS="com.uberspot.a2048_25.apk com.tuyafeng.watt.apk net.gitsaibot.af.apk
jp.takke.cpustats.apk com.mobile.bummerzaehler.apk com.gimranov.zandy.app.apk
ch.bailu.aat.apk com.asdoi.quicktiles.apk it.discorsionline.discorsi.apk
kr.ieodo.apk"

i=0
for name in $APPS; do
  [ -f "/c/pdmm_work/apks/$name" ] || { echo "MISSING $name" >>"$LOG"; continue; }
  label=$(basename "$name" .apk)
  i=$((i+1)); cfg="c$i"
  write_cfg "$cfg" "$name"
  echo ">>> $label baseline"
  run baseline "$cfg" "$label"
  echo ">>> $label ours"
  run ours "$cfg" "$label"
done
echo "DONE rows: $(($(wc -l < "$OUT") - 1))"
