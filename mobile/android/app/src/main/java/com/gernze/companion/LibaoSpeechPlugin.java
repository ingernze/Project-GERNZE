package com.gernze.companion;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;

@CapacitorPlugin(name="HebaoSpeech", permissions={@Permission(alias="microphone", strings={Manifest.permission.RECORD_AUDIO})})
public final class LibaoSpeechPlugin extends Plugin {
    private final Handler main = new Handler(Looper.getMainLooper());
    private SpeechSession sessions;
    private LocalSpeechWorker engine;
    private SherpaSpeechDriver speechFactory;
    private ActivityResultLauncher<String> permissionLauncher;
    private long permissionToken, permissionSerial;
    private volatile long warmEpoch;
    // Permission preparation owns no SpeechSession, decoder, or microphone.
    private PermissionRequest preparation;
    private boolean pageForeground = true;
    private static final class PermissionRequest {
        final String id;
        final PluginCall call;
        long token;
        boolean prompted, granted, resolved;
        Runnable deadline;
        PermissionRequest(String id, PluginCall call) { this.id = id; this.call = call; }
    }
    private boolean dead, foreground = true;
    private BroadcastReceiver screenOff;

    private boolean permitted() {
        return ContextCompat.checkSelfPermission(getContext(), Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }
    @Override public void load() {
        permissionLauncher = bridge.registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
            long ticket = permissionToken; permissionToken = 0;
            PermissionRequest request = preparation;
            if (dead || request == null || request.token != ticket || ticket == 0) return;
            boolean blocked = !granted && !ActivityCompat.shouldShowRequestPermissionRationale(getActivity(), Manifest.permission.RECORD_AUDIO);
            if (!granted || !permitted()) discardPreparation(blocked ? "permission_blocked" : "permission_denied");
            else { request.granted = true; completePreparation(); }
        });
        speechFactory = new SherpaSpeechDriver(getContext());
        engine = new LocalSpeechWorker(speechFactory, main::post);
        sessions = new SpeechSession(new SpeechSession.Platform() {
            public boolean available() { return unavailableCode() == null; }
            public boolean permitted() { return LibaoSpeechPlugin.this.permitted(); }
            public void askPermission(long token) {
                // A revoked permission must fail closed, never launch an implicit second dialog.
                throw new IllegalStateException("explicit preparation required");
            }
            public SpeechSession.Driver create(SpeechSession.Callbacks callbacks) { return engine.driver(callbacks); }
            public SpeechSession.Cancel later(long ms, Runnable action) {
                main.postDelayed(action, ms); return () -> main.removeCallbacks(action);
            }
            public void preview(String id, String text, int level) {
                if (dead) return;
                JSObject event = new JSObject(); event.put("sessionId", id); event.put("state", "preview");
                event.put("text", text); event.put("level", level); notifyListeners("speech", event);
            }
            public void emit(String id, String state, String code, String text) {
                if (dead) return;
                JSObject event = new JSObject(); event.put("sessionId", id); event.put("state", state);
                if (code != null) event.put("code", code);
                if (text != null) event.put("text", text);
                notifyListeners("speech", event); // not retained, persisted, or logged
            }
        });
        BroadcastReceiver receiver = new BroadcastReceiver() {
            public void onReceive(Context context, Intent intent) {
                if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) pause();
            }
        };
        try { getContext().registerReceiver(receiver, new IntentFilter(Intent.ACTION_SCREEN_OFF)); screenOff = receiver; }
        catch (RuntimeException error) { screenOff = null; }
    }
    private String unavailableCode() {
        if (dead || screenOff == null) return "lifecycle_unavailable";
        try { Class.forName("com.k2fsa.sherpa.onnx.OnlineRecognizer", false, getClass().getClassLoader()); }
        catch (ClassNotFoundException | LinkageError error) { return "engine_unavailable"; }
        return SherpaModelAssets.unavailableCode(getContext());
    }
    @PluginMethod public void warmup(PluginCall call) {
        boolean active = Boolean.TRUE.equals(call.getBoolean("active"));
        main.post(() -> {
            if (!dead && speechFactory != null) {
                if (!active) {
                    warmEpoch++;
                    speechFactory.setForeground(false);
                } else if (foreground && permitted() && unavailableCode() == null) {
                    speechFactory.setForeground(true);
                    long epoch = warmEpoch;
                    engine.warmup(() -> warmEpoch != epoch);
                }
            }
            call.resolve();
        });
    }

    @PluginMethod public void capabilities(PluginCall call) {
        main.post(() -> {
            String code = unavailableCode(); JSObject result = new JSObject();
            result.put("available", code == null); result.put("engine", "sherpa-local");
            result.put("engineVersion", "2.0.1"); result.put("model", SherpaModelAssets.MODEL);
            result.put("permissionGranted", permitted()); result.put("busy", engine != null && engine.busy());
            result.put("dialogAvailable", false); result.put("dialogAttemptSupported", false);
            if (code != null) result.put("code", code);
            call.resolve(result);
        });
    }
    private void resolvePreparation(PermissionRequest request, boolean prepared, String code) {
        if (request.resolved) return;
        request.resolved = true;
        JSObject result = new JSObject(); result.put("prepared", prepared);
        if (code != null) result.put("code", code);
        request.call.resolve(result);
    }
    private void discardPreparation(String code) {
        PermissionRequest old = preparation; preparation = null;
        if (old == null) return;
        main.removeCallbacks(old.deadline);
        resolvePreparation(old, false, code);
        // Do not clear permissionToken: the OS result still belongs to the old ticket.
    }
    private void completePreparation() {
        PermissionRequest request = preparation;
        if (request != null && request.granted && foreground && pageForeground && !dead) {
            resolvePreparation(request, true, null);
        }
    }
    @PluginMethod public void prepare(PluginCall call) {
        String id = call.getString("sessionId");
        main.post(() -> {
            String code = unavailableCode();
            if (code == null && (!foreground || dead)) code = "background";
            if (code == null && (preparation != null || sessions.active() || engine.busy())) code = "busy";
            if (code == null && permissionToken != 0) code = "permission_pending";
            if (code == null && (id == null || !id.matches("[A-Za-z0-9_-]{1,100}"))) code = "invalid_session";
            if (code != null) { JSObject result = new JSObject(); result.put("prepared", false); result.put("code", code); call.resolve(result); return; }
            pageForeground = true;
            speechFactory.setForeground(true);
            PermissionRequest request = new PermissionRequest(id, call); preparation = request;
            request.deadline = () -> { if (preparation == request) discardPreparation("timeout"); };
            main.postDelayed(request.deadline, 45000);
            if (permitted()) { request.granted = true; completePreparation(); return; }
            request.prompted = true; request.token = ++permissionSerial; permissionToken = request.token;
            try { permissionLauncher.launch(Manifest.permission.RECORD_AUDIO); }
            catch (RuntimeException error) { permissionToken = 0; discardPreparation("start_failed"); }
        });
    }
    @PluginMethod public void setPageForeground(PluginCall call) {
        String id = call.getString("sessionId");
        boolean value = Boolean.TRUE.equals(call.getBoolean("foreground"));
        main.post(() -> {
            // Only the current page owner can release a suspended preparation.
            PermissionRequest request = preparation;
            boolean owns = request != null && request.id.equals(id);
            if (owns) {
                pageForeground = value;
                speechFactory.setForeground(value && foreground);
                if (!value && (!request.prompted || request.resolved)) discardPreparation("background");
                else completePreparation();
            }
            JSObject result = new JSObject(); result.put("updated", owns); call.resolve(result);
        });
    }
    @PluginMethod public void start(PluginCall call) {
        String id = call.getString("sessionId");
        main.post(() -> {
            String code = unavailableCode();
            if (code == null && (!foreground || !pageForeground || dead)) code = "background";
            PermissionRequest request = preparation;
            if (code == null && (request == null || !request.id.equals(id) || !request.resolved || !request.granted)) code = "permission_required";
            if (code == null && !permitted()) code = "permission_denied";
            if (code == null && engine.busy()) code = "busy";
            JSObject ack = new JSObject();
            if (code != null) { ack.put("accepted", false); ack.put("code", code); }
            else {
                preparation = null; main.removeCallbacks(request.deadline);
                SpeechSession.Start result = sessions.start(id);
                ack.put("accepted", result.accepted); if (result.code != null) ack.put("code", result.code);
            }
            if (code != null && preparation != null && preparation.id.equals(id)) discardPreparation(code);
            call.resolve(ack);
        });
    }
    @PluginMethod public void stop(PluginCall call) {
        String id = call.getString("sessionId");
        main.post(() -> { JSObject ack = new JSObject(); ack.put("stopped", !dead && sessions.stop(id)); call.resolve(ack); });
    }
    @PluginMethod public void cancel(PluginCall call) {
        String id = call.getString("sessionId");
        main.post(() -> {
            boolean preparing = preparation != null && preparation.id.equals(id);
            if (preparing) discardPreparation("cancelled");
            JSObject ack = new JSObject(); ack.put("cancelled", preparing || (!dead && sessions.cancel(id))); call.resolve(ack);
        });
    }
    private void pause() {
        foreground = false; pageForeground = false;
        warmEpoch++;
        if (speechFactory != null) speechFactory.setForeground(false);
        discardPreparation("background");
        if (!dead && sessions != null) sessions.foreground(false);
    }
    @Override protected void handleOnPause() {
        foreground = false;
        warmEpoch++;
        if (speechFactory != null) speechFactory.setForeground(false);
        // Only an actually launched, unresolved permission preparation may survive
        // pause. A SpeechSession (including model initialization) never may.
        if (preparation == null || !preparation.prompted || preparation.resolved) discardPreparation("background");
        if (!dead && sessions != null) sessions.foreground(false);
    }
    @Override protected void handleOnStop() { pause(); }
    @Override protected void handleOnResume() {
        foreground = true;
        if (speechFactory != null) speechFactory.setForeground(pageForeground);
        if (!dead && sessions != null) sessions.foreground(true);
        completePreparation();
    }
    @Override protected void handleOnDestroy() {
        if (dead) return;
        warmEpoch++;
        discardPreparation("cancelled");
        if (sessions != null) sessions.destroy(); dead = true;
        if (engine != null) engine.close();
        if (speechFactory != null) speechFactory.close();
        if (screenOff != null) { try { getContext().unregisterReceiver(screenOff); } catch (RuntimeException ignored) {} screenOff = null; }
        if (permissionLauncher != null) permissionLauncher.unregister();
    }
}
