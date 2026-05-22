import math
import re
from datetime import datetime
from typing import List, Optional, Tuple

import httpx

try:
    from scrapling.fetchers import Fetcher
except ImportError:
    Fetcher = None

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_salary_monthly_mid_k(text: str) -> Optional[float]:
    """
    从招聘页纯文本中粗提取「月薪中值」，单位：千元/月。
    命中多个模式时取第一个合理区间；无法解析则返回 None。
    """
    t = text.replace("Ｋ", "k")

    patterns: List[Tuple[str, str]] = [
        (r"月薪\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*[kK千]", "k_range"),
        (r"薪资\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*[kK千]", "k_range"),
        (r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*[kK千]\s*/\s*月", "k_range"),
        (r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*万\s*/\s*月", "wan_month_range"),
        (r"月薪\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*万", "wan_month_range"),
    ]

    for pat, kind in patterns:
        m = re.search(pat, t)
        if not m:
            continue
        a = float(m.group(1))
        b = float(m.group(2))
        if kind == "k_range":
            lo, hi = sorted((a, b))
            if hi > 500:
                continue
            return (lo + hi) / 2.0
        if kind == "wan_month_range":
            lo, hi = sorted((a, b))
            if hi > 30:
                continue
            return (lo + hi) / 2.0 * 10.0

    solo = re.search(r"月薪\s*[:：]?\s*(\d+(?:\.\d+)?)\s*万", t)
    if solo:
        v = float(solo.group(1))
        if v <= 30:
            return v * 10.0

    solo_k = re.search(r"月薪\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[kK千]", t)
    if solo_k:
        v = float(solo_k.group(1))
        if v <= 500:
            return v

    return None


def fetch_job_page_text(url: str) -> str:
    last: Optional[Exception] = None
    if Fetcher is not None:
        try:
            page = Fetcher.get(url, impersonate="chrome", timeout=25.0)
            if getattr(page, "status", 0) == 200:
                raw = getattr(page, "html", None) or getattr(page, "text", None)
                if raw is None and hasattr(page, "content"):
                    raw = page.content
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                if raw:
                    return str(raw)
        except Exception as exc:  # noqa: BLE001
            last = exc

    try:
        resp = httpx.get(url, headers=DEFAULT_HEADERS, timeout=25.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        if last is not None:
            raise RuntimeError(f"抓取失败: {exc}; scrapling 错误: {last}") from exc
        raise


def scrape_salary_from_url(url: str) -> Tuple[Optional[float], str]:
    html = fetch_job_page_text(url)
    plain = _strip_html(html)
    val = extract_salary_monthly_mid_k(plain)
    return val, plain[:4000]


def linear_next_forecast_k(
    history: List[Tuple[datetime, float]],
) -> Optional[float]:
    """以时间为 x（天）、薪资为 y 做一元线性外推，预测「最后一次观测之后约 30 天」。"""
    if len(history) < 2:
        return None
    base = history[0][0].timestamp()
    xs = [(h[0].timestamp() - base) / 86400.0 for h in history]
    ys = [h[1] for h in history]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return ys[-1]
    slope = num / den
    intercept = my - slope * mx
    last_x = xs[-1]
    next_x = last_x + 30.0
    y_hat = slope * next_x + intercept
    return max(0.0, float(y_hat))
