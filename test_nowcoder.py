import json
import unittest
from unittest.mock import patch

from nowcoder_jobs import (
    build_intern_center_url,
    filter_by_keyword,
    parse_nowcoder_listings,
    sort_rows,
)


class TestNowcoderUrl(unittest.TestCase):
    def test_build_guangzhou(self):
        u = build_intern_center_url(city="广州", career_job_id=11075)
        self.assertIn("recruitType=2", u)
        self.assertIn("careerJob=11075", u)
        self.assertIn("city=%E5%B9%BF%E5%B7%9E", u)


class TestParse(unittest.TestCase):
    def test_parse_simple_cards(self):
        html = """
        <div class="job-name">Java 后端</div>
        <div class="job-salary">150-250元/天</div>
        <div class="job-name">前端</div>
        <div class="job-salary">200元/天</div>
        """
        rows = parse_nowcoder_listings(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Java 后端")
        self.assertEqual(rows[0]["salary_mid_yuan_per_day"], 200.0)
        self.assertEqual(rows[1]["salary_mid_yuan_per_day"], 200.0)

    def test_parse_rich_card_like_nowcoder(self):
        html = """
        <div class="job-name">产品策划</div>
        <div class="job-salary">350-400元/天</div>
        <span>5天/周</span><span>有转正</span><span>最少3个月</span>
        <div class="company-name">腾讯科技</div>
        <div class="company-info-item">通信电子</div>
        <div class="company-info-item">1000-9999人</div>
        <div class="job-name">ai产品经理 (实习)</div>
        <div class="job-salary">薪资面议</div>
        <span>3天/周</span>
        <div class="company-name">小红书</div>
        <div class="company-info-item">人工智能</div>
        <div class="company-info-item">10000人以上</div>
        """
        rows = parse_nowcoder_listings(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["company"], "腾讯科技")
        self.assertEqual(rows[0]["company_info"], "通信电子 / 1000-9999人")
        self.assertEqual(rows[0]["days_per_week"], 5)
        self.assertEqual(rows[0]["conversion"], "有转正")
        self.assertEqual(rows[0]["min_months"], 3)
        self.assertEqual(rows[1]["company"], "小红书")
        self.assertEqual(rows[1]["days_per_week"], 3)
        self.assertIn("10000人以上", rows[1]["company_info"])

    def test_parse_raw_api_payload(self):
        payload = {
            "code": 0,
            "data": {
                "datas": [
                    {
                        "jobName": "产品策划实习生",
                        "salaryMin": 350,
                        "salaryMax": 400,
                        "salaryMonth": 0,
                        "recruitType": 2,
                        "durationDays": 5,
                        "durationMonths": 3,
                        "jobOffer": 1,
                        "jobCity": "广州",
                        "careerJobId": 11075,
                        "recommendInternCompany": {
                            "companyShortName": "腾讯科技",
                            "industryTagNameList": ["通信电子"],
                            "personScales": "1000-9999人",
                            "address": "广州",
                        },
                    }
                ]
            },
        }
        rows = parse_nowcoder_listings(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "产品策划实习生")
        self.assertEqual(rows[0]["company"], "腾讯科技")
        self.assertEqual(rows[0]["company_info"], "通信电子 / 1000-9999人 / 广州")
        self.assertEqual(rows[0]["days_per_week"], 5)
        self.assertEqual(rows[0]["conversion"], "有转正")
        self.assertEqual(rows[0]["min_months"], 3)
        self.assertEqual(rows[0]["salary_mid_yuan_per_day"], 375.0)

    def test_parse_shell_html_via_initial_state_api_fallback(self):
        html = """
        <script>
        window.__INITIAL_STATE__={"fullPath":"\\/jobs\\/intern\\/center?recruitType=2&city=%E5%B9%BF%E5%B7%9E&careerJob=11075"};
        (function(){})();
        </script>
        """
        expected = [
            {
                "title": "后端开发",
                "salary_text": "200-300元/天",
                "salary_mid_yuan_per_day": 250.0,
                "dom_index": 0,
                "company": "示例公司",
                "company_info": "互联网 / 1000-9999人 / 广州",
                "days_per_week": 5,
                "conversion": "有转正",
                "min_months": 3,
            }
        ]
        with patch("nowcoder_jobs._fetch_nowcoder_api_rows", return_value=expected) as mocked:
            rows = parse_nowcoder_listings(html)
        mocked.assert_called_once()
        self.assertEqual(rows, expected)


class TestSort(unittest.TestCase):
    def test_reverse_dom(self):
        rows = [
            {"title": "A", "salary_text": "1元/天", "salary_mid_yuan_per_day": 1.0, "dom_index": 0},
            {"title": "B", "salary_text": "2元/天", "salary_mid_yuan_per_day": 2.0, "dom_index": 1},
        ]
        out = sort_rows(
            rows,
            list_order="列表逆序（默认）",
            expect_daily_yuan=1.5,
            keyword="",
            factors=["岗位匹配", "薪资接近期望", "牛客顺序"],
        )
        self.assertEqual(out[0]["title"], "B")

    def test_sort_by_company_and_filter_company(self):
        rows = [
            {
                "title": "PM",
                "company": "阿里",
                "company_info": "0-20人",
                "salary_text": "",
                "salary_mid_yuan_per_day": None,
                "dom_index": 0,
                "days_per_week": 5,
                "conversion": "",
                "min_months": None,
            },
            {
                "title": "PM",
                "company": "字节",
                "company_info": "1000-9999人",
                "salary_text": "",
                "salary_mid_yuan_per_day": None,
                "dom_index": 1,
                "days_per_week": 3,
                "conversion": "有转正",
                "min_months": None,
            },
        ]
        out = sort_rows(
            rows,
            list_order="公司名 A→Z",
            expect_daily_yuan=None,
            keyword="",
            factors=["岗位匹配", "薪资接近期望", "牛客顺序"],
        )
        self.assertEqual([r["company"] for r in out], ["字节", "阿里"])
        filt = filter_by_keyword(rows, "字节")
        self.assertEqual(len(filt), 1)
        self.assertEqual(filt[0]["company"], "字节")

    def test_composite_keyword_matches_company(self):
        rows = [
            {
                "title": "实习",
                "company": "腾讯科技",
                "company_info": "",
                "salary_text": "100元/天",
                "salary_mid_yuan_per_day": 100.0,
                "dom_index": 0,
            },
            {
                "title": "后端",
                "company": "其他",
                "company_info": "",
                "salary_text": "300元/天",
                "salary_mid_yuan_per_day": 300.0,
                "dom_index": 1,
            },
        ]
        out = sort_rows(
            rows,
            list_order="综合（三要素）",
            expect_daily_yuan=100.0,
            keyword="腾讯",
            factors=["岗位匹配", "薪资接近期望", "牛客顺序"],
        )
        self.assertEqual(out[0]["company"], "腾讯科技")


if __name__ == "__main__":
    unittest.main()


class TestNowcoderKeywordUrl(unittest.TestCase):
    def test_build_with_keyword_without_career_lock(self):
        u = build_intern_center_url(city="广州", keyword="后端")
        self.assertIn("recruitType=2", u)
        self.assertIn("city=%E5%B9%BF%E5%B7%9E", u)
        self.assertIn("query=%E5%90%8E%E7%AB%AF", u)
        self.assertNotIn("careerJob=", u)
