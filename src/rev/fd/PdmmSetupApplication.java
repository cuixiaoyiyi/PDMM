package rev.fd;

import java.io.File;
import java.util.Set;

import soot.SootClass;
import soot.jimple.infoflow.android.SetupApplication;
import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointCreator;

/**
 * FlowDroid's SetupApplication with the PDMM hook: before the entry point is
 * created, the transaction-site instrumentation runs on the app code
 * (pdmm.txsite=1). The shadowed ActivityEntryPointCreator does the rest.
 */
public class PdmmSetupApplication extends SetupApplication {

    public PdmmSetupApplication(File androidJar, File apkFile) {
        super(androidJar, apkFile);
    }

    @Override
    protected AndroidEntryPointCreator createEntryPointCreator(Set<SootClass> components) {
        if (PdmmConfig.txsite())
            TxSiteInstrumenter.run();
        return super.createEntryPointCreator(components);
    }
}
