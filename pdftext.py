# -*- coding: utf-8 -*-
# JobDibs — local job search.  Copyright (C) 2026 Shani Segev
# Licensed under the GNU AGPL-3.0. See LICENSE and NOTICE.
"""
חילוץ טקסט מ-PDF בספרייה סטנדרטית בלבד.

תומך גם בפונטים מסוג CID / Identity-H (מה שוורד, Pages ו-Google Docs מייצרים),
דרך פענוח מפות ToUnicode. אם מותקנות pypdf או pdftotext — נשתמש בהן כי הן טובות יותר.

    text, method, warning = extract(raw_bytes)
"""

import re
import shutil
import subprocess
import tempfile
import zlib


# ── 1. מפות ToUnicode ───────────────────────────────────────────────

def _utf16(hexstr):
    try:
        b = bytes.fromhex(hexstr if len(hexstr) % 2 == 0 else "0" + hexstr)
    except ValueError:
        return ""
    if len(b) >= 2:
        try:
            return b.decode("utf-16-be", "ignore")
        except Exception:
            pass
    return b.decode("latin-1", "ignore")


def _parse_cmap(data):
    """מחזיר (mapping code→str, code_width_bytes)."""
    txt = data.decode("latin-1", "replace")
    m, width = {}, 2

    for blk in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            width = max(1, len(src) // 2)
            m[int(src, 16)] = _utf16(dst)

    for blk in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for lo, hi, arr in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S):
            width = max(1, len(lo) // 2)
            for i, d in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", arr)):
                m[int(lo, 16) + i] = _utf16(d)
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            width = max(1, len(lo) // 2)
            a, b, base = int(lo, 16), int(hi, 16), int(dst, 16)
            if b - a > 65535:
                continue
            for i in range(b - a + 1):
                try:
                    m[a + i] = chr(base + i)
                except ValueError:
                    pass
    return m, width


# ── 2. אובייקטים וזרמים ─────────────────────────────────────────────

def _objects(raw):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)\bendobj", raw, re.S):
        objs[int(m.group(1))] = m.group(2)
    return objs


def _stream_of(body):
    m = re.search(rb"stream\r?\n?(.*?)\r?\n?endstream", body, re.S)
    if not m:
        return None
    data = m.group(1)
    for cand in (data, data.strip(b"\r\n")):
        try:
            return zlib.decompress(cand)
        except Exception:
            continue
    return data


def _is_content(b):
    """זרם תוכן = ASCII ברובו ומכיל אופרטורי טקסט (ולא קובץ פונט/תמונה)."""
    if not b or len(b) < 8:
        return False
    if b[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf") or b[:2] == b"\x80\x01":
        return False
    if b[:2] == b"%!" or b.startswith(b"\x89PNG") or b[:2] == b"\xff\xd8":
        return False
    if b"BT" not in b and b"Tj" not in b and b"TJ" not in b:
        return False
    sample = b[:4000]
    return sum(1 for c in sample if 9 <= c <= 126) / max(1, len(sample)) > 0.80


# ── 3. פענוח מחרוזות ────────────────────────────────────────────────

_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
        b"(": b"(", b")": b")", b"\\": b"\\"}


def _lit(b):
    out, i = bytearray(), 0
    while i < len(b):
        c = b[i:i + 1]
        if c == b"\\" and i + 1 < len(b):
            n = b[i + 1:i + 2]
            if n in _ESC:
                out += _ESC[n]; i += 2; continue
            if n.isdigit():
                j = i + 1
                while j < len(b) and j < i + 4 and b[j:j + 1].isdigit():
                    j += 1
                out.append(int(b[i + 1:j], 8) & 0xFF); i = j; continue
            if n in (b"\n", b"\r"):
                i += 2; continue
            out += n; i += 2; continue
        out += c; i += 1
    return bytes(out)


def _decode(data, cmap, width):
    if cmap:
        step = width or 2
        return "".join(cmap.get(int.from_bytes(data[i:i + step], "big"), "")
                       for i in range(0, len(data) - step + 1, step))
    return data.decode("cp1252", "replace")


# ── 4. סריקת זרם תוכן ───────────────────────────────────────────────

_TOKENS = re.compile(
    rb"/([A-Za-z0-9_.#-]+)\s+[-\d.eE+]+\s+Tf"
    rb"|\[((?:\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|[-\d.\s])*)\]\s*TJ"
    rb"|(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>)\s*(?:Tj|'|\")"
    rb"|(-?[\d.]+)\s+(-?[\d.]+)\s+(?:Td|TD)"
    rb"|(?:-?[\d.]+\s+){5}(-?[\d.]+)\s+Tm"
    rb"|(T\*|ET|BT)", re.S)

_ELEM = re.compile(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|-?[\d.]+")


def _show(tok, cmap, width):
    if tok.startswith(b"("):
        return _decode(_lit(tok[1:-1]), cmap, width)
    h = re.sub(rb"\s", b"", tok[1:-1])
    if len(h) % 2:
        h += b"0"
    try:
        return _decode(bytes.fromhex(h.decode()), cmap, width)
    except Exception:
        return ""


def _scan(stream, name_map):
    lines, buf = [], []
    cmap, width, last_y = None, 2, None

    def flush():
        if buf:
            lines.append("".join(buf))
            del buf[:]

    for t in _TOKENS.finditer(stream):
        font, arr, single, tx, ty, tm_y, brk = t.groups()

        if font is not None:
            cmap, width = name_map.get(font.decode("latin-1"), (None, 2))

        elif arr is not None:
            for e in _ELEM.finditer(arr):
                el = e.group(0)
                if el[:1] in (b"(", b"<"):
                    buf.append(_show(el, cmap, width))
                else:
                    try:
                        if float(el) <= -110:            # kerning גדול = רווח
                            buf.append(" ")
                    except ValueError:
                        pass

        elif single is not None:
            buf.append(_show(single, cmap, width))

        elif ty is not None:
            try:
                if abs(float(ty)) > 0.1:                 # ירידת שורה
                    flush()
            except ValueError:
                pass

        elif tm_y is not None:
            try:
                y = float(tm_y)
                if last_y is not None and abs(y - last_y) > 0.5:
                    flush()
                last_y = y
            except ValueError:
                pass

        elif brk is not None:
            flush()

    flush()
    return lines


# ── 5. חילוץ ────────────────────────────────────────────────────────

def _pure_python(raw):
    objs = _objects(raw)

    font_map = {}                                  # objnum → (cmap, width)
    for num, body in objs.items():
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if m:
            s = _stream_of(objs.get(int(m.group(1)), b""))
            if s:
                font_map[num] = _parse_cmap(s)

    name_map = {}                                  # "/F1" → (cmap, width)
    for body in objs.values():
        for fm in re.finditer(rb"/Font\s*<<(.*?)>>", body, re.S):
            for name, num in re.findall(rb"/([A-Za-z0-9_.#-]+)\s+(\d+)\s+\d+\s+R",
                                        fm.group(1)):
                n = int(num)
                if n in font_map:
                    name_map.setdefault(name.decode("latin-1"), font_map[n])

    lines = []
    for body in objs.values():
        st = _stream_of(body)
        if _is_content(st):
            lines.extend(_scan(st, name_map))

    return _reflow(lines)


def _reflow(lines):
    """
    PDF-ים רבים ממקמים כל מילה (ולפעמים כל תו) בנפרד, כך שכל 'שורה' היא מילה.
    אם זה המצב — מחברים חזרה לטקסט זורם, שזה מה שהתאמת מילות המפתח צריכה.
    """
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return ""
    med = sorted(len(l) for l in lines)[len(lines) // 2]
    text = (" ".join(lines) if med < 15 else "\n".join(lines))
    text = re.sub(r"(?<=\w) (?=[.,;:!?])", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _quality(t):
    """0..1 — כמה זה נראה כמו טקסט אמיתי. מעניש גם שורות של תו בודד."""
    if not t or len(t) < 60:
        return 0.0
    good = sum(1 for c in t if c.isalnum() or c.isspace() or c in ".,:;-()/@&'\"%+#")
    ratio = good / len(t)
    lines = [l for l in t.split("\n") if l.strip()]
    if lines:
        short = sum(1 for l in lines if len(l.strip()) <= 2) / len(lines)
        if short > 0.5:                      # פורק לתווים בודדים — לא שמיש
            ratio *= 0.35
    return ratio


def _via_pypdf(raw):
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader          # noqa
        except Exception:
            return ""
    import io
    try:
        return "\n".join((p.extract_text() or "")
                         for p in PdfReader(io.BytesIO(raw)).pages).strip()
    except Exception:
        return ""


def _via_poppler(raw):
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(raw)
        path = f.name
    try:
        out = subprocess.run([exe, "-layout", "-enc", "UTF-8", path, "-"],
                             capture_output=True, timeout=25)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def extract(raw):
    """מחזיר (text, method, warning). מנסה כמה שיטות ובוחר את הטובה ביותר."""
    best, method = "", ""
    for name, fn in (("poppler", _via_poppler), ("pypdf", _via_pypdf),
                     ("builtin", _pure_python)):
        try:
            t = fn(raw)
        except Exception:
            t = ""
        if _quality(t) > _quality(best) or (not best and t):
            best, method = t, name
        if _quality(best) > 0.9 and len(best) > 400:
            break

    if _quality(best) < 0.55 or len(best) < 120:
        return best, method, (
            "לא הצלחתי לחלץ טקסט קריא מה-PDF — כנראה סרוק כתמונה. "
            "הדביקי את תוכן קורות החיים בשדה הטקסט, "
            "או שדרגי בפקודה אחת:  pip3 install pypdf")
    return best, method, ""
