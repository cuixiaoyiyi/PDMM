package fbx.p3;

import android.app.Activity;
import androidx.fragment.app.Fragment;
import android.content.Context;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;

public class F extends Fragment {
    String data;

    @Override
    public void onAttach(Activity activity) {
        super.onAttach(activity);
        T.ev("F.onAttach", "this=" + T.tag("F", this) + " a0=" + T.tag("Activity", activity));
    }

    @Override
    public void onAttach(Context context) {
        super.onAttach(context);
        T.ev("F.onAttachContext", "this=" + T.tag("F", this) + " a0=" + T.tag("Context", context));
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        T.ev("F.onCreate", "this=" + T.tag("F", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onViewCreated(View view, Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        T.ev("F.onViewCreated", "this=" + T.tag("F", this) + " a0=" + T.tag("View", view) + " a1=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onActivityCreated(Bundle savedInstanceState) {
        super.onActivityCreated(savedInstanceState);
        T.ev("F.onActivityCreated", "this=" + T.tag("F", this) + " a0=" + T.tag("Bundle", savedInstanceState));
        if (savedInstanceState != null) Log.i("FBSINK", "p3 " + (savedInstanceState.getString("k")));
    }

    @Override
    public void onViewStateRestored(Bundle savedInstanceState) {
        super.onViewStateRestored(savedInstanceState);
        T.ev("F.onViewStateRestored", "this=" + T.tag("F", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onStart() {
        super.onStart();
        T.ev("F.onStart", "this=" + T.tag("F", this));
    }

    @Override
    public void onResume() {
        super.onResume();
        T.ev("F.onResume", "this=" + T.tag("F", this));
    }

    @Override
    public void onPause() {
        super.onPause();
        T.ev("F.onPause", "this=" + T.tag("F", this));
    }

    @Override
    public void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        T.ev("F.onSaveInstanceState", "this=" + T.tag("F", this) + " a0=" + T.tag("Bundle", outState));
        outState.putString("k", T.src(getActivity()));
    }

    @Override
    public void onStop() {
        super.onStop();
        T.ev("F.onStop", "this=" + T.tag("F", this));
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        T.ev("F.onDestroyView", "this=" + T.tag("F", this));
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        T.ev("F.onDestroy", "this=" + T.tag("F", this));
    }

    @Override
    public void onDetach() {
        super.onDetach();
        T.ev("F.onDetach", "this=" + T.tag("F", this));
    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {
        T.ev("F.onCreateView", "this=" + T.tag("F", this) + " a0=" + T.tag("LayoutInflater", inflater) + " a1=" + T.tag("ViewGroup", container) + " a2=" + T.tag("Bundle", savedInstanceState));
        Button v = new Button(getActivity());
        v.setText("F");
        v.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View w) {
                T.ev("F.viewClick", "this=" + T.tag("F", F.this) + " a0=" + T.tag("View", w));
            }
        });
        return v;
    }
}
