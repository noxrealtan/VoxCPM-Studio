#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génère le PNG maître (1024x1024) de l'icône VoxCPM Studio — sans dépendances."""
import os
import struct
import sys
import zlib

W = 1024


def in_rounded(x, y, cx, cy, hw, hh, r):
    dx = max(abs(x - cx) - (hw - r), 0)
    dy = max(abs(y - cy) - (hh - r), 0)
    return dx * dx + dy * dy <= r * r


def build():
    top = (91, 140, 255)    # #5b8cff
    bot = (139, 91, 255)    # #8b5bff
    white = (247, 249, 253)
    px = bytearray(W * W * 4)
    for y in range(W):
        t = y / (W - 1)
        bg = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            if not in_rounded(x, y, 512, 512, 500, 500, 230):
                continue
            c = bg
            # capsule du micro
            if in_rounded(x, y, 512, 400, 100, 190, 100):
                c = white
            # arc du support (demi-anneau bas)
            elif 200 <= (x - 512) ** 2 + (y - 620) ** 2 <= 250 ** 2 and y > 620:
                c = white
            # tige
            elif 490 <= x <= 534 and 620 <= y <= 740:
                c = white
            # base
            elif in_rounded(x, y, 512, 762, 110, 22, 22):
                c = white
            i = (y * W + x) * 4
            px[i:i + 3] = bytes(c)
            px[i + 3] = 255
    return bytes(px)


def png(path, w, h, rgba):
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


if __name__ == "__main__":
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "build", "iconset")
    out = sys.argv[1] if len(sys.argv) > 1 else default
    os.makedirs(out, exist_ok=True)
    png(os.path.join(out, "icon_512x512@2x.png"), W, W, build())
    print("PNG maître écrit dans %s" % out)
