#!/usr/bin/env python3
"""Build live trade-intel feeds for the dashboard.

This script pulls only official/public government sources and writes:
  data/live_intel.json
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "live_intel.json"

KEYWORDS = [
    "tariff",
    "tariffs",
    "duty",
    "duties",
    "countermeasure",
    "countermeasures",
    "retaliat",
    "section 232",
    "section 301",
    "ieepa",
    "customs",
    "trade",
    "import",
    "export",
]

FEEDS = {
    "federal_register": {
        "base": "https://www.federalregister.gov/api/v1/documents.json",
        "terms": ["tariff", "duty", "section 232", "reciprocal tariff", "de minimis"],
        "date_gte": "2025-01-01",
        "source": "Federal Register API",
    },
    "cbp_csms": {
        "url": "https://content.govdelivery.com/accounts/USDHSCBP/widgets/USDHSCBP_WIDGET_2.rss",
        "source": "U.S. Customs and Border Protection CSMS (GovDelivery RSS)",
    },
    "eu_commission": {
        "url": "https://ec.europa.eu/commission/presscorner/api/rss?language=en",
        "source": "European Commission Press Corner RSS",
    },
    "uk_dbt": {
        "url": "https://www.gov.uk/search/news-and-communications.atom?keywords=tariff%20duty%20trade&organisations%5B%5D=department-for-business-and-trade",
        "source": "UK GOV.UK DBT news Atom feed",
    },
    "china_mofcom": {
        "url": "https://english.mofcom.gov.cn/",
        "source": "MOFCOM English website",
    },
    "canada_finance": {
        "url": "https://www.canada.ca/en/department-finance/programs/international-trade-finance-policy/canadas-response-us-tariffs.html",
        "source": "Government of Canada Department of Finance",
    },
}


def now_utc_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def fetch_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TrumptarifftrackerBot/1.0 (+https://github.com/)"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def contains_keyword(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_ws(unescape(text))


def fetch_federal_register() -> dict:
    out = {
        "source": FEEDS["federal_register"]["source"],
        "source_url": FEEDS["federal_register"]["base"],
        "items": [],
        "errors": [],
    }
    merged: dict[str, dict] = {}

    for term in FEEDS["federal_register"]["terms"]:
        query = {
            "per_page": "100",
            "order": "newest",
            "conditions[publication_date][gte]": FEEDS["federal_register"]["date_gte"],
            "conditions[term]": term,
        }
        url = FEEDS["federal_register"]["base"] + "?" + urllib.parse.urlencode(query)
        try:
            raw = fetch_text(url)
            payload = json.loads(raw)
            for doc in payload.get("results", []):
                doc_num = (doc.get("document_number") or "")
                key = doc_num or (doc.get("html_url") or "")
                if not key:
                    continue

                title = normalize_ws(doc.get("title") or "")
                abstract = normalize_ws(doc.get("abstract") or "")
                if not contains_keyword(f"{title} {abstract}"):
                    continue

                existing = merged.get(key)
                item = {
                    "document_number": doc_num,
                    "publication_date": doc.get("publication_date"),
                    "title": title,
                    "type": doc.get("type"),
                    "html_url": doc.get("html_url"),
                    "raw_text_url": doc.get("raw_text_url"),
                    "term_hit": term,
                }
                if existing is None:
                    merged[key] = item
                else:
                    existing.setdefault("term_hit", term)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"term={term}: {exc}")

    items = sorted(
        merged.values(),
        key=lambda x: (x.get("publication_date") or "", x.get("document_number") or ""),
        reverse=True,
    )
    out["items"] = items[:80]
    return out


def parse_rss_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    rows = []
    for item in channel.findall("item"):
        title = normalize_ws(item.findtext("title") or "")
        link = normalize_ws(item.findtext("link") or "")
        pub_date = normalize_ws(item.findtext("pubDate") or "")
        guid = normalize_ws(item.findtext("guid") or "")
        description = item.findtext("description") or ""
        category = ", ".join(normalize_ws(c.text or "") for c in item.findall("category") if (c.text or "").strip())
        rows.append(
            {
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "guid": guid,
                "category": category,
                "description": strip_tags(description)[:700],
            }
        )
    return rows


def parse_atom_entries(xml_text: str) -> list[dict]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    rows = []
    for entry in root.findall("a:entry", ns):
        title = normalize_ws(entry.findtext("a:title", default="", namespaces=ns))
        updated = normalize_ws(entry.findtext("a:updated", default="", namespaces=ns))
        summary = normalize_ws(entry.findtext("a:summary", default="", namespaces=ns))
        link = ""
        link_node = entry.find("a:link", ns)
        if link_node is not None:
            link = normalize_ws(link_node.attrib.get("href", ""))
        rows.append({"title": title, "link": link, "updated": updated, "summary": summary})
    return rows


def fetch_cbp_csms() -> dict:
    out = {
        "source": FEEDS["cbp_csms"]["source"],
        "source_url": FEEDS["cbp_csms"]["url"],
        "items": [],
        "errors": [],
    }
    try:
        xml_text = fetch_text(FEEDS["cbp_csms"]["url"])
        items = parse_rss_items(xml_text)
        filtered = [
            i for i in items if contains_keyword(f"{i.get('title', '')} {i.get('description', '')}")
        ]
        out["items"] = filtered[:40]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
    return out


def fetch_eu_feed() -> dict:
    out = {
        "source": FEEDS["eu_commission"]["source"],
        "source_url": FEEDS["eu_commission"]["url"],
        "items": [],
        "errors": [],
    }
    try:
        xml_text = fetch_text(FEEDS["eu_commission"]["url"])
        items = parse_rss_items(xml_text)
        filtered = [
            i for i in items if contains_keyword(f"{i.get('title', '')} {i.get('description', '')} {i.get('category', '')}")
        ]
        # Keep feed non-empty for monitoring continuity even when tariff terms
        # are not present in the newest 10 press-corner headlines.
        out["items"] = (filtered if filtered else items)[:25]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
    return out


def fetch_uk_feed() -> dict:
    out = {
        "source": FEEDS["uk_dbt"]["source"],
        "source_url": FEEDS["uk_dbt"]["url"],
        "items": [],
        "errors": [],
    }
    try:
        xml_text = fetch_text(FEEDS["uk_dbt"]["url"])
        items = parse_atom_entries(xml_text)
        filtered = [
            i for i in items if contains_keyword(f"{i.get('title', '')} {i.get('summary', '')}")
        ]
        out["items"] = filtered[:25]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
    return out


def fetch_china_mofcom() -> dict:
    out = {
        "source": FEEDS["china_mofcom"]["source"],
        "source_url": FEEDS["china_mofcom"]["url"],
        "items": [],
        "errors": [],
    }
    try:
        html = fetch_text(FEEDS["china_mofcom"]["url"])
        rows = []
        seen = set()
        for href, title in re.findall(r'<a href="([^"]*?/News/SpokesmansRemarks/[^"]+)"[^>]*title="([^"]+)"', html, flags=re.IGNORECASE):
            full = href if href.startswith("http") else f"https://english.mofcom.gov.cn{href}"
            if full in seen:
                continue
            seen.add(full)
            clean_title = normalize_ws(unescape(title))
            year_match = re.search(r"/art/(\d{4})/", full)
            year = year_match.group(1) if year_match else ""
            rows.append(
                {
                    "title": clean_title,
                    "link": full,
                    "pub_date": year,
                    "description": "MOFCOM spokesperson remarks entry",
                }
            )
        filtered = [r for r in rows if contains_keyword(r.get("title", "")) or "spokesperson" in r.get("title", "").lower()]
        # Keep continuity if keyword filtering yields no items in the latest scrape.
        out["items"] = (filtered if filtered else rows)[:25]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
        out["items"] = [
            {
                "title": "MOFCOM English feed temporarily unavailable; check source directly.",
                "link": FEEDS["china_mofcom"]["url"],
                "pub_date": "",
                "description": "Automated pull failed in this run. Open source URL for latest postings.",
            }
        ]
    return out


def fetch_canada_page() -> dict:
    out = {
        "source": FEEDS["canada_finance"]["source"],
        "source_url": FEEDS["canada_finance"]["url"],
        "items": [],
        "errors": [],
        "dcterms_modified": None,
    }
    try:
        html = fetch_text(FEEDS["canada_finance"]["url"])
        mod = None
        m = re.search(r'<meta name="dcterms\.modified"[^>]*content="([^"]+)"', html, flags=re.IGNORECASE)
        if m:
            mod = m.group(1)
        out["dcterms_modified"] = mod

        text = strip_tags(html)
        snippets = []
        for marker in [
            "Countermeasures in response to U.S. tariffs",
            "counter tariffs on steel, aluminum and automobiles remain",
            "removed counter tariffs",
            "25 per cent tariffs",
        ]:
            idx = text.lower().find(marker.lower())
            if idx >= 0:
                snippets.append(text[max(0, idx - 120): idx + 260])

        summary = normalize_ws(" | ".join(snippets))[:900] if snippets else "Official policy page for Canada's tariff response."
        out["items"] = [
            {
                "title": "Canada's response to U.S. tariffs (policy page)",
                "link": FEEDS["canada_finance"]["url"],
                "pub_date": mod or "",
                "description": summary,
            }
        ]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc))
    return out


def build_payload() -> dict:
    return {
        "generated_at": now_utc_iso(),
        "about": {
            "description": "Automated live intelligence pull from official government/legal sources.",
            "keyword_filter": KEYWORDS,
        },
        "feeds": {
            "federal_register": fetch_federal_register(),
            "cbp_csms": fetch_cbp_csms(),
            "retaliation": {
                "eu_commission": fetch_eu_feed(),
                "uk_dbt": fetch_uk_feed(),
                "china_mofcom": fetch_china_mofcom(),
                "canada_finance": fetch_canada_page(),
            },
        },
    }


def main() -> int:
    payload = build_payload()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    fr_count = len(payload["feeds"]["federal_register"]["items"])
    csms_count = len(payload["feeds"]["cbp_csms"]["items"])
    ret_counts = {
        key: len(val.get("items", []))
        for key, val in payload["feeds"]["retaliation"].items()
    }
    print(f"wrote: {OUT_PATH}")
    print(f"federal_register_items={fr_count} cbp_csms_items={csms_count} retaliation_items={ret_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
