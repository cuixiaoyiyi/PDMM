package rev.measure;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
/** Synthetic allocation / early-error self-test. Never loads or analyzes APKs. */
public final class ProbeSmoke {
    public static void main(String[] args) throws Exception {
        ExportGcProbe probe = ExportGcProbe.start();
        long started = System.nanoTime();
        probe.generationStarted();
        String status = "OK";
        List<byte[]> retained = new ArrayList<byte[]>();
        try {
            if (args[1].equals("failure")) throw new IllegalStateException("fixture failure before observed GC");
            retained.add(new byte[2 * 1024 * 1024]);
            for (int i = 0; i < 20; i++) { byte[] allocation = new byte[512 * 1024]; allocation[0] = (byte) i; }
            System.gc();
            Thread.sleep(100); // fixture only, not used as GC completion proof
        } catch (RuntimeException ex) { status = "ERR:" + ex.getClass().getSimpleName(); }
        double seconds = (System.nanoTime() - started) / 1e9;
        probe.generationEnded(seconds);
        probe.finish(new File(args[0]), status, status.equals("OK"));
        if (!retained.isEmpty()) System.out.println("retained fixture bytes=" + retained.get(0).length);
        if (!status.equals("OK")) System.exit(1);
    }
}
