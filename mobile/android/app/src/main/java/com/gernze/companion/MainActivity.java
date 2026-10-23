package com.gernze.companion;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebView;
import androidx.activity.EdgeToEdge;
import androidx.activity.SystemBarStyle;
import androidx.core.graphics.Insets;
import androidx.core.splashscreen.SplashScreen;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;
import com.gernze.companion.updates.LibaoPairingScanner;
import com.gernze.companion.updates.transport.LibaoUpdateTransport;
import com.gernze.companion.updates.install.LibaoUpdateInstallerPlugin;
import java.util.Locale;
public class MainActivity extends BridgeActivity {
    private Insets safeArea = Insets.NONE;
    private boolean keyboardVisible;
    @Override public void onCreate(Bundle savedInstanceState){
        // Hand off the plain native launch surface to the existing web opening.
        SplashScreen splash = SplashScreen.installSplashScreen(this);
        splash.setOnExitAnimationListener(view -> view.remove());
        registerPlugin(LibaoShakePlugin.class);
        registerPlugin(LibaoChatPlugin.class);
        registerPlugin(LibaoPairingScanner.class);
        registerPlugin(LibaoUpdateTransport.class);
        registerPlugin(LibaoUpdateInstallerPlugin.class);
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this, SystemBarStyle.dark(Color.TRANSPARENT), SystemBarStyle.dark(Color.TRANSPARENT));
        if (bridge == null) return;
        // Keep the background behind the bars even on older WebViews. Only
        // interactive HTML content gets safe-area padding; there is no native
        // system-bar padding. Android/WebView retains its existing IME handling.
        View decor = getWindow().getDecorView();
        ViewCompat.setOnApplyWindowInsetsListener(decor, (view, insets) -> {
            safeArea = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            keyboardVisible = insets.isVisible(WindowInsetsCompat.Type.ime());
            applySafeArea();
            return new WindowInsetsCompat.Builder(insets)
                .setInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout(), Insets.NONE)
                .build();
        });
        bridge.addWebViewListener(new WebViewListener() {
            @Override public void onPageCommitVisible(WebView view, String url) {
                applySafeArea();
                ViewCompat.requestApplyInsets(decor);
            }
        });
        ViewCompat.requestApplyInsets(decor);
    }
    private void applySafeArea() {
        if (bridge == null || bridge.getWebView() == null) return;
        float density = getResources().getDisplayMetrics().density;
        String script = String.format(Locale.US,
            "(()=>{const s=document.documentElement.style;s.setProperty('--safe-area-inset-top','%.2fpx');s.setProperty('--safe-area-inset-right','%.2fpx');s.setProperty('--safe-area-inset-bottom','%.2fpx');s.setProperty('--safe-area-inset-left','%.2fpx');})()",
            safeArea.top/density, safeArea.right/density, (keyboardVisible ? 0 : safeArea.bottom)/density, safeArea.left/density);
        bridge.getWebView().evaluateJavascript(script, null);
    }
}
