"""Number -> words, matching the template's style:
41382 -> "Forty One Thousand Three Hundred Eighty Two Only."
Uses international (thousand/million) grouping as the sample certificate does.
"""

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety"]
_SCALES = [(10 ** 9, "Billion"), (10 ** 6, "Million"), (10 ** 3, "Thousand")]


def _below_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10])
        n %= 10
    if n:
        parts.append(_ONES[n])
    return " ".join(parts)


def amount_in_words(amount: float) -> str:
    n = int(round(amount))
    if n == 0:
        return "Zero Only."
    parts = []
    for scale, name in _SCALES:
        if n >= scale:
            parts.append(f"{_below_thousand(n // scale)} {name}")
            n %= scale
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts) + " Only."
