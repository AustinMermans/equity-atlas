"""Read the consolidated table in an SEC-rendered financial statement."""

from datetime import datetime
from html.parser import HTMLParser
import re


class ReportTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.report_count = 0
        self.rows = []
        self.row = None
        self.cell = None
        self.footnote = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif "report" in classes:
                self.report_count += 1
                self.depth = 1
        if self.depth != 1:
            return
        if tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"td", "th"}:
            self.cell = {"classes": classes, "text": [], "concept": None}
        elif self.cell is not None and tag == "a":
            concept = re.search(r"'defref_([\w-]+)_([\w]+)'", attrs.get("onclick", ""))
            if concept:
                self.cell["concept"] = ":".join(concept.groups())
        elif tag == "sup":
            self.footnote = True

    def handle_data(self, data):
        if self.depth == 1 and self.cell is not None and not self.footnote:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if self.depth == 1:
            if tag in {"td", "th"} and self.cell is not None:
                self.cell["text"] = " ".join(" ".join(self.cell["text"]).split())
                self.row.append(self.cell)
                self.cell = None
            elif tag == "tr" and self.row:
                self.rows.append(self.row)
                self.row = None
            elif tag == "sup":
                self.footnote = False
        if tag == "table" and self.depth:
            self.depth -= 1


def rendered_number(text):
    if not text:
        return None
    if text in {"-", "–", "—"}:
        return 0
    cleaned = text.replace("$", "").replace(",", "").strip()
    if re.fullmatch(r"\([0-9]+(?:\.[0-9]+)?\)", cleaned):
        cleaned = "-" + cleaned[1:-1]
    if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", cleaned):
        raise ValueError("Unsupported SEC-rendered cash-flow amount")
    return float(cleaned) if "." in cleaned else int(cleaned)


def read_cash_flow(raw, title, currency, end, scale):
    """Read only the consolidated period columns, stopping at the first dimensional block."""
    parser = ReportTable()
    parser.feed(raw.decode("utf-8"))
    parser.close()
    if parser.report_count != 1 or len(parser.rows) < 3 or len(parser.rows[0]) != 2:
        raise ValueError("Missing consolidated SEC-rendered cash-flow table")
    title_cell, period_cell = (x["text"] for x in parser.rows[0])
    unit = {1_000: "Thousands", 1_000_000: "Millions", 1_000_000_000: "Billions"}.get(scale)
    expected = f"{title} - {currency} ($) $ in {unit}" if unit else f"{title} - {currency} ($)"
    if title_cell.casefold() != expected.casefold() or period_cell != "12 Months Ended":
        raise ValueError("Unexpected title, currency, units or period on SEC cash-flow table")
    dates = [datetime.strptime(cell["text"].replace(".", ""), "%b %d, %Y").date().isoformat()
             for cell in parser.rows[1]]
    if dates.count(end) != 1:
        raise ValueError("Missing selected fiscal year on SEC cash-flow table")
    rows = []
    for cells in parser.rows[2:]:
        label = cells[0]
        if not label["concept"]:
            break
        values = [rendered_number(cell["text"]) for cell in cells[1:] if {"num", "nump", "text"} & set(cell["classes"])]
        if len(values) != len(dates):
            raise ValueError("Unexpected number of fiscal columns in SEC cash-flow row")
        rows.append([label["text"], label["concept"], *values])
    if not rows:
        raise ValueError("SEC-rendered cash-flow table contains no consolidated rows")
    return {"title": title, "currency": currency, "money_scale": scale, "rows": rows}, 2 + dates.index(end)
