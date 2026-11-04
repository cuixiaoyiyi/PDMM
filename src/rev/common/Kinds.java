package rev.common;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

import soot.SootClass;

/** Component kinds and the lifecycle method names of each kind. */
public final class Kinds {

    private Kinds() {}

    private static final String[] FRAGMENT_BASES = {
        "android.app.Fragment",
        "androidx.fragment.app.Fragment",
        "android.support.v4.app.Fragment",
    };

    private static final Set<String> ACT = set("attachBaseContext", "onCreate", "onStart", "onRestoreInstanceState",
        "onPostCreate", "onResume", "onPostResume", "onPause", "onCreateDescription", "onSaveInstanceState",
        "onStop", "onRestart", "onDestroy", "onAttachFragment", "onNewIntent", "onActivityResult");
    private static final Set<String> FRAG = set("onAttach", "onCreate", "onCreateView", "onViewCreated",
        "onActivityCreated", "onViewStateRestored", "onStart", "onResume", "onPause", "onSaveInstanceState",
        "onStop", "onDestroyView", "onDestroy", "onDetach");
    private static final Set<String> SRV = set("onCreate", "onStart", "onStartCommand", "onBind", "onRebind",
        "onUnbind", "onDestroy");
    private static final Set<String> RCV = set("onReceive");
    private static final Set<String> PRV = set("onCreate", "query", "insert", "update", "delete", "getType");
    private static final Set<String> APP = set("attachBaseContext", "onCreate", "onTerminate", "onLowMemory",
        "onTrimMemory", "onConfigurationChanged");

    private static Set<String> set(String... s) { return new HashSet<String>(Arrays.asList(s)); }

    public static String kindOf(SootClass c) {
        if (isSub(c, "android.app.Activity")) return "ACT";
        for (String f : FRAGMENT_BASES) if (isSub(c, f)) return "FRAG";
        if (isSub(c, "android.app.Service")) return "SRV";
        if (isSub(c, "android.content.BroadcastReceiver")) return "RCV";
        if (isSub(c, "android.content.ContentProvider")) return "PRV";
        if (isSub(c, "android.app.Application")) return "APP";
        return "CB";
    }

    public static boolean isFragment(SootClass c) { return "FRAG".equals(kindOf(c)); }
    public static boolean isActivity(SootClass c) { return "ACT".equals(kindOf(c)); }

    public static boolean isLifecycle(String kind, String methodName) {
        if ("ACT".equals(kind)) return ACT.contains(methodName);
        if ("FRAG".equals(kind)) return FRAG.contains(methodName);
        if ("SRV".equals(kind)) return SRV.contains(methodName);
        if ("RCV".equals(kind)) return RCV.contains(methodName);
        if ("PRV".equals(kind)) return PRV.contains(methodName);
        if ("APP".equals(kind)) return APP.contains(methodName);
        return false;
    }

    /** walks the superclass chain by name; works for phantom classes too */
    public static boolean isSub(SootClass c, String base) {
        Set<SootClass> seen = new HashSet<SootClass>();
        for (SootClass k = c; k != null && seen.add(k); ) {
            if (k.getName().equals(base)) return true;
            if (!k.hasSuperclass()) break;
            k = k.getSuperclass();
        }
        return false;
    }
}
