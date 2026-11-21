"""测试周报判定:weekly_cron 触发时刻匹配"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import is_weekly_push


TZ = timezone(timedelta(hours=8))

# 2026-08-17 是周一;2026-08-20 周四;2026-08-23 周日
WEEKLY_CFG = {
    "schedule": {
        "push_cron": ["0 8 * * *"],
        "weekly_cron": ["0 17 * * 4", "0 17 * * 0"],
        "timezone_hours": 8,
    }
}


def test_returns_false_when_weekly_cron_missing_or_empty():
    now = datetime(2026, 8, 20, 17, 0, tzinfo=TZ)  # 周四 17:00
    assert is_weekly_push(now, {"schedule": {}}) is False
    assert is_weekly_push(now, {"schedule": {"weekly_cron": []}}) is False


def test_thursday_1700_matches():
    assert is_weekly_push(datetime(2026, 8, 20, 17, 0, tzinfo=TZ), WEEKLY_CFG) is True


def test_sunday_1700_matches():
    assert is_weekly_push(datetime(2026, 8, 23, 17, 0, tzinfo=TZ), WEEKLY_CFG) is True


def test_drift_tolerance_within_two_minutes():
    """loop/systemd 执行延迟 2 分钟内仍命中"""
    assert is_weekly_push(datetime(2026, 8, 20, 17, 1, 59, tzinfo=TZ), WEEKLY_CFG) is True


def test_other_times_not_matched():
    cfg = WEEKLY_CFG
    # 周四早报时刻
    assert is_weekly_push(datetime(2026, 8, 20, 8, 0, tzinfo=TZ), cfg) is False
    # 周三 17:00
    assert is_weekly_push(datetime(2026, 8, 19, 17, 0, tzinfo=TZ), cfg) is False
    # 周五 17:00
    assert is_weekly_push(datetime(2026, 8, 21, 17, 0, tzinfo=TZ), cfg) is False
    # 周四 17:05 超出容差
    assert is_weekly_push(datetime(2026, 8, 20, 17, 5, tzinfo=TZ), cfg) is False


def test_dow_7_accepted_as_sunday():
    cfg = {"schedule": {"weekly_cron": ["0 17 * * 7"]}}
    assert is_weekly_push(datetime(2026, 8, 23, 17, 0, tzinfo=TZ), cfg) is True


def test_invalid_cron_ignored():
    cfg = {"schedule": {"weekly_cron": ["not-a-cron", "0 17 * * 4"]}}
    assert is_weekly_push(datetime(2026, 8, 20, 17, 0, tzinfo=TZ), cfg) is True
    assert is_weekly_push(datetime(2026, 8, 21, 17, 0, tzinfo=TZ), cfg) is False
