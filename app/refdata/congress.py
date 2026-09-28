import re
from collections import defaultdict
from dataclasses import dataclass, field

# Public-domain dataset: https://github.com/unitedstates/congress-legislators
BASE_URL = "https://unitedstates.github.io/congress-legislators"
LEGISLATORS_URL = f"{BASE_URL}/legislators-current.json"
COMMITTEES_URL = f"{BASE_URL}/committees-current.json"
MEMBERSHIP_URL = f"{BASE_URL}/committee-membership-current.json"

PARTY_CODES = {"Democrat": "D", "Republican": "R", "Independent": "I"}
_COMMITTEE_PREFIX = re.compile(
    r"^(?:House|Senate|Joint)\s+(?:Permanent\s+)?(?:Select\s+|Special\s+)?Committee\s+on\s+(?:the\s+)?"
)


@dataclass(frozen=True)
class PoliticianRecord:
    bioguide_id: str
    full_name: str
    first_name: str
    last_name: str
    chamber: str
    party: str
    state: str
    district: int | None
    committees: list[str] = field(default_factory=list)


def committee_short_name(name: str) -> str:
    return _COMMITTEE_PREFIX.sub("", name).strip() or name


def parse_legislators(legislators: list[dict], committees: list[dict], membership: dict[str, list[dict]]) -> list[PoliticianRecord]:
    # Only full committees; subcommittee ids (e.g. "SSAF13") aren't in the committees list.
    names = {c["thomas_id"]: committee_short_name(c["name"]) for c in committees if c.get("thomas_id")}
    by_member: dict[str, set[str]] = defaultdict(set)
    for committee_id, members in membership.items():
        if committee_id in names:
            for member in members:
                if member.get("bioguide"):
                    by_member[member["bioguide"]].add(names[committee_id])

    records = []
    for person in legislators:
        bioguide = person.get("id", {}).get("bioguide")
        terms = person.get("terms") or []
        if not bioguide or not terms:
            continue
        term = terms[-1]
        name = person.get("name", {})
        first, last = name.get("first", ""), name.get("last", "")
        party = term.get("party", "")
        records.append(PoliticianRecord(
            bioguide_id=bioguide,
            full_name=name.get("official_full") or f"{first} {last}".strip(),
            first_name=first,
            last_name=last,
            chamber="senate" if term.get("type") == "sen" else "house",
            party=PARTY_CODES.get(party, party[:1].upper() or "?"),
            state=term.get("state", ""),
            district=term.get("district") if term.get("type") == "rep" else None,
            committees=sorted(by_member.get(bioguide, set())),
        ))
    return records
