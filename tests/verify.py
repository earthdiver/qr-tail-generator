#!/usr/bin/env python3
"""Independently decode PNGs and inspect RS-corrected data using ZXing."""
import argparse
import base64
import importlib.util
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qr_tail', root / 'qr-tail.py')
qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qr)
parser = argparse.ArgumentParser()
parser.add_argument('--zxing-jar', required=True, type=Path)
args = parser.parse_args()
jar = args.zxing_jar.resolve()
with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp)
    subprocess.run(['javac', '-cp', str(jar), '-d', temp, str(root / 'tests/VerifyQr.java'),
                    str(root / 'tests/InspectQr.java')], check=True)
    cases = [('VISIBLE', ['HIDDEN', 'SECOND'], 0, mask, False, 'LMQH'[mask % 4]) for mask in range(8)]
    cases += [('通常の本文', ['終端後の文字列', '別の追加文字列'], 0, -1, True, 'M'),
              ('VISIBLE\x00BODY', ['tail\x00text\nline'], 10, 0, True, 'Q'),
              ('LONG' * 150, ['tail' * 120], 27, 7, True, 'H')]
    for index, (text, tails, minimum, mask, eci, ecc) in enumerate(cases):
        rows, version, offsets = qr.generate(text, tails, ecc, minimum, mask, eci)
        image = directory / f'{index}.png'
        image.write_bytes(qr.png(rows, 3, 4))
        result = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(image), '3', '4'],
                                capture_output=True, text=True, check=True).stdout.splitlines()
        assert base64.b64decode(result[0]).decode('utf-8') == text
        bits = ''.join(f'{byte:08b}' for byte in base64.b64decode(result[1]))
        position = 0
        def take(width):
            global position
            value = int(bits[position:position+width], 2)
            position += width
            return value
        if eci:
            assert take(4) == 7 and take(8) == 26
        for group, value in enumerate([text, *tails]):
            if group:
                assert position == offsets[group-1]
                assert take(4) == 0
            assert take(4) == 4
            count = take(8 if version < 10 else 16)
            recovered = bytes(take(8) for _ in range(count))
            assert recovered == value.encode('utf-8')
        terminator_size = min(4, len(bits) - position)
        if terminator_size:
            assert take(terminator_size) == 0
        while position % 8 and position < len(bits):
            assert take(1) == 0
        expected = 0xEC
        while position < len(bits):
            assert take(8) == expected
            expected ^= 0xFD
        print(f'PASS case {index+1}: V{version}, ECC {ecc}, mask {mask}, {len(tails)} additional groups')
    out = directory / 'cli.png'
    command = [str(root/'qr-tail.py'), '--text', 'BODY', '--tail', 'TAIL', '-o', str(out)]
    subprocess.run(command, check=True, capture_output=True)
    original = out.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert out.read_bytes() == original
    source = directory/'text.txt'
    source.write_bytes('本文\r\n'.encode())
    subprocess.run([str(root/'qr-tail.py'), '--text-file', str(source), '--tail-file', str(source),
                    '-o', str(directory/'files.png')], check=True, capture_output=True)
    decoded = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(directory/'files.png'), '8', '4'],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert base64.b64decode(decoded[0]).decode() == '本文\r\n'
    print('PASS CLI output overwrite protection and exact UTF-8 file input')
    binary_cases = [
        (['--text', '本文', '--tail-hex', '00 FF 80 FE', '--tail-hex', 'deadbeef'],
         ['本文'.encode(), bytes.fromhex('00ff80fe'), bytes.fromhex('deadbeef')]),
        (['--hex', bytes(range(256)).hex(), '--tail-hex', '00\tFF\n80'],
         [bytes(range(256)), bytes.fromhex('00ff80')]),
        (['--hex', '0041FF', '--tail', '追加文字列'], [bytes.fromhex('0041ff'), '追加文字列'.encode()]),
    ]
    for index, (options, expected_groups) in enumerate(binary_cases):
        output = directory / f'binary-{index}.png'
        subprocess.run([str(root/'qr-tail.py'), *options, '-o', str(output)], check=True, capture_output=True)
        decoded = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(output), '8', '4'],
                                 capture_output=True, text=True, check=True).stdout.splitlines()
        # Derive the symbol version from PNG dimensions, independently of the CLI report.
        import struct
        width = struct.unpack('>I', output.read_bytes()[16:20])[0]
        version = (width // 8 - 8 - 17) // 4
        bits = ''.join(f'{byte:08b}' for byte in base64.b64decode(decoded[1]))
        position = 0
        for group, expected in enumerate(expected_groups):
            if group:
                assert take(4) == 0
            assert take(4) == 4  # No automatic UTF-8 ECI for binary input.
            count = take(8 if version < 10 else 16)
            assert bytes(take(8) for _ in range(count)) == expected
        print(f'PASS binary CLI case {index+1}: exact payload bytes and no automatic ECI')
    for bad_hex in ['', ' ', '0', '0 0', '0xFF', 'GG', 'FF:00']:
        output = directory/'invalid.png'
        result = subprocess.run([str(root/'qr-tail.py'), '--text', 'BODY', '--tail-hex', bad_hex,
                                 '-o', str(output)], capture_output=True, text=True)
        assert result.returncode == 2 and not output.exists()
    result = subprocess.run([str(root/'qr-tail.py'), '--text', 'BODY', '--tail', 'TEXT', '--tail-hex', '00',
                             '-o', str(directory/'mixed.png')], capture_output=True, text=True)
    assert result.returncode == 2 and not (directory/'mixed.png').exists()
    print('PASS invalid HEX and conflicting tail options rejected without output')

    def inspect(rows):
        image = directory / 'inspect.png'
        image.write_bytes(qr.png(rows, 3, 4))
        lines = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(image), '3', '4'],
                               capture_output=True, text=True, check=True).stdout.splitlines()
        return [base64.b64decode(line) for line in [*lines[:4], lines[5]]], [tuple(map(int, b.split(':'))) for b in lines[4].split(',')]

    def check_replacement(body, target, tails, ecc='M', version=0, mask=-1, eci=None):
        stats = {}
        rows, actual_version, offsets = qr.generate(body, tails, ecc, version, mask, eci, target, stats)
        shared_eci = eci if eci is not None else all(isinstance(x, str) for x in [body, target, *tails])
        before = qr.generate(body, tails, ecc, actual_version, mask, shared_eci)
        after = qr.generate(target, tails, ecc, actual_version, mask, shared_eci)
        mixed, blocks = inspect(rows)
        expected, _ = inspect(after[0])
        def to_bytes(value):
            return value.encode('utf-8') if isinstance(value, str) else bytes(value)
        body_bytes, target_bytes = to_bytes(body), to_bytes(target)
        longest = max(len(body_bytes), len(target_bytes))
        count_bits = 8 if actual_version < 10 else 16
        # Independent bitstream construction, including zero padding outside
        # the body count, multiple tail segments, and final QR pad codewords.
        def expected_stream(value):
            bits = '011100011010' if shared_eci else ''
            term_offsets, tail_offsets = [], []
            for index, payload in enumerate([value, *map(to_bytes, tails)]):
                if index:
                    term_offsets.append(len(bits))
                    bits += '0000'
                    if index == 1:
                        bits += '0' * (8 * (longest - len(value)))
                    tail_offsets.append(len(bits))
                bits += '0100' + format(len(payload), f'0{count_bits}b')
                bits += ''.join(f'{byte:08b}' for byte in payload)
            capacity = len(mixed[1]) * 8
            bits += '0' * min(4, capacity - len(bits))
            bits += '0' * (-len(bits) % 8)
            data = bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8))
            data += bytes([0xEC, 0x11][i % 2] for i in range(capacity // 8 - len(data)))
            return data, term_offsets, tail_offsets
        original_data, original_terms, original_tails = expected_stream(body_bytes)
        target_data, target_terms, target_tails = expected_stream(target_bytes)
        assert offsets == original_terms
        assert original_tails == target_tails == stats['tail_offsets']
        assert stats['replacement_terminator'] == target_terms[0]
        assert stats['padding_bits'] == (longest - len(body_bytes)) * 8
        assert stats['replacement_padding_bits'] == (longest - len(target_bytes)) * 8
        assert mixed[0] == expected[0]  # Scanner text follows replacement.
        assert mixed[1] == target_data  # Corrected stream includes post-terminator padding.
        assert mixed[2] == original_data  # Physical data keeps original body and count.
        assert mixed[3] == mixed[4]  # Independent ZXing RS encoder verifies parity.
        tail_start = original_tails[0]
        original_bits = ''.join(f'{byte:08b}' for byte in mixed[2])
        corrected_bits = ''.join(f'{byte:08b}' for byte in mixed[1])
        assert original_bits[tail_start:] == corrected_bits[tail_start:]
        if body == target:
            assert rows == before[0]
        position = 0
        remaining = []
        for length, parity in blocks:
            changes = sum(a != b for a, b in zip(original_data[position:position+length], target_data[position:position+length]))
            remaining.append(parity // 2 - changes)
            position += length
        assert min(remaining) == stats['min_remaining'] >= 0
        # Enforce the independently measured boundary; accepted output is identical.
        checked = qr.generate(body, tails, ecc, version, mask, eci, target,
                              min_rs_margin=min(remaining))
        assert checked == (rows, actual_version, offsets)
        if min(remaining) < 15:
            try:
                qr.generate(body, tails, ecc, version, mask, eci, target,
                            min_rs_margin=min(remaining) + 1)
            except ValueError as error:
                assert 'below required minimum' in str(error)
            else:
                raise AssertionError('Insufficient RS margin accepted')
        return actual_version, stats

    for ecc in 'LMQH':
        for mask in range(8):
            check_replacement('HELLO', 'HALLO', ['HIDDEN', 'SECOND'], ecc, mask=mask)
            check_replacement('ABC', 'ABCDE', ['TAIL' * 50, 'SECOND'], ecc, mask=mask)
            check_replacement('ABCDE', 'ABC', ['TAIL' * 50, 'SECOND'], ecc, mask=mask)
    for body, target, tails, ecc, version, eci in [
        ('HELLO', 'HALLO', ['HIDDEN'], 'M', 0, None),
        ('本文あ', '本文い', ['秘密', '次'], 'H', 10, None),
        (b'A\x00\xff', b'B\x00\xfe', [bytes(range(256))], 'Q', 27, None),
        ('HELLO', bytes.fromhex('48414c4c4f'), ['追加'], 'H', 0, None),
        ('A', 'AA', ['Z'], 'H', 0, None),
        ('AA', 'A', ['Z'], 'H', 0, None),
        ('A', 'A', ['Z'], 'L', 0, None),
        ('HELLO', 'HALLO', ['Z'], 'M', 0, False),
        ('あ', 'あい', ['秘密' * 100, '次'], 'M', 0, None),
        ('あい', 'あ', ['秘密' * 100, '次'], 'M', 0, None),
        (b'A', b'AB', [bytes(range(256)), b'\x00\x00'], 'L', 0, None),
        (b'AB', b'A', [bytes(range(256)), b'\x00\x00'], 'L', 0, None),
    ]:
        check_replacement(body, target, tails, ecc, version, eci=eci)
    # Force a shared version, including the 8-to-16-bit count transition.
    assert qr.generate('A' * 4, ['Z'], 'H', eci=False)[1] == 1
    assert check_replacement('A' * 4, 'A' * 5, ['Z'], 'H', eci=False)[0] == 2
    assert qr.generate(bytes(226), [b'Z'], 'L', eci=False)[1] == 9
    assert check_replacement(bytes(226), bytes(228), [b'Z'], 'L', eci=False)[0] == 10
    assert check_replacement(bytes(228), bytes(226), [b'Z'], 'L', eci=False)[0] == 10
    _, stats = check_replacement(bytes(8), bytes([0x10]) * 3 + bytes(5), [b'Z'], 'L', eci=False)
    assert stats['min_remaining'] == 0
    print('PASS replacement: all ECC/masks, UTF-8, binary, unequal lengths, shared version, and exact RS boundary')

    def rejected(body, target, tails, ecc, version, block, changes, limit):
        try:
            qr.generate(body, tails, ecc, version, eci=False, replacement=target)
        except ValueError as error:
            assert str(error) == f'RS block {block}: {changes} differing data codewords exceed correction limit {limit}.'
        else:
            raise AssertionError('Uncorrectable replacement accepted')
    rejected(bytes(8), bytes([0x10]) * 4 + bytes(4), [b'Z'], 'L', 0, 1, 4, 3)
    # V5-Q has four blocks: total errors are small, but block 1 exceeds its limit.
    rejected(bytes(40), bytes([0x10]) * 10 + bytes(30), [b'Z'], 'Q', 5, 1, 10, 9)
    rejected(bytes(40), bytes(14) + bytes([0x10]) * 10 + bytes(16), [b'Z'], 'Q', 5, 2, 10, 9)
    # V5-Q block 2 alone consumes eight of its nine correction codewords.
    try:
        qr.generate(bytes(40), [b'Z'], 'Q', 5, eci=False,
                    replacement=bytes(14) + bytes([0x10]) * 8 + bytes(18), min_rs_margin=2)
    except ValueError as error:
        assert str(error) == ('RS block 2: remaining correction capacity 1 is below required minimum 2 '
                              'codewords (8 differing data codewords, correction limit 9).')
    else:
        raise AssertionError('Single-block margin failure accepted')
    # No replacement consumes no correction capacity; enforce the same boundary.
    for ecc, capacity in [('L', 3), ('M', 5), ('Q', 6), ('H', 8)]:
        for mask in [-1, *range(8)]:
            stats = {}
            normal = qr.generate('A', ['Z'], ecc, mask=mask, eci=False)
            checked = qr.generate('A', ['Z'], ecc, mask=mask, eci=False,
                                  diagnostics=stats, min_rs_margin=capacity)
            assert checked == normal and stats['min_remaining'] == capacity
            try:
                qr.generate('A', ['Z'], ecc, eci=False, min_rs_margin=capacity + 1)
            except ValueError as error:
                assert 'below required minimum' in str(error)
            else:
                raise AssertionError('Margin failure without replacement accepted')
    # Model 2 allows at most fifteen correctable codewords per block.
    assert qr.generate('A', ['Z'], 'H', 40, eci=False, min_rs_margin=15)[1] == 40
    for invalid in [-1, 16, 2**32, 1.5, '2', None, True]:
        try:
            qr.generate('A', ['Z'], min_rs_margin=invalid)
        except ValueError as error:
            assert 'Minimum RS margin' in str(error)
        else:
            raise AssertionError(f'Invalid margin accepted: {invalid!r}')
    print('PASS minimum RS margin: independent boundaries, individual blocks, no replacement, and input validation')
    # Previously failed because an odd length difference shifted final padding.
    check_replacement(bytes(227), bytes(228), [b'Z'], 'L', eci=False)
    scattered = bytearray(40)
    for index in [0, 14, 29, 39]:
        scattered[index] = 0x10
    check_replacement(bytes(40), bytes(scattered), [b'Z'], 'Q', 5, eci=False)

    replacement_file = directory / 'replacement.txt'
    replacement_file.write_bytes(b'HALLO\x00\r\n')
    for options in [['--ecc-text', 'HALLO\r\n'], ['--ecc-hex', '48414c4c4f'],
                    ['--ecc-text-file', str(replacement_file)]]:
        output = directory / 'replacement.png'
        result = subprocess.run([str(root/'qr-tail.py'), '--text', 'HELLO\r\n', '--tail', 'Z', '--ecc', 'H',
                                 *options, '-o', str(output), '--force'], capture_output=True, text=True, check=True)
        assert 'Minimum remaining RS correction capacity:' in result.stdout
        decoded = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(output), '8', '4'],
                                 capture_output=True, text=True, check=True).stdout.splitlines()
        expected = {'--ecc-text': b'HALLO\r\n', '--ecc-hex': b'HALLO', '--ecc-text-file': b'HALLO\x00\r\n'}[options[0]]
        assert base64.b64decode(decoded[0]) == expected
    for options in [['--ecc-text', ''], ['--ecc-hex', ''], ['--ecc-hex', 'GG'],
                    ['--ecc-text', 'X', '--ecc-hex', '58'], ['--ecc-text-file', str(directory/'missing')],
                    ['--ecc-text', 'B' * 2954], ['--ecc-text', 'B' * 2952], ['--ecc-text', 'B' * 8],
                    ['--ecc-text', 'BAAAAAAA', '--min-rs-margin', '3'],
                    ['--min-rs-margin', '4'], ['--min-rs-margin', '-1'],
                    ['--min-rs-margin', '16'], ['--min-rs-margin', '1.5']]:
        output = directory / 'rejected.png'
        command = [str(root/'qr-tail.py'), '--text', 'A' * 8, '--tail', 'Z', '--ecc', 'L', *options, '-o', str(output)]
        assert subprocess.run(command, capture_output=True).returncode == 2
        assert not output.exists()
        output.write_bytes(b'keep this file')
        assert subprocess.run([*command, '--force'], capture_output=True).returncode == 2
        assert output.read_bytes() == b'keep this file'
        output.unlink()
    print('PASS per-block overflow, replacement CLI options, invalid input, and output preservation')
    for mode in ['byte', 'alphanumeric']:
        output = directory / 'margin.png'
        command = [str(root/'qr-tail.py'), '--text', 'A', '--tail', 'Z', '--ecc', 'L',
                   '--no-eci', '--tail-mode', mode, '--min-rs-margin', '3', '-o', str(output), '--force']
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        assert 'Minimum remaining RS correction capacity: 3 codewords per block' in result.stdout
    print('PASS minimum RS margin CLI in both tail modes')
