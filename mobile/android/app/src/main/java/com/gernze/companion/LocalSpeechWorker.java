package com.gernze.companion;

import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;

/** One bounded capture/decoder worker. No Android, network, files or retained audio. */
public final class LocalSpeechWorker implements AutoCloseable {
    public interface Check { boolean cancelled(); }
    public interface Decoder extends AutoCloseable {
        String accept(short[] pcm, int count) throws Exception;
        String finish() throws Exception;
        default String preview() { return ""; }
        void close();
    }
    public interface Audio extends AutoCloseable {
        void start() throws Exception;
        int read(short[] pcm) throws Exception;
        void stop();
        void close();
    }
    public interface Factory {
        Decoder open(Check check) throws Exception;
        default void warmup(Check check) throws Exception {}
        Audio microphone() throws Exception;
    }
    public interface Dispatch { void post(Runnable action); }
    public static final class Failure extends Exception {
        public final String code;
        public Failure(String code) { super(code); this.code = code; }
    }
    public static final int SAMPLE_RATE = 16000, MAX_SAMPLES = SAMPLE_RATE * 30;
    private final Factory factory;
    private final Dispatch dispatch;
    private final ExecutorService worker;
    private boolean occupied, warming;
    private volatile boolean closed;
    private Work running;

    public LocalSpeechWorker(Factory factory, Dispatch dispatch) {
        this(factory, dispatch, Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "libao-local-asr"); t.setDaemon(true); return t;
        }));
    }
    // An injected executor permits deterministic cancellation-before-init checks.
    LocalSpeechWorker(Factory factory, Dispatch dispatch, ExecutorService worker) {
        this.factory = factory; this.dispatch = dispatch; this.worker = worker;
    }
    public SpeechSession.Driver driver(SpeechSession.Callbacks callbacks) { return new Work(callbacks); }
    public synchronized boolean busy() { return occupied; }
    public synchronized boolean warmup(Check check) {
        if (closed || occupied || warming) return false;
        warming = true;
        try {
            worker.execute(() -> {
                try {
                    if (!busy() && !closed && !check.cancelled()) factory.warmup(() -> closed || check.cancelled());
                } catch (Exception | LinkageError ignored) {
                    // An explicit recording still runs its normal, reported initialization.
                } finally {
                    synchronized (LocalSpeechWorker.this) { warming = false; }
                }
            });
        } catch (RejectedExecutionException error) {
            warming = false;
            return false;
        }
        return true;
    }
    private final class Work implements SpeechSession.Driver, Check {
        final SpeechSession.Callbacks callbacks;
        volatile boolean cancelled, stopping;
        boolean started;
        Audio audio;
        Work(SpeechSession.Callbacks callbacks) { this.callbacks = callbacks; }
        public boolean cancelled() { return cancelled; }
        public void start() {
            synchronized (LocalSpeechWorker.this) {
                if (started || cancelled) return;
                started = true;
                if (closed || occupied) { post(() -> callbacks.error("busy")); return; }
                occupied = true; running = this;
                try { worker.execute(this::run); }
                catch (RejectedExecutionException error) {
                    occupied = false; running = null; post(() -> callbacks.error("engine_unavailable"));
                }
            }
        }
        private void post(Runnable action) { dispatch.post(() -> { if (!cancelled && !closed) action.run(); }); }
        public void stop() { end(false); }
        public void cancel() { end(true); }
        public void destroy() { cancel(); }
        private synchronized void end(boolean discard) {
            if (discard) cancelled = true;
            stopping = true;
            // Never join, decode or release native pointers on the UI thread.
            if (audio != null) try { audio.stop(); } catch (RuntimeException ignored) {}
        }
        private void append(StringBuilder text, String segment) throws Failure {
            if (segment == null || segment.trim().isEmpty()) return;
            if (text.length() + segment.length() + 1 > 12000) throw new Failure("too_long");
            if (text.length() > 0) text.append(' ');
            text.append(segment.trim());
        }
        private void run() {
            Decoder decoder = null; Audio input = null;
            short[] pcm = new short[1600];
            String text = null, code = null;
            try {
                if (cancelled) return;
                decoder = factory.open(this); // model copy, hash and native init are off the UI thread
                if (cancelled) return;
                try { input = factory.microphone(); }
                catch (SecurityException | Failure error) { throw error; }
                catch (Exception error) { throw new Failure("audio"); }
                synchronized (this) {
                    // Cancel may happen while the model or AudioRecord is constructed.
                    // After cancel returns, this ticket can never start its microphone.
                    if (cancelled) return;
                    audio = input; input.start();
                }
                post(callbacks::ready); // only after confirmed capture, never during initialization
                int samples = 0, peak = 0, emptyReads = 0, previewAt = 0, previewPeak = 0;
                StringBuilder segments = new StringBuilder();
                while (!cancelled && !stopping) {
                    int n;
                    try { n = input.read(pcm); }
                    catch (Exception error) { if (stopping) break; throw new Failure("audio"); }
                    if (cancelled) return;
                    if (n <= 0) {
                        if (stopping) break;
                        if (n < 0 || ++emptyReads > 10) throw new Failure("audio");
                        continue;
                    }
                    emptyReads = 0;
                    if (n > pcm.length) throw new Failure("audio");
                    if (samples + n > MAX_SAMPLES) throw new Failure("audio_limit");
                    samples += n;
                    for (int i = 0; i < n; i++) previewPeak = Math.max(previewPeak, Math.abs((int) pcm[i]));
                    peak = Math.max(peak, previewPeak);
                    append(segments, decoder.accept(pcm, n));
                    Arrays.fill(pcm, (short) 0);
                    if (samples - previewAt >= SAMPLE_RATE / 5 && !stopping && !cancelled) {
                        previewAt = samples;
                        String current = decoder.preview();
                        String partial = current == null ? "" : current.trim();
                        String draft = segments + (segments.length() > 0 && !partial.isEmpty() ? " " : "") + partial;
                        String preview = draft.substring(0, Math.min(draft.length(), 12000));
                        int level = Math.min(100, previewPeak / 80);
                        previewPeak = 0;
                        post(() -> callbacks.preview(preview, level));
                    }
                }
                if (cancelled) return;
                post(callbacks::end);
                append(segments, decoder.finish());
                text = segments.toString().replaceAll("(?<=[\\u3400-\\u9fff]) +(?=[\\u3400-\\u9fff])", "").trim();
                if (text.isEmpty()) { code = samples == 0 || peak <= 16 ? "no_speech" : "no_match"; text = null; }
            } catch (Failure error) { code = error.code; }
            catch (LinkageError error) { code = "engine_unavailable"; }
            catch (SecurityException error) { code = "permission_denied"; }
            catch (Exception error) { code = decoder == null ? "engine_init" : "engine_error"; }
            finally {
                synchronized (this) { audio = null; }
                if (input != null) try { input.close(); } catch (RuntimeException | LinkageError ignored) {}
                if (decoder != null) try { decoder.close(); } catch (RuntimeException | LinkageError ignored) {}
                Arrays.fill(pcm, (short) 0);
                synchronized (LocalSpeechWorker.this) { occupied = false; if (running == this) running = null; }
            }
            if (cancelled) return;
            final String result = text, failure = code;
            if (failure != null) post(() -> callbacks.error(failure));
            else post(() -> callbacks.result(result));
        }
    }
    public void close() {
        Work old;
        synchronized (this) { if (closed) return; closed = true; old = running; }
        if (old != null) old.cancel();
        // Let queued cancelled work run its finally; no abandoned reserved ticket.
        worker.shutdown();
    }
}
