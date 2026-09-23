# QR post-terminator generator

A standalone Linux/WSL CLI. It uses Kentaro Fukuchi's libqrencode `invalid_null` branch to encode UTF-8 ECI, visible byte data, a four-bit terminator, and additional segments (byte mode by default). Each additional group is separated by a terminator. Error correction covers the entire encoded data stream.

See [the Japanese guide](README.ja.md) for detailed usage.

## Run

`qr-tail.py` requires Python 3, Git, and a C compiler (`cc`). Only initial library retrieval needs network access. Generation is offline and requires no third-party Python packages or system installation.

```bash
./build.sh
./qr-tail.py --text 'VISIBLE' --tail 'HIDDEN' -o sample.png
./qr-tail.py --text 'VISIBLE' --tail 'FIRST' --tail 'SECOND' -o multiple.svg
./qr-tail.py --text-file body.txt --tail-file extra.txt -o matrix.txt
./qr-tail.py --help
```

Outputs: PNG, SVG, or a borderless 0/1 text matrix. Defaults: ECC M, automatic version and mask, eight pixels per module, four-module quiet zone, explicit UTF-8 ECI. `--version` sets a minimum, not a fixed size. `--no-eci` omits UTF-8 ECI. `--force` permits overwriting an existing file. Input files preserve newlines and NUL characters. Visible data and each additional group must be nonempty. At most 16 additional groups are accepted, subject to QR capacity. FNC1, other encodings, and selectable body modes or numeric/Kanji tail modes are not exposed.

Ordinary readers stop at the first terminator and show visible text only. Strict readers may reject the noncanonical suffix. Additional data is not encrypted; this is not SQRC. Validation uses independent ZXing decoding and raw data checks.

## Additional segment modes

Use `--tail-mode byte|alphanumeric` to select the mode for all additional groups. The default is `byte`. The body always remains in byte mode, independent of the tail mode.

```bash
./qr-tail.py --text 'Visible body' --tail 'ORDER 123' --tail 'TOTAL $45.00' \
  --tail-mode alphanumeric -o alphanumeric.png
```

Alphanumeric mode accepts the 45 characters `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:`. Lowercase, non-ASCII text, newlines, and NUL are rejected without creating or overwriting output. No case conversion is performed. This also works with `--tail-file` and `--tail-hex`; decoded HEX bytes must belong to the same alphabet. Input type and encoding mode are independent, and HEX inputs retain the existing ECI omission rule.

Pairs consume 11 bits and a final unpaired character consumes 6 bits. The count field uses 9 bits for versions 1–9, 11 for 10–26, and 13 for 27–40. Replacement ECC uses the same tail mode and preserves alignment for unequal body lengths.

Python callers can use `generate(..., tail_mode='alphanumeric')`. The feature has no dependency on a particular data format or encryption scheme.

## Binary HEX input

```bash
./qr-tail.py --text 'VISIBLE' --tail-hex '00 FF 80 FE' -o binary-tail.png
./qr-tail.py --hex '00FF8041' --tail-hex 'DE AD BE EF' -o binary.png
./qr-tail.py --text 'VISIBLE' --tail-hex '00FF' --tail-hex '8081' -o two-tails.png
```

`--hex` supplies visible binary data; repeat `--tail-hex` for additional binary groups. Bytes are stored exactly; byte mode is the default. Upper/lowercase hexadecimal pairs and ASCII whitespace between bytes are accepted. Empty input, odd digits, `0x` prefixes, colons, and non-hexadecimal characters are rejected.

Choose one visible input type (`--text`, `--text-file`, or `--hex`) and one additional input type (`--tail`, `--tail-file`, or `--tail-hex`). The same additional option may be repeated; different additional option types cannot be mixed. Text in one part and HEX in the other are supported.

If any HEX input is used, UTF-8 ECI is automatically omitted for the entire symbol. Text inputs still become UTF-8 bytes, so their displayed encoding depends on reader heuristics; stored bytes remain exact. Text-only input retains the existing UTF-8 ECI default unless `--no-eci` is set. Inspect binary data as HEX rather than relying on decoded text.

## Replacement error correction

Run `./build.sh` again after updating to build the C extension.

```bash
./qr-tail.py --text 'H3llo W0rld!' --ecc-text 'Hello World.' --tail 'HIDDEN' -o replacement.png
./qr-tail.py --hex '48336C6C6F205730726C6421' --ecc-hex '48656C6C6F20576F726C642E' --tail-hex '00FF' -o replacement.svg
./qr-tail.py --text-file original.txt --ecc-text-file replacement.txt --tail 'HIDDEN' -o replacement.txt
```

Choose at most one of `--ecc-text`, `--ecc-text-file`, and `--ecc-hex`. These options store the original body in the data region but generate parity using the replacement body and the same additional groups. Ordinary scanners correct the body to the replacement: the first example stores `H3llo W0rld!` but reads as `Hello World.`. Parity covers the entire stream, including post-terminator data. Omitting these options preserves existing behavior.

Replacement data must be nonempty. Different body lengths are allowed; UTF-8 files preserve newlines and NUL. Lengths are compared in bytes after UTF-8 encoding. After the shorter body's first four-bit terminator, two extra `0000` groups are added per byte of difference. The first additional segment starts immediately after the longer body's terminator in both streams; subsequent groups and final padding also stay aligned. Padding is outside the body count and adds no NUL characters to the decoded body. This also applies to HEX input. `--ecc-hex` also triggers the existing rule that any HEX input disables automatic UTF-8 ECI for the whole symbol.

Both streams are encoded at a shared version that fits both inputs. For each RS block, the number of differing 8-bit data codewords must be at most half its ECC codeword count, rounded down. Differences include count headers, terminators, additional groups, and padding, not just changed characters. Exceeding any block's limit reports the block number, differences, and limit, exits with code 2, and leaves output files untouched even with `--force`.

`--version` remains a minimum. Capacity can increase the version, but the generator does not search larger versions or change ECC levels to satisfy the correction limit. Mask selection uses the combined original data and replacement parity.

Reported terminator offsets refer to data **before correction**. The corrected first terminator offset is reported separately because it depends on the replacement body length. Additional segment offsets are shared before/after correction; the CLI reports these offsets and both post-terminator padding lengths in bits. The CLI also reports the minimum remaining correction capacity across blocks. Zero remaining capacity is accepted, but intentional differences consume correction capacity that would otherwise protect against scanning errors. Binary text display and readers that reject post-terminator data remain reader-dependent.

Custom post-terminator parsers must skip `0000` groups in four-bit steps until the next mode indicator (`0100` for byte or `0010` for alphanumeric), then decode its count field and payload. Zeros inside the payload must not be skipped. Ordinary scanners stop at the first terminator. Existing tools that expect an additional segment immediately after that terminator need padding support.

## Verify

Requires a JDK and a ZXing core JAR (tested with 3.5.4):

```bash
python3 tests/verify.py --zxing-jar /path/to/core-3.5.4.jar
```

The checks decode generated PNGs with ZXing and inspect the RS-corrected data bytes, verifying visible text, exact terminator positions, additional groups, and final padding. Coverage includes all eight masks, all ECC levels, Japanese, multiple groups, versions above 9, NUL, preserved newlines, all 256 byte values, mixed text/HEX parts, and invalid HEX rejection.

Replacement tests independently extract uncorrected data and parity with ZXing, verifying that stored data matches the original stream, parity matches the replacement, and the entire corrected stream matches the replacement including additional groups and padding. Coverage includes all ECC levels × all eight masks with long tails and length changes in both directions, UTF-8 byte-length differences, post-terminator padding and bit-identical tails/final padding, the version 9/10 boundary, success exactly at the correction limit, rejection one codeword above the limit, per-block overflow, and output preservation on errors.

## Sources and license

- [Fukuchi's explanation](https://fukuchi.org/works/qrhack/qrhack1/)
- [libqrencode invalid_null](https://github.com/fukuchi/libqrencode/tree/invalid_null), pinned to `2d71c3b90185b85ca0e7530d128cb8ea175192c0`

The dynamically loaded library and its extension `qr-tail-encode.c` are LGPL-2.1-or-later; upstream source and license remain unchanged in `vendor/libqrencode`. The CLI, build script, and tests in this directory are MIT-licensed; see LICENSE.
