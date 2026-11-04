package fbx.p6;

import androidx.fragment.app.FragmentActivity;
import androidx.fragment.app.Fragment;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.View;

public class MainActivity extends FragmentActivity {
    String secret;
    static String S;
    F f;
    G g;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        T.ev("A.onCreate", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Bundle", savedInstanceState));
        setContentView(R.layout.main);
        findViewById(R.id.btn).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                T.ev("A.onClick", "this=" + T.tag("MainActivity", MainActivity.this) + " a0=" + T.tag("View", v));
            }
        });
        if (savedInstanceState != null) savedInstanceState.putString("k", T.src(this));
    }

    @Override
    protected void onStart() {
        super.onStart();
        T.ev("A.onStart", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onRestoreInstanceState(Bundle savedInstanceState) {
        super.onRestoreInstanceState(savedInstanceState);
        T.ev("A.onRestoreInstanceState", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Bundle", savedInstanceState));
        Log.i("FBSINK", "p6 " + (savedInstanceState.getString("k")));
    }

    @Override
    protected void onPostCreate(Bundle savedInstanceState) {
        super.onPostCreate(savedInstanceState);
        T.ev("A.onPostCreate", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    protected void onResume() {
        super.onResume();
        T.ev("A.onResume", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onPostResume() {
        super.onPostResume();
        T.ev("A.onPostResume", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onPause() {
        super.onPause();
        T.ev("A.onPause", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        T.ev("A.onSaveInstanceState", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Bundle", outState));
    }

    @Override
    protected void onStop() {
        super.onStop();
        T.ev("A.onStop", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onRestart() {
        super.onRestart();
        T.ev("A.onRestart", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        T.ev("A.onDestroy", "this=" + T.tag("MainActivity", this));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        T.ev("A.onNewIntent", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Intent", intent));
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        T.ev("A.onActivityResult", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Intent", data));
    }

    @Override
    public void onAttachFragment(Fragment fragment) {
        super.onAttachFragment(fragment);
        T.ev("A.onAttachFragment", "this=" + T.tag("MainActivity", this) + " a0=" + T.tag("Fragment", fragment));
    }

}
