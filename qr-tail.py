#!/usr/bin/env python3
"""Generate QR Model 2 symbols with byte or alphanumeric segments after terminators."""
import argparse
import ctypes as c
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent


class QRcode(c.Structure):
    _fields_ = [('version', c.c_int), ('width', c.c_int), ('data', c.POINTER(c.c_ubyte))]


def library():
    lib = c.CDLL(str(ROOT / 'build/libqrencode-tail.so'), use_errno=True)
    signatures = {
        'QRinput_new2': ([c.c_int, c.c_int], c.c_void_p),
        'QRinput_append': ([c.c_void_p, c.c_int, c.c_int, c.c_void_p], c.c_int),
        'QRinput_appendECIheader': ([c.c_void_p, c.c_uint], c.c_int),
        'QRinput_free': ([c.c_void_p], None),
        'QRcode_encodeMask': ([c.c_void_p, c.c_int], c.POINTER(QRcode)),
        'QRcode_encodeReplacement': ([c.c_void_p, c.c_void_p, c.c_int, c.POINTER(c.c_int)], c.POINTER(QRcode)),
        'QRcode_encodeReplacementWithMargin': ([c.c_void_p, c.c_void_p, c.c_int, c.c_int, c.POINTER(c.c_int)], c.POINTER(QRcode)),
        'QRcode_free': ([c.POINTER(QRcode)], None),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    return lib


def generate(text, tails=(), ecc='M', version=0, mask=-1, eci=None, replacement=None, diagnostics=None,
             *, tail_mode='byte', min_rs_margin=0):
    if any(not item for item in [text, *tails]):
        raise ValueError('The visible data and each additional group must be nonempty.')
    items = [text, *tails]
    if replacement is not None and not replacement:
        raise ValueError('Replacement data must be nonempty.')
    if ecc not in ('L', 'M', 'Q', 'H') or not 0 <= version <= 40 or not -1 <= mask <= 7:
        raise ValueError('Invalid ECC level, version, or mask.')
    if tail_mode not in ('byte', 'alphanumeric'):
        raise ValueError('Invalid additional segment mode.')
    if type(min_rs_margin) is not int or not 0 <= min_rs_margin <= 15:
        raise ValueError('Minimum RS margin must be an integer in 0..15 codewords per block.')
    if eci is None:
        eci = all(isinstance(item, str) for item in items + ([] if replacement is None else [replacement]))
    payloads = [item.encode('utf-8') if isinstance(item, str) else bytes(item) for item in items]
    target = None if replacement is None else (replacement.encode('utf-8') if isinstance(replacement, str) else bytes(replacement))
    body_length = max(len(payloads[0]), len(target) if target is not None else 0)
    padding_bits = (body_length - len(payloads[0])) * 8 if tails else 0
    alphanumeric = tail_mode == 'alphanumeric'
    if alphanumeric and any(byte not in b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
                            for payload in payloads[1:] for byte in payload):
        raise ValueError('Alphanumeric additional groups must use QR alphanumeric characters.')
    def tail_data_bits(length):
        return (length // 2) * 11 + (length % 2) * 6 if alphanumeric else length * 8
    if not alphanumeric and body_length + sum(map(len, payloads[1:])) > 2953:
        raise ValueError('Input exceeds the maximum QR byte capacity; shorten the input.')
    if alphanumeric and body_length * 8 + sum(tail_data_bits(len(data)) for data in payloads[1:]) > 2956 * 8:
        raise ValueError('Input exceeds the maximum QR data capacity; shorten the input.')
    lib = library()
    inp = lib.QRinput_new2(version, 'LMQH'.index(ecc))
    if not inp:
        raise ValueError('Could not allocate QR input.')
    code = None
    target_inp = None
    try:
        def append_segments(handle, segments):
            if eci and lib.QRinput_appendECIheader(handle, 26) < 0:
                raise ValueError('Could not append UTF-8 ECI.')
            for index, data in enumerate(segments):
                if index and lib.QRinput_append(handle, -1, 0, None) < 0:
                    raise ValueError('Could not append the four-bit terminator.')
                if index == 1:
                    # Extra terminators are padding after the true terminator,
                    # outside the body segment and its byte count.
                    for _ in range((body_length - len(segments[0])) * 2):
                        if lib.QRinput_append(handle, -1, 0, None) < 0:
                            raise ValueError('Could not append post-terminator zero padding.')
                buffer = c.create_string_buffer(data)
                mode = 1 if index and alphanumeric else 2  # QR_MODE_AN / QR_MODE_8
                if lib.QRinput_append(handle, mode, len(data), buffer) < 0:
                    raise ValueError('Could not append data segment.')
        append_segments(inp, payloads)
        if target is None and min_rs_margin == 0:
            code = lib.QRcode_encodeMask(inp, mask)
        else:
            target_inp = lib.QRinput_new2(version, 'LMQH'.index(ecc))
            if not target_inp:
                raise ValueError('Could not allocate replacement QR input.')
            append_segments(target_inp, [payloads[0] if target is None else target, *payloads[1:]])
            stats = (c.c_int * 4)()
            code = lib.QRcode_encodeReplacementWithMargin(inp, target_inp, mask, min_rs_margin, stats)
            if stats[0]:
                if stats[1] > stats[2]:
                    raise ValueError(f'RS block {stats[0]}: {stats[1]} differing data codewords exceed correction limit {stats[2]}.')
                raise ValueError(f'RS block {stats[0]}: remaining correction capacity {stats[2] - stats[1]} '
                                 f'is below required minimum {min_rs_margin} codewords '
                                 f'({stats[1]} differing data codewords, correction limit {stats[2]}).')
            if code and diagnostics is not None:
                diagnostics['min_remaining'] = stats[3]
        if not code:
            raise ValueError('Encoding failed: input may exceed capacity at this ECC level.')
        qr = code.contents
        rows = [[qr.data[y * qr.width + x] & 1 for x in range(qr.width)] for y in range(qr.width)]
        count_bits = 8 if qr.version < 10 else 16
        tail_count_bits = (9 if qr.version < 10 else 11 if qr.version < 27 else 13) if alphanumeric else count_bits
        position = (12 if eci else 0) + 4 + count_bits + len(payloads[0]) * 8
        offsets = []
        for index, payload in enumerate(payloads[1:]):
            offsets.append(position)
            if index == 0:
                position += padding_bits
            position += 4 + 4 + tail_count_bits + tail_data_bits(len(payload))
        if target is not None and diagnostics is not None:
            diagnostics['padding_bits'] = padding_bits
            diagnostics['replacement_padding_bits'] = (body_length - len(target)) * 8 if tails else 0
            diagnostics['replacement_terminator'] = (12 if eci else 0) + 4 + count_bits + len(target) * 8
            diagnostics['tail_offsets'] = [offset + 4 + (padding_bits if index == 0 else 0)
                                           for index, offset in enumerate(offsets)]
        return rows, qr.version, offsets
    finally:
        if code:
            lib.QRcode_free(code)
        lib.QRinput_free(inp)
        if target_inp:
            lib.QRinput_free(target_inp)


def png(rows, scale, margin):
    size = (len(rows) + 2 * margin) * scale
    white = b'\xff' * size
    raster = bytearray()
    for y in range(-margin, len(rows) + margin):
        row = white if not 0 <= y < len(rows) else (
            b'\xff' * (margin * scale) + b''.join(bytes([0 if cell else 255]) * scale for cell in rows[y]) +
            b'\xff' * (margin * scale))
        raster.extend((b'\0' + row) * scale)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 0, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raster)) + chunk(b'IEND', b''))


def output_bytes(rows, suffix, scale, margin):
    if suffix == '.png':
        return png(rows, scale, margin)
    if suffix == '.txt':
        return ('\n'.join(''.join(map(str, row)) for row in rows) + '\n').encode('ascii')
    if suffix == '.svg':
        size = len(rows) + margin * 2
        path = ''.join(f'M{x+margin},{y+margin}h1v1h-1z' for y, row in enumerate(rows) for x, cell in enumerate(row) if cell)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
                f'width="{size*scale}" height="{size*scale}" shape-rendering="crispEdges">'
                f'<path fill="white" d="M0,0h{size}v{size}H0z"/><path fill="black" d="{path}"/></svg>\n').encode('ascii')
    raise ValueError('Output extension must be .png, .svg, or .txt.')


def parse_hex(value):
    try:
        data = bytes.fromhex(value)
    except ValueError:
        raise argparse.ArgumentTypeError('HEX must contain pairs of hexadecimal digits, optionally separated by ASCII whitespace; no 0x prefix.') from None
    if not data:
        raise argparse.ArgumentTypeError('HEX data must not be empty.')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='HEX bytes are stored exactly. If any HEX input is used, UTF-8 ECI is omitted for the whole symbol; text inputs still use UTF-8 bytes.')
    visible = parser.add_mutually_exclusive_group(required=True)
    visible.add_argument('--hex', type=parse_hex, help='Visible binary data as HEX, e.g. "00 FF 80".')
    visible.add_argument('--text', help='Visible text (UTF-8).')
    visible.add_argument('--text-file', type=Path, help='Read visible UTF-8 text without trimming newlines.')
    replacement = parser.add_mutually_exclusive_group()
    replacement.add_argument('--ecc-hex', type=parse_hex, help='Use replacement HEX bytes to calculate ECC; scanners recover these bytes.')
    replacement.add_argument('--ecc-text', help='Use replacement UTF-8 text to calculate ECC; scanners recover this text.')
    replacement.add_argument('--ecc-text-file', type=Path, help='Read replacement UTF-8 text without trimming newlines.')
    hidden = parser.add_mutually_exclusive_group()
    hidden.add_argument('--tail-hex', type=parse_hex, action='append', help='Additional binary group as HEX; repeat for multiple terminators.')
    hidden.add_argument('--tail', action='append', help='Additional UTF-8 group; repeat for multiple terminators.')
    hidden.add_argument('--tail-file', type=Path, action='append', help='Read additional UTF-8 group from a file; repeat as needed.')
    parser.add_argument('--tail-mode', choices=['byte', 'alphanumeric'], default='byte',
                        help='Encoding mode for all additional groups, independent of the body (default: byte).')
    parser.add_argument('-o', '--output', required=True, type=Path, help='Output .png, .svg, or matrix .txt.')
    parser.add_argument('--ecc', choices=list('LMQH'), default='M')
    parser.add_argument('--min-rs-margin', type=int, choices=range(16), default=0, metavar='0..15',
                        help='Minimum remaining correction capacity in every RS block, in codewords (default: 0); no automatic version search.')
    parser.add_argument('--version', type=int, choices=range(0, 41), default=0, metavar='0..40', help='Minimum version; 0 selects automatically.')
    parser.add_argument('--mask', type=int, choices=range(-1, 8), default=-1, metavar='-1..7', help='-1 selects automatically.')
    parser.add_argument('--scale', type=int, default=8, help='Pixels per module (1..32).')
    parser.add_argument('--margin', type=int, default=4, help='Quiet zone in modules (4..16).')
    parser.add_argument('--no-eci', action='store_true', help='Omit UTF-8 ECI; reader encoding guesses may differ.')
    parser.add_argument('--force', action='store_true', help='Replace an existing output file.')
    args = parser.parse_args()
    try:
        if not 1 <= args.scale <= 32 or not 4 <= args.margin <= 16:
            raise ValueError('Scale must be 1..32 and margin 4..16.')
        if args.output.suffix.lower() not in ('.png', '.svg', '.txt'):
            raise ValueError('Output extension must be .png, .svg, or .txt.')
        def read(path):
            return path.read_bytes().decode('utf-8')
        text = args.hex if args.hex is not None else (args.text if args.text is not None else read(args.text_file))
        tails = args.tail_hex if args.tail_hex is not None else (args.tail if args.tail is not None else [read(path) for path in (args.tail_file or [])])
        if len(tails) > 16:
            raise ValueError('At most 16 additional groups are supported.')
        replacement = args.ecc_hex if args.ecc_hex is not None else (args.ecc_text if args.ecc_text is not None else
                      read(args.ecc_text_file) if args.ecc_text_file is not None else None)
        diagnostics = {}
        rows, version, offsets = generate(text, tails, args.ecc, args.version, args.mask,
                                          False if args.no_eci else None, replacement, diagnostics,
                                          tail_mode=args.tail_mode, min_rs_margin=args.min_rs_margin)
        data = output_bytes(rows, args.output.suffix.lower(), args.scale, args.margin)
        with args.output.open('wb' if args.force else 'xb') as stream:
            stream.write(data)
        print(f'{args.output}: version {version}, ECC {args.ecc}, {len(rows)}x{len(rows)} modules')
        if tails:
            print('Four-bit terminator starts (zero-based data bits): ' + ', '.join(map(str, offsets)))
        if replacement is not None:
            if tails:
                print('ECC replacement enabled; terminator offsets above describe data before RS correction.')
                print(f'First terminator after RS correction: {diagnostics["replacement_terminator"]}')
                print('Additional segment starts (shared before/after RS correction, zero-based data bits): ' +
                      ', '.join(map(str, diagnostics['tail_offsets'])))
                print(f'Post-terminator zero padding: original {diagnostics["padding_bits"]} bits, '
                      f'replacement {diagnostics["replacement_padding_bits"]} bits')
            else:
                print('ECC replacement enabled.')
        if replacement is not None or args.min_rs_margin:
            print(f'Minimum remaining RS correction capacity: {diagnostics["min_remaining"]} codewords per block')
    except (OSError, ValueError) as error:
        parser.exit(2, f'error: {error}\n')


if __name__ == '__main__':
    main()
