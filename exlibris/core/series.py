"""Series names and numbers from Open Library's edition "series" field, which is
often a publisher line ("Penguin classics L210") rather than a story series."""
import re

IMPRINT = re.compile(r"\b(classics?|library|collection|folio|penguin|virago|oxford|macmillan|complete works|works of|"
                     r"history of|fiction|edition|editions|books)\b", re.I)
NUMBERED = re.compile(r"^(?P<name>.+?)(?:\s*(?:,|;|--|—|–|#|\(|\bseries\b|\bbook\b|\bno\.?|\bvol\.?)\s*)+#?"
                      r"(?P<n>\d+(?:\.\d+)?)\)?$", re.I)


def parse(value):
    """-> (name, number) or (None, None)."""
    vals = value if isinstance(value, list) else [value]
    s = next((v.strip() for v in vals if isinstance(v, str) and v.strip()), "")
    s = s.strip().strip("()").strip(" .")
    if not s:
        return None, None
    m = NUMBERED.match(s)
    name, n = (m.group("name"), float(m.group("n"))) if m else (s, None)
    name = name.strip(" ,;:-–—#(")
    if not name or IMPRINT.search(name) or re.search(r"\b[A-Z]\d+$", name) or (n is not None and n > 100):
        return None, None
    return name, (int(n) if n is not None and n.is_integer() else n)


def gaps(indices):
    """Whole-number places missing between 1 and the highest owned."""
    have = {int(i) for i in indices if isinstance(i, (int, float)) and i > 0 and float(i).is_integer()}
    return [i for i in range(1, max(have) + 1) if i not in have] if have else []
