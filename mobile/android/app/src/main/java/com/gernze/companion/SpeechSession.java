package com.gernze.companion;

/** Serial, main-thread session owner. No Android dependency or retained transcription. */
public final class SpeechSession {
    public interface Cancel { void cancel(); }
    public interface Callbacks {
        void ready();
        void end();
        default void preview(String text, int level) {}
        void result(String text);
        void error(String code);
    }
    public interface Driver {
        void start();
        void stop();
        void cancel();
        void destroy();
    }
    public interface Platform {
        boolean available();
        boolean permitted();
        void askPermission(long token);
        Driver create(Callbacks callbacks);
        Cancel later(long ms, Runnable action);
        void emit(String sessionId, String state, String code, String text);
        default void preview(String sessionId, String text, int level) {}
    }
    public static final class Start {
        public final boolean accepted;
        public final String code;
        Start(boolean accepted, String code) { this.accepted = accepted; this.code = code; }
    }
    private static final class Session {
        final long token;
        final String id;
        String state = "requesting";
        Driver driver;
        Cancel deadline;
        Session(long token, String id) { this.token = token; this.id = id; }
    }
    private final Platform platform;
    private long serial;
    private Session active, permissionTicket;
    private boolean foreground = true, dead;

    public SpeechSession(Platform platform) { this.platform = platform; }
    public Start start(String id) {
        if (dead || !foreground) return new Start(false, "background");
        if (active != null) return new Start(false, "busy");
        // An OS permission dialog cannot be replaced by a second request. Its
        // callback belongs to its own ticket, even after cancellation/timeout.
        if (permissionTicket != null) return new Start(false, "permission_pending");
        if (id == null || !id.matches("[A-Za-z0-9_-]{1,100}")) return new Start(false, "invalid_session");
        try { if (!platform.available()) return new Start(false, "unavailable"); }
        catch (RuntimeException error) { return new Start(false, "unavailable"); }
        Session session = new Session(++serial, id);
        active = session;
        emit(session);
        try {
            if (platform.permitted()) open(session);
            else {
                permissionTicket = session;
                arm(session, 45000);
                platform.askPermission(session.token);
            }
        } catch (RuntimeException error) {
            if (permissionTicket == session) permissionTicket = null;
            finish(session, "error", "start_failed", null);
        }
        return new Start(true, null);
    }
    public void permission(long token, boolean granted, boolean blocked) {
        Session session = permissionTicket;
        if (session == null || session.token != token) return;
        permissionTicket = null;
        if (!current(session)) return;
        if (!granted) finish(session, "error", blocked ? "permission_blocked" : "permission_denied", null);
        else if (!foreground) finish(session, "cancelled", "background", null);
        else open(session);
    }
    private boolean current(Session session) { return !dead && active == session; }
    private void open(final Session session) {
        if (!current(session) || !foreground) return;
        session.state = "starting";
        emit(session);
        arm(session, 10000);
        try {
            Driver driver = platform.create(new Callbacks() {
                @Override public void ready() {
                    if (!current(session) || !session.state.equals("starting")) return;
                    session.state = "listening"; emit(session); arm(session, 45000);
                }
                @Override public void preview(String text, int level) {
                    if (current(session) && session.state.equals("listening")) platform.preview(session.id, text, level);
                }
                @Override public void end() { waitForFinal(session); }
                @Override public void result(String text) {
                    if (text == null || text.trim().isEmpty()) finish(session, "error", "empty_result", null);
                    else finish(session, "final", null, text);
                }
                @Override public void error(String code) { finish(session, "error", code, null); }
            });
            if (!current(session)) { try { driver.cancel(); } catch (RuntimeException ignored) {} try { driver.destroy(); } catch (RuntimeException ignored) {} return; }
            session.driver = driver;
            driver.start();
        } catch (RuntimeException error) { finish(session, "error", "start_failed", null); }
    }
    private void emit(Session session) { platform.emit(session.id, session.state, null, null); }
    private void arm(final Session session, long ms) {
        if (session.deadline != null) session.deadline.cancel();
        session.deadline = platform.later(ms, () -> finish(session, "error", session.state.equals("starting") ? "start_timeout" : "timeout", null));
    }
    private void waitForFinal(Session session) {
        if (!current(session) || session.state.equals("waiting")) return;
        session.state = "waiting"; emit(session); arm(session, 8000);
    }
    public boolean stop(String id) {
        Session session = active;
        if (session == null || !session.id.equals(id)) return false;
        if (session.driver == null || session.state.equals("waiting")) return false;
        waitForFinal(session);
        try { session.driver.stop(); }
        catch (RuntimeException error) { finish(session, "error", "service_error", null); }
        return true;
    }
    public boolean cancel(String id) {
        Session session = active;
        if (session == null || !session.id.equals(id)) return false;
        finish(session, "cancelled", "cancelled", null); return true;
    }
    private void finish(Session session, String state, String code, String text) {
        if (!current(session)) return;
        active = null; // Invalidate BEFORE cancel/destroy can call back synchronously.
        if (session.deadline != null) session.deadline.cancel();
        Driver driver = session.driver;
        session.driver = null;
        if (driver != null) {
            if (!state.equals("final")) { try { driver.cancel(); } catch (RuntimeException ignored) {} }
            try { driver.destroy(); } catch (RuntimeException ignored) {}
        }
        platform.emit(session.id, state, code, text);
    }
    public void foreground(boolean value) {
        foreground = value;
        if (!value && active != null) finish(active, "cancelled", "background", null);
    }
    public boolean active() { return active != null; }
    public boolean permissionPending() { return permissionTicket != null; }
    public void destroy() {
        if (dead) return;
        foreground(false); dead = true; permissionTicket = null;
    }
}
