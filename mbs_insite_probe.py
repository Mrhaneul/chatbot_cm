"""
mbs_insite_probe.py  (v3 — endpoints confirmed from DevTools capture)
---------------------------------------------------------------------
Confirmed flow for CBU's MBS InSite storefront (bookstore.calbaptist.edu):

  1. warm up   GET  /textbooks                 -> session cookie + antiforgery token
  2. terms     POST /SelectTermDept/Terms      -> JSON [{term}]        (needs token)
  3. depts     POST /SelectTermDept/Department  -> JSON [{department}]  (needs token)
  4. courses   POST /SelectTermDept/Courses     -> JSON [{course}]      (needs token)
  5. sections  POST /SelectTermDept/CourseList  -> JSON [{csId,...}]    (needs token)
  6. seed      POST /CourseMaterials/AddCourse  -> {added:true}  body {csId,nB,nba}
  7. render    GET  /CourseMaterials?ids={csId} -> HTML book list
  8. parse     parse_materials(html)            -> structured records

parse_materials() is already validated against the live ANT 225 markup.
The dropdown-walk field names (steps 3-5) still need to be filled from the
Response/Payload tabs of those calls -- see TODO_FROM_CAPTURE markers.

    pip install curl_cffi beautifulsoup4
    python mbs_insite_probe.py
    python mbs_insite_probe.py --playwright  # optional fallback; requires playwright + chromium
"""

import argparse
import re
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi
from curl_cffi.requests import exceptions as cffi_exceptions
import yaml

BASE = "https://bookstore.calbaptist.edu"
WARMUP_URL = f"{BASE}/textbooks"
MATERIALS_URL = f"{BASE}/CourseMaterials"
SELECT_URL = f"{BASE}/SelectTermDept"
ROOT = Path(__file__).resolve().parent
BOOKSTORE_CONFIG_PATH = ROOT / "config" / "bookstore_config.yaml"

NAV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

XHR_HEADERS = {
    "User-Agent": NAV_HEADERS["User-Agent"],
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": BASE,
    "Referer": WARMUP_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
REQUEST_DELAY_SECONDS = 1.25
SECTION_DELAY_SECONDS = 1.5


# ---------------------------------------------------------------- session ---
def _sleep_between_requests():
    time.sleep(REQUEST_DELAY_SECONDS)


def _request_with_retry(client, method, url, *, headers=None, retry_on=(403,), **kwargs):
    last_exc = None
    for attempt in range(2):
        if attempt:
            print(f"retrying {method.upper()} {url} after {last_exc or 'blocked response'}")
            time.sleep(2.0)
        else:
            _sleep_between_requests()
        try:
            response = getattr(client, method.lower())(
                url,
                headers=headers,
                timeout=30,
                allow_redirects=True,
                **kwargs,
            )
            if response.status_code in retry_on and attempt == 0:
                last_exc = f"HTTP {response.status_code}"
                continue
            return response
        except (cffi_exceptions.Timeout, cffi_exceptions.RequestException) as exc:
            last_exc = exc
            if attempt == 0:
                continue
            raise


def _extract_token(html):
    tok_el = BeautifulSoup(html, "html.parser").select_one(
        'input[name="__RequestVerificationToken"]'
    )
    return tok_el["value"] if tok_el and tok_el.has_attr("value") else None


def _print_warmup_diagnostics(response):
    print("warmup.status_code:", response.status_code)
    for name in ("Server", "Cf-Ray", "Cf-Mitigated", "Content-Encoding"):
        print(f"warmup.header.{name}:", response.headers.get(name))
    print("warmup.set_cookie:", bool(response.headers.get("Set-Cookie")))
    print("warmup.body.first_600:")
    print((response.text or "")[:600])


def make_session():
    """Warm up to collect the session cookie, and scrape the antiforgery token."""
    client = cffi.Session(impersonate="chrome")
    page = _request_with_retry(client, "GET", WARMUP_URL, headers=NAV_HEADERS)
    _print_warmup_diagnostics(page)
    token = _extract_token(page.text)
    if not token:
        # token may only render on /SelectTermDept -- try there as a fallback
        select_headers = {
            **NAV_HEADERS,
            "Referer": WARMUP_URL,
            "Sec-Fetch-Site": "same-origin",
        }
        page = _request_with_retry(client, "GET", SELECT_URL, headers=select_headers)
        token = _extract_token(page.text)
    print("cookies:", dict(client.cookies), "| token:", (token[:18] + "...") if token else None)
    return client, token


# ------------------------------------------------------- dropdown walk ------
# These return JSON. Run each, print the raw body once, then map the fields.
def get_terms(client, token, *, verbose=True):
    r = _request_with_retry(client, "POST", f"{BASE}/SelectTermDept/Terms",
                    headers=XHR_HEADERS,
                    data={"__RequestVerificationToken": token})
    r.raise_for_status()
    if verbose:
        print("TERMS:", r.text[:400])
    return r.json()

def get_departments(client, token, term_id, *, verbose=True):
    r = _request_with_retry(client, "POST", f"{BASE}/SelectTermDept/Department",
                    headers=XHR_HEADERS,
                    data={"__RequestVerificationToken": token,
                          "termId": term_id})
    r.raise_for_status()
    if verbose:
        print("DEPARTMENTS:", r.text[:400])
    return r.json()

def get_courses(client, token, term_id, dept_id, *, verbose=True):
    r = _request_with_retry(client, "POST", f"{BASE}/SelectTermDept/Courses",
                    headers=XHR_HEADERS,
                    data={"__RequestVerificationToken": token,
                          "termId": term_id, "deptId": dept_id})
    r.raise_for_status()
    if verbose:
        print("COURSES:", r.text[:400])
    return r.json()

def get_course_sections(
    client,
    token,
    term_id,
    dept_id,
    course_id,
    *,
    term_label="",
    dept_label="",
    course_label="",
    verbose=True,
):
    model = {
        "term": term_label,
        "termId": term_id,
        "department": dept_label,
        "deptId": dept_id,
        "courseSection": course_label,
        "courseId": course_id,
    }
    data = [
        ("__RequestVerificationToken", token),
        ("model[term]", model["term"]),
        ("model[termId]", model["termId"]),
        ("model[department]", model["department"]),
        ("model[deptId]", model["deptId"]),
        ("model[courseSection]", model["courseSection"]),
        ("model[courseId]", model["courseId"]),
    ]
    r = _request_with_retry(client, "POST", f"{BASE}/SelectTermDept/CourseList",
                    headers=XHR_HEADERS,
                    data=urlencode(data))
    r.raise_for_status()
    if verbose:
        print("COURSELIST:", r.text[:400])
    return r.json()   # expect each section to carry a csId (+ nB / nba flags)


def _parse_dropdown_items(raw_html, prefix):
    soup = BeautifulSoup(raw_html or "", "html.parser")
    items = []
    for li in soup.select("li[data-id]"):
        raw_id = li.get("data-id", "").strip()
        item_id = raw_id
        marker = f"{prefix}-"
        if item_id.startswith(marker):
            item_id = item_id[len(marker):]
        items.append({
            "id": item_id,
            "raw_id": raw_id,
            "label": li.get_text(" ", strip=True),
        })
    return items


def _clean_term_label(label):
    return re.sub(r"\s*\(Order Now\)\s*$", "", label or "", flags=re.I).strip()


def map_dropdown_shapes():
    client, token = make_session()
    terms_raw = get_terms(client, token)
    print("\nRAW TERMS JSON:")
    print(json.dumps(terms_raw, indent=2))
    terms = _parse_dropdown_items(terms_raw, "ter")
    if not terms:
        return {}

    first_term = terms[0]
    depts_raw = get_departments(client, token, first_term["id"])
    print("\nRAW DEPARTMENTS JSON:")
    print(json.dumps(depts_raw, indent=2))
    departments = _parse_dropdown_items(depts_raw, "dpt")
    if not departments:
        return {"terms": terms}

    first_dept = departments[0]
    courses_raw = get_courses(client, token, first_term["id"], first_dept["id"])
    print("\nRAW COURSES JSON:")
    print(json.dumps(courses_raw, indent=2))
    courses = _parse_dropdown_items(courses_raw, "cou")
    if not courses:
        return {"terms": terms, "departments": departments}

    first_course = courses[0]
    sections_raw = get_course_sections(
        client,
        token,
        first_term["id"],
        first_dept["id"],
        first_course["id"],
        term_label=first_term["label"],
        dept_label=first_dept["label"],
        course_label=first_course["label"],
    )
    print("\nRAW COURSELIST JSON:")
    print(json.dumps(sections_raw, indent=2))
    return {
        "terms": terms,
        "departments": departments,
        "courses": courses,
        "course_list": sections_raw,
    }


# ------------------------------------------------------------- seed + get ---
def add_course(client, cs_id, n_b="false", n_ba="false", token=None, *, verbose=True):
    """Seed the session with one course-section."""
    headers = {
        **XHR_HEADERS,
        "Referer": MATERIALS_URL,
    }
    data = {"csId": cs_id, "nB": n_b, "nba": n_ba}
    if token:
        data["__RequestVerificationToken"] = token
    r = _request_with_retry(client, "POST", f"{MATERIALS_URL}/AddCourse",
                    headers=headers,
                    data=data)
    r.raise_for_status()
    if verbose:
        print("AddCourse.status_code:", r.status_code)
        print("AddCourse:", r.text[:600])
    return r


def delete_course(client, cs_id, token=None, *, verbose=True):
    headers = {
        **XHR_HEADERS,
        "Referer": MATERIALS_URL,
    }
    data = {"csId": cs_id}
    if token:
        data["__RequestVerificationToken"] = token
    r = _request_with_retry(client, "POST", f"{MATERIALS_URL}/DeleteCourse",
                    headers=headers,
                    data=data)
    r.raise_for_status()
    if verbose:
        print("DeleteCourse:", r.text[:200])
    return r

def fetch_materials_html(client, cs_id=None):
    headers = {
        **NAV_HEADERS,
        "Referer": WARMUP_URL,
        "Sec-Fetch-Site": "same-origin",
    }
    url = f"{MATERIALS_URL}?ids={cs_id}" if cs_id else MATERIALS_URL
    r = _request_with_retry(client, "GET", url, headers=headers)
    r.raise_for_status()
    return r.text


def run_validation(cs_id="5021563", n_b="false", n_ba="false"):
    client, token = make_session()
    add_course(client, cs_id, n_b=n_b, n_ba=n_ba, token=token)
    html = fetch_materials_html(client, cs_id=cs_id)
    result = parse_materials(html)
    print("\n=== PARSED ===")
    print(json.dumps(result, indent=2))
    return result, client, token


def _cart_clear(records):
    return not records or all(not record.get("books") for record in records)


def enumerate_term(client, token, term_id, *, dry_run=False, on_records=None, verbose=True):
    errors = []
    term_label = str(term_id)
    terms = _parse_dropdown_items(get_terms(client, token, verbose=verbose), "ter")
    for term in terms:
        if term["id"] == str(term_id):
            term_label = term["label"]
            break

    records = []
    processed_sections = 0
    checked_cart_clear = False
    departments = _parse_dropdown_items(get_departments(client, token, term_id, verbose=verbose), "dpt")
    for dept in departments:
        courses = _parse_dropdown_items(get_courses(client, token, term_id, dept["id"], verbose=verbose), "cou")
        for course in courses:
            cs_id = course["id"]
            try:
                get_course_sections(
                    client,
                    token,
                    term_id,
                    dept["id"],
                    cs_id,
                    term_label=term_label,
                    dept_label=dept["label"],
                    course_label=course["label"],
                    verbose=verbose,
                )
                add_course(client, cs_id, token=token, verbose=verbose)
                html = fetch_materials_html(client, cs_id=cs_id)
                parsed = parse_materials(html)
                records.extend(parsed)
                if on_records and parsed:
                    on_records(parsed)
                if dry_run:
                    print(f"\n=== DRY RUN PARSED {processed_sections + 1} ({cs_id}) ===")
                    print(json.dumps(parsed, indent=2))
            except Exception as exc:
                error = {
                    "csId": cs_id,
                    "department": dept["label"],
                    "course": course["label"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
                errors.append(error)
                print(f"[ENUMERATE ERROR] csId={cs_id} {error['error']}")
            finally:
                try:
                    delete_course(client, cs_id, token=token, verbose=verbose)
                except Exception as exc:
                    print(f"[DELETE ERROR] csId={cs_id} {type(exc).__name__}: {exc}")
                if not checked_cart_clear:
                    clear_html = fetch_materials_html(client)
                    clear_records = parse_materials(clear_html)
                    print(f"cart clear: {_cart_clear(clear_records)}")
                    checked_cart_clear = True
                time.sleep(SECTION_DELAY_SECONDS)
            processed_sections += 1
            if not verbose and processed_sections % 25 == 0:
                print(f"processed {processed_sections} sections; cached {len(records)} parsed courses")
            if dry_run and processed_sections >= 2:
                enumerate_term.last_errors = errors
                return records
    enumerate_term.last_errors = errors
    return records


def cache_term(term_label, *, dry_run=False, term_id=None):
    from app.bookstore_cache import upsert_courses

    client, token = make_session()
    terms = _parse_dropdown_items(get_terms(client, token), "ter")
    selected = None
    wanted = (term_label or "").strip().lower()
    if term_id:
        for term in terms:
            if str(term["id"]) == str(term_id):
                selected = term
                break
    else:
        for term in terms:
            label = _clean_term_label(term["label"])
            if label.lower() == wanted or term["label"].strip().lower() == wanted:
                selected = term
                break
    if selected is None:
        available = ", ".join(_clean_term_label(term["label"]) for term in terms)
        raise ValueError(f"Term not found: {term_label or term_id}. Available terms: {available}")

    flushed_ids = set()

    def _flush(parsed_records):
        upsert_courses(parsed_records)
        for record in parsed_records:
            if record.get("course_id"):
                flushed_ids.add(record["course_id"])

    records = enumerate_term(
        client,
        token,
        selected["id"],
        dry_run=dry_run,
        on_records=_flush,
        verbose=dry_run,
    )
    if dry_run:
        remaining = [record for record in records if record.get("course_id") not in flushed_ids]
        if remaining:
            upsert_courses(remaining)
    book_count = sum(len(record.get("books", [])) for record in records)
    print(f"Cached {_clean_term_label(selected['label'])}: {len(records)} courses, {book_count} materials")
    errors = getattr(enumerate_term, "last_errors", [])
    if errors:
        print("Errors:")
        print(json.dumps(errors, indent=2))
    return records


def load_bookstore_config(path=BOOKSTORE_CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cache_configured_terms(*, dry_run=False):
    config = load_bookstore_config()
    active_terms = config.get("active_terms") or []
    if not active_terms:
        raise ValueError(f"No active_terms configured in {BOOKSTORE_CONFIG_PATH}")

    all_records = []
    all_errors = []
    for configured in active_terms:
        label = configured.get("label", "")
        term_id = configured.get("term_id")
        print(f"\n=== Caching configured term: {label} ({term_id}) ===")
        try:
            records = cache_term(label, dry_run=dry_run, term_id=term_id)
        except ValueError as exc:
            error = {"term": label, "term_id": term_id, "error": str(exc)}
            all_errors.append(error)
            print(f"[TERM ERROR] {json.dumps(error)}")
            continue
        all_records.extend(records)
        all_errors.extend(getattr(enumerate_term, "last_errors", []))

    course_count = len(all_records)
    material_count = sum(len(record.get("books", [])) for record in all_records)
    print(f"\nCached configured terms total: {course_count} courses, {material_count} materials")
    if all_errors:
        print("Combined errors:")
        print(json.dumps(all_errors, indent=2))
    return all_records


def run_playwright_validation(cs_id="5021563"):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright fallback requires: python -m pip install playwright "
            "&& python -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            user_agent=NAV_HEADERS["User-Agent"],
        )
        page = context.new_page()
        page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        add_url = f"{MATERIALS_URL}/AddCourse"
        page.evaluate(
            """async ([url, csId]) => {
                const body = new URLSearchParams({csId, nB: "false", nba: "false"});
                const response = await fetch(url, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    body
                });
                if (!response.ok) throw new Error(`AddCourse ${response.status}`);
                return response.text();
            }""",
            [add_url, cs_id],
        )
        page.goto(f"{MATERIALS_URL}?ids={cs_id}", wait_until="domcontentloaded", timeout=60000)
        html = page.content()
        result = parse_materials(html)
        cookies = context.cookies()
        print("\n=== PLAYWRIGHT COOKIES ===")
        print(json.dumps(cookies, indent=2))
        print("\n=== PARSED ===")
        print(json.dumps(result, indent=2))
        browser.close()
        return result, cookies


# --------------------------------------------------------------- parser -----
# Validated against live ANT 225 markup. Pulls clean values from the GA4 hidden
# inputs and the labelled <p> fields.
def _clean(s):
    return re.sub(r"\s+", " ", s).strip() if s else s

def _hidden(scope, cls):
    el = scope.select_one(f"input.{cls}")
    return _clean(el["value"]) if (el and el.has_attr("value")) else None

def _label_value(scope, cls):
    el = scope.select_one(f".{cls}")
    if not el:
        return None
    el = BeautifulSoup(str(el), "html.parser").select_one(f".{cls}")
    strong = el.find("strong")
    if strong:
        strong.extract()
    return _clean(el.get_text(" ", strip=True))

def parse_materials(html):
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for card in soup.select("div.Materials_Course"):
        course = {
            "term": _hidden(card, "ga4-course-term"),
            "department": _hidden(card, "ga4-course-department"),
            "course_number": _hidden(card, "ga4-course-courseNumber"),
            "section": _hidden(card, "ga4-course-sectionNumber"),
            "instructor": _hidden(card, "ga4-course-instructor"),
            "course_internal_id": _hidden(card, "ga4-course-courseID"),
            "course_id": None,
            "books": [],
        }
        if course["department"] and course["course_number"]:
            course["course_code"] = f'{course["department"]} {course["course_number"]}'
        cid = card.select_one(".No_Material_Course_ID")
        if cid:
            course["course_id"] = cid.get_text(" ", strip=True).split(":", 1)[-1].split("|")[0].strip()

        for bk in card.select("div.courseBookDetail"):
            notes_el = bk.select_one(".Book_Notes")
            notes_raw = notes_el.get_text(" ", strip=True) if notes_el else ""
            ia = ("!!IA!!" in notes_raw) or ("Immediate Access" in bk.get_text())
            hide_pricing = "!!Hide-Pricing!!" in notes_raw
            notes = _clean(notes_raw.replace("!!IA!!", "").replace("!!Hide-Pricing!!", ""))
            pub_link = None
            if notes_el and notes_el.find("a") and notes_el.find("a").has_attr("href"):
                href = notes_el.find("a")["href"]
                pub_link = "h" + href[2:] if href.startswith("hhttp") else href  # site's 'hhttps' typo
            req_el = bk.select_one(".Course_With_Material_Required")
            title = bk.select_one(".Book_Title")
            isbn = _hidden(bk, "ga4-book-isbn") or _label_value(bk, "Book_ISBN")
            isbn_digits = re.sub(r"\D", "", isbn or "")
            is_zero_isbn = not isbn_digits or set(isbn_digits) == {"0"}
            isbn_source = "label"
            if is_zero_isbn:
                isbn_source = "unresolved"
                note_text_for_isbn = notes_raw or ""
                isbn_match = re.search(r"ISBN[:\s#]*([0-9][0-9\-]{8,16}[0-9])", note_text_for_isbn, re.I)
                if isbn_match:
                    candidate = re.sub(r"[\s-]", "", isbn_match.group(1)).upper()
                    if len(candidate) not in {10, 13} or not candidate[:-1].isdigit() or not re.match(r"^[0-9]{9}[0-9X]$|^[0-9]{13}$", candidate):
                        candidate = None
                else:
                    candidate = None
                if not candidate:
                    bare_13 = re.search(r"\b(97[89]\d{10})\b", note_text_for_isbn)
                    candidate = bare_13.group(1) if bare_13 else None
                if not candidate:
                    bare_10 = re.search(r"\b(\d{9}[\dXx])\b", note_text_for_isbn)
                    candidate = bare_10.group(1).upper() if bare_10 else None
                if candidate:
                    isbn = candidate
                    isbn_source = "note"

            prices, fmt, formats = [], None, []
            price_div = bk.select_one(".price-div")
            if price_div:
                hdr = price_div.select_one(".Access_Price_Title, .accessName, .print_header")
                if hdr:
                    fmt = _clean(hdr.get_text())
                for radio in bk.select("input.Course_Material_Radio"):
                    amount = radio.get("data-price")
                    variant = radio.get("data-title")
                    fmt_name = radio.get("data-name")
                    if not amount:
                        continue
                    amount = amount.replace("$", "").replace(",", "").strip()
                    fmt_name = _clean(fmt_name) if fmt_name else None
                    if fmt_name and fmt_name not in formats:
                        formats.append(fmt_name)
                    prices.append({
                        "amount": amount,
                        "condition": fmt_name,
                        "variant": _clean(variant) if variant else None,
                    })
                for radio_row in bk.select(".Course_Material_Radio_Print"):
                    if radio_row.select_one("input.Course_Material_Radio"):
                        continue
                    row_text = radio_row.get_text(" ", strip=True)
                    match = re.search(r"\$\s*([\d,]+\.\d{2})\s*([A-Za-z][A-Za-z ]*)?", row_text)
                    if not match:
                        continue
                    group_hdr = radio_row.find_previous("h3")
                    fmt_name = _clean(group_hdr.get_text()) if group_hdr else fmt
                    if fmt_name not in {"Print", "Digital"}:
                        continue
                    variant = _clean(match.group(2)) if match.group(2) else None
                    amount = match.group(1).replace(",", "")
                    if fmt_name and fmt_name not in formats:
                        formats.append(fmt_name)
                    if not any(p.get("amount") == amount and p.get("variant") == variant for p in prices):
                        prices.append({
                            "amount": amount,
                            "condition": fmt_name,
                            "variant": variant,
                        })
                if not prices:
                    for m in re.finditer(r"\$\s*([\d,]+\.\d{2})\s*([A-Za-z][A-Za-z ]*)?",
                                         price_div.get_text(" ", strip=True)):
                        prices.append({"amount": m.group(1),
                                       "condition": _clean(m.group(2)) if m.group(2) else None})

            course["books"].append({
                "isbn": isbn,
                "isbn_source": isbn_source,
                "title": _clean(title.get_text()) if title else _hidden(bk, "ga4-book-name"),
                "author": _label_value(bk, "Book_Author") or _hidden(bk, "ga4-book-author"),
                "edition": _label_value(bk, "Book_Edition"),
                "published": _label_value(bk, "Book_Published"),
                "publisher": _label_value(bk, "Book_Publisher"),
                "requirement": _clean(req_el.get_text()) if req_el else "Optional",
                "immediate_access": ia,
                "format": fmt,
                "formats": formats,
                "prices": prices,
                "hide_pricing": hide_pricing,
                "publisher_direct_link": pub_link,
                "notes": notes,
                "image": (bk.select_one("img")["src"]
                          if (bk.select_one("img") and bk.select_one("img").has_attr("src")) else None),
            })
        courses.append(course)
    return courses


# ---------------------------------------------------------------- runner ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe CBU MBS InSite course materials.")
    parser.add_argument("--cs-id", default="5021563")
    parser.add_argument("--n-b", default="false")
    parser.add_argument("--n-ba", default="false")
    parser.add_argument("--map-dropdowns", action="store_true")
    parser.add_argument("--cache-term")
    parser.add_argument("--cache-configured", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Use headless Chromium fallback instead of the lightweight curl_cffi path.",
    )
    args = parser.parse_args()

    if args.map_dropdowns:
        map_dropdown_shapes()
    elif args.cache_configured:
        cache_configured_terms(dry_run=args.dry_run)
    elif args.cache_term:
        cache_term(args.cache_term, dry_run=args.dry_run)
    elif args.playwright:
        run_playwright_validation(args.cs_id)
    else:
        # FAST VALIDATION: skip the dropdown walk, seed a known csId directly.
        # 5021563 = ANT 225 / Section A (the value visible in your captured page).
        # If this prints a parsed book list, the seed->render->parse chain works.
        run_validation(args.cs_id, n_b=args.n_b, n_ba=args.n_ba)

    # Once validated, walk the dropdowns to enumerate every course for a term:
    #   for term in get_terms(client, token):
    #       for dept in get_departments(client, token, term_id):
    #           for course in get_courses(client, token, term_id, dept_id):
    #               for sec in get_course_sections(client, token, term_id, dept_id, course_id):
    #                   add_course(client, sec["csId"]) ; ... parse ...
