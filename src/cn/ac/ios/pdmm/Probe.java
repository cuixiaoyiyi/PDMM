package cn.ac.ios.pdmm;

import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointConstants;

/** Toolchain + constant-value probe. Prints the lifecycle method subsignatures
 *  used by FlowDroid/DMMPP so we can encode the canonical lifecycle spec. */
public class Probe {
    public static void main(String[] a) {
        String[][] act = {
            {"ACTIVITY_ONCREATE", AndroidEntryPointConstants.ACTIVITY_ONCREATE},
            {"ACTIVITY_ONSTART", AndroidEntryPointConstants.ACTIVITY_ONSTART},
            {"ACTIVITY_ONRESTOREINSTANCESTATE", AndroidEntryPointConstants.ACTIVITY_ONRESTOREINSTANCESTATE},
            {"ACTIVITY_ONPOSTCREATE", AndroidEntryPointConstants.ACTIVITY_ONPOSTCREATE},
            {"ACTIVITY_ONRESUME", AndroidEntryPointConstants.ACTIVITY_ONRESUME},
            {"ACTIVITY_ONPOSTRESUME", AndroidEntryPointConstants.ACTIVITY_ONPOSTRESUME},
            {"ACTIVITY_ONPAUSE", AndroidEntryPointConstants.ACTIVITY_ONPAUSE},
            {"ACTIVITY_ONCREATEDESCRIPTION", AndroidEntryPointConstants.ACTIVITY_ONCREATEDESCRIPTION},
            {"ACTIVITY_ONSAVEINSTANCESTATE", AndroidEntryPointConstants.ACTIVITY_ONSAVEINSTANCESTATE},
            {"ACTIVITY_ONSTOP", AndroidEntryPointConstants.ACTIVITY_ONSTOP},
            {"ACTIVITY_ONRESTART", AndroidEntryPointConstants.ACTIVITY_ONRESTART},
            {"ACTIVITY_ONDESTROY", AndroidEntryPointConstants.ACTIVITY_ONDESTROY},
        };
        String[][] frag = {
            {"FRAGMENT_ONATTACH", AndroidEntryPointConstants.FRAGMENT_ONATTACH},
            {"FRAGMENT_ONCREATE", AndroidEntryPointConstants.FRAGMENT_ONCREATE},
            {"FRAGMENT_ONCREATEVIEW", AndroidEntryPointConstants.FRAGMENT_ONCREATEVIEW},
            {"FRAGMENT_ONVIEWCREATED", AndroidEntryPointConstants.FRAGMENT_ONVIEWCREATED},
            {"FRAGMENT_ONACTIVITYCREATED", AndroidEntryPointConstants.FRAGMENT_ONACTIVITYCREATED},
            {"FRAGMENT_ONSTART", AndroidEntryPointConstants.FRAGMENT_ONSTART},
            {"FRAGMENT_ONRESUME", AndroidEntryPointConstants.FRAGMENT_ONRESUME},
            {"FRAGMENT_ONPAUSE", AndroidEntryPointConstants.FRAGMENT_ONPAUSE},
            {"FRAGMENT_ONSAVEINSTANCESTATE", AndroidEntryPointConstants.FRAGMENT_ONSAVEINSTANCESTATE},
            {"FRAGMENT_ONSTOP", AndroidEntryPointConstants.FRAGMENT_ONSTOP},
            {"FRAGMENT_ONDESTROYVIEW", AndroidEntryPointConstants.FRAGMENT_ONDESTROYVIEW},
        };
        System.out.println("=== ACTIVITY ===");
        for (String[] e : act) System.out.println(e[0] + " || " + e[1]);
        System.out.println("=== FRAGMENT ===");
        for (String[] e : frag) System.out.println(e[0] + " || " + e[1]);
    }
}
