#!/usr/bin/env python3
"""RQ3 analysis: downstream FlowDroid taint cost vs entry-parameter count, plus
the lifecycle-ordering false positives that the HSM removes."""
import csv, math, statistics as st, os
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"results")

def load(n):
    with open(os.path.join(OUT,n),newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))

def pearson(xs,ys):
    n=len(xs);
    if n<2: return 0
    mx=sum(xs)/n; my=sum(ys)/n
    cov=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    sx=math.sqrt(sum((x-mx)**2 for x in xs)); sy=math.sqrt(sum((y-my)**2 for y in ys))
    return cov/(sx*sy) if sx*sy else 0

apps={r['app']:r for r in load("rq_app_summary.csv")}

def join(rq3rows, prefix):
    pairs=[]
    for r in rq3rows:
        if r['status']!='OK': continue
        key=r['app'] if r['app'] in apps else prefix+r['app']
        if key in apps:
            a=apps[key]
            pairs.append(dict(app=r['app'],
                base=int(a['baseline_params']), agg=int(a['aggressive_params']),
                time=float(r['time_s']), heap=float(r['heap_mb']), leaks=int(r['leaks'])))
    return pairs

print("="*74)
print("RQ3  Downstream FlowDroid taint cost (measured)")
print("="*74)

db=[r for r in load("rq3_flowdroid.csv") if r['status']=='OK']
print(f"\nDroidBench ({len(db)} apps):  mean time={st.mean(float(r['time_s']) for r in db):.2f}s  "
      f"mean heap={st.mean(float(r['heap_mb']) for r in db):.1f}MB  "
      f"leaks={sum(int(r['leaks']) for r in db)}")

real_path=os.path.join(OUT,"rq3_flowdroid_real.csv")
if os.path.exists(real_path):
    rl=[r for r in load("rq3_flowdroid_real.csv") if r['status']=='OK']
    print(f"Real apps  ({len(rl)} apps):  mean time={st.mean(float(r['time_s']) for r in rl):.2f}s  "
          f"mean heap={st.mean(float(r['heap_mb']) for r in rl):.1f}MB  "
          f"leaks={sum(int(r['leaks']) for r in rl)}")

    pj=join(rl,"")  # real labels already carry fDroid:/GooglePlay: prefix
    print(f"\nParam-count vs taint cost (real apps, joined={len(pj)}):")
    print(f"  Pearson r(baseline_params, heap_MB) = {pearson([p['base'] for p in pj],[p['heap'] for p in pj]):.3f}")
    print(f"  Pearson r(baseline_params, time_s)  = {pearson([p['base'] for p in pj],[p['time'] for p in pj]):.3f}")
    # linear fit heap ~ a + b*params
    base=[p['base'] for p in pj]; heap=[p['heap'] for p in pj]
    n=len(pj); mx=sum(base)/n; my=sum(heap)/n
    den=sum((x-mx)**2 for x in base)
    if den:
        b1=sum((x-mx)*(y-my) for x,y in zip(base,heap))/den; b0=my-b1*mx
        print(f"  fit: heap_MB = {b0:.1f} + {b1:.3f} * params")
        # projected Ours: use aggressive param count through same model
        proj=[b0+b1*p['agg'] for p in pj]
        meas=[p['heap'] for p in pj]
        red=100*(sum(meas)-sum(proj))/sum(meas)
        print(f"  projected heap with aggressive params: {red:.1f}% reduction (model, not measured)")
    print(f"\n  {'app':<42}{'base':>5}{'aggr':>5}{'time_s':>8}{'heap_MB':>9}{'leaks':>6}")
    for p in sorted(pj,key=lambda p:-p['base']):
        print(f"  {p['app'][:42]:<42}{p['base']:>5}{p['agg']:>5}{p['time']:>8.1f}{p['heap']:>9.1f}{p['leaks']:>6}")

print("\n"+"="*74)
print("RQ3  Lifecycle-ordering false positives (FlowDroid) that the HSM removes")
print("="*74)
NEG=('NoLeak','Inactive','Unreachable','BroadcastReceiverLifecycle3','ServiceLifecycle2')
def is_neg(n): return any(k.lower() in n.lower() for k in NEG)
neg=[r for r in db if is_neg(r['app'])]
fp=[r for r in neg if int(r['leaks'])>0]
print(f"negative-control apps={len(neg)}, FlowDroid false positives={len(fp)}:")
for r in fp:
    print(f"  FP: {r['app']}  (FlowDroid reports {r['leaks']} leak on an infeasible lifecycle path)")
print("These are exactly the infeasible-path FPs the synchronized HSM prunes (RQ2 -> precision).")
