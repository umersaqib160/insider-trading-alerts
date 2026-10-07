"""SEC EDGAR access: the daily form index and Form 4 (insider transaction) filings."""

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime

import httpx

EDGAR_BASE = "https://www.sec.gov"
# SEC's fair-access limit is 10 requests/second, but it also throttles sustained bursts; stay well under.
MIN_REQUEST_INTERVAL = 0.2
RETRY_STATUSES = {429, 503}
RETRY_BACKOFF = (10.0, 30.0, 60.0)
MAX_RETRY_WAIT = 120.0

_INDEX_LINE = re.compile(
    r"^(?P<form>\S+(?: \S+)*?)\s{2,}(?P<company>.+?)\s+(?P<cik>\d+)\s+(?P<filed>\d{8})\s+(?P<path>edgar/\S+\.txt)\s*$"
)
_XML_BLOCK = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.S)


class EdgarError(Exception):
    pass


@dataclass(frozen=True)
class IndexEntry:
    form: str
    company: str
    cik: int
    filed: date
    path: str

    @property
    def accession_no(self) -> str:
        return self.path.rsplit("/", 1)[-1].removesuffix(".txt")


@dataclass(frozen=True)
class InsiderTrade:
    accession_no: str
    issuer_cik: int
    ticker: str
    issuer_name: str
    insider_name: str
    insider_title: str
    code: str
    shares: float
    avg_price: float | None
    value: float | None
    shares_owned_after: float | None
    trade_date: date
    is_10b5_1: bool


@dataclass(frozen=True)
class FeedEntry:
    form: str
    accession_no: str
    cik: int
    role: str  # "Issuer" (the company) or "Reporting" (the insider)
    filed: date
    updated: datetime


_FEED_TITLE = re.compile(r"^(?P<form>.+?) - .*\((?P<cik>\d{10})\) \((?P<role>\w+)\)\s*$")
_FEED_FILED = re.compile(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})")
_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def current_feed_path(start: int = 0, count: int = 100) -> str:
    """SEC's "latest filings" feed. `type=4` is a prefix filter, so other forms (e.g. 424B2) appear too."""
    return (f"/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=include"
            f"&start={start}&count={count}&output=atom")


def parse_current_feed(xml: str) -> list[FeedEntry]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise EdgarError("SEC EDGAR returned an unreadable filings feed") from exc
    entries = []
    for entry in root.findall("a:entry", _ATOM):
        title = _FEED_TITLE.match((entry.findtext("a:title", "", _ATOM) or "").strip())
        entry_id = entry.findtext("a:id", "", _ATOM) or ""
        updated = entry.findtext("a:updated", "", _ATOM) or ""
        filed = _FEED_FILED.search(entry.findtext("a:summary", "", _ATOM) or "")
        if not title or "accession-number=" not in entry_id or not updated:
            continue
        try:
            updated_at = datetime.fromisoformat(updated)
        except ValueError:
            continue
        entries.append(FeedEntry(
            form=title["form"].strip(),
            accession_no=entry_id.split("accession-number=", 1)[1].strip(),
            cik=int(title["cik"]),
            role=title["role"],
            filed=date.fromisoformat(filed.group(1)) if filed else updated_at.date(),
            updated=updated_at,
        ))
    return entries


def daily_index_path(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"/Archives/edgar/daily-index/{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx"


def filing_index_url(cik: int, accession_no: str) -> str:
    return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_no.replace('-', '')}/{accession_no}-index.htm"


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not user_agent:
            raise EdgarError("SEC_USER_AGENT must be set, e.g. 'Behind The Curtain you@example.com'.")
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._sleep = sleep
        self._clock = clock
        self._last_request = float("-inf")

    def _throttle(self) -> None:
        wait = self._last_request + MIN_REQUEST_INTERVAL - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def get_text(self, path: str) -> str | None:
        """Fetch a sec.gov path or full SEC URL. Returns None for 404 (e.g. no index on a holiday)."""
        url = path if path.startswith("https://") else EDGAR_BASE + path
        for attempt, backoff in enumerate((*RETRY_BACKOFF, None)):
            self._throttle()
            try:
                response = self._http.get(url, headers=self._headers)
            except httpx.HTTPError as exc:
                raise EdgarError(f"Couldn't reach SEC EDGAR for {path}: {exc}") from exc
            if response.status_code in RETRY_STATUSES and backoff is not None:
                # SEC throttles bursts with 429; wait as asked (or back off) and try again.
                retry_after = response.headers.get("Retry-After", "")
                self._sleep(min(float(retry_after), MAX_RETRY_WAIT) if retry_after.isdigit() else backoff)
                continue
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise EdgarError(f"SEC EDGAR returned HTTP {response.status_code} for {path}")
            return response.text
        raise AssertionError("unreachable")

    def get_json(self, path: str) -> dict | None:
        text = self.get_text(path)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError as exc:
            raise EdgarError(f"SEC EDGAR returned invalid JSON for {path}") from exc


def parse_daily_index(text: str) -> list[IndexEntry]:
    entries = []
    in_body = False
    for line in text.splitlines():
        if not in_body:
            in_body = line.startswith("-----")
            continue
        match = _INDEX_LINE.match(line.strip())
        if not match:
            continue
        filed = match["filed"]
        entries.append(IndexEntry(
            form=match["form"],
            company=match["company"].strip(),
            cik=int(match["cik"]),
            filed=date(int(filed[:4]), int(filed[4:6]), int(filed[6:])),
            path=match["path"],
        ))
    return entries


def _text(element: ET.Element | None, path: str) -> str:
    if element is None:
        return ""
    found = element.find(path)
    return (found.text or "").strip() if found is not None else ""


def _number(element: ET.Element, path: str) -> float | None:
    raw = _text(element, path)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _flag(raw: str) -> bool:
    return raw.lower() in {"1", "true"}


_ENTITY_WORDS = {
    "INC", "INC.", "LLC", "L.L.C.", "LP", "L.P.", "LLP", "CORP", "CORP.", "CORPORATION", "CO", "CO.", "COMPANY",
    "LTD", "LTD.", "TRUST", "FUND", "FUNDS", "HOLDINGS", "HOLDING", "PARTNERS", "CAPITAL", "GROUP", "MANAGEMENT",
    "FOUNDATION", "BANK", "PLC", "N.V.", "S.A.", "AG", "&", "ADVISORS", "INVESTMENTS", "ASSOCIATES",
}
_NAME_SUFFIXES = {"JR", "JR.", "SR", "SR.", "II", "III", "IV"}
_KEEP_UPPER = {"CEO", "CFO", "COO", "CTO", "CIO", "CAO", "CLO", "CMO", "CPO", "CHRO", "CRO", "CSO", "EVP", "SVP", "SEVP",
               "VP", "GC", "US", "U.S.", "II", "III", "IV", "LLC", "LP", "IT", "HR", "R&D"}
_KEEP_LOWER = {"AND", "OF", "THE", "FOR", "TO", "IN", "AT", "ON"}


def _tidy_case(text: str) -> str:
    """Title-case text that EDGAR filed in all capitals; leave mixed case alone."""
    if not text or text != text.upper():
        return text
    words = []
    for i, word in enumerate(text.split()):
        bare = word.strip(",;()")
        if bare in _KEEP_UPPER:
            words.append(word)
        elif bare in _KEEP_LOWER and i > 0:
            words.append(word.lower())
        else:
            words.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(words)


def person_name(raw: str) -> str:
    """EDGAR files people surname-first ("SAMUELI HENRY"); show them first-name-first ("Henry Samueli")."""
    words = raw.split()
    if len(words) < 2 or len(words) > 5 or any(w.upper() in _ENTITY_WORDS for w in words) or "," in raw:
        return _tidy_case(raw)
    suffix = [words.pop()] if words[-1].upper() in _NAME_SUFFIXES and len(words) > 2 else []
    return _tidy_case(" ".join(words[1:] + words[:1] + suffix))


def _insider_title(relationship: ET.Element | None) -> str:
    parts = []
    if _flag(_text(relationship, "isOfficer")):
        parts.append(_tidy_case(_text(relationship, "officerTitle")) or "Officer")
    if _flag(_text(relationship, "isDirector")):
        parts.append("Director")
    if _flag(_text(relationship, "isTenPercentOwner")):
        parts.append("10% Owner")
    if not parts and _flag(_text(relationship, "isOther")):
        parts.append(_text(relationship, "otherText") or "Insider")
    return ", ".join(parts)


def parse_form4(submission: str, accession_no: str) -> list[InsiderTrade]:
    """Open-market purchases (P) and sales (S) in a Form 4, one InsiderTrade per code."""
    block = _XML_BLOCK.search(submission)
    if not block:
        return []
    try:
        root = ET.fromstring(block.group(1))
    except ET.ParseError:
        return []
    if _text(root, "documentType") != "4":
        return []

    owners = root.findall("reportingOwner")
    names = [person_name(_text(o, "reportingOwnerId/rptOwnerName")) for o in owners]
    names = [n for n in names if n]
    insider_name = names[0] if len(names) <= 1 else f"{names[0]} and {len(names) - 1} other{'s' if len(names) > 2 else ''}"
    insider_title = _insider_title(owners[0].find("reportingOwnerRelationship")) if owners else ""

    totals: dict[str, dict] = {}
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        shares = _number(tx, "transactionAmounts/transactionShares/value")
        raw_date = _text(tx, "transactionDate/value")[:10]
        if code not in {"P", "S"} or not shares or not raw_date:
            continue
        try:
            tx_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        price = _number(tx, "transactionAmounts/transactionPricePerShare/value")
        t = totals.setdefault(code, {"shares": 0.0, "priced_shares": 0.0, "value": 0.0, "date": tx_date, "after": None})
        t["shares"] += shares
        if price:
            t["priced_shares"] += shares
            t["value"] += shares * price
        t["date"] = min(t["date"], tx_date)
        after = _number(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        if after is not None:
            t["after"] = after

    issuer_cik = _text(root, "issuer/issuerCik")
    trades = []
    for code, t in totals.items():
        avg_price = t["value"] / t["priced_shares"] if t["priced_shares"] else None
        trades.append(InsiderTrade(
            accession_no=accession_no,
            issuer_cik=int(issuer_cik) if issuer_cik.isdigit() else 0,
            ticker=_text(root, "issuer/issuerTradingSymbol").upper(),
            issuer_name=_text(root, "issuer/issuerName"),
            insider_name=insider_name,
            insider_title=insider_title,
            code=code,
            shares=t["shares"],
            avg_price=avg_price,
            value=avg_price * t["shares"] if avg_price is not None else None,
            shares_owned_after=t["after"],
            trade_date=t["date"],
            is_10b5_1=_flag(_text(root, "aff10b5One")),
        ))
    return trades
