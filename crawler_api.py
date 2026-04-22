import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from models import BilibiliCourse

try:
    from scrapling.fetchers import Fetcher
except ImportError:
    Fetcher = None


class BilibiliScraplingCrawler:
    """Bilibili course crawler with API-first fetching and optional HTML fallback."""

    SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    SEARCH_HTML = "https://search.bilibili.com/all"
    DEFAULT_HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "referer": "https://www.bilibili.com/",
    }

    def __init__(self, impersonate: str = "chrome"):
        self._impersonate = impersonate

    @staticmethod
    def _parse_number(text: Any) -> int:
        if text is None:
            return 0
        if isinstance(text, (int, float)):
            return int(text)

        value = str(text).strip()
        if "万" in value:
            return int(float(value.replace("万", "")) * 10000)
        if "亿" in value:
            return int(float(value.replace("亿", "")) * 100000000)

        cleaned = re.sub(r"[^\d.]", "", value)
        return int(float(cleaned)) if cleaned else 0

    @staticmethod
    def _format_date(timestamp: int) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds <= 0:
            return "00:00"
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

    def _search_via_api(self, skill: str, max_results: int = 20) -> Optional[List[BilibiliCourse]]:
        params = {
            "__refresh__": "true",
            "page": "1",
            "page_size": str(min(50, max_results)),
            "single_column": "0",
            "keyword": skill,
            "search_type": "video",
            "order": "totalrank",
            "duration": "0",
            "tids_1": "0",
        }
        query = "&".join(f"{key}={quote(str(value))}" for key, value in params.items())
        url = f"{self.SEARCH_API}?{query}"

        try:
            response = httpx.get(url, headers=self.DEFAULT_HEADERS, timeout=20.0)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return None

        code = data.get("code", -1)
        if code in {-412, -509}:
            return None
        if code != 0:
            return None

        courses: List[BilibiliCourse] = []
        result_list = data.get("data", {}).get("result", [])
        for item in result_list[:max_results]:
            course = self._parse_api_item(item, skill)
            if course is not None:
                courses.append(course)
        return courses

    def _parse_api_item(self, item: Dict[str, Any], skill: str) -> Optional[BilibiliCourse]:
        try:
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))
            arcurl = item.get("arcurl", "")
            url = arcurl if arcurl.startswith("http") else f"https:{arcurl}"
            author = item.get("author", "未知")
            publish_date = self._format_date(item.get("pubdate", 0))
            view_count = self._parse_number(item.get("play", 0))
            like_count = self._parse_number(item.get("like", 0))
            favorite_count = self._parse_number(item.get("favorites", 0))
            coin_count = self._parse_number(item.get("coin", 0))
            danmaku_count = self._parse_number(item.get("video_review", 0))
            duration_value = item.get("duration", 0)
            duration = (
                self._format_duration(duration_value)
                if isinstance(duration_value, int) and duration_value > 0
                else str(duration_value or "")
            )
            description = re.sub(r"<[^>]+>", "", item.get("description", ""))
            pic = item.get("pic", "")
            thumbnail = pic if pic.startswith("http") else f"https:{pic}"

            return BilibiliCourse(
                title=title,
                url=url,
                view_count=view_count,
                favorite_count=favorite_count,
                like_count=like_count,
                coin_count=coin_count,
                danmaku_count=danmaku_count,
                publish_date=publish_date,
                uploader=author,
                skill=skill,
                duration=duration,
                description=description,
                thumbnail=thumbnail,
                aid=self._parse_number(item.get("aid", 0)),
                bvid=item.get("bvid", ""),
            )
        except Exception:
            return None

    def _search_via_html(self, skill: str, max_results: int = 20) -> List[BilibiliCourse]:
        if Fetcher is None:
            return []

        url = f"{self.SEARCH_HTML}?keyword={quote(skill)}&order=totalrank"
        try:
            page = Fetcher.get(url, impersonate=self._impersonate, timeout=20)
        except Exception:
            return []

        if page.status != 200:
            return []

        cards = page.css("div.bili-video-card")
        courses: List[BilibiliCourse] = []
        for idx, card in enumerate(cards):
            if idx >= max_results:
                break
            course = self._parse_html_card(card, skill)
            if course is not None:
                courses.append(course)
        return courses

    def _parse_html_card(self, card, skill: str) -> Optional[BilibiliCourse]:
        try:
            title = card.css("h3.bili-video-card__info--tit::attr(title)").get() or ""
            if not title:
                title = card.css("h3.bili-video-card__info--tit::text").get() or ""
            title = title.strip()
            if not title:
                return None

            href = card.css("a::attr(href)").get() or ""
            url = f"https:{href}" if href and not href.startswith("http") else href
            bvid_match = re.search(r"(BV[\w]+)", url)
            bvid = bvid_match.group(1) if bvid_match else ""

            author = (card.css("span.bili-video-card__info--author::text").get() or "未知").strip()
            date_raw = (card.css("span.bili-video-card__info--date::text").get() or "").strip()
            publish_date = date_raw.lstrip("路 ").strip() or datetime.now().strftime("%Y-%m-%d")

            stats = card.css("span.bili-video-card__stats--item")
            view_count = 0
            danmaku_count = 0
            if len(stats) >= 1:
                view_text = stats[0].css("span::text").getall()
                if view_text:
                    view_count = self._parse_number(view_text[-1])
            if len(stats) >= 2:
                dm_text = stats[1].css("span::text").getall()
                if dm_text:
                    danmaku_count = self._parse_number(dm_text[-1])

            duration = (card.css("span.bili-video-card__stats__duration::text").get() or "").strip()
            img_src = card.css("img::attr(src)").get() or ""
            thumbnail = f"https:{img_src}" if img_src and not img_src.startswith("http") else img_src

            return BilibiliCourse(
                title=title,
                url=url,
                view_count=view_count,
                favorite_count=0,
                like_count=0,
                coin_count=0,
                danmaku_count=danmaku_count,
                publish_date=publish_date,
                uploader=author,
                skill=skill,
                duration=duration,
                description="",
                thumbnail=thumbnail,
                bvid=bvid,
            )
        except Exception:
            return None

    def search_skill(self, skill: str, max_results: int = 20) -> List[BilibiliCourse]:
        courses = self._search_via_api(skill, max_results)
        if courses is not None:
            return courses
        return self._search_via_html(skill, max_results)


BilibiliAPICrawlerSync = BilibiliScraplingCrawler


class BilibiliAPICrawler:
    def __init__(self):
        self._sync = BilibiliScraplingCrawler()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def _generate_buvid3(self) -> Dict[str, str]:
        return {}

    async def search_skill(self, skill: str, max_results: int = 20) -> List[BilibiliCourse]:
        return await asyncio.to_thread(self._sync.search_skill, skill, max_results)
