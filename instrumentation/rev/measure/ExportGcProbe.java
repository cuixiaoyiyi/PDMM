package rev.measure;

import java.io.File;
import java.io.PrintWriter;
import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.MemoryType;
import java.lang.management.MemoryUsage;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import javax.management.Notification;
import javax.management.NotificationEmitter;
import javax.management.NotificationListener;
import javax.management.openmbean.CompositeData;
import com.sun.management.GarbageCollectionNotificationInfo;

/** GC-event measurements for new exporters; never substitutes current used heap for after-GC data. */
public final class ExportGcProbe implements NotificationListener {
    private final Object eventLock = new Object();
    private final List<String> heapPools = new ArrayList<String>();
    private final List<NotificationEmitter> emitters = new ArrayList<NotificationEmitter>();
    private final List<Map<String, Object>> collectors = new ArrayList<Map<String, Object>>();
    private final List<Map<String, Object>> events = new ArrayList<Map<String, Object>>();
    private final Map<String, Long> attachGcIds = new LinkedHashMap<String, Long>();
    private Map<String, Long> generationStartGcIds = new LinkedHashMap<String, Long>();
    private Map<String, Long> generationEndGcIds = new LinkedHashMap<String, Long>();
    private Map<String, Long> beforeForceGcIds = new LinkedHashMap<String, Long>();
    private final List<String> errors = new ArrayList<String>();
    private final int capacity = Integer.getInteger("pdmm.gc.max_events", 10000);
    private final long forceWaitMillis = Long.getLong("pdmm.gc.force_wait_ms", 2000L);
    private long attachUptime, detachUptime, generationStartUptime = Long.MAX_VALUE, generationEndUptime = Long.MAX_VALUE;
    private long forceRequestUptime = Long.MAX_VALUE, eventCount, droppedEvents, callbacksNanos, setupNanos;
    private long generationAnyCount, generationMajorCount;
    private Long generationPeakAny, generationPeakMajor, overallPeakAny, overallPeakMajor, forcedAfterHeap;
    private Double generationSeconds;
    private boolean forceConfirmed, forceMajorConfirmed, closed;

    public static ExportGcProbe start() {
        ExportGcProbe probe = new ExportGcProbe();
        long start = System.nanoTime();
        probe.attachUptime = uptime();
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans())
            if (pool.getType() == MemoryType.HEAP) probe.heapPools.add(pool.getName());
        probe.attachGcIds.putAll(gcIds());
        for (GarbageCollectorMXBean gc : ManagementFactory.getGarbageCollectorMXBeans()) {
            Map<String, Object> detail = new LinkedHashMap<String, Object>();
            detail.put("name", gc.getName());
            detail.put("collection_count_at_attach", gc.getCollectionCount());
            detail.put("notification_emitter", gc instanceof NotificationEmitter);
            detail.put("listener_registered", false);
            if (gc instanceof NotificationEmitter) {
                try {
                    NotificationEmitter emitter = (NotificationEmitter) gc;
                    emitter.addNotificationListener(probe, null, null);
                    probe.emitters.add(emitter);
                    detail.put("listener_registered", true);
                } catch (Exception ex) { probe.errors.add("register " + gc.getName() + ": " + ex); }
            }
            probe.collectors.add(detail);
        }
        probe.setupNanos = System.nanoTime() - start;
        return probe;
    }

    public void generationStarted() { synchronized (eventLock) { generationStartUptime = uptime(); generationStartGcIds = gcIds(); } }
    public void generationEnded(double seconds) {
        synchronized (eventLock) { generationEndUptime = uptime(); generationSeconds = seconds; generationEndGcIds = gcIds(); }
    }
    private static Map<String, Long> gcIds() {
        Map<String, Long> ids = new LinkedHashMap<String, Long>();
        for (GarbageCollectorMXBean gc : ManagementFactory.getGarbageCollectorMXBeans()) {
            long id = -1;
            if (gc instanceof com.sun.management.GarbageCollectorMXBean) {
                com.sun.management.GcInfo last = ((com.sun.management.GarbageCollectorMXBean) gc).getLastGcInfo();
                id = last == null ? 0 : last.getId();
            }
            ids.put(gc.getName(), id);
        }
        return ids;
    }
    private static long uptime() { return ManagementFactory.getRuntimeMXBean().getUptime(); }
    private static Long maximum(Long current, long value) { return current == null || value > current ? value : current; }

    @Override public void handleNotification(Notification notification, Object handback) {
        if (!GarbageCollectionNotificationInfo.GARBAGE_COLLECTION_NOTIFICATION.equals(notification.getType())) return;
        long started = System.nanoTime();
        try {
            GarbageCollectionNotificationInfo info = GarbageCollectionNotificationInfo.from((CompositeData) notification.getUserData());
            long used = 0;
            for (Map.Entry<String, MemoryUsage> pool : info.getGcInfo().getMemoryUsageAfterGc().entrySet())
                if (heapPools.contains(pool.getKey())) used += pool.getValue().getUsed();
            long end = info.getGcInfo().getEndTime(), begin = info.getGcInfo().getStartTime();
            boolean major = info.getGcAction().toLowerCase(Locale.ROOT).contains("major");
            synchronized (eventLock) {
                long id = info.getGcInfo().getId();
                Long attachId = attachGcIds.get(info.getGcName());
                if (closed || (attachId != null && attachId >= 0 && id <= attachId)) return;
                eventCount++;
                overallPeakAny = maximum(overallPeakAny, used);
                if (major) overallPeakMajor = maximum(overallPeakMajor, used);
                Long lower = generationStartGcIds.get(info.getGcName()), upper = generationEndGcIds.get(info.getGcName());
                boolean inGeneration = lower != null && lower >= 0 && id > lower && (upper == null || id <= upper);
                if (inGeneration) {
                    generationAnyCount++;
                    generationPeakAny = maximum(generationPeakAny, used);
                    if (major) { generationMajorCount++; generationPeakMajor = maximum(generationPeakMajor, used); }
                }
                // HotSpot GcInfo timestamps can use an offset from MXBean
                // uptime. Match per-collector GC IDs sampled before request.
                Long before = beforeForceGcIds.get(info.getGcName());
                boolean forced = before != null && before >= 0 && id > before && info.getGcCause().contains("System.gc");
                if (forced) {
                    forceConfirmed = true;
                    if (major) { forceMajorConfirmed = true; forcedAfterHeap = used; }
                    eventLock.notifyAll();
                }
                if (events.size() < capacity) {
                    Map<String, Object> event = new LinkedHashMap<String, Object>();
                    event.put("ordinal", eventCount); event.put("collector", info.getGcName());
                    event.put("cause", info.getGcCause()); event.put("action", info.getGcAction());
                    event.put("gc_id", info.getGcInfo().getId()); event.put("start_uptime_ms", begin); event.put("end_uptime_ms", end);
                    event.put("duration_ms", info.getGcInfo().getDuration()); event.put("heap_used_after_gc_bytes", used);
                    event.put("major_action", major); event.put("in_generation_window", inGeneration); event.put("matches_probe_gc_request", forced);
                    events.add(event);
                } else droppedEvents++;
            }
        } catch (Exception ex) { synchronized (eventLock) { errors.add("GC notification: " + ex); } }
        finally { synchronized (eventLock) { callbacksNanos += System.nanoTime() - started; } }
    }

    /** System.gc and waiting occur outside the event lock, so notifications can arrive. */
    public void finish(File metricsFile, String exportStatus, boolean generationComplete) throws Exception {
        boolean requested = generationComplete && "OK".equals(exportStatus);
        long forceCallNanos = 0, forceWaitNanos = 0;
        String forceMissing = requested ? null : "not requested for failed or incomplete generation";
        boolean interrupted = false;
        if (requested) {
            synchronized (eventLock) { forceRequestUptime = uptime(); beforeForceGcIds = gcIds(); }
            long started = System.nanoTime();
            System.gc(); // no monitor lock is held here
            forceCallNanos = System.nanoTime() - started;
            started = System.nanoTime();
            long deadline = started + Math.max(0, forceWaitMillis) * 1000000L;
            synchronized (eventLock) {
                while (!forceMajorConfirmed && System.nanoTime() < deadline) {
                    long left = Math.max(1, (deadline - System.nanoTime()) / 1000000L);
                    try { eventLock.wait(Math.min(50, left)); }
                    catch (InterruptedException ex) { interrupted = true; break; }
                }
                if (!forceMajorConfirmed) forceMissing = interrupted ? "interrupted waiting for matching major-GC notification"
                    : "no matching major-GC notification before deadline; explicit GC may be disabled or unsupported";
            }
            forceWaitNanos = System.nanoTime() - started;
        }
        long cleanupStart = System.nanoTime();
        for (NotificationEmitter emitter : emitters) {
            try { emitter.removeNotificationListener(this); }
            catch (Exception ex) { synchronized (eventLock) { errors.add("unregister: " + ex); } }
        }
        synchronized (eventLock) { detachUptime = uptime(); closed = true; }
        long cleanupNanos = System.nanoTime() - cleanupStart;
        Map<String, Object> record = new LinkedHashMap<String, Object>();
        synchronized (eventLock) {
            record.put("schema_version", 1); record.put("export_status", exportStatus); record.put("generation_complete", generationComplete);
            record.put("measurement_quality", generationComplete && "OK".equals(exportStatus) ? "completed exporter observation" : "failed exporter; partial observation");
            record.put("original_generation_seconds", generationSeconds);
            record.put("metric", "sum of used bytes in HEAP pools from GarbageCollectionNotificationInfo.memoryUsageAfterGc");
            record.put("major_classification", "reported gcAction contains major, case-insensitive; collector-dependent");
            record.put("generation_peak_after_any_gc_bytes", generationPeakAny); record.put("generation_peak_after_major_gc_bytes", generationPeakMajor);
            record.put("generation_gc_notification_count", generationAnyCount); record.put("generation_major_gc_notification_count", generationMajorCount);
            record.put("generation_any_gc_missing_reason", generationPeakAny == null ? "no observed GC notification in generation window" : null);
            record.put("generation_major_gc_missing_reason", generationPeakMajor == null ? "no observed major-GC notification in generation window" : null);
            record.put("overall_observed_peak_after_any_gc_bytes", overallPeakAny); record.put("overall_observed_peak_after_major_gc_bytes", overallPeakMajor);
            record.put("forced_gc_requested", requested); record.put("forced_gc_notification_confirmed", forceConfirmed);
            record.put("forced_major_gc_notification_confirmed", forceMajorConfirmed); record.put("forced_gc_after_heap_bytes", forcedAfterHeap);
            record.put("forced_gc_missing_reason", forceMissing); record.put("forced_gc_call_seconds", forceCallNanos / 1e9);
            record.put("forced_gc_notification_wait_seconds", forceWaitNanos / 1e9);
            record.put("forced_gc_total_overhead_seconds", (forceCallNanos + forceWaitNanos) / 1e9); record.put("forced_gc_wait_limit_ms", forceWaitMillis);
            record.put("forced_gc_request_uptime_ms", requested ? forceRequestUptime : null);
            record.put("forced_gc_match", "per-collector GC ID > last GC ID sampled before request and cause contains System.gc; asynchronous third-party explicit requests cannot be uniquely distinguished");
            record.put("listener_attach_gc_ids", attachGcIds); record.put("generation_start_gc_ids", generationStartGcIds);
            record.put("generation_end_gc_ids", generationEndGcIds); record.put("before_forced_gc_ids", beforeForceGcIds);
            record.put("generation_gc_window", "per-collector GC IDs sampled just after the original timer start/end; GcInfo timestamps are not aligned with RuntimeMXBean uptime");
            record.put("listener_attach_uptime_ms", attachUptime); record.put("generation_start_uptime_ms", generationStartUptime);
            record.put("generation_end_uptime_ms", generationEndUptime); record.put("listener_detach_uptime_ms", detachUptime);
            record.put("notification_count", eventCount); record.put("event_storage_capacity", capacity); record.put("event_rows_dropped", droppedEvents);
            record.put("registered_collectors", collectors); record.put("heap_pool_names", heapPools); record.put("errors", errors);
            record.put("observer_setup_seconds", setupNanos / 1e9); record.put("observer_unregister_seconds", cleanupNanos / 1e9);
            record.put("observer_callback_elapsed_sum_seconds", callbacksNanos / 1e9);
            record.put("observer_overhead_note", "callback elapsed sums can overlap generation; not a corrected overhead or CPU-time estimate. Heap includes probe objects.");
            record.put("coverage_note", "only delivered GC notifications while listeners are registered; no pre-attach or post-detach events, no guarantee every collection was delivered");
            record.put("any_gc_note", "post-young-GC heap can contain old-generation garbage; observed after-GC maxima are not an absolute peak live set");
            record.put("jvm_version", System.getProperty("java.version")); record.put("jvm_input_arguments", ManagementFactory.getRuntimeMXBean().getInputArguments());
        }
        Path metric = metricsFile.toPath();
        Files.createDirectories(metric.toAbsolutePath().getParent());
        Path eventsFile = metric.resolveSibling(metric.getFileName().toString().replace(".metrics.json", ".events.csv"));
        Path tempEvents = Files.createTempFile(eventsFile.getParent(), "gc-events-", ".tmp");
        try (PrintWriter writer = new PrintWriter(Files.newBufferedWriter(tempEvents, StandardCharsets.UTF_8))) {
            String[] columns = {"ordinal", "collector", "cause", "action", "gc_id", "start_uptime_ms", "end_uptime_ms", "duration_ms", "heap_used_after_gc_bytes", "major_action", "in_generation_window", "matches_probe_gc_request"};
            writer.println(csv(columns));
            for (Map<String, Object> event : events) {
                String[] values = new String[columns.length];
                for (int i = 0; i < values.length; i++) values[i] = String.valueOf(event.get(columns[i]));
                writer.println(csv(values));
            }
        }
        move(tempEvents, eventsFile);
        record.put("events_csv", eventsFile.toString());
        Path temp = Files.createTempFile(metric.getParent(), "gc-metric-", ".tmp");
        Files.write(temp, (json(record) + "\n").getBytes(StandardCharsets.UTF_8));
        move(temp, metric);
        if (interrupted) Thread.currentThread().interrupt();
    }
    private static void move(Path source, Path target) throws Exception {
        try { Files.move(source, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
        catch (AtomicMoveNotSupportedException ex) { Files.move(source, target, StandardCopyOption.REPLACE_EXISTING); }
    }
    private static String csv(String[] fields) {
        StringBuilder result = new StringBuilder();
        for (String field : fields) { if (result.length() > 0) result.append(','); result.append('"').append(field.replace("\"", "\"\"")).append('"'); }
        return result.toString();
    }
    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof Number || value instanceof Boolean) return String.valueOf(value);
        if (value instanceof Map) {
            StringBuilder out = new StringBuilder("{");
            for (Object item : ((Map<?, ?>) value).entrySet()) { Map.Entry<?, ?> entry = (Map.Entry<?, ?>) item;
                if (out.length() > 1) out.append(','); out.append(json(String.valueOf(entry.getKey()))).append(':').append(json(entry.getValue())); }
            return out.append('}').toString();
        }
        if (value instanceof Iterable) { StringBuilder out = new StringBuilder("["); for (Object item : (Iterable<?>) value) {
            if (out.length() > 1) out.append(','); out.append(json(item)); } return out.append(']').toString(); }
        String text = String.valueOf(value).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
        return "\"" + text + "\"";
    }
}
