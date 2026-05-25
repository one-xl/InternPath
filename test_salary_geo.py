import unittest
from datetime import datetime, timedelta

from salary_scraper import (
    extract_salary_monthly_mid_k,
    haversine_km,
    linear_next_forecast_k,
)


class TestSalaryParse(unittest.TestCase):
    def test_k_range(self):
        t = "我们提供月薪：15-25k/月，另有补贴"
        v = extract_salary_monthly_mid_k(t)
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v, 20.0, places=3)

    def test_wan_month(self):
        t = "薪资1.5-2万/月"
        v = extract_salary_monthly_mid_k(t)
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v, 17.5, places=3)


class TestHaversine(unittest.TestCase):
    def test_beijing_shanghai_order(self):
        # 北京天安门附近 vs 上海人民广场附近（直线距离应约 1000km 量级）
        d = haversine_km(39.9042, 116.4074, 31.2304, 121.4737)
        self.assertGreater(d, 900)
        self.assertLess(d, 1100)


class TestLinearForecast(unittest.TestCase):
    def test_flat_increases_with_slope(self):
        base = datetime(2026, 1, 1)
        hist = [
            (base, 10.0),
            (base + timedelta(days=30), 12.0),
            (base + timedelta(days=60), 14.0),
        ]
        nxt = linear_next_forecast_k(hist)
        self.assertIsNotNone(nxt)
        self.assertGreater(nxt, 14.0)


class TestSSRFPrevention(unittest.TestCase):
    def test_ssrf_validation(self):
        from salary_scraper import validate_url_for_ssrf
        from config import Config
        
        # Backup original setting
        orig_prod = Config.IS_PRODUCTION
        
        try:
            # Under production Mode
            Config.IS_PRODUCTION = True
            
            # Non-http scheme should be blocked
            with self.assertRaises(ValueError):
                validate_url_for_ssrf("ftp://example.com")
            with self.assertRaises(ValueError):
                validate_url_for_ssrf("file:///etc/passwd")
                
            # Loopback/Private IP should be blocked
            with self.assertRaises(ValueError):
                validate_url_for_ssrf("http://127.0.0.1/test")
            with self.assertRaises(ValueError):
                validate_url_for_ssrf("https://192.168.1.100/jobs")
            with self.assertRaises(ValueError):
                validate_url_for_ssrf("http://localhost/jobs")

            # Normal public URLs should pass
            validate_url_for_ssrf("https://www.baidu.com")
            validate_url_for_ssrf("http://news.sina.com.cn/test")

        finally:
            Config.IS_PRODUCTION = orig_prod


if __name__ == "__main__":
    unittest.main()
