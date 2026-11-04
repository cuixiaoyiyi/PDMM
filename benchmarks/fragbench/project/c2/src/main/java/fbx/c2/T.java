package fbx.c2;

import android.content.Context;
import android.telephony.TelephonyManager;
import android.util.Log;

/** Source wrapper and trace helper shared by all FragBench apps. */
public final class T {
    private T() {}
    static int seq = 0;

    /** taint source: the device id (statically a FlowDroid source); the emulator throws, so the marker string is returned */
    public static String src(Context c) {
        String s;
        try {
            TelephonyManager tm = (TelephonyManager) c.getSystemService(Context.TELEPHONY_SERVICE);
            s = tm.getDeviceId();
        } catch (Throwable t) {
            s = null;
        }
        return "TAINT#" + s;
    }

    /** identity of an object as <declared type>@<identity hash>; no heap write, no array, so that
     *  FlowDroid's alias analysis is not affected by the instrumentation */
    public static String tag(String type, Object o) {
        if (o == null) return "null";
        return type + "@" + Integer.toHexString(System.identityHashCode(o));
    }

    /** trace record: FBTRACE <case> <seq> <event> this=<id> a0=<id> ... ; Log.println is not a FlowDroid sink */
    public static void ev(String event, String ids) {
        Log.println(Log.DEBUG, "FBTRACE", "c2 " + (seq++) + " " + event + " " + ids + " t=" + Thread.currentThread().getId());
    }
}
