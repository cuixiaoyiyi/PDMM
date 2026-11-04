package rev.measure;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import rev.common.LiveSetTracker;
/** Synthetic GC sidecar check; does not load Soot, SymbolicEngine, or APKs. */
public final class AndrolicProbeSmoke {
    public static void main(String[] args) throws Exception {
        AndrolicGcProbe probe = AndrolicGcProbe.start();
        LiveSetTracker legacy = LiveSetTracker.start();
        long started = System.nanoTime();
        probe.generationSolveStarted();
        String status = "OK";
        List<byte[]> retained = new ArrayList<byte[]>();
        try {
            if (args[1].equals("failure")) throw new IllegalStateException("fixture failure");
            retained.add(new byte[2 * 1024 * 1024]);
            for (int i = 0; i < 20; i++) { byte[] allocation = new byte[512 * 1024]; allocation[0] = (byte) i; }
            System.gc(); Thread.sleep(100); // fixture only; completion still requires a notification
        } catch (RuntimeException ex) { status = "ERR:" + ex.getClass().getSimpleName(); }
        double seconds = (System.nanoTime() - started) / 1e9;
        probe.generationSolveEnded(seconds);
        long[] reported = legacy.finish(); // deliberately retain the original tracker and its limitations
        probe.finish(new File(args[0]), status, status.equals("OK"), 0, 0, reported, "fixture", "fixed/perarg", "1");
        if (!retained.isEmpty()) System.out.println(retained.get(0).length);
        if (!status.equals("OK")) System.exit(1);
    }
}
