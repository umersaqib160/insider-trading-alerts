import csv
import io
from dataclasses import dataclass

# Maintained mirror of Wikipedia's constituents table, including SEC CIK numbers.
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


@dataclass(frozen=True)
class CompanyRecord:
    ticker: str
    name: str
    sector: str
    sub_industry: str
    cik: str | None


def parse_constituents(text: str) -> list[CompanyRecord]:
    records: dict[str, CompanyRecord] = {}
    for row in csv.DictReader(io.StringIO(text)):
        ticker = (row.get("Symbol") or "").strip().upper()
        name = (row.get("Security") or "").strip()
        if not ticker or not name:
            continue
        cik = (row.get("CIK") or "").strip()
        records[ticker] = CompanyRecord(
            ticker=ticker,
            name=name,
            sector=(row.get("GICS Sector") or "").strip(),
            sub_industry=(row.get("GICS Sub-Industry") or "").strip(),
            cik=cik.zfill(10) if cik.isdigit() else None,
        )
    return list(records.values())
