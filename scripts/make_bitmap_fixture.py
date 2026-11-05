"""Create a small PGS display set to exercise the real bitmap decoder."""
import struct
from pathlib import Path

def segment(kind, data, pts=90000):
    return b'PG' + struct.pack('>IIBH', pts, pts, kind, len(data)) + data

# Palette: transparent background and opaque white foreground.
palette = b'\x00\x00' + bytes([0, 16, 128, 128, 0, 1, 235, 128, 128, 255])
width, height = 120, 30
# Each line is one run of 120 white pixels, followed by EOL.
rle = (bytes([0, 0xc0, 120, 1, 0, 0])) * height
obj = struct.pack('>HBB', 0, 0, 0xc0) + (len(rle) + 4).to_bytes(3, 'big') + struct.pack('>HH', width, height) + rle
pcs = struct.pack('>HHBHBBBB', 960, 540, 0x10, 0, 0x80, 0, 0, 1) + struct.pack('>HBBHH', 0, 0, 0, 400, 450)
wds = bytes([1, 0]) + struct.pack('>HHHH', 400, 450, width, height)
clear = struct.pack('>HHBHBBBB', 960, 540, 0x10, 1, 0, 0, 0, 0)
data = segment(0x16, pcs) + segment(0x17, wds) + segment(0x14, palette) + segment(0x15, obj) + segment(0x80, b'') + segment(0x16, clear, 360000) + segment(0x80, b'', 360000)
Path(__file__).resolve().parents[1].joinpath('artifacts/bitmap.sup').write_bytes(data)
