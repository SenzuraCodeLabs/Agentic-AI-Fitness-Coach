"""Generate resources/confusables.json.

Built from explicit codepoint lists rather than a Unicode data download so the
resource is reproducible offline and every entry is auditable. Each entry maps
a lookalike character to the Latin letter it imitates.
"""

import json
import unicodedata

# Cyrillic homoglyphs -> Latin
cyrillic = {
    "\u0430": "a",
    "\u0410": "A",
    "\u0435": "e",
    "\u0415": "E",
    "\u043e": "o",
    "\u041e": "O",
    "\u0440": "p",
    "\u0420": "P",
    "\u0441": "c",
    "\u0421": "C",
    "\u0445": "x",
    "\u0425": "X",
    "\u0443": "y",
    "\u0423": "Y",
    "\u0456": "i",
    "\u0406": "I",
    "\u0458": "j",
    "\u0408": "J",
    "\u043a": "k",
    "\u041a": "K",
    "\u043c": "m",
    "\u041c": "M",
    "\u043d": "h",
    "\u041d": "H",
    "\u0432": "B",
    "\u0412": "B",
    "\u0433": "r",
    "\u0413": "T",
    "\u0442": "t",
    "\u0422": "T",
    "\u0405": "S",
    "\u0455": "s",
    "\u04bb": "h",
    "\u049b": "k",
    "\u04cf": "l",
    "\u0501": "d",
    "\u051b": "q",
    "\u0525": "p",
    "\u0261": "g",
}

# Greek homoglyphs -> Latin
greek = {
    "\u03b1": "a",
    "\u0391": "A",
    "\u0392": "B",
    "\u03b5": "e",
    "\u0395": "E",
    "\u0396": "Z",
    "\u0397": "H",
    "\u0399": "I",
    "\u039a": "K",
    "\u039c": "M",
    "\u039d": "N",
    "\u039f": "O",
    "\u03bf": "o",
    "\u03a1": "P",
    "\u03a4": "T",
    "\u03a5": "Y",
    "\u03a7": "X",
    "\u03c1": "p",
    "\u03c3": "o",
    "\u03c5": "u",
    "\u03bd": "v",
    "\u03ba": "k",
    "\u03b9": "i",
    "\u03c4": "t",
    "\u03b3": "y",
    "\u03c7": "x",
    "\u03b2": "B",
    "\u039b": "A",
    "\u03a3": "E",
}

# Fullwidth forms -> ASCII
fullwidth = {chr(0xFF21 + i): chr(ord("A") + i) for i in range(26)}
fullwidth.update({chr(0xFF41 + i): chr(ord("a") + i) for i in range(26)})
fullwidth.update({chr(0xFF10 + i): chr(ord("0") + i) for i in range(10)})

# Mathematical alphanumeric symbols: bold, italic, script, monospace, etc.
# These render as normal letters but are distinct codepoints, a very common
# filter-evasion trick.
math_blocks = [
    0x1D400,
    0x1D434,
    0x1D468,
    0x1D49C,
    0x1D4D0,
    0x1D504,
    0x1D538,
    0x1D56C,
    0x1D5A0,
    0x1D5D4,
    0x1D608,
    0x1D63C,
    0x1D670,
]
math = {}
for base in math_blocks:
    for i in range(26):
        up, lo = chr(base + i), chr(base + 26 + i)
        math[up] = chr(ord("A") + i)
        math[lo] = chr(ord("a") + i)

# Circled and parenthesised letters
enclosed = {}
for i in range(26):
    enclosed[chr(0x24B6 + i)] = chr(ord("A") + i)  # circled capital
    enclosed[chr(0x24D0 + i)] = chr(ord("a") + i)  # circled small
    enclosed[chr(0x1F110 + i)] = chr(ord("A") + i)  # parenthesised

# Misc Latin lookalikes and punctuation that splits words
misc = {
    "\u0131": "i",
    "\u0142": "l",
    "\u017f": "s",
    "\u0180": "b",
    "\u01dd": "e",
    "\u0250": "a",
    "\u0254": "c",
    "\u0258": "e",
    "\u026a": "i",
    "\u0279": "r",
    "\u027e": "r",
    "\u028c": "v",
    "\u028f": "y",
    "\u0292": "z",
    "\u1d00": "a",
    "\u1d04": "c",
    "\u1d07": "e",
    "\u0e04": "o",
    "\u2170": "i",
    "\u217c": "l",
    "\u2044": "/",
    "\u2215": "/",
}

table = {}
for src in (cyrillic, greek, fullwidth, math, enclosed, misc):
    table.update(src)

# Drop any entry that is already its own target after NFKC, since L1 runs NFKC
# first and those would be dead weight.
pruned = {k: v for k, v in table.items() if unicodedata.normalize("NFKC", k) != v}
dropped = len(table) - len(pruned)

out = {
    "_comment": "Homoglyph map: lookalike codepoint -> Latin equivalent. "
    "Entries already handled by NFKC normalisation are excluded.",
    "_generated_by": "scripts/gen_confusables.py",
    "map": dict(sorted(pruned.items())),
}
path = "services/agent1_gatekeeper/resources/confusables.json"
with open(path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(f"total candidates={len(table)} kept={len(pruned)} dropped_as_nfkc_handled={dropped}")
