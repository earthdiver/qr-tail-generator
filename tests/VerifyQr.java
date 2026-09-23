import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import javax.imageio.ImageIO;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.decoder.Decoder;

public class VerifyQr {
    public static void main(String[] args) throws Exception {
        var image = ImageIO.read(new File(args[0]));
        int scale = Integer.parseInt(args[1]);
        int margin = Integer.parseInt(args[2]);
        int size = image.getWidth() / scale - 2 * margin;
        var matrix = new BitMatrix(size);
        for (int y = 0; y < size; y++) for (int x = 0; x < size; x++) {
            if ((image.getRGB((x + margin) * scale + scale / 2, (y + margin) * scale + scale / 2) & 0xFFFFFF) == 0)
                matrix.set(x, y);
        }
        var result = new Decoder().decode(matrix.clone());
        System.out.println(Base64.getEncoder().encodeToString(result.getText().getBytes(StandardCharsets.UTF_8)));
        System.out.println(Base64.getEncoder().encodeToString(result.getRawBytes()));
        com.google.zxing.qrcode.decoder.InspectQr.print(matrix, result.getRawBytes());
    }
}
