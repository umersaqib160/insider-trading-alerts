"""Approximate GICS-style sectors from SEC SIC codes, for companies outside the S&P 500.

S&P 500 members keep their official GICS sector. Everyone else gets the
closest match from their SIC industry code, which is good enough for a
sector filter and for matching trades to congressional committees.
"""
import re

# (first SIC, last SIC, sector). The first matching range wins, so narrow ranges come before broad ones.
_RANGES = [
    (1311, 1389, "Energy"),
    (2830, 2836, "Health Care"),
    (2840, 2844, "Consumer Staples"),
    (2900, 2999, "Energy"),
    (3570, 3579, "Information Technology"),
    (3630, 3639, "Consumer Discretionary"),
    (3710, 3716, "Consumer Discretionary"),
    (3720, 3729, "Industrials"),
    (3760, 3769, "Industrials"),
    (3812, 3812, "Industrials"),
    (3840, 3851, "Health Care"),
    (5120, 5122, "Health Care"),
    (5400, 5499, "Consumer Staples"),
    (5910, 5912, "Consumer Staples"),
    (6500, 6553, "Real Estate"),
    (6798, 6798, "Real Estate"),
    (7370, 7379, "Information Technology"),
    (100, 999, "Consumer Staples"),
    (1000, 1499, "Materials"),
    (1500, 1799, "Industrials"),
    (2000, 2199, "Consumer Staples"),
    (2200, 2399, "Consumer Discretionary"),
    (2400, 2499, "Materials"),
    (2500, 2599, "Consumer Discretionary"),
    (2600, 2699, "Materials"),
    (2700, 2799, "Communication Services"),
    (2800, 2899, "Materials"),
    (3000, 3099, "Materials"),
    (3100, 3199, "Consumer Discretionary"),
    (3200, 3399, "Materials"),
    (3400, 3569, "Industrials"),
    (3580, 3599, "Industrials"),
    (3600, 3699, "Information Technology"),
    (3700, 3799, "Industrials"),
    (3800, 3899, "Information Technology"),
    (3900, 3999, "Consumer Discretionary"),
    (4000, 4799, "Industrials"),
    (4800, 4899, "Communication Services"),
    (4900, 4999, "Utilities"),
    (5000, 5199, "Industrials"),
    (5200, 5999, "Consumer Discretionary"),
    (6000, 6799, "Financials"),
    (7000, 7299, "Consumer Discretionary"),
    (7300, 7399, "Industrials"),
    (7800, 7999, "Communication Services"),
    (8000, 8099, "Health Care"),
    (8100, 8999, "Industrials"),
]


def sector_for_sic(sic: int | None) -> str:
    if sic is None:
        return ""
    for low, high, sector in _RANGES:
        if low <= sic <= high:
            return sector
    return ""


def tidy_industry(description: str) -> str:
    """SEC writes some industries in capitals ("SERVICES-PREPACKAGED SOFTWARE")."""
    if description != description.upper():
        return description
    return re.sub(r"[A-Z]+", lambda m: m.group().capitalize(), description)
