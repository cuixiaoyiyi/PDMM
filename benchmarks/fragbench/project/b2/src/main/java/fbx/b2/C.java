package fbx.b2;

import android.app.Activity;
import androidx.fragment.app.Fragment;
import android.content.Context;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;

public class C extends Fragment {
    String data;

    @Override
    public void onAttach(Activity activity) {
        super.onAttach(activity);
        T.ev("C.onAttach", "this=" + T.tag("C", this) + " a0=" + T.tag("Activity", activity));
    }

    @Override
    public void onAttach(Context context) {
        super.onAttach(context);
        T.ev("C.onAttachContext", "this=" + T.tag("C", this) + " a0=" + T.tag("Context", context));
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        T.ev("C.onCreate", "this=" + T.tag("C", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onViewCreated(View view, Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        T.ev("C.onViewCreated", "this=" + T.tag("C", this) + " a0=" + T.tag("View", view) + " a1=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onActivityCreated(Bundle savedInstanceState) {
        super.onActivityCreated(savedInstanceState);
        T.ev("C.onActivityCreated", "this=" + T.tag("C", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onViewStateRestored(Bundle savedInstanceState) {
        super.onViewStateRestored(savedInstanceState);
        T.ev("C.onViewStateRestored", "this=" + T.tag("C", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onStart() {
        super.onStart();
        T.ev("C.onStart", "this=" + T.tag("C", this));
    }

    @Override
    public void onResume() {
        super.onResume();
        T.ev("C.onResume", "this=" + T.tag("C", this));
    }

    @Override
    public void onPause() {
        super.onPause();
        T.ev("C.onPause", "this=" + T.tag("C", this));
    }

    @Override
    public void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        T.ev("C.onSaveInstanceState", "this=" + T.tag("C", this) + " a0=" + T.tag("Bundle", outState));
    }

    @Override
    public void onStop() {
        super.onStop();
        T.ev("C.onStop", "this=" + T.tag("C", this));
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        T.ev("C.onDestroyView", "this=" + T.tag("C", this));
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        T.ev("C.onDestroy", "this=" + T.tag("C", this));
    }

    @Override
    public void onDetach() {
        super.onDetach();
        T.ev("C.onDetach", "this=" + T.tag("C", this));
    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {
        T.ev("C.onCreateView", "this=" + T.tag("C", this) + " a0=" + T.tag("LayoutInflater", inflater) + " a1=" + T.tag("ViewGroup", container) + " a2=" + T.tag("Bundle", savedInstanceState));
        Button v = new Button(getActivity());
        v.setText("C");
        v.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View w) {
                T.ev("C.viewClick", "this=" + T.tag("C", C.this) + " a0=" + T.tag("View", w));
            }
        });
        return v;
    }
}
