"""Builds Form 4 submission text in EDGAR's real layout (SGML header + ownershipDocument XML)."""


def transaction(code: str, shares: str, price: str | None, day: str, after: str = "1000", acquired: str = "D") -> str:
    price_xml = f"<value>{price}</value>" if price is not None else '<footnoteId id="F1"/>'
    return f"""
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>{day}</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>{code}</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{shares}</value></transactionShares>
                <transactionPricePerShare>{price_xml}</transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{acquired}</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>{after}</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
            <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
        </nonDerivativeTransaction>"""


def owner(name: str, *, director: bool = False, officer_title: str = "", ten_percent: bool = False) -> str:
    return f"""
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001214156</rptOwnerCik>
            <rptOwnerName>{name}</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>{'true' if director else 'false'}</isDirector>
            <isOfficer>{'true' if officer_title else 'false'}</isOfficer>
            <isTenPercentOwner>{'true' if ten_percent else 'false'}</isTenPercentOwner>
            <isOther>false</isOther>
            <officerTitle>{officer_title}</officerTitle>
            <otherText></otherText>
        </reportingOwnerRelationship>
    </reportingOwner>"""


def submission(
    accession_no: str,
    transactions: list[str],
    owners: list[str],
    *,
    issuer_cik: str = "0000320193",
    ticker: str = "AAPL",
    issuer_name: str = "Apple Inc.",
    document_type: str = "4",
    plan: bool = False,
) -> str:
    return f"""<SEC-DOCUMENT>{accession_no}.txt : 20260925
<SEC-HEADER>{accession_no}.hdr.sgml : 20260925
ACCESSION NUMBER:		{accession_no}
CONFORMED SUBMISSION TYPE:	{document_type}
</SEC-HEADER>
<DOCUMENT>
<TYPE>{document_type}
<TEXT>
<XML>
<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>{document_type}</documentType>
    <periodOfReport>2026-09-23</periodOfReport>
    <issuer>
        <issuerCik>{issuer_cik}</issuerCik>
        <issuerName>{issuer_name}</issuerName>
        <issuerTradingSymbol>{ticker}</issuerTradingSymbol>
    </issuer>
    {''.join(owners)}
    <aff10b5One>{'1' if plan else '0'}</aff10b5One>
    <nonDerivativeTable>{''.join(transactions)}
    </nonDerivativeTable>
    <derivativeTable></derivativeTable>
</ownershipDocument>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""


# The three filings referenced by tests/fixtures/form_index_sample.idx.
APPLE_CEO_SALE = submission(
    "0001140361-26-000101",
    [
        transaction("S", "1000", "250.00", "2026-09-23", after="9000"),
        transaction("S", "3000", "252.00", "2026-09-24", after="6000"),
        transaction("F", "500", "251.00", "2026-09-24", after="5500"),
    ],
    [owner("Cook Timothy D", officer_title="Chief Executive Officer")],
    plan=True,
)
NVIDIA_DIRECTOR_BUY = submission(
    "0001045810-26-000202",
    [transaction("P", "2000", "180.50", "2026-09-24", after="12000", acquired="A")],
    [owner("Stevens Mark A", director=True)],
    issuer_cik="0001045810", ticker="NVDA", issuer_name="NVIDIA CORP",
)
APPLE_GRANT_ONLY = submission(
    "0001140361-26-000303",
    [transaction("A", "10000", "0", "2026-09-24", acquired="A")],
    [owner("Adams Katherine L", officer_title="SVP, General Counsel")],
)
