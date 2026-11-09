"""Read selected Inline XBRL numbers from verified issuer-hosted SEC filings."""
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
import re

from .edgar import XBRL, _context, _periods
from .facts import REVERSE

ISSUER_INLINE = {
    1045609: "https://ir.prologis.com/financials/sec-filings/content",
    2115436: "https://investor.exxonmobil.com/sec-filings/all-sec-filings/content",
}
IX = "http://www.xbrl.org/2013/inlineXBRL"
DEI = r"https?://xbrl\.sec\.gov/dei/[^/]+"
TRANSFORMS = {
    "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
    "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
}
RESOURCE_NAMES = {name.lower(): name for name in (
    "context", "entity", "identifier", "period", "startDate", "endDate", "instant",
    "segment", "scenario", "unit", "measure", "divide", "unitNumerator", "unitDenominator",
)}
HEADER_NAMES = {"EntityCentralIndexKey", "DocumentType", "DocumentPeriodEndDate"}
MONTHS = "January February March April May June July August September October November December".split()


def inline_url(cik, filing):
    root = ISSUER_INLINE.get(cik)
    return f"{root}/{filing['accession']}/{filing['primary']}" if root else None


class InlineDocument(HTMLParser):
    """Capture only XBRL resources and facts, including HTML-serialized filings."""
    def __init__(self):
        super().__init__()
        self.namespaces = {}
        self.resources = None
        self.builder = None
        self.open_facts = []
        self.facts = []

    def expanded(self, name):
        prefix, sep, local = name.partition(":")
        return self.namespaces.get(prefix, "") if sep else "", local if sep else prefix

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name, uri in attrs.items():
            if name.startswith("xmlns:"):
                prefix = name.removeprefix("xmlns:")
                if prefix in self.namespaces and self.namespaces[prefix] != uri:
                    raise ValueError("Ambiguous Inline XBRL namespace prefix")
                self.namespaces[prefix] = uri
        namespace, local = self.expanded(tag)
        if namespace == IX and local == "resources":
            if self.builder is not None or self.resources is not None:
                raise ValueError("Multiple Inline XBRL resource blocks")
            self.builder = ET.TreeBuilder()
        if self.builder is not None:
            self.builder.start(self.resource_tag(namespace, local), {k: v for k, v in attrs.items() if v is not None})
        elif namespace == IX and local in {"nonfraction", "nonnumeric", "exclude"}:
            self.open_facts.append((local, attrs, []))

    def handle_endtag(self, tag):
        namespace, local = self.expanded(tag)
        if self.builder is not None:
            self.builder.end(self.resource_tag(namespace, local))
            if namespace == IX and local == "resources":
                self.resources = self.builder.close()
                self.builder = None
        elif namespace == IX and local in {"nonfraction", "nonnumeric", "exclude"}:
            if not self.open_facts or self.open_facts[-1][0] != local:
                raise ValueError("Unbalanced Inline XBRL fact")
            kind, attrs, parts = self.open_facts.pop()
            if kind != "exclude":
                self.facts.append((kind, attrs, "".join(parts).strip()))

    def handle_data(self, data):
        if self.builder is not None:
            self.builder.data(data)
        else:
            for kind, _, parts in reversed(self.open_facts):
                if kind == "exclude":
                    break
                parts.append(data)

    @staticmethod
    def resource_tag(namespace, local):
        if namespace == XBRL[1:-1]:
            local = RESOURCE_NAMES.get(local, local)
        return f"{{{namespace}}}{local}"


def inline_number(document, attrs, text):
    transform = attrs.get("format")
    if transform:
        namespace, rule = document.expanded(transform)
        if namespace not in TRANSFORMS:
            return None
        if rule == "fixed-zero":
            text = "0"
        elif rule == "num-dot-decimal" and re.fullmatch(r"[, 0-9\u00a0]*(\.[ 0-9\u00a0]+)?", text):
            text = re.sub(r"[, \u00a0]", "", text)
        else:
            return None
    sign = attrs.get("sign", "")
    scale = attrs.get("scale", "0")
    if (sign not in {"", "-"} or not re.fullmatch(r"-?[0-9]{1,2}", scale)
            or not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", text)):
        return None
    # Decimal construction with an exponent keeps the filed coefficient exact.
    return Decimal(f"{sign}{text}e{scale}")


def filing_day(value):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    m = re.fullmatch(r"([A-Za-z]+) ([0-9]{1,2}),? ([0-9]{4})", value)
    if m and m[1] in MONTHS:
        return date(int(m[3]), MONTHS.index(m[1])+1, int(m[2]))
    return None


def periods_from_inline(raw, meta, filing, cik, kinds):
    document = InlineDocument()
    document.feed(raw.decode("utf-8-sig"))
    document.close()
    resources = document.resources
    if resources is None or document.builder is not None or document.open_facts:
        raise ValueError("Incomplete Inline XBRL document")
    ids = [x.get("id") for x in resources if x.tag in {XBRL + "context", XBRL + "unit"}]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate Inline XBRL resource ID")
    contexts = {x.get("id"): _context(x, cik) for x in resources.findall(XBRL + "context")}
    header = {}
    numbers = []
    for kind, attrs, text in document.facts:
        namespace, local = document.expanded(attrs.get("name", ""))
        context_id = attrs.get("contextref")
        context = contexts.get(context_id)
        if not context or context[1].isoformat() != filing["end"]:
            continue
        if kind == "nonnumeric" and re.fullmatch(DEI, namespace) and local in HEADER_NAMES:
            header.setdefault(local, set()).add(" ".join(text.split()))
        if kind != "nonfraction" or local not in REVERSE or attrs.get("xsi:nil") in {"true", "1"}:
            continue
        value = inline_number(document, attrs, text)
        if value is None:
            continue
        node = ET.Element(f"{{{namespace}}}{local}", {
            "contextRef": context_id, "unitRef": attrs.get("unitref", ""),
            "decimals": attrs.get("decimals", ""), "id": attrs.get("id", ""),
        })
        node.text = str(value)
        numbers.append(node)
    if (header.get("EntityCentralIndexKey") != {f"{cik:010d}"} or header.get("DocumentType") != {filing["form"]}
            or {filing_day(d) for d in header.get("DocumentPeriodEndDate", ())} != {date.fromisoformat(filing["end"])}):
        raise ValueError("Inline XBRL cover does not match SEC filing metadata")
    result = _periods(resources, numbers, document.namespaces, meta, filing, cik, kinds)
    for periods in result.values():
        for period in periods:
            period["route"] = "issuer_inline"
    return result
