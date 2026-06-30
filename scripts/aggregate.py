#!/usr/bin/env python3
"""Aggregate raw PDMM metric CSVs into RQ1/RQ2 summary tables."""
import csv, statistics as st, sys, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

def load(name):
    p = os.path.join(OUT, name)
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def dataset_of(app):
    return app.split(':', 1)[0] if ':' in app else 'other'

def fnum(x):
    try: return float(x)
    except: return 0.0

def main():
    apps = load("rq_app_summary.csv")
    comps = load("rq1_components.csv")
    print(f"apps={len(apps)}  components={len(comps)}\n")

    # group apps by dataset
    groups = {}
    for r in apps:
        groups.setdefault(dataset_of(r['app']), []).append(r)

    print("="*78)
    print("RQ1  Parameter de-bloat (per-dataset, app-level totals)")
    print("="*78)
    print(f"{'dataset':<12}{'#apps':>6}{'base':>9}{'cons':>9}{'aggr':>9}{'PRR_con%':>10}{'PRR_agg%':>10}")
    allbase=allcon=allagg=0
    for ds, rs in sorted(groups.items()):
        b=sum(int(r['baseline_params']) for r in rs)
        c=sum(int(r['conservative_params']) for r in rs)
        a=sum(int(r['aggressive_params']) for r in rs)
        allbase+=b; allcon+=c; allagg+=a
        prc = 100*(b-c)/b if b else 0
        pra = 100*(b-a)/b if b else 0
        print(f"{ds:<12}{len(rs):>6}{b:>9}{c:>9}{a:>9}{prc:>10.1f}{pra:>10.1f}")
    prc = 100*(allbase-allcon)/allbase if allbase else 0
    pra = 100*(allbase-allagg)/allbase if allbase else 0
    print(f"{'ALL':<12}{len(apps):>6}{allbase:>9}{allcon:>9}{allagg:>9}{prc:>10.1f}{pra:>10.1f}")

    # mean of per-app PRR (matches paper "average reduction")
    pr_con = [fnum(r['prr_conservative']) for r in apps if int(r['baseline_params'])>0]
    pr_agg = [fnum(r['prr_aggressive']) for r in apps if int(r['baseline_params'])>0]
    print(f"\nmean per-app PRR  conservative={st.mean(pr_con):.1f}%  aggressive={st.mean(pr_agg):.1f}%")

    # largest real apps table (top by baseline params)
    real = [r for r in apps if dataset_of(r['app']) in ('fDroid','GooglePlay')]
    real.sort(key=lambda r:-int(r['baseline_params']))
    print("\n--- Largest real-world apps (RQ1 Table II style) ---")
    print(f"{'app':<42}{'base':>7}{'cons':>7}{'aggr':>7}{'PRRcon':>8}{'PRRagg':>8}")
    for r in real[:15]:
        b=int(r['baseline_params']); c=int(r['conservative_params']); a=int(r['aggressive_params'])
        print(f"{r['app'][:42]:<42}{b:>7}{c:>7}{a:>7}{(100*(b-c)/b if b else 0):>7.1f}%{(100*(b-a)/b if b else 0):>7.1f}%")

    print("\n"+"="*78)
    print("RQ2  Lifecycle Consistency Score (edge-weighted mean per dataset)")
    print("="*78)
    print(f"{'dataset':<12}{'#apps':>6}{'LCS_FD':>9}{'LCS_DMMPP':>11}{'LCS_Ours':>10}")
    def wmean(rs, lcs_col, edge_col):
        num=sum(fnum(r[lcs_col])*int(r[edge_col]) for r in rs)
        den=sum(int(r[edge_col]) for r in rs)
        return num/den if den else 0
    for ds, rs in sorted(groups.items()):
        fd=wmean(rs,'lcs_flowdroid','edges_fd')
        dm=wmean(rs,'lcs_dmmpp','edges_dmmpp')
        ou=wmean(rs,'lcs_ours','edges_ours')
        print(f"{ds:<12}{len(rs):>6}{fd:>9.3f}{dm:>11.3f}{ou:>10.3f}")
    fd=wmean(apps,'lcs_flowdroid','edges_fd')
    dm=wmean(apps,'lcs_dmmpp','edges_dmmpp')
    ou=wmean(apps,'lcs_ours','edges_ours')
    print(f"{'ALL':<12}{len(apps):>6}{fd:>9.3f}{dm:>11.3f}{ou:>10.3f}")

    # unweighted per-app mean too
    print("\nUnweighted per-app mean LCS:")
    print(f"  FlowDroid={st.mean([fnum(r['lcs_flowdroid']) for r in apps]):.3f}"
          f"  DMMPP={st.mean([fnum(r['lcs_dmmpp']) for r in apps]):.3f}"
          f"  Ours={st.mean([fnum(r['lcs_ours']) for r in apps]):.3f}")

    # DroidBench-only (paper Fig.3 is on DroidBench)
    db=[r for r in apps if dataset_of(r['app'])=='DroidBench']
    if db:
        print("\nDroidBench-only mean LCS (paper Fig.3 setting, %):")
        print(f"  FlowDroid={100*st.mean([fnum(r['lcs_flowdroid']) for r in db]):.1f}"
              f"  DMMPP={100*st.mean([fnum(r['lcs_dmmpp']) for r in db]):.1f}"
              f"  Ours={100*st.mean([fnum(r['lcs_ours']) for r in db]):.1f}")

    # commit vs commitNow stats
    cn=sum(1 for r in apps if int(r['commitNow_calls'])>0)
    cm=sum(1 for r in apps if int(r['commit_calls'])>0)
    print(f"\napps using commit()={cm}  apps using commitNow()={cn}")

if __name__=='__main__':
    main()
