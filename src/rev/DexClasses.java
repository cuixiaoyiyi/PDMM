package rev;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import com.android.tools.smali.dexlib2.iface.MultiDexContainer;

/**
 * Lists every class of an APK with its superclass (all dex files), without
 * loading the app into Soot. Used to count fragment classes for corpus selection.
 *
 * Usage: java rev.DexClasses <apk> <out.tsv>   (lines: class \t superclass)
 */
public class DexClasses {
    public static void main(String[] args) throws Exception {
        File apk = new File(args[0]);
        MultiDexContainer<? extends DexBackedDexFile> container = DexFileFactory.loadDexContainer(apk, Opcodes.getDefault());
        List<String> names = new ArrayList<>(container.getDexEntryNames());
        int n = 0;
        try (PrintWriter pw = new PrintWriter(args[1], "UTF-8")) {
            for (String name : names) {
                DexBackedDexFile dex = container.getEntry(name).getDexFile();
                for (ClassDef cd : dex.getClasses()) {
                    pw.println(cd.getType() + "\t" + (cd.getSuperclass() == null ? "" : cd.getSuperclass()));
                    n++;
                }
            }
        }
        System.out.println("classes=" + n + " dex=" + names.size());
    }
}
