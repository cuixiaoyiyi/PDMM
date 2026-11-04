#!/usr/bin/env python3
"""Generates the FragBench app sources from cases.py.

Output: C:\\pdmm_work2\\fragbench\\src\\<id>\\{AndroidManifest.xml, res/layout/main.xml, java/fb/<id>/*.java}
Every lifecycle callback of every class is overridden and starts with a trace call
(Log.println with tag FBTRACE, which is not a FlowDroid sink) that records the
identity of the receiver and of every argument. Snippets from cases.py follow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cases import CASES  # noqa: E402

OUT = r"C:\pdmm_work2\fragbench\src"
OUTX = r"C:\pdmm_work2\fragbench\srcx"   # androidx variant, a Gradle multi-module project

# variant-dependent names
VARIANT = {"platform": dict(pkg="fb", act_base="Activity", act_import="android.app.Activity",
                            frag_import="android.app.Fragment", fm="getFragmentManager()"),
           "androidx": dict(pkg="fbx", act_base="FragmentActivity", act_import="androidx.fragment.app.FragmentActivity",
                            frag_import="androidx.fragment.app.Fragment", fm="getSupportFragmentManager()")}

# (java signature, trace name, argument names, super call, return)
ACTIVITY_CBS = [
    ("protected void onCreate(Bundle savedInstanceState)", "A.onCreate", ["savedInstanceState"], "super.onCreate(savedInstanceState);", ""),
    ("protected void onStart()", "A.onStart", [], "super.onStart();", ""),
    ("protected void onRestoreInstanceState(Bundle savedInstanceState)", "A.onRestoreInstanceState", ["savedInstanceState"], "super.onRestoreInstanceState(savedInstanceState);", ""),
    ("protected void onPostCreate(Bundle savedInstanceState)", "A.onPostCreate", ["savedInstanceState"], "super.onPostCreate(savedInstanceState);", ""),
    ("protected void onResume()", "A.onResume", [], "super.onResume();", ""),
    ("protected void onPostResume()", "A.onPostResume", [], "super.onPostResume();", ""),
    ("protected void onPause()", "A.onPause", [], "super.onPause();", ""),
    ("protected void onSaveInstanceState(Bundle outState)", "A.onSaveInstanceState", ["outState"], "super.onSaveInstanceState(outState);", ""),
    ("protected void onStop()", "A.onStop", [], "super.onStop();", ""),
    ("protected void onRestart()", "A.onRestart", [], "super.onRestart();", ""),
    ("protected void onDestroy()", "A.onDestroy", [], "super.onDestroy();", ""),
    ("protected void onNewIntent(Intent intent)", "A.onNewIntent", ["intent"], "super.onNewIntent(intent);", ""),
    ("protected void onActivityResult(int requestCode, int resultCode, Intent data)", "A.onActivityResult", ["data"], "super.onActivityResult(requestCode, resultCode, data);", ""),
    ("public void onAttachFragment(Fragment fragment)", "A.onAttachFragment", ["fragment"], "super.onAttachFragment(fragment);", ""),
]

FRAGMENT_CBS = [
    ("public void onAttach(Activity activity)", "onAttach", ["activity"], "super.onAttach(activity);", ""),
    ("public void onAttach(Context context)", "onAttachContext", ["context"], "super.onAttach(context);", ""),
    ("public void onCreate(Bundle savedInstanceState)", "onCreate", ["savedInstanceState"], "super.onCreate(savedInstanceState);", ""),
    ("public void onViewCreated(View view, Bundle savedInstanceState)", "onViewCreated", ["view", "savedInstanceState"], "super.onViewCreated(view, savedInstanceState);", ""),
    ("public void onActivityCreated(Bundle savedInstanceState)", "onActivityCreated", ["savedInstanceState"], "super.onActivityCreated(savedInstanceState);", ""),
    ("public void onViewStateRestored(Bundle savedInstanceState)", "onViewStateRestored", ["savedInstanceState"], "super.onViewStateRestored(savedInstanceState);", ""),
    ("public void onStart()", "onStart", [], "super.onStart();", ""),
    ("public void onResume()", "onResume", [], "super.onResume();", ""),
    ("public void onPause()", "onPause", [], "super.onPause();", ""),
    ("public void onSaveInstanceState(Bundle outState)", "onSaveInstanceState", ["outState"], "super.onSaveInstanceState(outState);", ""),
    ("public void onStop()", "onStop", [], "super.onStop();", ""),
    ("public void onDestroyView()", "onDestroyView", [], "super.onDestroyView();", ""),
    ("public void onDestroy()", "onDestroy", [], "super.onDestroy();", ""),
    ("public void onDetach()", "onDetach", [], "super.onDetach();", ""),
]

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"{pkgattr}>
    <uses-permission android:name="android.permission.READ_PHONE_STATE"/>
    <application android:label="fb {id}" android:allowBackup="false">
        <activity android:name=".MainActivity" android:exported="true"{single_top}>
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>{second}
    </application>
</manifest>
"""

LAYOUT = """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent" android:layout_height="match_parent" android:orientation="vertical">
    <Button android:id="@+id/btn" android:layout_width="match_parent" android:layout_height="300dp" android:text="btn"/>
    <FrameLayout android:id="@+id/container" android:layout_width="match_parent" android:layout_height="200dp"/>
    <FrameLayout android:id="@+id/container2" android:layout_width="match_parent" android:layout_height="200dp"/>{xmlfrag}
</LinearLayout>
"""

XMLFRAG = """
    <fragment android:name="{pkg}.{id}.F" android:id="@+id/xmlfrag" android:layout_width="match_parent" android:layout_height="100dp"/>"""

T_JAVA = """package {pkg}.{id};

import android.content.Context;
import android.telephony.TelephonyManager;
import android.util.Log;

/** Source wrapper and trace helper shared by all FragBench apps. */
public final class T {{
    private T() {{}}
    static int seq = 0;

    /** taint source: the device id (statically a FlowDroid source); the emulator throws, so the marker string is returned */
    public static String src(Context c) {{
        String s;
        try {{
            TelephonyManager tm = (TelephonyManager) c.getSystemService(Context.TELEPHONY_SERVICE);
            s = tm.getDeviceId();
        }} catch (Throwable t) {{
            s = null;
        }}
        return "TAINT#" + s;
    }}

    /** identity of an object as <declared type>@<identity hash>; no heap write, no array, so that
     *  FlowDroid's alias analysis is not affected by the instrumentation */
    public static String tag(String type, Object o) {{
        if (o == null) return "null";
        return type + "@" + Integer.toHexString(System.identityHashCode(o));
    }}

    /** trace record: FBTRACE <case> <seq> <event> this=<id> a0=<id> ... ; Log.println is not a FlowDroid sink */
    public static void ev(String event, String ids) {{
        Log.println(Log.DEBUG, "FBTRACE", "{id} " + (seq++) + " " + event + " " + ids + " t=" + Thread.currentThread().getId());
    }}
}}
"""

SECOND_JAVA = """package {pkg}.{id};

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public class Second extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        T.ev("Second.onCreate", "this=" + T.tag("Second", this) + " a0=" + T.tag("Bundle", savedInstanceState));
        Intent result = new Intent();
        result.putExtra("k", "clean");
        setResult(RESULT_OK, result);
        finish();
    }}
}}
"""


def ids(cls, sig, args):
    """java expression for 'this=<cls@hash> a0=<Type@hash> ...' from the callback's parameter list"""
    types = {}
    inside = sig[sig.index("(") + 1:sig.rindex(")")]
    for part in [x.strip() for x in inside.split(",") if x.strip()]:
        t, n = part.rsplit(" ", 1)
        types[n] = t
    expr = '"this=" + T.tag("%s", this)' % cls
    for i, a in enumerate(args):
        expr += ' + " a%d=" + T.tag("%s", %s)' % (i, types[a], a)
    return expr


def sink(snippet, cid):
    return snippet.replace("SINK(", 'Log.i("FBSINK", "%s " + ' % cid).replace("SINK(", "").replace(");", ");") if "SINK(" in snippet else snippet


def expand(snippet, cid):
    """SINK(x) -> Log.i("FBSINK", "<cid> " + (x));"""
    out = ""
    i = 0
    while True:
        j = snippet.find("SINK(", i)
        if j < 0:
            out += snippet[i:]
            return out
        out += snippet[i:j]
        depth = 0
        k = j + 5
        start = k
        while k < len(snippet):
            if snippet[k] == "(":
                depth += 1
            elif snippet[k] == ")":
                if depth == 0:
                    break
                depth -= 1
            k += 1
        arg = snippet[start:k]
        out += 'Log.i("FBSINK", "%s " + (%s))' % (cid, arg)
        i = k + 1


def activity_java(c, v):
    cid = c["id"]
    a = c["a"]
    lines = ["package %s.%s;" % (v["pkg"], cid), "",
             "import %s;" % v["act_import"], "import %s;" % v["frag_import"], "import android.content.Intent;",
             "import android.os.Bundle;", "import android.util.Log;", "import android.view.View;", "",
             "public class MainActivity extends %s {" % v["act_base"],
             "    String secret;", "    static String S;", "    F f;", "    G g;", ""]
    for sig, name, args, sup, ret in ACTIVITY_CBS:
        lines.append("    @Override")
        lines.append("    %s {" % sig)
        lines.append("        %s" % sup)
        lines.append("        T.ev(\"%s\", %s);" % (name, ids("MainActivity", sig, args)))
        key = name.split(".")[1]
        if key == "onCreate":
            if a.get("beforeSetContentView"):
                lines.append("        " + expand(a["beforeSetContentView"], cid))
            lines.append("        setContentView(R.layout.main);")
            lines.append("        findViewById(R.id.btn).setOnClickListener(new View.OnClickListener() {")
            lines.append("            @Override public void onClick(View v) {")
            lines.append("                T.ev(\"A.onClick\", \"this=\" + T.tag(\"MainActivity\", MainActivity.this) + \" a0=\" + T.tag(\"View\", v));")
            if c["click"]:
                lines.append("                " + expand(c["click"], cid).replace("getFragmentManager()", v["fm"]))
            lines.append("            }")
            lines.append("        });")
            if a.get("onCreate"):
                lines.append("        " + expand(a["onCreate"], cid))
            if c["oncreate_tx"]:
                lines.append("        " + expand(c["oncreate_tx"], cid).replace("getFragmentManager()", v["fm"]))
        elif a.get(key):
            lines.append("        " + expand(a[key], cid))
        lines.append("    }")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def fragment_java(c, cls, snippets, v):
    cid = c["id"]
    lines = ["package %s.%s;" % (v["pkg"], cid), "",
             "import android.app.Activity;", "import %s;" % v["frag_import"], "import android.content.Context;",
             "import android.os.Bundle;", "import android.util.Log;", "import android.view.LayoutInflater;",
             "import android.view.View;", "import android.view.ViewGroup;", "import android.widget.Button;", "",
             "public class %s extends Fragment {" % cls,
             "    String data;", ""]
    for sig, name, args, sup, ret in FRAGMENT_CBS:
        lines.append("    @Override")
        lines.append("    %s {" % sig)
        lines.append("        %s" % sup)
        lines.append("        T.ev(\"%s.%s\", %s);" % (cls, name, ids(cls, sig, args)))
        if snippets.get(name):
            lines.append("        " + expand(snippets[name], cid).replace("getFragmentManager()", v["fm"]))
        lines.append("    }")
        lines.append("")
    # onCreateView builds a button so that a fragment-owned view and its click listener exist
    lines.append("    @Override")
    lines.append("    public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {")
    lines.append("        T.ev(\"%s.onCreateView\", \"this=\" + T.tag(\"%s\", this) + \" a0=\" + T.tag(\"LayoutInflater\", inflater) + \" a1=\" + T.tag(\"ViewGroup\", container) + \" a2=\" + T.tag(\"Bundle\", savedInstanceState));" % (cls, cls))
    lines.append("        Button v = new Button(getActivity());")
    lines.append("        v.setText(\"%s\");" % cls)
    lines.append("        v.setOnClickListener(new View.OnClickListener() {")
    lines.append("            @Override public void onClick(View w) {")
    lines.append("                T.ev(\"%s.viewClick\", \"this=\" + T.tag(\"%s\", %s.this) + \" a0=\" + T.tag(\"View\", w));" % (cls, cls, cls))
    if snippets.get("viewClick"):
        lines.append("                " + expand(snippets["viewClick"], cid))
    lines.append("            }")
    lines.append("        });")
    if snippets.get("onCreateViewTag"):
        lines.append("        " + expand(snippets["onCreateViewTag"], cid))
    if snippets.get("onCreateView"):
        lines.append("        " + expand(snippets["onCreateView"], cid))
    lines.append("        return v;")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


MODULE_GRADLE = """plugins { id 'com.android.application' }
android {
    namespace '{pkg}.{id}'
    compileSdk 34
    defaultConfig { applicationId '{pkg}.{id}'; minSdk 24; targetSdk 29; versionCode 1; versionName '1' }
    compileOptions { sourceCompatibility JavaVersion.VERSION_1_8; targetCompatibility JavaVersion.VERSION_1_8 }
    lint { abortOnError false; checkReleaseBuilds false }
}
dependencies { implementation platform('org.jetbrains.kotlin:kotlin-bom:1.8.20'); implementation 'androidx.fragment:fragment:1.6.2' }
"""

ROOT_SETTINGS = """pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = 'fragbenchx'
{includes}
"""

ROOT_BUILD = """plugins { id 'com.android.application' version '8.5.0' apply false }
"""

ROOT_PROPS = """android.useAndroidX=true
org.gradle.jvmargs=-Xmx4g
org.gradle.parallel=true
org.gradle.daemon=false
android.nonTransitiveRClass=true
"""


def emit(c, root, v, gradle):
    cid = c["id"]
    pkg = v["pkg"]
    d = os.path.join(root, cid, "src", "main") if gradle else os.path.join(root, cid)
    second = '\n        <activity android:name=".Second" android:exported="false"/>' if c["second_activity"] else ""
    single_top = ' android:launchMode="singleTop"' if c["launch_single_top"] else ""
    pkgattr = "" if gradle else ' package="%s.%s"' % (pkg, cid)
    write(os.path.join(d, "AndroidManifest.xml"), MANIFEST.format(id=cid, second=second, single_top=single_top, pkgattr=pkgattr))
    write(os.path.join(d, "res", "layout", "main.xml"),
          LAYOUT.format(xmlfrag=XMLFRAG.format(id=cid, pkg=pkg) if c["layout_fragment"] else ""))
    jd = os.path.join(d, "java", pkg, cid)
    write(os.path.join(jd, "T.java"), T_JAVA.format(id=cid, pkg=pkg))
    write(os.path.join(jd, "MainActivity.java"), activity_java(c, v))
    write(os.path.join(jd, "F.java"), fragment_java(c, "F", c["f"], v))
    write(os.path.join(jd, "G.java"), fragment_java(c, "G", c["g"], v))
    write(os.path.join(jd, "C.java"), fragment_java(c, "C", c["c"], v))
    if c["second_activity"]:
        write(os.path.join(jd, "Second.java"), SECOND_JAVA.format(id=cid, pkg=pkg))
    if gradle:
        write(os.path.join(root, cid, "build.gradle"), MODULE_GRADLE.replace("{pkg}", pkg).replace("{id}", cid))


def main():
    for c in CASES:
        emit(c, OUT, VARIANT["platform"], False)
        emit(c, OUTX, VARIANT["androidx"], True)
    write(os.path.join(OUTX, "settings.gradle"), ROOT_SETTINGS.replace("{includes}", "\n".join("include ':%s'" % c["id"] for c in CASES)))
    write(os.path.join(OUTX, "build.gradle"), ROOT_BUILD)
    write(os.path.join(OUTX, "gradle.properties"), ROOT_PROPS)
    for root in (OUT, OUTX):
        with open(os.path.join(root, "cases.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("id,group,expect,description\n")
            for c in CASES:
                fh.write('%s,%s,%s,"%s"\n' % (c["id"], c["group"], c["expect"], c["desc"].replace('"', "'")))
    print("generated %d apps under %s and %s" % (len(CASES), OUT, OUTX))


if __name__ == "__main__":
    main()
