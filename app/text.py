#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Découpage du texte en segments (recommandation officielle du dépôt VoxCPM)."""
import re

from .state import MAX_CHUNK_CHARS

_SENT_RE = re.compile(r"(?<=[.!?;\u3002\uff01\uff1f\u2026\n])\s+")


def split_text(text, max_chars=MAX_CHUNK_CHARS):
    text = text.strip()
    if not text:
        return []
    parts = [p for p in _SENT_RE.split(text) if p.strip()]
    if not parts:
        parts = [text]
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) + 1 <= max_chars or not buf:
            buf = (buf + " " + p).strip() if buf else p.strip()
        else:
            chunks.append(buf)
            buf = p.strip()
    if buf:
        chunks.append(buf)
    # mots tres longs sans ponctuation : couper brutalement
    final = []
    for c in chunks:
        while len(c) > max_chars * 1.6:
            cut = c.rfind(" ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            final.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            final.append(c)
    return final
