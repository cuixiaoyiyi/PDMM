package soot.jimple.infoflow.android.entryPointCreators.components;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import rev.fd.FragmentPhaseCreator;
import rev.fd.HsmActivityLifecycle;
import rev.fd.PdmmConfig;
import rev.fd.PdmmRegistry;
import soot.Body;
import soot.IntType;
import soot.Local;
import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootField;
import soot.SootMethod;
import soot.Type;
import soot.Value;
import soot.VoidType;
import soot.jimple.Jimple;
import soot.jimple.JimpleBody;
import soot.jimple.NopStmt;
import soot.jimple.NullConstant;
import soot.jimple.Stmt;
import soot.jimple.infoflow.android.InfoflowAndroidConfiguration;
import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointConstants;
import soot.jimple.infoflow.android.entryPointCreators.ComponentExchangeInfo;
import soot.jimple.infoflow.android.manifest.IManifestHandler;
import soot.jimple.infoflow.cfg.LibraryClassPatcher;
import soot.jimple.infoflow.entryPointCreators.SimulatedCodeElementTag;
import soot.jimple.toolkits.scalar.NopEliminator;
import soot.util.MultiMap;

/**
 * Entry point creator for Android activities.
 *
 * PDMM: this class shadows FlowDroid 2.15.1's ActivityEntryPointCreator. With
 * pdmm.lifecycle=native the generated code is the original one. With
 * pdmm.lifecycle=hsm the lifecycle of every hosted fragment is split into phase
 * methods (FragmentPhaseCreator) that are called at the synchronisation points of
 * the hierarchical lifecycle model instead of running the whole fragment
 * lifecycle between onCreate and onStart.
 *
 * @author Steven Arzt (original), PDMM revision
 */
public class ActivityEntryPointCreator extends AbstractComponentEntryPointCreator {

	private final MultiMap<SootClass, String> activityLifecycleCallbacks;
	private final Map<SootClass, SootField> callbackClassToField;
	private final Map<SootClass, SootMethod> fragmentToMainMethod;

	// PDMM: state of the hsm mode
	private Map<SootClass, Map<FragmentPhaseCreator.Phase, SootMethod>> phaseMethods = null;
	private Local activityStateBundle = null;
	private HsmActivityLifecycle hsm = null;

	public ActivityEntryPointCreator(SootClass component, SootClass applicationClass,
			MultiMap<SootClass, String> activityLifecycleCallbacks, Map<SootClass, SootField> callbackClassToField,
			Map<SootClass, SootMethod> fragmentToMainMethod, IManifestHandler manifest, SootField instantiatorField,
			SootField classLoaderField, ComponentExchangeInfo componentExchangeInfo) {
		super(component, applicationClass, manifest, instantiatorField, classLoaderField, componentExchangeInfo);
		this.activityLifecycleCallbacks = activityLifecycleCallbacks;
		this.callbackClassToField = callbackClassToField;
		this.fragmentToMainMethod = fragmentToMainMethod;
	}

	@Override
	protected Local generateClassConstructor(SootClass createdClass) {
		if (createdClass == component && instantiatorField != null) {
			return super.generateInstantiator(createdClass,
					AndroidEntryPointConstants.APPCOMPONENTFACTORY_INSTANTIATEACTIVITY, body.getParameterLocal(0));
		}
		return super.generateClassConstructor(createdClass);
	}

	// ------------------------------------------------------------------ PDMM

	/**
	 * Creates the phase methods of every fragment hosted by this activity. They
	 * live in the dummy main class next to the component dummy mains.
	 */
	private void createPhaseMethods() {
		phaseMethods = new LinkedHashMap<>();
		if (fragmentToMainMethod == null)
			return;
		for (SootClass fragment : fragmentToMainMethod.keySet()) {
			Map<FragmentPhaseCreator.Phase, SootMethod> m = new LinkedHashMap<>();
			for (FragmentPhaseCreator.Phase p : FragmentPhaseCreator.Phase.values()) {
				FragmentPhaseCreator c = new FragmentPhaseCreator(fragment, component, applicationClass, manifest,
						instantiatorField, classLoaderField, componentExchangeInfo, p);
				c.setDummyClassName(mainMethod.getDeclaringClass().getName());
				SootMethod sm = c.createDummyMain();
				m.put(p, sm);
			}
			phaseMethods.put(fragment, m);
			if (PdmmConfig.txsite())
				fillSyncStubs(fragment, m);
		}
	}

	/**
	 * Fills the stubs that the transaction-site instrumentation inserted after
	 * commitNow() and executePendingTransactions(): a synchronous transaction
	 * brings the fragment to the host's current state at the call site.
	 */
	private void fillSyncStubs(SootClass fragment, Map<FragmentPhaseCreator.Phase, SootMethod> m) {
		fillSyncStub(PdmmRegistry.syncStubCreated.get(fragment), fragment, m,
				FragmentPhaseCreator.Phase.CREATE, FragmentPhaseCreator.Phase.VIEW);
		fillSyncStub(PdmmRegistry.syncStubResumed.get(fragment), fragment, m,
				FragmentPhaseCreator.Phase.CREATE, FragmentPhaseCreator.Phase.VIEW,
				FragmentPhaseCreator.Phase.START, FragmentPhaseCreator.Phase.RESUME);
	}

	private void fillSyncStub(SootMethod stub, SootClass fragment, Map<FragmentPhaseCreator.Phase, SootMethod> m,
			FragmentPhaseCreator.Phase... phases) {
		if (stub == null || !stub.hasActiveBody())
			return;
		Body b = stub.getActiveBody();
		// the phase methods are re-created in every round of FlowDroid's callback
		// analysis, so the stub body is rebuilt each time with fresh method references
		Jimple j = Jimple.v();
		Local host = b.getParameterLocal(0);
		Local f = b.getParameterLocal(1);
		b.getUnits().removeIf(u -> !(u instanceof soot.jimple.IdentityStmt));
		for (FragmentPhaseCreator.Phase p : phases) {
			SootMethod pm = m.get(p);
			if (pm == null)
				continue;
			List<Value> args = Arrays.asList(NullConstant.v(), host, f, NullConstant.v());
			if (p == FragmentPhaseCreator.Phase.CREATE)
				b.getUnits().add(j.newAssignStmt(f, j.newStaticInvokeExpr(pm.makeRef(), args)));
			else
				b.getUnits().add(j.newInvokeStmt(j.newStaticInvokeExpr(pm.makeRef(), args)));
		}
		b.getUnits().add(j.newAssignStmt(j.newStaticFieldRef(PdmmRegistry.fragmentField(fragment).makeRef()), f));
		b.getUnits().add(j.newReturnVoidStmt());
	}

	/** the state Bundle of the activity: written by onSaveInstanceState, read by the next onCreate */
	private Local createActivityStateBundle() {
		Jimple j = Jimple.v();
		RefType bundle = RefType.v("android.os.Bundle");
		Local sl = generator.generateLocal(bundle);
		body.getUnits().add(j.newAssignStmt(sl, j.newNewExpr(bundle)));
		SootMethod init = bundle.getSootClass().getMethodUnsafe("void <init>()");
		if (init != null)
			body.getUnits().add(j.newInvokeStmt(j.newSpecialInvokeExpr(sl, init.makeRef())));
		return sl;
	}

	/**
	 * Copy of AbstractComponentEntryPointCreator.createDummyMainInternal with the
	 * PDMM additions: phase methods are created first, and the activity state
	 * Bundle is allocated outside the re-creation loop.
	 */
	@Override
	protected SootMethod createDummyMainInternal() {
		if (!PdmmConfig.hsm())
			return super.createDummyMainInternal();

		createPhaseMethods();
		if (PdmmConfig.alias())
			activityStateBundle = createActivityStateBundle();
		hsm = new HsmActivityLifecycle(new HsmActivityLifecycle.Host() {
			@Override public Body body() { return body; }
			@Override public Local intentLocal() { return intentLocal; }
			@Override public Local thisLocal() { return thisLocal; }
			@Override public Local newLocal(RefType t) { return generator.generateLocal(t); }
			@Override public void opaqueIf(Stmt target) { createIfStmt(target); }
		}, phaseMethods);
		hsm.declareLocals();

		Stmt beforeComponentStmt = Jimple.v().newNopStmt();
		body.getUnits().add(beforeComponentStmt);

		Stmt endClassStmt = Jimple.v().newNopStmt();
		try {
			createIfStmt(endClassStmt);
			if (thisLocal == null)
				thisLocal = generateClassConstructor(component);
			if (thisLocal != null) {
				localVarsForClasses.put(component, thisLocal);
				body.getUnits().add(Jimple.v().newInvokeStmt(Jimple.v().newInterfaceInvokeExpr(thisLocal,
						componentExchangeInfo.setIntentMethod.makeRef(), Arrays.asList(intentLocal))));
				generateComponentLifecycle();
			}
			createIfStmt(beforeComponentStmt);
		} finally {
			body.getUnits().add(endClassStmt);
			if (thisLocal == null)
				body.getUnits().add(Jimple.v().newReturnStmt(NullConstant.v()));
			else
				body.getUnits().add(Jimple.v().newReturnStmt(thisLocal));
		}
		NopEliminator.v().transform(body);
		instrumentDummyMainMethod();
		if (System.getProperty("pdmm.debug") != null) {
			StringBuilder sb = new StringBuilder();
			for (Local l : body.getLocals())
				sb.append(l.getName()).append('#').append(System.identityHashCode(l)).append(' ');
			System.err.println("[pdmm] locals of " + mainMethod.getName() + ": " + sb);
		}
		return mainMethod;
	}

	/** with pdmm.alias the same Bundle is passed to onCreate, onRestoreInstanceState, onPostCreate and onSaveInstanceState */
	private Set<SootClass> stateParents(Set<SootClass> base) {
		if (!PdmmConfig.alias() || activityStateBundle == null)
			return base;
		SootClass bundle = Scene.v().getSootClass("android.os.Bundle");
		localVarsForClasses.put(bundle, activityStateBundle);
		Set<SootClass> s = new HashSet<>(base);
		s.add(bundle);
		return s;
	}

	// ------------------------------------------------------------------

	@Override
	protected void generateComponentLifecycle() {
		if (PdmmConfig.hsm()) {
			generateHsmLifecycle();
			return;
		}
		SootClass activityClass = getModelledClass();
		Set<SootClass> currentClassSet = Collections.singleton(component);
		final Body body = mainMethod.getActiveBody();

		Set<SootClass> referenceClasses = new HashSet<>();
		if (applicationClass != null)
			referenceClasses.add(applicationClass);
		if (this.activityLifecycleCallbacks != null)
			for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
				referenceClasses.add(callbackClass);
		referenceClasses.add(component);

		// Get the application class
		Local applicationLocal = null;
		if (applicationClass != null) {
			applicationLocal = generator.generateLocal(RefType.v("android.app.Application"));
			SootClass scApplicationHolder = LibraryClassPatcher.createOrGetApplicationHolder();
			body.getUnits().add(Jimple.v().newAssignStmt(applicationLocal,
					Jimple.v().newStaticFieldRef(scApplicationHolder.getFieldByName("application").makeRef())));
			localVarsForClasses.put(applicationClass, applicationLocal);
		}

		// Get the callback classes
		for (SootClass sc : callbackClassToField.keySet()) {
			Local callbackLocal = generator.generateLocal(RefType.v(sc));
			body.getUnits().add(Jimple.v().newAssignStmt(callbackLocal,
					Jimple.v().newStaticFieldRef(callbackClassToField.get(sc).makeRef())));
			localVarsForClasses.put(sc, callbackLocal);
		}

		// 1. attachBaseContext
		searchAndBuildMethod(AndroidEntryPointConstants.ATTACH_BASE_CONTEXT, thisLocal);

		// 2. onCreate:
		{
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONCREATE, thisLocal);
			for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
				searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYCREATED,
						localVarsForClasses.get(callbackClass), currentClassSet);
			}
		}

		// Adding the lifecycle of the Fragments that belong to this Activity:
		// iterate through the fragments detected in the CallbackAnalyzer
		if (fragmentToMainMethod != null && !fragmentToMainMethod.isEmpty()) {
			for (SootClass scFragment : fragmentToMainMethod.keySet()) {
				// Call the fragment's main method
				SootMethod smFragment = fragmentToMainMethod.get(scFragment);
				List<Value> args = new ArrayList<>();
				args.add(intentLocal);
				args.add(thisLocal);
				body.getUnits()
						.add(Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(smFragment.makeRef(), args)));
			}
		}

		// 3. onStart:
		Stmt onStartStmt;
		{
			onStartStmt = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSTART, thisLocal);
			for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
				Stmt s = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSTARTED,
						localVarsForClasses.get(callbackClass), currentClassSet);
				if (onStartStmt == null)
					onStartStmt = s;
			}

			// If we don't have an onStart method, we need to create a
			// placeholder so that we
			// have somewhere to jump
			if (onStartStmt == null)
				body.getUnits().add(onStartStmt = Jimple.v().newNopStmt());

		}
		// onRestoreInstanceState is optional, the system only calls it if a
		// state has previously been stored.
		{
			Stmt afterOnRestore = Jimple.v().newNopStmt();
			createIfStmt(afterOnRestore);
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESTOREINSTANCESTATE, thisLocal,
					currentClassSet);
			body.getUnits().add(afterOnRestore);
		}
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPOSTCREATE, thisLocal);

		// 4. onResume:
		Stmt onResumeStmt = Jimple.v().newNopStmt();
		body.getUnits().add(onResumeStmt);
		{
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESUME, thisLocal);
			for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
				searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYRESUMED,
						localVarsForClasses.get(callbackClass), currentClassSet);
			}
		}
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPOSTRESUME, thisLocal);

		// Scan for other entryPoints of this class:
		if (this.callbacks != null && !this.callbacks.isEmpty()) {
			NopStmt startWhileStmt = Jimple.v().newNopStmt();
			NopStmt endWhileStmt = Jimple.v().newNopStmt();
			body.getUnits().add(startWhileStmt);
			createIfStmt(endWhileStmt);

			// Add the callbacks
			addCallbackMethods();

			body.getUnits().add(endWhileStmt);
			createIfStmt(startWhileStmt);
		}

		// 5. onPause:
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPAUSE, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYPAUSED,
					localVarsForClasses.get(callbackClass), currentClassSet);
		}
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONCREATEDESCRIPTION, thisLocal);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSAVEINSTANCESTATE, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSAVEINSTANCESTATE,
					localVarsForClasses.get(callbackClass), currentClassSet);
		}

		// goTo Stop, Resume or Create:
		// (to stop is fall-through, no need to add)
		createIfStmt(onResumeStmt);
		// createIfStmt(onCreateStmt); // no, the process gets killed in between

		// 6. onStop:
		Stmt onStop = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSTOP, thisLocal);
		boolean hasAppOnStop = false;
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			Stmt onActStoppedStmt = searchAndBuildMethod(
					AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSTOPPED,
					localVarsForClasses.get(callbackClass), currentClassSet);
			hasAppOnStop |= onActStoppedStmt != null;
		}
		if (hasAppOnStop && onStop != null)
			createIfStmt(onStop);

		// goTo onDestroy, onRestart or onCreate:
		// (to restart is fall-through, no need to add)
		NopStmt stopToDestroyStmt = Jimple.v().newNopStmt();
		createIfStmt(stopToDestroyStmt);
		// createIfStmt(onCreateStmt); // no, the process gets killed in between

		// 7. onRestart:
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESTART, thisLocal);
		body.getUnits().add(Jimple.v().newGotoStmt(onStartStmt)); // jump to onStart()

		// 8. onDestroy
		body.getUnits().add(stopToDestroyStmt);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONDESTROY, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYDESTROYED,
					localVarsForClasses.get(callbackClass), currentClassSet);
		}
	}

	/**
	 * PDMM hierarchical lifecycle: the activity lifecycle of FlowDroid with the
	 * fragment phases spliced in at the points observed on the device
	 * (FragBench traces, API 29/30):
	 *
	 *   [restore: CREATE] onCreate [CREATE VIEW] onStart [START] onRestoreInstanceState?
	 *   onPostCreate onResume [RESUME] onPostResume { callbacks [CALLBACKS] [dynamic
	 *   bring-up / tear-down] } [PAUSE] onPause onCreateDescription [SAVE]
	 *   onSaveInstanceState -> onResume | [STOP] onStop -> onRestart onStart |
	 *   [DESTROYVIEW DESTROY] onDestroy
	 */
	private void generateHsmLifecycle() {
		final Set<SootClass> currentClassSet = Collections.singleton(component);
		final Body body = mainMethod.getActiveBody();
		final Jimple j = Jimple.v();

		Local applicationLocal = null;
		if (applicationClass != null) {
			applicationLocal = generator.generateLocal(RefType.v("android.app.Application"));
			SootClass scApplicationHolder = LibraryClassPatcher.createOrGetApplicationHolder();
			body.getUnits().add(j.newAssignStmt(applicationLocal,
					j.newStaticFieldRef(scApplicationHolder.getFieldByName("application").makeRef())));
			localVarsForClasses.put(applicationClass, applicationLocal);
		}
		for (SootClass sc : callbackClassToField.keySet()) {
			Local callbackLocal = generator.generateLocal(RefType.v(sc));
			body.getUnits().add(j.newAssignStmt(callbackLocal,
					j.newStaticFieldRef(callbackClassToField.get(sc).makeRef())));
			localVarsForClasses.put(sc, callbackLocal);
		}

		hsm.resetInstances();
		Set<SootClass> stateSet = stateParents(currentClassSet);

		// 1. attachBaseContext
		searchAndBuildMethod(AndroidEntryPointConstants.ATTACH_BASE_CONTEXT, thisLocal);

		// fragments restored from saved state are attached before the host's onCreate runs
		if (PdmmConfig.restore())
			hsm.all(FragmentPhaseCreator.Phase.CREATE);

		// 2. onCreate
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONCREATE, thisLocal, stateSet);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYCREATED,
					localVarsForClasses.get(callbackClass), currentClassSet);

		// transactions committed in onCreate and fragments from the layout: attached and
		// brought to ACTIVITY_CREATED before onStart
		hsm.all(FragmentPhaseCreator.Phase.CREATE);
		hsm.all(FragmentPhaseCreator.Phase.VIEW);

		// 3. onStart
		Stmt onStartStmt = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSTART, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			Stmt s = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSTARTED,
					localVarsForClasses.get(callbackClass), currentClassSet);
			if (onStartStmt == null)
				onStartStmt = s;
		}
		if (onStartStmt == null)
			body.getUnits().add(onStartStmt = j.newNopStmt());
		hsm.all(FragmentPhaseCreator.Phase.START);

		{
			Stmt afterOnRestore = j.newNopStmt();
			createIfStmt(afterOnRestore);
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESTOREINSTANCESTATE, thisLocal, stateSet);
			body.getUnits().add(afterOnRestore);
		}
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPOSTCREATE, thisLocal, stateSet);

		// 4. onResume
		Stmt onResumeStmt = j.newNopStmt();
		body.getUnits().add(onResumeStmt);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESUME, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYRESUMED,
					localVarsForClasses.get(callbackClass), currentClassSet);
		hsm.all(FragmentPhaseCreator.Phase.RESUME);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPOSTRESUME, thisLocal);

		// running: activity callbacks, fragment callbacks, dynamic transactions
		boolean hasCallbacks = this.callbacks != null && !this.callbacks.isEmpty();
		if (hasCallbacks || hsm.hasFragments()) {
			NopStmt startWhileStmt = j.newNopStmt();
			NopStmt endWhileStmt = j.newNopStmt();
			body.getUnits().add(startWhileStmt);
			createIfStmt(endWhileStmt);
			if (hasCallbacks)
				addCallbackMethods();
			hsm.all(FragmentPhaseCreator.Phase.CALLBACKS);
			hsm.dynamicTransactions();
			body.getUnits().add(endWhileStmt);
			createIfStmt(startWhileStmt);
		}

		// 5. onPause (fragments pause first)
		hsm.all(FragmentPhaseCreator.Phase.PAUSE);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONPAUSE, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYPAUSED,
					localVarsForClasses.get(callbackClass), currentClassSet);
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONCREATEDESCRIPTION, thisLocal);
		hsm.all(FragmentPhaseCreator.Phase.SAVE);
		if (PdmmConfig.alias() && activityStateBundle != null) {
			// onSaveInstanceState receives a fresh Bundle (ActivityThread.java:5297); the same
			// object reaches the next instance's onCreate through the re-creation loop
			RefType bundle = RefType.v("android.os.Bundle");
			body.getUnits().add(j.newAssignStmt(activityStateBundle, j.newNewExpr(bundle)));
			SootMethod init = bundle.getSootClass().getMethodUnsafe("void <init>()");
			if (init != null)
				body.getUnits().add(j.newInvokeStmt(j.newSpecialInvokeExpr(activityStateBundle, init.makeRef())));
		}
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSAVEINSTANCESTATE, thisLocal, stateSet);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSAVEINSTANCESTATE,
					localVarsForClasses.get(callbackClass), currentClassSet);

		createIfStmt(onResumeStmt);

		// 6. onStop (fragments stop first)
		hsm.all(FragmentPhaseCreator.Phase.STOP);
		Stmt onStop = searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONSTOP, thisLocal);
		boolean hasAppOnStop = false;
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet()) {
			Stmt onActStoppedStmt = searchAndBuildMethod(
					AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYSTOPPED,
					localVarsForClasses.get(callbackClass), currentClassSet);
			hasAppOnStop |= onActStoppedStmt != null;
		}
		if (hasAppOnStop && onStop != null)
			createIfStmt(onStop);

		NopStmt stopToDestroyStmt = j.newNopStmt();
		createIfStmt(stopToDestroyStmt);

		// 7. onRestart
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONRESTART, thisLocal);
		body.getUnits().add(j.newGotoStmt(onStartStmt));

		// 8. onDestroy (fragments are destroyed first)
		body.getUnits().add(stopToDestroyStmt);
		hsm.allGroup(FragmentPhaseCreator.Phase.DESTROYVIEW, FragmentPhaseCreator.Phase.DESTROY);
		hsm.clearInstances();
		searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONDESTROY, thisLocal);
		for (SootClass callbackClass : this.activityLifecycleCallbacks.keySet())
			searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITYLIFECYCLECALLBACK_ONACTIVITYDESTROYED,
					localVarsForClasses.get(callbackClass), currentClassSet);
	}

	@Override
	protected void createAdditionalMethods() {
		super.createAdditionalMethods();
		if (InfoflowAndroidConfiguration.getCreateActivityEntryMethods()) {

			createGetIntentMethod();
			createSetIntentMethod();
			createSetResultMethod();
		}
	}

	/**
	 * Creates an implementation of setIntent() that writes the given intent into
	 * the correct field
	 */
	private void createSetIntentMethod() {
		// We need to create an implementation of "setIntent". If there is already such
		// an implementation, we don't touch it.
		if (component.declaresMethod("void setIntent(android.content.Intent)"))
			return;

		Type intentType = RefType.v("android.content.Intent");
		SootMethod sm = Scene.v().makeSootMethod("setIntent", Collections.singletonList(intentType), VoidType.v(),
				Modifier.PUBLIC);
		component.addMethod(sm);
		sm.addTag(SimulatedCodeElementTag.TAG);

		JimpleBody b = Jimple.v().newBody(sm);
		sm.setActiveBody(b);
		b.insertIdentityStmts();

		Local lcIntent = b.getParameterLocal(0);
		b.getUnits().add(Jimple.v().newInvokeStmt(Jimple.v().newInterfaceInvokeExpr(b.getThisLocal(),
				componentExchangeInfo.setIntentMethod.makeRef(), Arrays.asList(lcIntent))));
		b.getUnits().add(Jimple.v().newReturnVoidStmt());
	}

	/**
	 * Creates an implementation of setResult() that writes the given intent into
	 * the correct field
	 */
	private void createSetResultMethod() {
		// We need to create an implementation of "getIntent". If there is already such
		// an implementation, we don't touch it.
		if (component.declaresMethod("void setResult(int,android.content.Intent)"))
			return;

		Type intentType = RefType.v("android.content.Intent");
		List<Type> params = new ArrayList<>();
		params.add(IntType.v());
		params.add(intentType);
		SootMethod sm = Scene.v().makeSootMethod("setResult", params, VoidType.v(), Modifier.PUBLIC);
		component.addMethod(sm);
		sm.addTag(SimulatedCodeElementTag.TAG);

		JimpleBody b = Jimple.v().newBody(sm);
		sm.setActiveBody(b);
		b.insertIdentityStmts();

		Local lcIntent = b.getParameterLocal(1);
		b.getUnits().add(Jimple.v().newInvokeStmt(Jimple.v().newInterfaceInvokeExpr(b.getThisLocal(),
				componentExchangeInfo.setResultIntentMethod.makeRef(), Arrays.asList(lcIntent))));
		b.getUnits().add(Jimple.v().newReturnVoidStmt());

		// Activity.setResult() is final. We need to change that
		SootMethod smSetResult = Scene.v()
				.grabMethod("<android.app.Activity: void setResult(int,android.content.Intent)>");
		if (smSetResult != null && smSetResult.getDeclaringClass().isApplicationClass())
			smSetResult.setModifiers(smSetResult.getModifiers() & ~Modifier.FINAL);
	}

	@Override
	protected SootClass getModelledClass() {
		return Scene.v().getSootClass(AndroidEntryPointConstants.ACTIVITYCLASS);
	}

}
