package cn.ac.ios.pdmm;

import java.io.File;
import java.io.PrintWriter;
import java.lang.management.ManagementFactory;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;

import cn.ac.ios.dmmpp.AndroidCallBacks;
import cn.ac.ios.dmmpp.gen.DMMFactory;
import cn.ac.ios.dmmpp.gen.PDMMGen;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraph;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphActivity;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphBroadcastReceiver;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphContentProvider;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphFragment;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphService;
import jymbolic.android.config.AndroidSootConfig;
import jymbolic.android.config.AndrolicConfigurationManager;
import jymbolic.execution.SymbolicEngine;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.util.MultiMap;

/**
 * RQ3 "Ours" column: run the *real* DMMPP downstream analyzer (Androlic /
 * jymbolic SymbolicEngine) on the same app, once with the baseline DMMPP dummy
 * main (DMMFactory) and once with our parameter-de-bloated dummy main (PDMMGen),
 * and measure symbolic-analysis time + peak memory.
 *
 * Because Androlic's own `Main.analyzeDummyMainMethod` hard-codes
 * `DMMFactory.createDDM`, we reproduce its loop here but make the generator
 * swappable -- everything else (Soot config, SymbolicEngine, path bounds from the
 * config file) is Androlic's, unchanged.
 *
 * Usage: java cn.ac.ios.pdmm.AndrolicRQ3 <baseline|ours> <configFile> <outCsv> <label>
 */
public class AndrolicRQ3 {

    public static void main(String[] args) throws Exception {
        String mode = args[0];
        String configFile = args[1];
        String outCsv = args[2];
        String label = args[3];

        AndrolicConfigurationManager.init(new String[]{"-configureFile", configFile});
        new AndroidSootConfig().sootInitialization();

        List<SootClass> classes = new ArrayList<>(Scene.v().getApplicationClasses());
        int analyzed = 0, dmmNull = 0; long totalPaths = 0;

        // True peak-heap sampler: poll used heap every 30ms, track the maximum
        // over the whole analysis (robust to GC timing, unlike a point sample).
        final long[] peak = {0};
        final boolean[] stop = {false};
        Thread sampler = new Thread(() -> {
            while (!stop[0]) {
                long u = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed();
                if (u > peak[0]) peak[0] = u;
                try { Thread.sleep(30); } catch (InterruptedException e) { return; }
            }
        });
        sampler.setDaemon(true);
        sampler.start();

        long t0 = System.nanoTime();

        for (SootClass c : classes) {
            if (c.isAbstract()) continue;
            SootMethod dmm;
            try {
                // Both arms use our CFG-correct generator so the analysis actually
                // runs (the shipped DMMFactory NPEs on real components); the ONLY
                // difference is parameter merging, isolating the de-bloat effect.
                //   baseline = one formal param per argument (DMMPP's intent)
                //   ours     = de-bloated (one shared param per type)
                dmm = buildDMM(c, "ours".equals(mode));
            } catch (Throwable t) { dmm = null; }
            if (dmm == null) { dmmNull++; continue; }
            try {
                int paths = new SymbolicEngine(c).solve(dmm);
                totalPaths += paths;
                analyzed++;
            } catch (Throwable t) {
                // a single component blowing up must not abort the whole app
            }
        }
        long t1 = System.nanoTime();
        stop[0] = true;
        double secs = (t1 - t0) / 1e9;
        double mb = peak[0] / (1024.0 * 1024.0);

        boolean header = !new File(outCsv).exists();
        try (PrintWriter pw = new PrintWriter(new java.io.FileWriter(outCsv, true))) {
            if (header) pw.println("app,mode,analyzed_components,dmm_null,total_paths,time_s,peak_heap_mb");
            pw.printf("%s,%s,%d,%d,%d,%.2f,%.1f%n", label.replace(',', ';'), mode,
                    analyzed, dmmNull, totalPaths, secs, mb);
        }
        System.out.printf("[ANDROLIC] %-28s mode=%-8s analyzed=%d paths=%d time=%.1fs heap=%.0fMB%n",
                label, mode, analyzed, totalPaths, secs, mb);
    }

    /** Build a dummy main for a component; merge=true de-bloats, false = baseline. */
    static SootMethod buildDMM(SootClass c, boolean merge) {
        LifecycleGraph graph;
        if (PDMMMain.isActivity(c)) {
            List<String> cbs = new ArrayList<>();
            try {
                Set<SootClass> inv = AndroidCallBacks.getSootClassesInvoked(c, null, null).mInvokedSootClasses;
                MultiMap<SootClass, SootMethod> cb = AndroidCallBacks.getCallBackMultiMap(inv);
                for (SootClass lc : cb.keySet()) for (SootMethod m : cb.get(lc)) cbs.add(m.getSignature());
            } catch (Throwable ignore) {}
            graph = new LifecycleGraphActivity(cbs);
        } else if (PDMMMain.isFragment(c)) graph = new LifecycleGraphFragment();
        else if (PDMMMain.isService(c)) graph = new LifecycleGraphService();
        else if (PDMMMain.isBroadcastReceiver(c)) graph = new LifecycleGraphBroadcastReceiver();
        else if (PDMMMain.isContentProvider(c)) graph = new LifecycleGraphContentProvider();
        else return null;
        return new PDMMGen(c, graph, merge).createDDM();
    }
}
