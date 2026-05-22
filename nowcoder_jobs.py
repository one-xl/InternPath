"""
牛客实习广场抓取与解析。

现网页面的职位列表主要由前端调用接口动态加载，初始 HTML 往往只有壳页，
不再包含旧版的 `job-name` / `job-salary` 节点。这里改为：

1. 优先根据页面 URL 或壳页中的 `window.__INITIAL_STATE__` 反推出查询条件；
2. 直接请求 `nowpick.nowcoder.com` 的职位接口，转换为项目现有的职位行结构；
3. 保留旧版静态 HTML 的正则解析作为兜底。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx

try:
    from scrapling.fetchers import Fetcher
except ImportError:
    Fetcher = None

NOWCODER_INTERN_CENTER = "https://www.nowcoder.com/jobs/intern/center"
NOWCODER_API_BASE = "https://nowpick.nowcoder.com"
NOWCODER_ROWS_MARKER = "__nowcoder_rows__"
NOWCODER_PAGE_SIZE = 50
NOWCODER_MAX_PAGES = 4
NOWCODER_ROW_TARGET = 80

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "referer": NOWCODER_INTERN_CENTER,
    "origin": "https://www.nowcoder.com",
}


def build_intern_center_url(
    *,
    city: str,
    career_job_id: Optional[int] = None,
    keyword: str = "",
    recruit_type: int = 2,
) -> str:
    city_q = quote((city or "").strip())
    parts = [f"recruitType={int(recruit_type)}", f"city={city_q}"]
    if career_job_id:
        parts.append(f"careerJob={int(career_job_id)}")
    keyword_q = quote((keyword or "").strip())
    if keyword_q:
        parts.append(f"query={keyword_q}")
    return f"{NOWCODER_INTERN_CENTER}?{'&'.join(parts)}"


def _safe_int(value: Any) -> Optional[int]:
    if value in (None, "", [], ()):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_query_context_from_url(url: str) -> Optional[Dict[str, Any]]:
    parsed = urlparse(url)
    if "nowcoder.com" not in parsed.netloc or "/intern/center" not in parsed.path:
        return None

    query = parse_qs(parsed.query)
    recruit_type = _safe_int((query.get("recruitType") or [2])[0]) or 2
    career_job_id = _safe_int((query.get("careerJob") or query.get("careerJobId") or [""])[0])
    return {
        "source_url": url,
        "city": ((query.get("city") or [""])[0] or "").strip(),
        "query": ((query.get("search") or query.get("query") or [""])[0] or "").strip(),
        "career_job_id": career_job_id,
        "recruit_type": recruit_type,
    }


def _extract_query_context_from_initial_state(html: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"window\.__INITIAL_STATE__=(\{.*?\});\s*\(function", html, flags=re.S)
    if not match:
        return None

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    full_path = payload.get("fullPath") or payload.get("path")
    if not isinstance(full_path, str) or "/intern/center" not in full_path:
        return None

    url = full_path if full_path.startswith("http") else f"https://www.nowcoder.com{full_path}"
    return _extract_query_context_from_url(url)


def _request_nowcoder_api(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = httpx.post(
        f"{NOWCODER_API_BASE}{path}",
        headers=DEFAULT_HEADERS,
        data=body,
        timeout=20.0,
        follow_redirects=True,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"牛客接口返回格式异常: {type(payload).__name__}")
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"牛客接口返回失败: {payload.get('msg') or payload}")
    return payload


def _unwrap_nowcoder_job_item(item: Dict[str, Any]) -> Dict[str, Any]:
    nested = item.get("data")
    if isinstance(nested, dict):
        return nested
    return item


def _collect_texts(parts: Iterable[Any]) -> str:
    items: List[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in items:
            items.append(text)
    return " / ".join(items)


def _company_name_from_job(job: Dict[str, Any]) -> str:
    company = job.get("recommendInternCompany") or {}
    if isinstance(company, dict):
        name = (company.get("companyShortName") or company.get("companyName") or "").strip()
        if name:
            return name

    user = job.get("user") or {}
    identities = user.get("identity") or []
    for identity in identities:
        if not isinstance(identity, dict):
            continue
        name = (identity.get("companyName") or "").strip()
        if name:
            return name
    return ""


def _company_info_from_job(job: Dict[str, Any]) -> str:
    company = job.get("recommendInternCompany") or {}
    industries: List[str] = []
    if isinstance(company, dict):
        industries = [str(x).strip() for x in (company.get("industryTagNameList") or []) if str(x).strip()]

    return _collect_texts(
        [
            "/".join(industries) if industries else "",
            job.get("industryName"),
            company.get("personScales") if isinstance(company, dict) else "",
            company.get("scaleTagName") if isinstance(company, dict) else "",
            job.get("jobCity"),
            job.get("jobAddress"),
        ]
    )


def _company_logo_from_job(job: Dict[str, Any]) -> str:
    company = job.get("recommendInternCompany") or {}
    if isinstance(company, dict):
        logo = str(company.get("picUrl") or "").strip()
        if logo:
            return logo
    return ""


def _job_detail_url_from_job(job: Dict[str, Any]) -> str:
    external = str(job.get("redirectExternalUrl") or "").strip()
    if external:
        if external.startswith("http://") or external.startswith("https://"):
            return external
        if external.startswith("//"):
            return f"https:{external}"
        return f"https://www.nowcoder.com{external}" if external.startswith("/") else f"https://{external}"

    job_id = _safe_int(job.get("id"))
    if job_id is not None:
        return f"https://www.nowcoder.com/jobs/detail/{job_id}"
    return ""


def _salary_text_from_job(job: Dict[str, Any]) -> str:
    salary_show = str(job.get("salaryShow") or "").strip()
    if salary_show:
        return salary_show

    salary_min = _safe_int(job.get("salaryMin"))
    salary_max = _safe_int(job.get("salaryMax"))
    salary_month = _safe_int(job.get("salaryMonth")) or 0
    recruit_type = _safe_int(job.get("recruitType")) or 2

    if (salary_min or 0) == 0 and (salary_max or 0) >= 9999999:
        return "薪资面议"
    if salary_min is None and salary_max is None:
        return "薪资面议"

    if salary_min is None:
        salary_min = salary_max
    if salary_max is None:
        salary_max = salary_min

    if recruit_type == 2:
        if salary_min == salary_max:
            return f"{salary_min}元/天"
        return f"{salary_min}-{salary_max}元/天"

    if salary_month > 0:
        return f"{salary_min}-{salary_max}K * {salary_month}薪"
    if salary_min == salary_max:
        return f"{salary_min}K/月"
    return f"{salary_min}-{salary_max}K/月"


def fetch_html(url: str) -> str:
    last: Optional[Exception] = None
    context = _extract_query_context_from_url(url)
    if context is not None:
        try:
            rows = _fetch_nowcoder_api_rows(context)
            return json.dumps(
                {
                    NOWCODER_ROWS_MARKER: True,
                    "rows": rows,
                    "context": context,
                },
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            last = exc

    if Fetcher is not None:
        try:
            page = Fetcher.get(url, impersonate="chrome", timeout=30.0)
            if getattr(page, "status", 0) == 200:
                raw = getattr(page, "html", None) or getattr(page, "text", None)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                if raw:
                    return str(raw)
        except Exception as exc:  # noqa: BLE001
            last = exc
    try:
        response = httpx.get(url, headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.text
    except Exception as exc:  # noqa: BLE001
        if last is not None:
            raise RuntimeError(f"抓取失败: {exc}; previous: {last}") from exc
        raise


def _parse_daily_mid_yuan(text: str) -> Optional[float]:
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"(\d+)\s*[-~至到]\s*(\d+)\s*元\s*/\s*天", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (a + b) / 2.0
    m = re.search(r"(\d+)\s*元\s*/\s*天", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*[kK千]\s*/\s*月", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (a + b) / 2.0 * 1000.0 / 22.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*[kK千]\s*/\s*月", t)
    if m:
        return float(m.group(1)) * 1000.0 / 22.0
    return None


JOB_NAME_RE = re.compile(
    r'class="[^"]*job-name[^"]*"[^>]*>(?:\s*<[^>]+>)*\s*([^<]+?)\s*<',
    flags=re.IGNORECASE,
)
JOB_SALARY_RE = re.compile(
    r'class="[^"]*job-salary[^"]*"[^>]*>\s*([^<]+?)\s*<',
    flags=re.IGNORECASE,
)
COMPANY_NAME_RE = re.compile(
    r'class="[^"]*company-name[^"]*"[^>]*>(?:\s*<[^>]+>)*\s*([^<]+?)\s*<',
    flags=re.IGNORECASE,
)
COMPANY_INFO_ITEM_RE = re.compile(
    r'class="[^"]*company-info-item[^"]*"[^>]*>(?:\s*<[^>]+>)*\s*([^<]+?)\s*<',
    flags=re.IGNORECASE,
)


def _first_match_text(pattern: re.Pattern[str], block: str) -> str:
    m = pattern.search(block)
    return (m.group(1).strip() if m else "") or ""


def _all_match_texts(pattern: re.Pattern[str], block: str) -> List[str]:
    return [m.group(1).strip() for m in pattern.finditer(block) if m.group(1).strip()]


def _parse_days_per_week(block: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*天\s*/\s*周", block)
    if m:
        return int(m.group(1))
    return None


def _parse_conversion(block: str) -> str:
    if "有转正" in block:
        return "有转正"
    if "无转正" in block or "不提供转正" in block:
        return "无转正"
    return ""


def _parse_min_months(block: str) -> Optional[int]:
    m = re.search(r"最少\s*(\d+)\s*个月", block)
    if m:
        return int(m.group(1))
    return None


def _headcount_mid_for_sort(company_info: str) -> float:
    """用于公司规模排序：越大表示人数规模越大；无法解析时为 -1。"""
    t = company_info or ""
    if re.search(r"10000人以上|万人以上", t):
        return 15000.0
    m = re.search(r"(\d+)\s*[-~至到]\s*(\d+)\s*人", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) / 2.0
    m = re.search(r"(\d+)\s*人以上", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*人以下", t)
    if m:
        return float(m.group(1)) * 0.5
    return -1.0


def _parse_legacy_zip_rows(html: str) -> List[Dict[str, Any]]:
    names = re.findall(
        r'class="[^"]*job-name[^"]*"[^>]*>(?:\s*<[^>]+>)*\s*([^<]+?)\s*<',
        html,
        flags=re.IGNORECASE,
    )
    if not names:
        names = re.findall(
            r'class="[^"]*job-name[^"]*"[^>]*>\s*([^<]+)\s*<',
            html,
            flags=re.IGNORECASE,
        )
    salaries = list(JOB_SALARY_RE.findall(html))
    if not salaries:
        salaries = re.findall(r'job-salary[^>]*>\s*([^<]+)\s*<', html, flags=re.IGNORECASE)
    if not names and not salaries:
        return []
    n = max(len(names), len(salaries))
    rows: List[Dict[str, Any]] = []
    for i in range(n):
        title = (names[i].strip() if i < len(names) else "") or f"职位{i+1}"
        sal_text = (salaries[i].strip() if i < len(salaries) else "")
        rows.append(_row_from_parts(title, sal_text, i))
    return rows


def _row_from_parts(
    title: str,
    sal_text: str,
    dom_index: int,
    *,
    company: str = "",
    company_info: str = "",
    days_per_week: Optional[int] = None,
    conversion: str = "",
    min_months: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = {
        "title": title,
        "salary_text": sal_text,
        "salary_mid_yuan_per_day": _parse_daily_mid_yuan(sal_text),
        "dom_index": dom_index,
        "company": company,
        "company_info": company_info,
        "days_per_week": days_per_week,
        "conversion": conversion,
        "min_months": min_months,
    }
    if extra:
        row.update(extra)
    return row


def _parse_by_job_name_cards(html: str) -> List[Dict[str, Any]]:
    matches = list(JOB_NAME_RE.finditer(html))
    if not matches:
        return []
    rows: List[Dict[str, Any]] = []
    for i, m in enumerate(matches):
        title = (m.group(1) or "").strip() or f"职位{i+1}"
        nxt = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        forward = html[m.end() : nxt]
        pre = html[max(0, m.start() - 2000) : m.start()]
        sal_text = _first_match_text(JOB_SALARY_RE, forward) or _first_match_text(JOB_SALARY_RE, pre)
        company = _first_match_text(COMPANY_NAME_RE, forward) or _first_match_text(COMPANY_NAME_RE, pre)
        infos = _all_match_texts(COMPANY_INFO_ITEM_RE, forward) or _all_match_texts(COMPANY_INFO_ITEM_RE, pre)
        company_info = " / ".join(infos) if infos else ""
        rows.append(
            _row_from_parts(
                title,
                sal_text,
                i,
                company=company,
                company_info=company_info,
                days_per_week=_parse_days_per_week(forward),
                conversion=_parse_conversion(forward),
                min_months=_parse_min_months(forward),
            )
        )
    return rows


def _job_matches_context(job: Dict[str, Any], context: Dict[str, Any]) -> bool:
    career_job_id = _safe_int(context.get("career_job_id"))
    if career_job_id is not None:
        raw_career = _safe_int(job.get("careerJobId"))
        if raw_career is not None and raw_career != career_job_id:
            return False

    city = str(context.get("city") or "").strip()
    if city:
        haystack = " ".join(
            str(part or "").strip()
            for part in [
                job.get("jobCity"),
                job.get("jobAddress"),
            ]
        )
        if city not in haystack:
            return False

    keyword = str(context.get("query") or "").strip().lower()
    if keyword:
        lowered = " ".join(
            (
                str(job.get("jobName") or ""),
                _company_name_from_job(job),
                _company_info_from_job(job),
            )
        ).lower()
        if keyword not in lowered:
            return False

    return True


def _row_from_api_job(job: Dict[str, Any], dom_index: int) -> Dict[str, Any]:
    conversion = ""
    job_offer = job.get("jobOffer")
    if job_offer in (1, "1", True):
        conversion = "有转正"
    elif job_offer in (0, "0"):
        conversion = "无转正"

    return _row_from_parts(
        (job.get("jobName") or "").strip() or f"职位{dom_index + 1}",
        _salary_text_from_job(job),
        dom_index,
        company=_company_name_from_job(job),
        company_info=_company_info_from_job(job),
        days_per_week=_safe_int(job.get("durationDays")),
        conversion=conversion,
        min_months=_safe_int(job.get("durationMonths")),
        extra={
            "job_city": (job.get("jobCity") or "").strip(),
            "career_job_id": _safe_int(job.get("careerJobId")),
            "job_id": _safe_int(job.get("id")),
            "source_url": _job_detail_url_from_job(job),
            "company_logo": _company_logo_from_job(job),
        },
    )


def _rows_from_api_items(items: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    ctx = context or {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        job = _unwrap_nowcoder_job_item(raw)
        if not isinstance(job, dict) or not job:
            continue
        if not _job_matches_context(job, ctx):
            continue
        rows.append(_row_from_api_job(job, len(rows)))
    return rows


def _fetch_square_search_items(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for page in range(1, NOWCODER_MAX_PAGES + 1):
        body: Dict[str, Any] = {
            "page": page,
            "pageSize": NOWCODER_PAGE_SIZE,
            "recruitType": _safe_int(context.get("recruit_type")) or 2,
            "requestFrom": 0,
            "pageSource": 5026,
        }
        if context.get("city"):
            body["city"] = str(context["city"])
        if context.get("career_job_id") is not None:
            body["careerJobId"] = int(context["career_job_id"])
        if context.get("query"):
            body["query"] = str(context["query"])

        payload = _request_nowcoder_api("/u/job/square-search", body)
        data = payload.get("data") or {}
        page_items = data.get("datas") or []
        if not isinstance(page_items, list):
            break
        items.extend(page_items)
        total_page = _safe_int(data.get("totalPage")) or page
        if page >= total_page:
            break
        if len(_rows_from_api_items(items, context)) >= NOWCODER_ROW_TARGET:
            break
    return items


def _fetch_expand_job_items(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for page in range(1, NOWCODER_MAX_PAGES + 1):
        body: Dict[str, Any] = {
            "page": page,
            "pageSize": NOWCODER_PAGE_SIZE,
            "recruitType": _safe_int(context.get("recruit_type")) or 2,
            "requestFrom": 1,
        }
        if context.get("career_job_id") is not None:
            body["careerJobId"] = int(context["career_job_id"])

        payload = _request_nowcoder_api("/u/job/expand-job", body)
        data = payload.get("data") or {}
        page_items = data.get("datas") or []
        if not isinstance(page_items, list):
            break
        items.extend(page_items)
        total_page = _safe_int(data.get("totalPage")) or page
        if page >= total_page:
            break
        if len(_rows_from_api_items(items, context)) >= NOWCODER_ROW_TARGET:
            break
    return items


def _fetch_nowcoder_api_rows(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _rows_from_api_items(_fetch_square_search_items(context), context)
    if rows:
        return rows
    return _rows_from_api_items(_fetch_expand_job_items(context), context)


def _parse_marshaled_rows(blob: str) -> Optional[List[Dict[str, Any]]]:
    text = (blob or "").strip()
    if not text or text[0] not in "[{":
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict) and payload.get(NOWCODER_ROWS_MARKER) and isinstance(payload.get("rows"), list):
        return list(payload["rows"])

    if isinstance(payload, dict):
        data = payload.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("datas"), list):
            return _rows_from_api_items(data["datas"], payload.get("context"))

        if isinstance(payload.get("items"), list):
            return _rows_from_api_items(payload["items"], payload.get("context"))

    return None


def parse_nowcoder_listings(html: str) -> List[Dict[str, Any]]:
    """
    从牛客页面内容中提取职位列表。

    优先顺序：
    1. 已包装的 API 结果；
    2. 原始 API JSON；
    3. 带 `window.__INITIAL_STATE__` 的壳页 HTML，再反查接口；
    4. 旧版静态 HTML 的 class 解析。
    """
    if not html:
        return []

    api_rows = _parse_marshaled_rows(html)
    if api_rows is not None:
        return api_rows

    context = _extract_query_context_from_initial_state(html)
    if context is not None:
        try:
            rows = _fetch_nowcoder_api_rows(context)
            if rows or "window.__INITIAL_STATE__" in html:
                return rows
        except Exception:  # noqa: BLE001
            pass

    by_cards = _parse_by_job_name_cards(html)
    if by_cards:
        return by_cards
    return _parse_legacy_zip_rows(html)


def filter_by_keyword(rows: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    k = (keyword or "").strip()
    if not k:
        return list(rows)
    kl = k.lower()

    def hit(r: Dict[str, Any]) -> bool:
        if kl in (r.get("title") or "").lower():
            return True
        if kl in (r.get("company") or "").lower():
            return True
        if kl in (r.get("company_info") or "").lower():
            return True
        return False

    return [r for r in rows if hit(r)]


def sort_rows(
    rows: List[Dict[str, Any]],
    *,
    list_order: str,
    expect_daily_yuan: Optional[float],
    keyword: str,
    factors: List[str],
) -> List[Dict[str, Any]]:
    """
    list_order: 列表逆序 | 列表正序 | 薪资排序 | 综合（三要素）| 公司名/岗位/规模/每周几天/转正 等
    factors: 子集，用于「综合」加权，可选 岗位匹配、薪资接近、牛客顺序
    """
    data = list(rows)
    if list_order == "列表逆序（默认）":
        data = list(reversed(data))
    elif list_order == "列表正序":
        pass
    elif list_order == "薪资从高到低":
        data.sort(key=lambda r: -(r.get("salary_mid_yuan_per_day") or -1.0))
    elif list_order == "薪资从低到高":
        data.sort(key=lambda r: (r.get("salary_mid_yuan_per_day") if r.get("salary_mid_yuan_per_day") is not None else 1e9))
    elif list_order == "公司名 A→Z":
        data.sort(key=lambda r: (r.get("company") or "").lower())
    elif list_order == "公司名 Z→A":
        data.sort(key=lambda r: (r.get("company") or "").lower(), reverse=True)
    elif list_order == "岗位 A→Z":
        data.sort(key=lambda r: (r.get("title") or "").lower())
    elif list_order == "岗位 Z→A":
        data.sort(key=lambda r: (r.get("title") or "").lower(), reverse=True)
    elif list_order == "公司规模（大到小）":

        def _sz_desc(r: Dict[str, Any]) -> tuple:
            m = _headcount_mid_for_sort(str(r.get("company_info") or ""))
            return (1, 0.0) if m < 0 else (0, -m)

        data.sort(key=_sz_desc)
    elif list_order == "公司规模（小到大）":

        def _sz_asc(r: Dict[str, Any]) -> tuple:
            m = _headcount_mid_for_sort(str(r.get("company_info") or ""))
            return (1, 0.0) if m < 0 else (0, m)

        data.sort(key=_sz_asc)
    elif list_order == "每周几天（多→少）":
        data.sort(
            key=lambda r: (
                r.get("days_per_week") is None,
                -(int(r["days_per_week"]) if r.get("days_per_week") is not None else 0),
            )
        )
    elif list_order == "每周几天（少→多）":
        data.sort(
            key=lambda r: (
                r.get("days_per_week") is None,
                int(r["days_per_week"]) if r.get("days_per_week") is not None else 999,
            )
        )
    elif list_order == "转正机会（有转正在前）":
        data.sort(key=lambda r: (0 if r.get("conversion") == "有转正" else 1, r.get("dom_index", 0)))
    elif list_order == "转正机会（无转正在前）":
        data.sort(key=lambda r: (0 if r.get("conversion") == "无转正" else 1, r.get("dom_index", 0)))
    elif list_order == "综合（三要素）":
        k = (keyword or "").strip().lower()
        exp = expect_daily_yuan

        def kw_score(r: Dict[str, Any]) -> float:
            if not k:
                return 0.5
            t = (r.get("title") or "").lower()
            c = (r.get("company") or "").lower()
            info = (r.get("company_info") or "").lower()
            return 1.0 if (k in t or k in c or k in info) else 0.0

        def sal_score(r: Dict[str, Any]) -> float:
            v = r.get("salary_mid_yuan_per_day")
            if exp is None or v is None:
                return 0.5
            d = abs(float(v) - float(exp))
            return max(0.0, 1.0 - d / max(300.0, abs(exp)))

        max_dom = max((int(r.get("dom_index", 0)) for r in data), default=1)

        def ord_score(r: Dict[str, Any]) -> float:
            return float(r.get("dom_index", 0)) / float(max_dom) if max_dom else 1.0

        fac_map = {
            "岗位匹配": kw_score,
            "薪资接近期望": sal_score,
            "牛客顺序": ord_score,
        }
        use = [f for f in factors if f in fac_map]
        if not use:
            use = list(fac_map.keys())

        def total(r: Dict[str, Any]) -> float:
            s = 0.0
            for f in use:
                s += fac_map[f](r)
            return s / max(1, len(use))

        data.sort(key=total, reverse=True)
    return data
