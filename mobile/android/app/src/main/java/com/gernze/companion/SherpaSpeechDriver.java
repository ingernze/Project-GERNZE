package com.gernze.companion;

import android.content.Context;
import android.content.res.AssetManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import com.k2fsa.sherpa.onnx.OnlineModelConfig;
import com.k2fsa.sherpa.onnx.OnlineRecognizer;
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig;
import com.k2fsa.sherpa.onnx.OnlineStream;
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig;
import java.util.Arrays;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/** Thin adapter to the official sherpa-onnx Android AAR. */
final class SherpaSpeechDriver implements LocalSpeechWorker.Factory {
    private static final int SAMPLE_RATE = LocalSpeechWorker.SAMPLE_RATE;
    private static final int FOREGROUND_IDLE_MINUTES = 3;
    private final Context context;
    private final ScheduledExecutorService cacheWorker = Executors.newSingleThreadScheduledExecutor(task -> {
        Thread thread = new Thread(task, "libao-asr-cache");
        thread.setDaemon(true);
        return thread;
    });
    private OnlineRecognizer idleRecognizer;
    private ScheduledFuture<?> expiry;
    private long cacheVersion;
    private boolean allowCache = true, closed;
    SherpaSpeechDriver(Context context) { this.context = context; }

    private synchronized OnlineRecognizer takeCached() {
        cacheVersion++;
        if (expiry != null) expiry.cancel(false);
        expiry = null;
        OnlineRecognizer result = idleRecognizer;
        idleRecognizer = null;
        return result;
    }
    private synchronized void retain(OnlineRecognizer recognizer) {
        if (closed || !allowCache) {
            recognizer.release(); // Called by the ASR worker after its stream closes.
            return;
        }
        idleRecognizer = recognizer;
        long version = ++cacheVersion;
        expiry = cacheWorker.schedule(() -> expire(version), FOREGROUND_IDLE_MINUTES, TimeUnit.MINUTES);
    }
    private void expire(long version) {
        OnlineRecognizer old;
        synchronized (this) {
            if (version != cacheVersion) return;
            old = idleRecognizer;
            idleRecognizer = null;
            expiry = null;
        }
        if (old != null) old.release();
    }
    synchronized void setForeground(boolean foreground) {
        allowCache = foreground && !closed;
        if (allowCache) return;
        cacheVersion++;
        if (expiry != null) expiry.cancel(false);
        expiry = null;
        OnlineRecognizer old = idleRecognizer;
        idleRecognizer = null;
        if (old != null) cacheWorker.execute(old::release);
    }
    synchronized void close() {
        if (closed) return;
        closed = true;
        setForeground(false);
        cacheWorker.shutdown();
    }

    private OnlineRecognizer createRecognizer(LocalSpeechWorker.Check check) throws Exception {

        AssetManager assets = SherpaModelAssets.verify(context, check);
        String root = SherpaModelAssets.ROOT;
        OnlineTransducerModelConfig transducer = new OnlineTransducerModelConfig();
        transducer.setEncoder(root + "encoder-epoch-99-avg-1.int8.onnx");
        transducer.setDecoder(root + "decoder-epoch-99-avg-1.onnx");
        transducer.setJoiner(root + "joiner-epoch-99-avg-1.int8.onnx");
        OnlineModelConfig model = new OnlineModelConfig();
        model.setTransducer(transducer);
        model.setTokens(root + "tokens.txt");
        model.setNumThreads(1);
        model.setProvider("cpu");
        model.setModelType("zipformer");
        OnlineRecognizerConfig config = new OnlineRecognizerConfig();
        config.getFeatConfig().setSampleRate(SAMPLE_RATE);
        config.getFeatConfig().setFeatureDim(80);
        config.setModelConfig(model);
        // The existing explicit Stop button defines the utterance boundary.
        config.setEnableEndpoint(false);
        config.setDecodingMethod("greedy_search");
        if (check.cancelled()) throw new LocalSpeechWorker.Failure("cancelled");
        return new OnlineRecognizer(assets, config);
    }

    @Override public void warmup(LocalSpeechWorker.Check check) throws Exception {
        synchronized (this) {
            if (closed || !allowCache || idleRecognizer != null) return;
        }
        if (check.cancelled()) return;
        OnlineRecognizer recognizer = createRecognizer(check);
        if (check.cancelled()) recognizer.release();
        else retain(recognizer);
    }

    public LocalSpeechWorker.Decoder open(LocalSpeechWorker.Check check) throws Exception {
        OnlineRecognizer cached = takeCached();
        final OnlineRecognizer recognizer = cached != null ? cached : createRecognizer(check);
        OnlineStream stream;
        try {
            if (check.cancelled()) throw new LocalSpeechWorker.Failure("cancelled");
            stream = recognizer.createStream("");
        } catch (Exception | LinkageError error) {
            recognizer.release();
            throw error;
        }
        return new LocalSpeechWorker.Decoder() {
            private void decodeReady() {
                while (!check.cancelled() && recognizer.isReady(stream)) recognizer.decode(stream);
            }

            public String accept(short[] pcm, int count) {
                float[] samples = new float[count];
                for (int i = 0; i < count; i++) samples[i] = pcm[i] / 32768.0f;
                try {
                    stream.acceptWaveform(samples, SAMPLE_RATE);
                    decodeReady();
                } finally {
                    Arrays.fill(samples, 0.0f);
                }
                return null;
            }

            public String preview() {
                return check.cancelled() ? "" : recognizer.getResult(stream).getText();
            }

            public String finish() {
                if (check.cancelled()) return null;
                // 0.66 seconds of zeros flushes the model's right context.
                stream.acceptWaveform(new float[10560], SAMPLE_RATE);
                stream.inputFinished();
                decodeReady();
                return check.cancelled() ? null : recognizer.getResult(stream).getText();
            }

            public void close() {
                try { stream.release(); }
                finally { retain(recognizer); }
            }
        };
    }

    public LocalSpeechWorker.Audio microphone() throws Exception {
        int rate = LocalSpeechWorker.SAMPLE_RATE;
        int min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (min <= 0) throw new LocalSpeechWorker.Failure("audio");
        AudioRecord recorder = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, rate,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min * 2, 16000));
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            recorder.release(); throw new LocalSpeechWorker.Failure("audio");
        }
        return new LocalSpeechWorker.Audio() {
            public void start() throws Exception {
                recorder.startRecording();
                if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING)
                    throw new LocalSpeechWorker.Failure("audio");
            }
            public int read(short[] pcm) { return recorder.read(pcm, 0, pcm.length); }
            public void stop() { if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) recorder.stop(); }
            public void close() { try { stop(); } finally { recorder.release(); } }
        };
    }
}
