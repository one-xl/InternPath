import asyncio
import random
import string
import time
from typing import List, Optional, Dict, Any
from datetime import datetime
from fake_useragent import UserAgent
import httpx
from config import Config
from models import BilibiliCourse


class BilibiliAPICrawler:
    def __init__(self):
        self.ua = UserAgent()
        self.client: Optional[httpx.AsyncClient] = None
        self.cookie = self._generate_buvid3()

    def _generate_buvid3(self) -> Dict[str, str]:
        return {
            "innersign": "0",
            "buvid3": "".join(random.choice(string.hexdigits) for _ in range(16)) + "infoc",
            "i-wanna-go-back": "-1",
            "b_ut": "7",
            "FEED_LIVE_VERSION": "V8",
            "header_theme_version": "undefined",
            "home_feed_column": "4",
            "b_nut": "1",
            "CURRENT_FNVAL": "4048",
            "buvid_fp": "".join(random.choice(string.hexdigits) for _ in range(32))
        }

    def _get_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': self.ua.random,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

    def _parse_number(self, num: Any) -> int:
        if num is None:
            return 0
        try:
            return int(num)
        except (ValueError, TypeError):
            return 0

    def _format_duration(self, duration: int) -> str:
        if duration <= 0:
            return "00:00"
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _format_date(self, timestamp: int) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return datetime.now().strftime('%Y-%m-%d')

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            cookies=self.cookie
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.aclose()

    async def _random_delay(self, min_delay: float = 0.5, max_delay: float = 2.0):
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)

    async def _fetch_api(self, url: str, params: Dict[str, Any], max_retries: int = 3) -> Optional[Dict[str, Any]]:
        for attempt in range(max_retries):
            try:
                await self._random_delay()

                headers = self._get_headers()

                response = await self.client.get(
                    url,
                    params=params,
                    headers=headers
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0:
                        return data
                    elif data.get('code') == -412:
                        wait_time = (attempt + 1) * 3
                        await asyncio.sleep(wait_time)
                    else:
                        await asyncio.sleep(1)
                elif response.status_code == 429:
                    wait_time = (attempt + 1) * 2
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(1)

            except httpx.HTTPError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"HTTP Error: {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"Error fetching API: {e}")

        return None

    async def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> List[BilibiliCourse]:
        courses: List[BilibiliCourse] = []

        search_url = "https://api.bilibili.com/x/web-interface/search/type"

        params = {
            "__refresh__": "true",
            "page": page,
            "page_size": page_size,
            "single_column": "0",
            "keyword": keyword,
            "search_type": "video",
            "order": "totalrank",
            "duration": "0",
            "tids_1": "0"
        }

        try:
            data = await self._fetch_api(search_url, params)

            if not data:
                return courses

            result_list = data.get('data', {}).get('result', [])

            for item in result_list:
                try:
                    course = self._parse_video_item(item, keyword)
                    if course:
                        courses.append(course)
                except Exception as e:
                    continue

        except Exception as e:
            print(f"搜索 {keyword} 时出错: {str(e)}")

        return courses

    def _parse_video_item(self, item: Dict[str, Any], skill: str) -> Optional[BilibiliCourse]:
        try:
            title = item.get('title', '')
            title = title.replace('<em class="keyword">', '').replace('</em>', '')

            arcurl = item.get('arcurl', '')
            url = arcurl if arcurl.startswith('http') else f"https:{arcurl}"

            author = item.get('author', '未知')

            pubdate = item.get('pubdate', 0)
            publish_date = self._format_date(pubdate)

            play = item.get('play', 0)
            view_count = self._parse_number(play)

            like_count = self._parse_number(item.get('like', 0))
            favorite_count = self._parse_number(item.get('favorites', 0))
            coin_count = self._parse_number(item.get('coin', 0))
            danmaku_count = self._parse_number(item.get('video_review', 0))

            duration = item.get('duration', 0)
            duration_str = self._format_duration(duration) if duration > 0 else ''

            description = item.get('description', '')
            description = description.replace('<em class="keyword">', '').replace('</em>', '')

            pic = item.get('pic', '')
            thumbnail = pic if pic.startswith('http') else f"https:{pic}"

            aid = item.get('aid', 0)
            bvid = item.get('bvid', '')

            course = BilibiliCourse(
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
                duration=duration_str,
                description=description,
                thumbnail=thumbnail,
                aid=aid,
                bvid=bvid
            )

            return course

        except Exception as e:
            print(f"解析视频项时出错: {e}")
            return None

    async def search_skill(self, skill: str, max_results: int = 20) -> List[BilibiliCourse]:
        all_courses: List[BilibiliCourse] = []
        page = 1
        page_size = min(50, max_results)

        while len(all_courses) < max_results:
            remaining = max_results - len(all_courses)
            current_page_size = min(page_size, remaining)

            courses = await self.search_videos(skill, page, current_page_size)

            if not courses:
                break

            all_courses.extend(courses)

            if len(courses) < current_page_size:
                break

            page += 1

            if page > 3:
                break

        return all_courses[:max_results]


class BilibiliAPICrawlerSync:
    def __init__(self):
        self.crawler = BilibiliAPICrawler()
        self.ua = UserAgent()
        self.cookie = self.crawler._generate_buvid3()

    def _get_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': self.ua.random,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

    def _random_delay(self, min_delay: float = 0.5, max_delay: float = 2.0):
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _fetch_api_sync(self, url: str, params: Dict[str, Any], max_retries: int = 3) -> Optional[Dict[str, Any]]:
        for attempt in range(max_retries):
            try:
                self._random_delay()

                headers = self._get_headers()

                with httpx.Client(timeout=30.0, follow_redirects=True, cookies=self.cookie) as client:
                    response = client.get(
                        url,
                        params=params,
                        headers=headers
                    )

                    if response.status_code == 200:
                        data = response.json()
                        if data.get('code') == 0:
                            return data
                        elif data.get('code') == -412:
                            wait_time = (attempt + 1) * 3
                            time.sleep(wait_time)
                        else:
                            time.sleep(1)
                    elif response.status_code == 429:
                        wait_time = (attempt + 1) * 2
                        time.sleep(wait_time)
                    else:
                        time.sleep(1)

            except httpx.HTTPError as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"HTTP Error: {e}")
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"Error fetching API: {e}")

        return None

    def search_skill(self, skill: str, max_results: int = 20) -> List[BilibiliCourse]:
        courses: List[BilibiliCourse] = []

        search_url = "https://api.bilibili.com/x/web-interface/search/type"

        params = {
            "__refresh__": "true",
            "page": 1,
            "page_size": min(50, max_results),
            "single_column": "0",
            "keyword": skill,
            "search_type": "video",
            "order": "totalrank"
        }

        try:
            data = self._fetch_api_sync(search_url, params)

            if not data:
                return courses

            result_list = data.get('data', {}).get('result', [])

            for item in result_list[:max_results]:
                try:
                    title = item.get('title', '')
                    title = title.replace('<em class="keyword">', '').replace('</em>', '')

                    arcurl = item.get('arcurl', '')
                    url = arcurl if arcurl.startswith('http') else f"https:{arcurl}"

                    author = item.get('author', '未知')

                    pubdate = item.get('pubdate', 0)
                    try:
                        publish_date = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%d')
                    except (ValueError, TypeError):
                        publish_date = datetime.now().strftime('%Y-%m-%d')

                    play = item.get('play', 0)
                    view_count = int(play) if play else 0

                    like_count = int(item.get('like', 0))
                    favorite_count = int(item.get('favorites', 0))
                    coin_count = int(item.get('coin', 0))

                    course = BilibiliCourse(
                        title=title,
                        url=url,
                        view_count=view_count,
                        favorite_count=favorite_count,
                        like_count=like_count,
                        coin_count=coin_count,
                        publish_date=publish_date,
                        uploader=author,
                        skill=skill
                    )
                    courses.append(course)

                except Exception as e:
                    continue

        except Exception as e:
            print(f"搜索 {skill} 时出错: {str(e)}")

        return courses
