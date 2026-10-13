"""
Code-only reading of the Ind AS 108 segment note (no language model): the revenue-by-geography table and the major-customer sentences, from the annual report's
own text lines. It writes its findings in the SAME shape as a model answer, so scripts/revenue_profile.py checks them with exactly the same rules (every quote word
for word on its page, every number inside its quote, rows adding up to the stated total). When it finds enough, no model call is made for that company.

  geography   a "Geographical information" block that speaks of revenue (or sales / turnover / income), its region lines with their amounts, and a Total line.
              Kept only when the rows add up to the total within 3%. The current-year column is the one whose year comes first in the block's header (Indian reports
              put the current year first; when the earlier year comes first, the second column is used). Asset tables (non-current assets by region) end the block.
  none        a sentence saying no single customer brings 10% or more of revenue (the same test the model's answer must pass).
  major       a sentence about ONE customer (one / single / a / largest customer) and revenue with a percentage of 10 or more (the first one written, which is the
              current year), or an amount in crore / lakh / million that the profile turns into a share using the checked geography total.
Pure functions (tests/test_revenue_rules.py).
"""
import re

REGION = re.compile(r"^\s*(?:[a-z]\)|\(?[ivx]+\)|\d+\.)?\s*(within india|in india|india|domestic(?: sales| market| revenue)?|local(?: sales)?|export(?:s| sales)?|outside india|overseas|rest of (?:the )?world|exports?|international|foreign countries|"
                    r"other countries|others?|usa|u\.s\.a\.?|united states(?: of america)?|north america|south america|latin america|europe|european union|uk|united kingdom|"
                    r"middle east|gcc|asia(?: pacific)?|africa|china|japan|sri lanka|bangladesh|nepal|south east asia|australia|row|americas)\b", re.I)
TOTAL = re.compile(r"^\s*total\b", re.I)
NUM = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
HEAD = re.compile(r"geographic(?:al)? (?:(?:gross )?revenue|information|areas?|segments?|break-?up|distribution)|entity[- ]wide disclosures?|revenue (?:from external customers )?by geograph", re.I)
REVENUE = re.compile(r"revenue|sales|turnover|income from operations", re.I)
STOP = re.compile(r"non[- ]current assets|segment assets|^\s*assets\b|capital expenditure|trade receivables", re.I)
UNIT = re.compile(r"(?:rs\.?|₹|`|inr)?\s*\(?\s*in\s+(?:rs\.?\s*|₹\s*|inr\s*)?(crores?|lakhs?|lacs?|millions?|mn|billions?|thousands?)\b", re.I)
YEAR = re.compile(r"\b(20\d\d)\b")
TEN = r"(?:10(?:\.0+)?\s?%|ten per ?cent)"                              # "10%", "10.0 %", "ten percent"
NO_MAJOR = re.compile(r"\b(no|not|none|neither|nil|any single|did not|does not|do not)\b.{0,140}" + TEN + r"|" + TEN + r".{0,140}\b(no|not|none|nil)\b", re.I)
AT_LEAST_10 = re.compile(r"(more than|over|exceed(?:s|ing|ed)?|above|at least|in excess of)\s+" + TEN + r"|" + TEN + r"\s*(or more|and above|or above)", re.I)
CUSTOMER = re.compile(r"customer|client|buyer|party", re.I)
ONE_CUSTOMER = re.compile(r"\b(one|single|a|an|largest|major|key|its)\s+(?:external\s+)?(customer|client)\b|\bcustomer [A-Z]\b", re.I)
PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
AMOUNT = re.compile(r"(?:rs\.?|₹|`|inr)\s*([\d,]+(?:\.\d+)?)\s*(crores?|lakhs?|lacs?|millions?|mn|billions?)\b", re.I)


def _nums(line):
    out = []
    for m in NUM.finditer(line):
        t = m.group(0)
        if re.fullmatch(r"\(?(19|20)\d\d\)?", t):                 # a year, not an amount
            continue
        neg = t.startswith("(") and t.endswith(")")
        try:
            v = float(t.strip("()").replace(",", ""))
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def geography(pages):
    """pages: {no: raw page text}. -> a model-shaped 'geography' answer or None."""
    for no, text in pages.items():
        lines = (text or "").splitlines()
        for i, ln in enumerate(lines):
            if not HEAD.search(ln):
                continue
            block = lines[i:i + 45]
            unit = next((m.group(0).strip() for b in block[:12] for m in [UNIT.search(b)] if m), None)
            years = [int(y) for b in block[:12] for y in YEAR.findall(b)]
            col = 1 if len(years) >= 2 and years[0] < years[1] else 0
            rev_seen, rows, total, used = REVENUE.search(ln) is not None, [], None, [ln]
            for b in block[1:]:
                used.append(b)
                if STOP.search(b) and rows:
                    break
                if STOP.search(b) and not rev_seen:
                    break
                if REVENUE.search(b):
                    rev_seen = True
                if not rev_seen:
                    continue
                m = REGION.match(b)
                if m:
                    n = _nums(b[m.end():])
                    if len(n) > col and n[col] >= 0:
                        rows.append({"region": m.group(1).strip(), "amount": n[col]})
                    continue
                if TOTAL.match(b) and rows:
                    n = _nums(b)
                    if len(n) > col:
                        total = n[col]
                    break
            if len(rows) >= 2 and total and 0.97 <= sum(r["amount"] for r in rows) / total <= 1.03:
                quote = "\n".join(used)
                head = next((b for b in block[:12] if YEAR.search(b)), None)
                return {"unit": unit, "column_heading": head, "scope": None, "page": no, "quote": quote, "rows": rows, "total": total}
    return None


def _sentences(text):
    t = re.sub(r"\s+", " ", text or "")
    return [s.strip() for s in re.split(r"(?<=[.;:])\s+(?=[A-Z(\d]|[a-z]\)\s)", t) if 20 <= len(s.strip()) <= 450]     # also before "43 RELATED..." and "c) Information..."


TABLE_TAIL = re.compile(r".*(?:\d[\d,]*(?:\.\d+)?\)?|\s-)\s+(?=[A-Z(])")                # leftover table cells before the sentence proper
SEVERAL = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:major\s+|large\s+|key\s+)?customers?\b", re.I)


def _trim(s):
    """The sentence without the table cells that text extraction glued in front of it (still a verbatim piece of the page)."""
    m = CUSTOMER.search(s)
    if not m or m.start() < 60:
        return s
    t = TABLE_TAIL.match(s[:m.start()])
    return s[t.end():] if t else s


def customers(pages):
    """-> (no_major answer or None, [major customer answers])."""
    none, major = None, []
    for no, text in pages.items():
        for s in _sentences(text):
            if not (CUSTOMER.search(s) and REVENUE.search(s)):
                continue
            s = _trim(s)
            if len(s) < 20 or not (CUSTOMER.search(s) and REVENUE.search(s)):
                continue
            if NO_MAJOR.search(s):
                if none is None:
                    none = {"page": no, "quote": s}
                continue
            if not ONE_CUSTOMER.search(s) or SEVERAL.search(s):            # a statement about several customers is not one customer's share
                continue
            pcts = [float(p) for p in PCT.findall(s)]
            a = AMOUNT.search(s)
            if AT_LEAST_10.search(s):                                     # "one customer ... more than 10%": the threshold, with its amount when written
                major.append({"name": None, "share_pct": None, "amount": float(a.group(1).replace(",", "")) if a else None, "unit": a.group(2) if a else None, "page": no, "quote": s})
            elif pcts and 10 <= pcts[0] <= 100:
                major.append({"name": None, "share_pct": pcts[0], "amount": None, "unit": None, "page": no, "quote": s})
            if len(major) >= 5:
                break
    return none, major


def answer(pages):
    """The code-only reading in the model's answer shape: {"no_major_customer", "major_customers", "geography"}."""
    none, major = customers(pages)
    return {"no_major_customer": none, "major_customers": major, "geography": geography(pages)}
