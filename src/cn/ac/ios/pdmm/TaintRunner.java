package cn.ac.ios.pdmm;

import java.io.File;
import java.io.PrintWriter;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryMXBean;

import soot.jimple.infoflow.android.SetupApplication;
import soot.jimple.infoflow.results.InfoflowResults;

/**
 * RQ3 baseline: run the real FlowDroid taint engine (its native dummy-main +
 * IFDS solver) on an APK and record wall-clock time, peak heap, and the number
 * of detected source->sink leaks. This reproduces the "FlowDroid" column of the
 * paper's downstream tables with measured data.
 *
 * Usage: java cn.ac.ios.pdmm.TaintRunner <platforms> <apk> <sourcesSinks> <out-csv> <label>
 */
public class TaintRunner {
    public static void main(String[] args) throws Exception {
        String platforms = args[0], apk = args[1], ss = args[2], outCsv = args[3], label = args[4];

        System.gc();
        MemoryMXBean mem = ManagementFactory.getMemoryMXBean();
        long t0 = System.nanoTime();

        int leaks = -1; String status = "OK";
        long peakHeap = 0;
        try {
            SetupApplication app = new SetupApplication(platforms, apk);
            app.getConfig().setMergeDexFiles(true);
            // keep it tractable on a workstation
            app.getConfig().getSolverConfiguration().setMaxCalleesPerCallSite(75);
            InfoflowResults res = app.runInfoflow(ss);
            leaks = (res == null || res.getResults() == null) ? 0 : res.getResults().size();
            peakHeap = mem.getHeapMemoryUsage().getUsed();
        } catch (Throwable t) {
            status = "ERR:" + t.getClass().getSimpleName();
            System.err.println("taint failed for " + label + ": " + t);
        }
        long t1 = System.nanoTime();
        double secs = (t1 - t0) / 1e9;
        double mb = peakHeap / (1024.0 * 1024.0);

        boolean header = !new File(outCsv).exists();
        try (PrintWriter pw = new PrintWriter(new java.io.FileWriter(outCsv, true))) {
            if (header) pw.println("app,leaks,time_s,heap_mb,status");
            pw.printf("%s,%d,%.2f,%.1f,%s%n", label.replace(',', ';'), leaks, secs, mb, status);
        }
        System.out.printf("[TAINT] %-40s leaks=%d time=%.1fs heap=%.0fMB %s%n", label, leaks, secs, mb, status);
    }
}
