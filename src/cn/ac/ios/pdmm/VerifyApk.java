package cn.ac.ios.pdmm;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.options.Options;

/** Load a generated APK and print every injected PDMMPP dummy-main signature +
 *  body, proving the emitted dex is well-formed and the params are reduced. */
public class VerifyApk {
    public static void main(String[] a) {
        String platforms = a[0], apk = a[1];
        String want = a.length > 2 ? a[2] : null;
        soot.G.reset();
        Options.v().set_android_jars(platforms);
        Options.v().set_process_dir(Collections.singletonList(apk));
        Options.v().set_process_multiple_dex(true);
        Options.v().set_src_prec(Options.src_prec_apk);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_output_format(Options.output_format_none);
        List<String> excl = new ArrayList<>();
        for (String p : new String[]{"android.*","androidx.*","java.*","kotlin.*"}) excl.add(p);
        Options.v().set_exclude(excl);
        soot.Main.v().autoSetOptions();
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();

        int found = 0;
        for (SootClass c : Scene.v().getApplicationClasses()) {
            SootMethod m = c.getMethodByNameUnsafe("PDMMPP");
            if (m == null) m = c.getMethodByNameUnsafe("DMMPP");
            if (m == null) continue;
            if (want != null && !c.getName().contains(want)) continue;
            found++;
            System.out.println("== " + c.getName() + " ==");
            System.out.println("  signature : " + m.getSubSignature());
            System.out.println("  #params   : " + m.getParameterCount());
            try {
                System.out.println("  body OK, units=" + m.retrieveActiveBody().getUnits().size());
            } catch (Throwable t) {
                System.out.println("  body FAILED: " + t);
            }
        }
        System.out.println("injected dummy-main methods found: " + found);
    }
}
