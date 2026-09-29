#!/usr/bin/env python3
"""Verify generic tail modes with ZXing; no encryption dependencies required."""
import argparse
import base64
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qr_tail', ROOT / 'qr-tail.py')
qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qr)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--zxing-jar', required=True, type=Path)
args = parser.parse_args()
alphabet = b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'

# The alphanumeric capacity check must allow more than 2953 characters.
_, compact, _ = qr.generate('A', ['A'*3010], ecc='L', replacement='B', tail_mode='alphanumeric')
assert compact <= 40
_, compact, _ = qr.generate('A', ['A'*500], ecc='L', tail_mode='alphanumeric')
_, byte_version, _ = qr.generate('A', ['A'*500], ecc='L')
assert compact < byte_version
for tails, mode in [(['A'*3010], 'byte'), (['A'*5000], 'alphanumeric'),
                    (['lowercase'], 'alphanumeric'), (['A'], 'invalid')]:
    try:
        qr.generate('A', tails, tail_mode=mode)
    except ValueError:
        pass
    else:
        raise AssertionError((mode, tails[0][:20]))

with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp)
    jar = args.zxing_jar.resolve()
    subprocess.run(['javac', '-cp', str(jar), '-d', temp,
                    str(ROOT/'tests/VerifyQr.java'), str(ROOT/'tests/InspectQr.java')], check=True)
    cases = []
    for version in [1, 9, 10, 26, 27]:
        for source, target in [('本文', None), ('ABC', 'ABCDE'), ('ABCDE', 'ABC')]:
            cases.append((source, target, [alphabet, alphabet+b'A'], version, 'alphanumeric'))
    cases += [(b'\0\xffA', b'\0\xffB', [alphabet], 1, 'alphanumeric'),
              ('BODY', None, [b'\0\xff\x80'], 1, 'byte')]
    for index, (source, target, tails, minimum, mode) in enumerate(cases):
        output = directory/f'{index}.png'
        # Exercise both text and HEX inputs; file input is checked below.
        text_input = isinstance(source, str)
        body = source.encode() if text_input else source
        corrected = body if target is None else target.encode() if isinstance(target, str) else target
        use_text_tails = text_input and mode == 'alphanumeric'
        command = [str(ROOT/'qr-tail.py'), '--text' if text_input else '--hex', source if text_input else source.hex(),
                   '--tail-mode', mode, '--ecc', 'H', '--version', str(minimum), '--mask', str(index % 8), '-o', str(output)]
        if target is not None:
            command += ['--ecc-text' if text_input else '--ecc-hex', target if text_input else target.hex()]
        for tail in tails:
            command += ['--tail' if use_text_tails else '--tail-hex', tail.decode() if use_text_tails else tail.hex()]
        report = subprocess.run(command, check=True, capture_output=True, text=True).stdout
        lines = subprocess.run(['java', '-cp', f'{temp}:{jar}', 'VerifyQr', str(output), '8', '4'],
                               check=True, capture_output=True, text=True).stdout.splitlines()
        assert lines[3] == lines[5]  # Stored ECC matches the corrected stream.
        width = int.from_bytes(output.read_bytes()[16:20], 'big')
        version = (width//8 - 8 - 17)//4
        eci = text_input and use_text_tails
        def parse(stream, expected_body):
            bits = ''.join(f'{value:08b}' for value in stream)
            position = 0
            def take(n):
                nonlocal position
                value = int(bits[position:position+n], 2)
                position += n
                return value
            if eci:
                assert (take(4), take(8)) == (7, 26)
            assert take(4) == 4
            count = take(8 if version < 10 else 16)
            assert bytes(take(8) for _ in range(count)) == expected_body
            offsets, starts = [], []
            for group, expected in enumerate(tails):
                offsets.append(position)
                assert take(4) == 0
                if group == 0:
                    for _ in range((max(len(body), len(corrected))-len(expected_body))*2):
                        assert take(4) == 0
                starts.append(position)
                if mode == 'byte':
                    assert take(4) == 4
                    count = take(8 if version < 10 else 16)
                    actual = bytes(take(8) for _ in range(count))
                else:
                    assert take(4) == 2
                    count = take(9 if version < 10 else 11 if version < 27 else 13)
                    actual = bytearray()
                    for _ in range(count//2):
                        pair = take(11)
                        actual.extend([alphabet[pair//45], alphabet[pair % 45]])
                    if count % 2:
                        actual.append(alphabet[take(6)])
                assert actual == expected
            return offsets, starts, bits[starts[0]:]
        before = parse(base64.b64decode(lines[2]), body)
        after = parse(base64.b64decode(lines[1]), corrected)
        assert before[1:] == after[1:]
        assert 'Four-bit terminator starts (zero-based data bits): ' + ', '.join(map(str, before[0])) in report
        if target is not None:
            assert 'Additional segment starts (shared before/after RS correction, zero-based data bits): ' + ', '.join(map(str, before[1])) in report
        if eci:
            assert base64.b64decode(lines[0]) == corrected

    source = directory/'tail.txt'
    source.write_bytes(alphabet)
    output = directory/'file.png'
    command = [str(ROOT/'qr-tail.py'), '--text', 'BODY', '--tail-file', str(source),
               '--tail-mode', 'alphanumeric', '-o', str(output)]
    subprocess.run(command, check=True, capture_output=True)
    preserved = output.read_bytes()
    for invalid in [b'lowercase', b'A\n', b'A\0', '日本語'.encode()]:
        source.write_bytes(invalid)
        assert subprocess.run(command+['--force'], capture_output=True).returncode == 2
        assert output.read_bytes() == preserved
    print(f'PASS {len(cases)} independent mixed-mode QR cases; capacity, file inputs, and invalid-character output protection')
