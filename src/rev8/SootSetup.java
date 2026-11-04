package rev8;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import soot.Body;
import soot.BodyTransformer;
import soot.PackManager;
import soot.Scene;
import soot.Transform;
import soot.options.Options;

/**
 * Loads an APK into Soot with the same options as DMMPP's DMMSootConfig, except
 * that no output is written. Kept identical on purpose so that the generated
 * dummy mains are the ones DMMPP itself would produce.
 */
public final class SootSetup {

    private SootSetup() {}

    /**
     * DMMPP's AndroidCallBacks reads the APK path from package-private static
     * fields of DMMSootConfig in its static initializer (manifest and layout
     * parsing), so they have to be set before any DMMPP class is used.
     */
    private static void setDmmppConfig(String platforms, String apk) {
        try {
            Class<?> k = Class.forName("cn.ac.ios.dmmpp.DMMSootConfig");
            java.lang.reflect.Field f = k.getDeclaredField("ApkPath");
            f.setAccessible(true);
            f.set(null, apk);
            f = k.getDeclaredField("ANDROID_PLATFORM_PATH");
            f.setAccessible(true);
            f.set(null, platforms);
        } catch (Exception e) {
            throw new IllegalStateException("cannot configure DMMPP", e);
        }
    }

    /** reads apkBasePath/apkName/androidPath from an Androlic config file and configures DMMPP accordingly */
    public static void configureDmmpp(String androlicConfig) throws java.io.IOException {
        String base = null, name = null, platforms = null;
        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Paths.get(androlicConfig))) {
            String[] kv = line.trim().split(" +", 2);
            if (kv.length < 2) continue;
            if (kv[0].equals("apkBasePath")) base = kv[1];
            else if (kv[0].equals("apkName")) name = kv[1];
            else if (kv[0].equals("androidPath")) platforms = kv[1];
        }
        setDmmppConfig(platforms, base + java.io.File.separator + name);
    }

    public static void load(String platforms, String apk) {
        setDmmppConfig(platforms, apk);
        soot.G.reset();
        Options.v().set_android_jars(platforms);
        Options.v().set_process_dir(Collections.singletonList(apk));
        Options.v().set_no_bodies_for_excluded(true);
        Options.v().set_process_multiple_dex(true);
        Options.v().set_whole_program(true);
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_src_prec(Options.src_prec_apk);
        Options.v().set_allow_phantom_refs(true);

        List<String> excl = new ArrayList<String>();
        for (String p : new String[] { "android.*", "org.*", "soot.*", "java.*", "sun.*", "javax.*", "com.sun.*",
                "com.ibm.*", "org.xml.*", "org.w3c.*", "apple.awt.*", "com.apple.*" })
            excl.add(p);
        Options.v().set_exclude(excl);

        PackManager.v().getPack("jtp").add(new Transform("jtp.bt", new BodyTransformer() {
            @Override
            protected void internalTransform(Body b, String phase, Map<String, String> options) {
                b.getMethod().setActiveBody(b);
            }
        }));

        soot.Main.v().autoSetOptions();
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();
    }
}
