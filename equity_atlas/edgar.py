"""Read SEC's extracted XBRL instance when Company Facts misses a filing."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
from xml.etree import ElementTree as ET

from .facts import EPS_FIELDS, REVERSE, SHARE_FIELDS, _assemble, qualifies

XBRL = "{http://www.xbrl.org/2003/instance}"
ISO4217 = "{http://www.xbrl.org/2003/iso4217}"
NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


# Scope verified against the explanatory note in each amendment. Each
# accession is paired with the original consolidated financial statements.
REVIEWED_AMENDMENTS = {
    ("0001193125-23-124228", "0000947871-24-000559"): "PetroChina updated Item 16I disclosures.",
    ("0000002488-26-000018", "0000002488-26-000021"): "AMD corrected client processor shipment and pricing growth in MD&A.",
    ("0001193125-25-307982", "0001193125-25-321328"): "Bank of Montreal corrected the date on its MD&A.",
    ("0001193125-26-049810", "0001193125-26-100426"): "Enbridge added Part III and related exhibits.",
    ("0001381197-26-000062", "0001381197-26-000072"): "Interactive Brokers corrected a date in the internal-controls auditor report.",
    ("0000764180-26-000017", "0000764180-26-000077"): "Altria added the financial statements of equity investee AB InBev.",
    ("0001477333-26-000016", "0001477333-26-000026"): "Cloudflare added Part III and related certifications.",
    ("0001594805-26-000007", "0001594805-26-000011"): "Shopify added Part III and related certifications.",
    ("0001628280-26-003952", "0001104659-26-053166"): "Tesla added Part III and related certifications.",
}


def amendment_reviews(filings, statement, latest):
    original = filings.get(statement["filing"])
    if (not original or original["end"] != latest["end"] or
            original["form"] != latest["form"].removesuffix("/A")):
        return []
    amendments = sorted(
        (f for f in filings.values() if f["form"] == latest["form"] and f["end"] == latest["end"]
         and f["filed"] >= original["filed"]),
        key=lambda f: (f["filed"], f["accession"]),
    )
    results = []
    for filing in amendments:
        reason = REVIEWED_AMENDMENTS.get((original["accession"], filing["accession"]))
        if reason is None:
            return []
        results.append({"accession": filing["accession"], "url": filing["url"], "scope": reason})
    return results


def instance_url(filing):
    doc = PurePosixPath(filing["primary"])
    if doc.suffix.lower() not in {".htm", ".html"}:
        raise ValueError("Primary filing is not an HTML document")
    return f"{filing['path']}/{doc.stem}_{doc.suffix[1:]}.xml"


def _context(node, cik):
    entity = node.find(XBRL + "entity")
    period = node.find(XBRL + "period")
    if entity is None or period is None or entity.find(XBRL + "segment") is not None:
        return None
    if node.find(XBRL + "scenario") is not None:
        return None
    identifier = entity.find(XBRL + "identifier")
    if identifier is None or identifier.get("scheme") != "http://www.sec.gov/CIK":
        return None
    if not (identifier.text or "").strip().isdigit() or int(identifier.text) != cik:
        return None
    instant = period.findtext(XBRL + "instant")
    start = period.findtext(XBRL + "startDate")
    end = instant or period.findtext(XBRL + "endDate")
    if not end or (not instant and not start):
        return None
    return date.fromisoformat(start) if start else None, date.fromisoformat(end)


def _unit(node, namespaces):
    def expanded(item):
        prefix, sep, name = (item.text or "").strip().partition(":")
        if not sep or prefix not in namespaces:
            return ""
        return "{" + namespaces[prefix] + "}" + name

    measures = node.findall(XBRL + "measure")
    if len(measures) == 1:
        unit = expanded(measures[0])
        if unit == XBRL + "shares":
            return "shares"
        if unit.startswith(ISO4217):
            return unit.removeprefix(ISO4217)
    divide = node.find(XBRL + "divide")
    if divide is not None:
        numerator = divide.findall(XBRL + "unitNumerator/" + XBRL + "measure")
        denominator = divide.findall(XBRL + "unitDenominator/" + XBRL + "measure")
        if len(numerator) == len(denominator) == 1 and expanded(denominator[0]) == XBRL + "shares":
            value = expanded(numerator[0])
            if value.startswith(ISO4217):
                return value.removeprefix(ISO4217) + "/shares"
    return None


def annual_from_instance(raw, meta, filing, cik):
    return periods_from_instance(raw, meta, filing, cik, ("annual",))["annual"]


def periods_from_instance(raw, meta, filing, cik, kinds):
    """Read one instance for the requested consolidated duration windows."""
    if re.search(rb"<!DOCTYPE", raw, flags=re.I):
        raise ValueError("Unexpected DTD in extracted filing")
    try:
        parsed = ET.XMLPullParser(events=("start-ns", "end"))
        parsed.feed(raw)
        namespaces = {}
        root = None
        for event, obj in parsed.read_events():
            if event == "start-ns":
                prefix, uri = obj
                if prefix in namespaces and namespaces[prefix] != uri:
                    raise ValueError("Ambiguous XBRL namespace prefix")
                namespaces[prefix] = uri
            else:
                root = obj
        parsed.close()
    except ET.ParseError as exc:
        raise ValueError("Invalid extracted XBRL XML") from exc
    if root is None or root.tag != XBRL + "xbrl":
        raise ValueError("Expected SEC extracted XBRL instance")
    contexts = {el.get("id"): _context(el, cik) for el in root.findall(XBRL + "context")}
    units = {el.get("id"): _unit(el, namespaces) for el in root.findall(XBRL + "unit")}
    groups = {kind: defaultdict(lambda: defaultdict(list)) for kind in kinds}
    period = date.fromisoformat(filing["end"])
    for node in root:
        namespace, _, tag = node.tag.removeprefix("{").partition("}")
        if re.fullmatch(r"https?://fasb\.org/us-gaap/[^/]+", namespace):
            standard = "us-gaap"
        elif re.fullmatch(r"https?://xbrl\.ifrs\.org/taxonomy/[^/]+/ifrs-full", namespace):
            standard = "ifrs-full"
        else:
            continue
        context = contexts.get(node.get("contextRef"))
        unit = units.get(node.get("unitRef"))
        if tag not in REVERSE or not context or not unit or node.get(NIL) in {"true", "1"}:
            continue
        start, end = context
        if end != period:
            continue
        try:
            value = Decimal(node.text or "")
        except InvalidOperation:
            continue
        if not value.is_finite() or abs(value) > Decimal("1e30"):
            continue
        number = int(value) if value == value.to_integral_value() else float(value)
        for metric, priority in REVERSE[tag]:
            if (metric in SHARE_FIELDS) != (unit == "shares") or (metric in EPS_FIELDS) != unit.endswith("/shares"):
                continue
            fact = {
                "value": number, "tag": standard + ":" + tag, "filed": filing["filed"], "unit": unit,
                "start": str(start) if start else None, "accession": filing["accession"], "form": filing["form"],
                "priority": priority, "url": filing["url"], "source": meta["url"], "sha256": meta["sha256"],
                "context_id": node.get("contextRef"), "decimals": node.get("decimals"),
            }
            for kind in kinds:
                if qualifies(metric, start, end, kind):
                    groups[kind][(end, unit.split("/")[0], filing["accession"])][metric].append(fact)
    for grouped in groups.values():
        share_facts = grouped.pop((period, "shares", filing["accession"]), {})
        for fields in grouped.values():
            fields.update(share_facts)
    return {kind: _assemble(grouped, {filing["accession"]: filing}, kind)
            for kind, grouped in groups.items()}
