package cn.ac.ios.pdmm;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import cn.ac.ios.dmmpp.AndroidCallBacks;
import cn.ac.ios.dmmpp.gen.PDMMGen;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraph;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphActivity;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphBroadcastReceiver;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphContentProvider;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphFragment;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphService;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.options.Options;
import soot.util.MultiMap;

/**
 * Real artifact: emit an instrumented APK in which every component carries a
 * parameter-de-bloated dummy main ("PDMMPP"), produced by {@link PDMMGen}.
 *
 * This is the de-bloated analogue of DMMPP's own DMMMain: same pipeline, same
 * dex output, but the generated dummy main's signature is reduced to one shared
 * formal parameter per distinct type. The reduction realised per component is
 * written to results/rq1_generated.csv so the emitted code can be cross-checked
 * against the RQ1 metric numbers.
 *
 * Usage: java cn.ac.ios.pdmm.PDMMGenMain <platforms> <apk> <out-dir>
 */
public class PDMMGenMain {

    public static void main(String[] args) {
        String platforms = args[0], apk = args[1], out = args[2];
        new File(out).mkdirs();

        soot.G.reset();
        Options.v().set_android_jars(platforms);
        Options.v().set_process_dir(Collections.singletonList(apk));
        Options.v().set_no_bodies_for_excluded(true);
        Options.v().set_process_multiple_dex(true);
        Options.v().set_whole_program(true);
        Options.v().set_output_dir(out);
        Options.v().set_output_format(Options.output_format_dex);
        Options.v().set_src_prec(Options.src_prec_apk);
        Options.v().set_allow_phantom_refs(true);
        List<String> excl = new ArrayList<>();
        for (String p : new String[]{"android.*","androidx.*","org.*","soot.*","java.*","sun.*",
                "javax.*","com.sun.*","com.ibm.*","org.xml.*","org.w3c.*","apple.awt.*","com.apple.*","kotlin.*"})
            excl.add(p);
        Options.v().set_exclude(excl);
        soot.Main.v().autoSetOptions();
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();

        long base = 0, reduced = 0; int comps = 0;
        String csv = "results" + File.separator + "rq1_generated.csv";
        new File("results").mkdirs();
        boolean header = !new File(csv).exists();
        String appName = new File(apk).getName();
        try (PrintWriter pw = new PrintWriter(new java.io.FileWriter(csv, true))) {
            if (header) pw.println("app,component,kind,baseline_params,emitted_params");

            for (SootClass c : new HashSet<>(Scene.v().getApplicationClasses())) {
                String kind; LifecycleGraph graph;
                if (PDMMMain.isActivity(c)) {
                    kind = "Activity";
                    List<String> cbs = new ArrayList<>();
                    try {
                        Set<SootClass> inv = AndroidCallBacks.getSootClassesInvoked(c, null, null).mInvokedSootClasses;
                        MultiMap<SootClass, SootMethod> cb = AndroidCallBacks.getCallBackMultiMap(inv);
                        for (SootClass lc : cb.keySet()) for (SootMethod m : cb.get(lc)) cbs.add(m.getSignature());
                    } catch (Throwable ignore) {}
                    graph = new LifecycleGraphActivity(cbs);
                } else if (PDMMMain.isFragment(c)) { kind = "Fragment"; graph = new LifecycleGraphFragment(); }
                else if (PDMMMain.isService(c)) { kind = "Service"; graph = new LifecycleGraphService(); }
                else if (PDMMMain.isBroadcastReceiver(c)) { kind = "Receiver"; graph = new LifecycleGraphBroadcastReceiver(); }
                else if (PDMMMain.isContentProvider(c)) { kind = "Provider"; graph = new LifecycleGraphContentProvider(); }
                else continue;

                try {
                    PDMMGen gen = new PDMMGen(c, graph);
                    SootMethod ddm = gen.createDDM();
                    if (ddm != null) {
                        comps++;
                        base += gen.baselineParamCount;
                        reduced += gen.reducedParamCount;
                        pw.printf("%s,%s,%s,%d,%d%n", appName.replace(',', ';'),
                                c.getName().replace(',', ';'), kind,
                                gen.baselineParamCount, gen.reducedParamCount);
                    }
                } catch (Throwable t) {
                    System.err.println("PDMMGen failed for " + c.getName() + ": " + t);
                    if (System.getenv("PDMM_DEBUG") != null) t.printStackTrace();
                }
            }
        } catch (Exception e) { e.printStackTrace(); }

        // write the instrumented APK
        File old = new File(out + File.separator + appName);
        if (old.exists()) old.delete();
        if (Options.v().output_format() != Options.output_format_none) PackManager.v().writeOutput();
        File produced = new File(out + File.separator + appName);
        if (produced.exists()) produced.renameTo(new File(out + File.separator + "PDMMPP_" + appName));

        double prr = base == 0 ? 0 : 100.0 * (base - reduced) / base;
        System.out.printf("[PDMMGen] %s  components=%d  params %d -> %d  (%.1f%% reduction)  -> %s%n",
                appName, comps, base, reduced, prr, out + File.separator + "PDMMPP_" + appName);
    }
}
