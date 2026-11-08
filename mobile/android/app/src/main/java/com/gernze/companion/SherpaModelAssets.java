package com.gernze.companion;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.Properties;

/** Pinned files in the app's read-only assets. No runtime download or extraction. */
final class SherpaModelAssets {
    static final String ROOT = "stt/sherpa-zipformer-bilingual/";
    static final String MODEL = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20";
    private static final String REVISION = "98590b7ed6443e77b714204da2757d75e1a642f4";
    private static final ModelFile[] FILES = {
        new ModelFile("encoder-epoch-99-avg-1.int8.onnx", 181895032L, "8fa764187a261844f859d7143ebaa563af5d10adfece4c18a8f414c88cba2a9b"),
        new ModelFile("decoder-epoch-99-avg-1.onnx", 13876452L, "2e3b5ec371f8899ee6acd829fd753ba45772df57a91bdf37cde3136354e7db7d"),
        new ModelFile("joiner-epoch-99-avg-1.int8.onnx", 3228404L, "1ed689c5ed19dbaa725d9d191bb4822b5f4855a39e1ffd28cbc1f340d25b2ee0"),
        new ModelFile("tokens.txt", 56317L, "a8e0e4ec53810e433789b54a5c0134a7eaa2ffca595a6334d54c00da858841d3"),
    };
    // The verified AssetManager belongs to this installed APK. An app update
    // starts a new process. We retain no recognizer, stream, audio or text here.
    private static volatile AssetManager verified;

    private static final class ModelFile {
        final String name;
        final long bytes;
        final String sha256;
        ModelFile(String name, long bytes, String sha256) {
            this.name = name;
            this.bytes = bytes;
            this.sha256 = sha256;
        }
    }

    static String unavailableCode(Context context) {
        try {
            checkAssets(context.getAssets());
            return null;
        } catch (LocalSpeechWorker.Failure error) {
            return error.code;
        } catch (IOException error) {
            return "model_missing";
        }
    }

    private static void checkAssets(AssetManager assets) throws IOException, LocalSpeechWorker.Failure {
        Properties properties = new Properties();
        try (InputStream input = assets.open(ROOT + "model-files.properties")) {
            properties.load(input);
        } catch (IllegalArgumentException error) {
            throw new LocalSpeechWorker.Failure("model_invalid");
        }
        if (!MODEL.equals(properties.getProperty("model")) || !REVISION.equals(properties.getProperty("revision"))) {
            throw new LocalSpeechWorker.Failure("model_invalid");
        }
        for (ModelFile file : FILES) {
            if (!file.sha256.equals(properties.getProperty(file.name + ".sha256"))) {
                throw new LocalSpeechWorker.Failure("model_invalid");
            }
            try (InputStream input = assets.open(ROOT + file.name)) {
                if (input.read() < 0) throw new LocalSpeechWorker.Failure("model_invalid");
            }
        }
    }

    static AssetManager verify(Context context, LocalSpeechWorker.Check check) throws Exception {
        AssetManager assets = context.getAssets();
        if (check.cancelled()) throw new LocalSpeechWorker.Failure("cancelled");
        if (verified == assets) return assets;
        try {
            checkAssets(assets);
            byte[] buffer = new byte[65536];
            for (ModelFile file : FILES) {
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                long bytes = 0;
                try (InputStream input = assets.open(ROOT + file.name)) {
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (check.cancelled()) throw new LocalSpeechWorker.Failure("cancelled");
                        bytes += count;
                        if (bytes > file.bytes) throw new LocalSpeechWorker.Failure("model_invalid");
                        digest.update(buffer, 0, count);
                    }
                }
                StringBuilder hash = new StringBuilder(64);
                for (byte value : digest.digest()) hash.append(String.format(Locale.ROOT, "%02x", value & 255));
                if (bytes != file.bytes || !file.sha256.contentEquals(hash)) {
                    throw new LocalSpeechWorker.Failure("model_invalid");
                }
            }
        } catch (IOException error) {
            throw new LocalSpeechWorker.Failure("model_missing");
        }
        if (check.cancelled()) throw new LocalSpeechWorker.Failure("cancelled");
        verified = assets;
        return assets;
    }
}
