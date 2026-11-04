package rev.fd;

/**
 * Switches of the revised dummy-main generator, read from system properties so
 * that the same FlowDroid build serves every configuration of the evaluation.
 *
 *   pdmm.lifecycle  native | hsm   (default native: FlowDroid 2.15.1 unchanged)
 *   pdmm.txsite     0 | 1          transaction-site instrumentation: the fragment
 *                                  object the app adds is the one whose lifecycle
 *                                  runs; commitNow/executePendingTransactions splice
 *   pdmm.alias      0 | 1          saved-state Bundle and onCreateView/onViewCreated
 *                                  view are shared objects instead of null
 *   pdmm.restore    0 | 1          restored fragments may be re-attached before the
 *                                  host's onCreate (default 1, only with hsm)
 *   pdmm.phases     optional | mandatory   whether each fragment phase call is
 *                                  guarded by an opaque predicate (default optional)
 */
public final class PdmmConfig {

    private PdmmConfig() {}

    public static boolean hsm() { return "hsm".equals(System.getProperty("pdmm.lifecycle", "native")); }
    public static boolean txsite() { return "1".equals(System.getProperty("pdmm.txsite", "0")); }
    public static boolean alias() { return "1".equals(System.getProperty("pdmm.alias", "0")); }
    public static boolean restore() { return "1".equals(System.getProperty("pdmm.restore", "0")); }
    public static boolean mandatoryPhases() { return "mandatory".equals(System.getProperty("pdmm.phases", "optional")); }

    public static String describe() {
        return "lifecycle=" + (hsm() ? "hsm" : "native") + " txsite=" + (txsite() ? 1 : 0) + " alias=" + (alias() ? 1 : 0)
                + " restore=" + (restore() ? 1 : 0) + " phases=" + (mandatoryPhases() ? "mandatory" : "optional");
    }
}
