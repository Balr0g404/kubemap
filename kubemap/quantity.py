import re

_UNITS = {
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5,
    "k": 1000, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4, "P": 1000**5,
}
_RE = re.compile(r"^([0-9.]+)([A-Za-z]*)$")


def parse_bytes(q) -> int:
    m = _RE.match(str(q))
    if not m:
        raise ValueError(f"quantité invalide : {q!r}")
    number, unit = m.groups()
    if unit == "":
        return int(float(number))
    if unit not in _UNITS:
        raise ValueError(f"unité inconnue : {q!r}")
    return int(float(number) * _UNITS[unit])


def parse_cpu(q) -> float:
    """Millicœurs."""
    s = str(q)
    if s.endswith("n"):
        return float(s[:-1]) / 1_000_000
    if s.endswith("u"):
        return float(s[:-1]) / 1000
    if s.endswith("m"):
        return float(s[:-1])
    return float(s) * 1000


def format_bytes(n: int) -> str:
    value, unit = float(n), "B"
    for unit in ("B", "Ki", "Mi", "Gi", "Ti", "Pi"):
        if value < 1024 or unit == "Pi":
            break
        value /= 1024
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} {unit}"
