import random
import time
import re
from typing import List
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from config import Config
from models import BilibiliCourse

class BilibiliCrawler:
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        ]
    
    def _random_delay(self):
        delay = random.uniform(Config.CRAWLER_DELAY_MIN, Config.CRAWLER_DELAY_MAX)
        time.sleep(delay)
    
    def _get_headers(self):
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def _parse_number(self, text: str) -> int:
        text = text.strip()
        if '万' in text:
            num = float(text.replace('万', '')) * 10000
            return int(num)
        elif '亿' in text:
            num = float(text.replace('亿', '')) * 100000000
            return int(num)
        else:
            num = re.sub(r'[^0-9]', '', text)
            return int(num) if num else 0
    
    def search_skill(self, skill: str) -> List[BilibiliCourse]:
        courses = []
        search_url = f"{Config.BILIBILI_SEARCH_URL}?keyword={skill}&order=totalrank"
        
        try:
            self._random_delay()
            response = requests.get(search_url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            video_items = soup.find_all('li', class_='bili-video-card')
            
            for item in video_items[:20]:
                try:
                    title_tag = item.find('h3', class_='bili-video-card__info--tit')
                    if not title_tag:
                        continue
                    
                    title = title_tag.get('title', '').strip()
                    if not title:
                        title = title_tag.get_text(strip=True)
                    
                    url_tag = item.find('a', class_='bili-video-card__wrap pic')
                    url = f"https:{url_tag.get('href', '')}" if url_tag else ''
                    
                    uploader_tag = item.find('span', class_='bili-video-card__info--author')
                    uploader = uploader_tag.get_text(strip=True) if uploader_tag else '未知'
                    
                    date_tag = item.find('span', class_='bili-video-card__info--date')
                    publish_date = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime('%Y-%m-%d')
                    
                    view_tag = item.find('span', class_='bili-video-card__stats--view')
                    view_count = self._parse_number(view_tag.get_text(strip=True)) if view_tag else 0
                    
                    like_count = 0
                    favorite_count = 0
                    coin_count = 0
                    
                    course = BilibiliCourse(
                        title=title,
                        url=url,
                        view_count=view_count,
                        favorite_count=favorite_count,
                        like_count=like_count,
                        coin_count=coin_count,
                        publish_date=publish_date,
                        uploader=uploader,
                        skill=skill
                    )
                    courses.append(course)
                    
                except Exception as e:
                    continue
            
        except Exception as e:
            print(f"搜索 {skill} 时出错: {str(e)}")
        
        return courses
