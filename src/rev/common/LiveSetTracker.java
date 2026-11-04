package rev.common;

import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.MemoryType;
import java.lang.management.MemoryUsage;
import java.util.Map;

import javax.management.Notification;
import javax.management.NotificationEmitter;
import javax.management.NotificationListener;
import javax.management.openmbean.CompositeData;

import com.sun.management.GarbageCollectionNotificationInfo;

/**
 * Records the heap occupancy right after garbage collections, i.e. live data
 * rather than garbage. Two numbers are kept: the maximum after any collection
 * (an upper bound: old-generation garbage survives young collections) and the
 * maximum after major collections plus a final forced collection.
 */
public final class LiveSetTracker implements NotificationListener {

    private long maxAfterAny = 0;
    private long maxAfterMajor = 0;
    private int majorCount = 0;

    public static LiveSetTracker start() {
        LiveSetTracker t = new LiveSetTracker();
        for (GarbageCollectorMXBean gc : ManagementFactory.getGarbageCollectorMXBeans())
            if (gc instanceof NotificationEmitter)
                ((NotificationEmitter) gc).addNotificationListener(t, null, null);
        return t;
    }

    @Override
    public void handleNotification(Notification n, Object handback) {
        if (!GarbageCollectionNotificationInfo.GARBAGE_COLLECTION_NOTIFICATION.equals(n.getType()))
            return;
        GarbageCollectionNotificationInfo info = GarbageCollectionNotificationInfo.from((CompositeData) n.getUserData());
        long used = 0;
        for (Map.Entry<String, MemoryUsage> e : info.getGcInfo().getMemoryUsageAfterGc().entrySet())
            if (isHeapPool(e.getKey()))
                used += e.getValue().getUsed();
        synchronized (this) {
            if (used > maxAfterAny) maxAfterAny = used;
            if (info.getGcAction().toLowerCase().contains("major")) {
                majorCount++;
                if (used > maxAfterMajor) maxAfterMajor = used;
            }
        }
    }

    private static boolean isHeapPool(String name) {
        for (MemoryPoolMXBean p : ManagementFactory.getMemoryPoolMXBeans())
            if (p.getName().equals(name))
                return p.getType() == MemoryType.HEAP;
        return false;
    }

    /** forces a collection and returns {maxAfterAnyMB, maxAfterMajorMB, majorCount} */
    public synchronized long[] finish() {
        System.gc();
        try { Thread.sleep(200); } catch (InterruptedException ignore) {}
        long now = 0;
        for (MemoryPoolMXBean p : ManagementFactory.getMemoryPoolMXBeans())
            if (p.getType() == MemoryType.HEAP)
                now += p.getUsage().getUsed();
        if (now > maxAfterMajor) maxAfterMajor = now;
        if (now > maxAfterAny) maxAfterAny = now;
        return new long[] { maxAfterAny / (1024 * 1024), maxAfterMajor / (1024 * 1024), majorCount };
    }
}
