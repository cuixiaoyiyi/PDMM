package rev.measure;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** Names the already validated event probe's window as Androlic generation+solve. */
public final class AndrolicGcProbe {
    private final ExportGcProbe delegate;
    private AndrolicGcProbe(ExportGcProbe delegate) { this.delegate = delegate; }
    public static AndrolicGcProbe start() { return new AndrolicGcProbe(ExportGcProbe.start()); }
    public void generationSolveStarted() { delegate.generationStarted(); }
    public void generationSolveEnded(double seconds) { delegate.generationEnded(seconds); }
    public void finish(File metricsFile, String status, boolean complete, int generationFailures, int solveFailures,
                       long[] legacyReported, String label, String config, String repetition) throws Exception {
        delegate.finish(metricsFile, status, complete);
        Path metric = metricsFile.toPath();
        Path events = metric.resolveSibling(metric.getFileName().toString().replace(".metrics.json", ".events.csv"));
        String eventText = new String(Files.readAllBytes(events), StandardCharsets.UTF_8)
            .replace("\"in_generation_window\"", "\"in_generation_solve_window\"");
        atomicWrite(events, eventText);
        String text = new String(Files.readAllBytes(metric), StandardCharsets.UTF_8).trim()
            .replace("\"generation_", "\"generation_solve_")
            .replace("\"original_generation_seconds\"", "\"original_generation_solve_seconds\"")
            .replace("\"export_status\"", "\"androlic_status\"")
            .replace("no observed GC notification in generation window", "no observed GC notification in Androlic generation+solve window")
            .replace("no observed major-GC notification in generation window", "no observed major-GC notification in Androlic generation+solve window")
            .replace("not requested for failed or incomplete generation", "not requested for failed or incomplete Androlic generation+solve")
            .replace("completed exporter observation", "completed Androlic generation+solve observation")
            .replace("failed exporter; partial observation", "failed Androlic instance; partial generation+solve observation");
        if (!text.endsWith("}")) throw new IllegalStateException("GC delegate JSON is truncated");
        String extra = ",\"measurement_variant\":\"androlic_gc_probe_v1\",\"metric_scope\":\"Androlic generation+solve\""
            + ",\"legacy_tracker_tail_outside_stage\":true,\"generation_component_failures\":" + generationFailures
            + ",\"solve_component_failures\":" + solveFailures
            + ",\"legacy_reported_live_any_mb\":" + legacyReported[0] + ",\"legacy_reported_live_major_mb\":" + legacyReported[1]
            + ",\"legacy_reported_major_gcs\":" + legacyReported[2]
            + ",\"legacy_reported_policy\":\"original synchronized LiveSetTracker.finish output preserved; these values do not confirm final GC completion\""
            + ",\"label\":" + quote(label) + ",\"config\":" + quote(config) + ",\"repetition\":" + quote(repetition);
        atomicWrite(metric, text.substring(0, text.length() - 1) + extra + "}\n");
    }
    private static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }
    private static void atomicWrite(Path target, String text) throws Exception {
        Path temporary = Files.createTempFile(target.getParent(), "androlic-gc-", ".tmp");
        Files.write(temporary, text.getBytes(StandardCharsets.UTF_8));
        try { Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
        catch (AtomicMoveNotSupportedException ex) { Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING); }
    }
}
