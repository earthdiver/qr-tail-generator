package com.google.zxing.qrcode.decoder;

import java.io.ByteArrayOutputStream;
import java.util.Base64;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.common.reedsolomon.GenericGF;
import com.google.zxing.common.reedsolomon.ReedSolomonEncoder;

/** Inspect uncorrected, deinterleaved codewords using ZXing's QR parser. */
public class InspectQr {
    public static void print(BitMatrix matrix, byte[] corrected) throws Exception {
        var parser = new BitMatrixParser(matrix.clone());
        var version = parser.readVersion();
        var level = parser.readFormatInformation().getErrorCorrectionLevel();
        var blocks = DataBlock.getDataBlocks(parser.readCodewords(), version, level);
        var data = new ByteArrayOutputStream();
        var ecc = new ByteArrayOutputStream();
        var expectedEcc = new ByteArrayOutputStream();
        var encoder = new ReedSolomonEncoder(GenericGF.QR_CODE_FIELD_256);
        int offset = 0;
        var lengths = new StringBuilder();
        for (var block : blocks) {
            int n = block.getNumDataCodewords();
            byte[] words = block.getCodewords();
            data.write(words, 0, n);
            ecc.write(words, n, words.length - n);
            int[] expected = new int[words.length];
            for (int i = 0; i < n; i++) expected[i] = corrected[offset++] & 0xFF;
            encoder.encode(expected, words.length - n);
            for (int i = n; i < words.length; i++) expectedEcc.write(expected[i]);
            if (lengths.length() > 0) lengths.append(",");
            lengths.append(n).append(":").append(words.length - n);
        }
        System.out.println(Base64.getEncoder().encodeToString(data.toByteArray()));
        System.out.println(Base64.getEncoder().encodeToString(ecc.toByteArray()));
        System.out.println(lengths);
        System.out.println(Base64.getEncoder().encodeToString(expectedEcc.toByteArray()));
    }
}
