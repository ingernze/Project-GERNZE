package com.gernze.companion.updates.transport;

import java.io.DataInputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;

/** Reconstruct exact signed APK bytes from bounded copy and literal operations. */
final class ApkDelta {
    interface Check { void run() throws Exception; }
    interface Progress { void update(long received) throws Exception; }
    private static final long MAX_SIZE = 536870912L;
    private static final int MAX_OPS = 8192;
    private static final byte[] MAGIC = "GZDELTA1".getBytes(StandardCharsets.US_ASCII);

    static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    static String hash(RandomAccessFile source, Check check) throws Exception {
        long size = source.length();
        require(size > 0 && size <= MAX_SIZE);
        source.seek(0);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[65536];
        long read = 0;
        int count;
        while ((count = source.read(buffer)) != -1) {
            check.run();
            read += count;
            require(read <= size);
            digest.update(buffer, 0, count);
        }
        require(read == size && source.length() == size);
        return hex(digest.digest());
    }

    private static void require(boolean valid) throws IOException {
        if (!valid) throw new IOException("invalid APK delta");
    }

    private static final class Counted extends FilterInputStream {
        long count;
        final long limit;
        Counted(InputStream input, long limit) { super(input); this.limit = limit; }
        @Override public int read() throws IOException {
            int value = in.read();
            if (value >= 0) { count++; require(count <= limit); }
            return value;
        }
        @Override public int read(byte[] buffer, int offset, int length) throws IOException {
            int countRead = in.read(buffer, offset, length);
            if (countRead > 0) { count += countRead; require(count <= limit); }
            return countRead;
        }
    }

    static void apply(RandomAccessFile base, String baseHash, String targetHash, long targetSize,
                      InputStream patch, long wireSize, OutputStream output,
                      Check check, Progress progress) throws Exception {
        require(targetSize > 0 && targetSize <= MAX_SIZE && wireSize >= 92 && wireSize <= MAX_SIZE);
        Counted counted = new Counted(patch, wireSize);
        DataInputStream input = new DataInputStream(counted);
        byte[] magic = new byte[8], oldHash = new byte[32], newHash = new byte[32];
        input.readFully(magic);
        require(Arrays.equals(magic, MAGIC));
        long oldSize = input.readLong();
        input.readFully(oldHash);
        long newSize = input.readLong();
        input.readFully(newHash);
        int operations = input.readInt();
        require(oldSize == base.length() && oldSize > 0 && oldSize <= MAX_SIZE);
        require(hex(oldHash).equals(baseHash) && newSize == targetSize && hex(newHash).equals(targetHash));
        require(operations > 0 && operations <= MAX_OPS);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[65536];
        long written = 0;
        for (int op = 0; op < operations; op++) {
            check.run();
            int kind = input.readUnsignedByte();
            long start = 0;
            if (kind == 0) start = input.readLong();
            require(kind == 0 || kind == 1);
            long length = input.readLong();
            require(length > 0 && length <= targetSize - written);
            if (kind == 0) {
                require(start >= 0 && start <= oldSize && length <= oldSize - start);
                base.seek(start);
            }
            long remaining = length;
            while (remaining > 0) {
                check.run();
                int count = (int)Math.min(buffer.length, remaining);
                if (kind == 0) base.readFully(buffer, 0, count);
                else input.readFully(buffer, 0, count);
                output.write(buffer, 0, count);
                digest.update(buffer, 0, count);
                written += count;
                remaining -= count;
                progress.update(counted.count);
            }
        }
        require(written == targetSize && counted.count == wireSize && input.read() == -1);
        require(hex(digest.digest()).equals(targetHash));
        check.run();
    }
}
