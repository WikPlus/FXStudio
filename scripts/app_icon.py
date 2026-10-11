"""Vector rasterization of the app's brand orange waveform mark for macOS."""
import math
import struct
import zlib


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(size):
    rows = bytearray()
    bars = [(0.28, 0.12), (0.368, 0.36), (0.456, 0.48),
            (0.544, 0.20), (0.632, 0.36), (0.72, 0.12)]
    radius = 0.022
    for y in range(size):
        rows.append(0)
        py = (y + 0.5) / size
        for x in range(size):
            px = (x + 0.5) / size
            dx = max(abs(px - 0.5) - 0.24, 0)
            dy = max(abs(py - 0.5) - 0.24, 0)
            edge = math.hypot(dx, dy) - 0.18
            alpha = max(0, min(1, 0.5 - edge * size))
            stroke = 0
            for bx, height in bars:
                distance = math.hypot(px - bx, max(abs(py - 0.5) - height / 2 + radius, 0)) - radius
                stroke = max(stroke, max(0, min(1, 0.5 - distance * size)))
            bg = (25 + 8 * (1 - py), 27 + 8 * (1 - py), 31 + 8 * (1 - py))
            orange = (251, 119, 49)
            rows.extend(round(bg[c] * (1 - stroke) + orange[c] * stroke) for c in range(3))
            rows.append(round(255 * alpha))
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def write_icon(path):
    content = bytearray()
    for kind, size in ((b'ic07', 128), (b'ic08', 256), (b'ic09', 512), (b'ic10', 1024)):
        data = png(size)
        content.extend(kind + struct.pack('>I', len(data) + 8) + data)
    path.write_bytes(b'icns' + struct.pack('>I', len(content) + 8) + content)
