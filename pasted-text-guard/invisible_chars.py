#!/usr/bin/env python3
"""Find invisible and bidirectional-control Unicode characters in text.

A small library plus a command-line check. It finds characters that a screen
draws as nothing (or that silently reorder what is drawn) but that a model
still reads: zero-width spaces, word joiners, bidirectional overrides and
isolates, Unicode tag characters, stray variation selectors, Hangul fillers,
and every other format character (category Cf) not listed as visible.

Characters that real scripts and emoji need are kept when they appear where
those scripts and emoji put them:

- U+200C ZERO WIDTH NON-JOINER: kept when it is a single character with a
  letter of a joining script (Arabic, Persian, Syriac, Indic, Mongolian and
  others) on at least one side, as in Persian "می‌خواهم" or "PDF‌ها".
- U+200D ZERO WIDTH JOINER: kept inside emoji sequences, and next to a
  letter of a joining script, under the same single-character rule.
- U+200E/U+200F/U+061C directional marks: kept as single characters on a
  line that contains right-to-left letters.
- Variation selectors: kept as single characters after a visible base
  character (FE00-FE0F), after a CJK ideograph (E0100-E01EF), or after a
  Mongolian letter (Mongolian free variation selectors).
- Tag characters: kept only in an emoji flag sequence (U+1F3F4, 2-7 tags
  from a-z or 0-9, then U+E007F CANCEL TAG), such as the flag of England.
- U+00AD SOFT HYPHEN: kept as a single character between two letters.

Everything else in those classes is reported. Runs of two or more invisible
characters are reported unless they form one of the sequences above.

Standard library only. See README.md for why this is a library and not a
registered hook.

Command line:
    python3 invisible_chars.py [FILE ...]          report; exit 1 if found
    python3 invisible_chars.py --strip [FILE ...]  write cleaned text to stdout
With no FILE, reads standard input.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass

# --- character classes ------------------------------------------------------

ZWNJ = 0x200C
ZWJ = 0x200D
LRM, RLM, ALM = 0x200E, 0x200F, 0x061C
SOFT_HYPHEN = 0x00AD
BLACK_FLAG = 0x1F3F4
CANCEL_TAG = 0xE007F

# Always reported, whatever surrounds them.
_ALWAYS = (
    [(0x200B, 0x200B)]  # ZERO WIDTH SPACE
    + [(0x2060, 0x2064)]  # WORD JOINER, invisible math operators
    + [(0xFEFF, 0xFEFF)]  # ZERO WIDTH NO-BREAK SPACE / BOM
    + [(0x180E, 0x180E)]  # MONGOLIAN VOWEL SEPARATOR
    + [(0x202A, 0x202E)]  # LRE RLE PDF LRO RLO
    + [(0x2066, 0x2069)]  # LRI RLI FSI PDI
    + [(0x206A, 0x206F)]  # deprecated format characters
    + [(0xFFF9, 0xFFFB)]  # interlinear annotation
    + [(0xE0000, 0xE007F)]  # tag block (flag sequences are exempted separately)
    + [(0x115F, 0x1160), (0x3164, 0x3164), (0xFFA0, 0xFFA0)]  # Hangul fillers
    + [(0x1D173, 0x1D17A)]  # musical formatting
    + [(0x1BCA0, 0x1BCA3)]  # shorthand format controls
)

# Format characters (category Cf) that are drawn visibly; never reported.
_VISIBLE_CF = [
    (0x0600, 0x0605),  # Arabic number signs
    (0x06DD, 0x06DD),  # ARABIC END OF AYAH
    (0x070F, 0x070F),  # SYRIAC ABBREVIATION MARK
    (0x0890, 0x0891),  # Arabic pound/piastre mark above
    (0x08E2, 0x08E2),  # ARABIC DISPUTED END OF AYAH
    (0x110BD, 0x110BD),  # KAITHI NUMBER SIGN
    (0x110CD, 0x110CD),  # KAITHI NUMBER SIGN ABOVE
]

_VS_BASIC = (0xFE00, 0xFE0F)
_VS_SUPPLEMENT = (0xE0100, 0xE01EF)
_MONGOLIAN_FVS = [(0x180B, 0x180D), (0x180F, 0x180F)]

# Scripts that use ZWNJ/ZWJ between letters.
_JOINING_SCRIPTS = [
    (0x0600, 0x06FF),  # Arabic, Persian, Urdu
    (0x0700, 0x074F),  # Syriac
    (0x0750, 0x077F),  # Arabic Supplement
    (0x07C0, 0x07FF),  # NKo
    (0x0860, 0x08FF),  # Syriac Supplement, Arabic Extended-B/-A
    (0x0900, 0x0DFF),  # Devanagari .. Sinhala
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
    (0x1820, 0x18AF),  # Mongolian letters
    (0xA840, 0xA87F),  # Phags-pa
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFC),  # Arabic Presentation Forms-B
    (0x10D00, 0x10D3F),  # Hanifi Rohingya
    (0x1E900, 0x1E95F),  # Adlam
]

# Right-to-left letters, for the directional-mark rule.
_RTL = [
    (0x0590, 0x08FF),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFC),
    (0x10800, 0x10FFF),
    (0x1E800, 0x1EFFF),
]

_CJK = [
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x3FFFF),
]

_MONGOLIAN_LETTERS = [(0x1820, 0x18AF)]

# Characters that can take part in an emoji ZWJ sequence. An approximation of
# Extended_Pictographic, which the standard library does not expose.
_EMOJI = [
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x21AA),
    (0x2300, 0x23FF),
    (0x24C2, 0x24C2),
    (0x25A0, 0x25FF),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B00, 0x2BFF),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F000, 0x1FAFF),
]
_SKIN_TONE = (0x1F3FB, 0x1F3FF)

_TAG_SPEC_OK = [(0xE0030, 0xE0039), (0xE0061, 0xE007A)]  # tag digits, tag a-z


def _in(cp: int, ranges) -> bool:
    if isinstance(ranges, tuple):
        return ranges[0] <= cp <= ranges[1]
    return any(lo <= cp <= hi for lo, hi in ranges)


def is_invisible(cp: int) -> bool:
    """True for every code point this module treats as invisible or bidi
    control, before any context exemption is applied."""
    if _in(cp, _ALWAYS) or _in(cp, _VS_BASIC) or _in(cp, _VS_SUPPLEMENT):
        return True
    if _in(cp, _MONGOLIAN_FVS):
        return True
    if cp in (ZWNJ, ZWJ, LRM, RLM, ALM, SOFT_HYPHEN):
        return True
    if unicodedata.category(chr(cp)) == "Cf" and not _in(cp, _VISIBLE_CF):
        return True
    return False


def _is_mark(cp: int) -> bool:
    return unicodedata.category(chr(cp)) in ("Mn", "Mc", "Me")


def _is_letter(cp: int) -> bool:
    return unicodedata.category(chr(cp)).startswith("L")


# --- findings ---------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    index: int  # code-point index into the text
    line: int  # 1-based
    column: int  # 1-based, in code points
    codepoint: int
    reason: str

    @property
    def label(self) -> str:
        return f"U+{self.codepoint:04X}"

    @property
    def name(self) -> str:
        return unicodedata.name(chr(self.codepoint), "UNNAMED FORMAT CHARACTER")


def _allowed_tag_indices(cps: list[int]) -> set[int]:
    """Indices of tag characters that belong to a valid emoji flag sequence."""
    ok: set[int] = set()
    i = 0
    n = len(cps)
    while i < n:
        if cps[i] == BLACK_FLAG:
            j = i + 1
            while j < n and _in(cps[j], _TAG_SPEC_OK) and j - i <= 7:
                j += 1
            spec_len = j - i - 1
            if 2 <= spec_len <= 7 and j < n and cps[j] == CANCEL_TAG:
                ok.update(range(i + 1, j + 1))
                i = j + 1
                continue
        i += 1
    return ok


def _emoji_base_before(cps: list[int], i: int) -> int | None:
    """Index of the emoji that a ZWJ at i joins from, skipping one FE0F and
    one skin-tone modifier; None if there is none."""
    j = i - 1
    if j >= 0 and cps[j] == 0xFE0F:
        j -= 1
    if j >= 0 and _in(cps[j], _SKIN_TONE):
        j -= 1
    if j >= 0 and _in(cps[j], _EMOJI) and not _in(cps[j], _SKIN_TONE):
        return j
    if j >= 0 and _in(cps[j], _SKIN_TONE):  # a bare modifier is an emoji too
        return j
    return None


def _allowed_emoji_indices(cps: list[int]) -> set[int]:
    """ZWJs (and an FE0F just before them) inside emoji ZWJ sequences."""
    ok: set[int] = set()
    for i, cp in enumerate(cps):
        if cp != ZWJ:
            continue
        base = _emoji_base_before(cps, i)
        if base is None or i + 1 >= len(cps) or not _in(cps[i + 1], _EMOJI):
            continue
        ok.add(i)
        if cps[i - 1] == 0xFE0F:
            ok.add(i - 1)
    return ok


def _neighbour(cps: list[int], i: int, step: int) -> int | None:
    """Nearest code point in direction step, skipping combining marks."""
    j = i + step
    while 0 <= j < len(cps) and _is_mark(cps[j]) and not is_invisible(cps[j]):
        j += step
    return cps[j] if 0 <= j < len(cps) else None


def _single(cps: list[int], i: int, exempt: set[int]) -> bool:
    """No other invisible character directly next to position i, apart from
    ones already accepted as part of a known sequence."""
    for j in (i - 1, i + 1):
        if 0 <= j < len(cps) and is_invisible(cps[j]) and j not in exempt:
            return False
    return True


def _line_has_rtl(cps: list[int], i: int) -> bool:
    lo = i
    while lo > 0 and cps[lo - 1] not in (0x0A, 0x0D):
        lo -= 1
    hi = i
    while hi < len(cps) - 1 and cps[hi + 1] not in (0x0A, 0x0D):
        hi += 1
    return any(_in(cps[k], _RTL) and _is_letter(cps[k]) for k in range(lo, hi + 1))


def _reason(cps: list[int], i: int, exempt: set[int]) -> str | None:
    """Why the invisible character at i is reported, or None if it is kept."""
    cp = cps[i]
    if i in exempt:
        return None
    if 0xE0000 <= cp <= 0xE007F:
        return "tag character outside an emoji flag sequence"
    if _in(cp, _ALWAYS):
        if _in(cp, [(0x202A, 0x202E), (0x2066, 0x2069)]):
            return "bidirectional embedding, override or isolate control"
        return "invisible character"
    single = _single(cps, i, exempt)
    prev_n, next_n = _neighbour(cps, i, -1), _neighbour(cps, i, +1)
    if cp in (ZWNJ, ZWJ):
        if not single:
            return "joiner in a run of invisible characters"
        if any(n is not None and _in(n, _JOINING_SCRIPTS) for n in (prev_n, next_n)):
            return None
        return "joiner not next to a letter of a script that uses it"
    if cp in (LRM, RLM, ALM):
        if single and _line_has_rtl(cps, i):
            return None
        return "directional mark on a line with no right-to-left text"
    if _in(cp, _VS_BASIC):
        prev = cps[i - 1] if i > 0 else None
        visible_base = (
            prev is not None
            and not is_invisible(prev)
            and not unicodedata.category(chr(prev)).startswith("Z")
            and prev not in (0x09, 0x0A, 0x0D)
        )
        if single and visible_base:
            return None
        return "variation selector without a visible base character"
    if _in(cp, _VS_SUPPLEMENT):
        if single and i > 0 and _in(cps[i - 1], _CJK):
            return None
        return "variation selector outside a CJK ideograph sequence"
    if _in(cp, _MONGOLIAN_FVS):
        if single and i > 0 and _in(cps[i - 1], _MONGOLIAN_LETTERS):
            return None
        return "Mongolian variation selector outside Mongolian text"
    if cp == SOFT_HYPHEN:
        if single and prev_n is not None and next_n is not None and _is_letter(prev_n) and _is_letter(next_n):
            return None
        return "soft hyphen outside a word"
    return "invisible format character"


def scan(text: str) -> list[Finding]:
    """Every reported character in text, in order."""
    cps = [ord(c) for c in text]
    exempt = _allowed_tag_indices(cps) | _allowed_emoji_indices(cps)
    findings: list[Finding] = []
    line, col = 1, 0
    for i, cp in enumerate(cps):
        if cp == 0x0A:
            line, col = line + 1, 0
            continue
        col += 1
        if not is_invisible(cp):
            continue
        reason = _reason(cps, i, exempt)
        if reason is not None:
            findings.append(Finding(i, line, col, cp, reason))
    return findings


def has_hidden(text: str) -> bool:
    return bool(scan(text))


def strip(text: str) -> str:
    """text with every reported character removed; kept characters stay."""
    drop = {f.index for f in scan(text)}
    if not drop:
        return text
    return "".join(c for i, c in enumerate(text) if i not in drop)


def _decode_tags(cps: list[int]) -> str:
    out = []
    for cp in cps:
        if 0xE0020 <= cp <= 0xE007E:
            out.append(chr(cp - 0xE0000))
    return "".join(out)


def describe(findings: list[Finding], limit: int = 20) -> str:
    """A short human-readable report: one line per run of adjacent findings.
    Tag-character runs are decoded, since tags encode ASCII text."""
    if not findings:
        return "No invisible or bidirectional-control characters found."
    runs: list[list[Finding]] = []
    for f in findings:
        if runs and f.index == runs[-1][-1].index + 1 and f.line == runs[-1][-1].line:
            runs[-1].append(f)
        else:
            runs.append([f])
    total = len(findings)
    lines = [f"Found {total} invisible or bidirectional-control character{'s' if total != 1 else ''}:"]
    for run in runs[:limit]:
        first = run[0]
        where = f"line {first.line}, column {first.column}"
        if len(run) == 1:
            lines.append(f"  {where}: {first.label} {first.name} ({first.reason})")
            continue
        labels = sorted({f.label for f in run})
        shown = ", ".join(labels[:4]) + (", ..." if len(labels) > 4 else "")
        line = f"  {where}: run of {len(run)} characters ({shown}; {first.reason})"
        hidden = _decode_tags([f.codepoint for f in run])
        if hidden:
            snippet = hidden if len(hidden) <= 120 else hidden[:117] + "..."
            line += f"; the tag characters spell: {snippet!r}"
        lines.append(line)
    if len(runs) > limit:
        lines.append(f"  ... and {len(runs) - limit} more run(s)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--strip"]
    do_strip = "--strip" in argv
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return 0
    sources = args or ["-"]
    found = False
    for src in sources:
        try:
            if src == "-":
                text = sys.stdin.read()
            else:
                with open(src, encoding="utf-8", errors="surrogateescape") as f:
                    text = f.read()
        except OSError as e:
            print(f"{src}: cannot read: {e}", file=sys.stderr)
            return 2
        findings = scan(text)
        found = found or bool(findings)
        report_to = sys.stderr if do_strip else sys.stdout
        if len(sources) > 1 or src != "-":
            print(f"{src}:", file=report_to)
        print(describe(findings), file=report_to)
        if do_strip:
            sys.stdout.write(strip(text))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
