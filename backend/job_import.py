from pydantic import BaseModel, Field
from typing import Optional
import re

class JobImportPayload(BaseModel):
    title: str
    company: str = ""
    location: str = ""  # maps to region
    salary_range: str = ""
    jd_text: str
    source_url: str = ""


def parse_salary_range(salary_str: str) -> float:
    """Parses various Chinese salary range formats to a single monthly salary in thousands (k/month).
    Examples:
    - "15k-25k" -> 20.0
    - "15-25K" -> 20.0
    - "200-300元/天" or "250/天" -> (average * 22 / 1000) -> 5.5
    - "3-5万/月" -> 40.0
    - "30-50万/年" -> 40.0 / 12 -> 33.3
    - "100元/小时" -> 100 * 8 * 22 / 1000 -> 17.6
    """
    if not salary_str:
        return 15.0  # default fallback
        
    s = salary_str.lower().strip()
    
    # 1. Check annual salary
    is_annual = "年" in s or "y" in s
    
    # 2. Check daily rate
    is_daily = "天" in s or "d" in s or "day" in s
    
    # 3. Check hourly rate
    is_hourly = "小时" in s or "时" in s or "h" in s
    
    # Extract all numbers/floats in the string
    numbers = [float(n) for n in re.findall(r"\d+\.?\d*", s)]
    if not numbers:
        return 15.0
        
    avg_num = sum(numbers) / len(numbers)
    
    if is_daily:
        return round((avg_num * 22.0) / 1000.0, 1)
    elif is_hourly:
        return round((avg_num * 8.0 * 22.0) / 1000.0, 1)
    
    # If the string contains "万" (ten thousand)
    has_wan = "万" in s or "w" in s
    
    if has_wan:
        val_k = avg_num * 10.0
    else:
        if avg_num > 1000.0:
            val_k = avg_num / 1000.0
        else:
            val_k = avg_num
            
    if is_annual:
        val_k = val_k / 12.0
        
    return round(val_k, 1)
