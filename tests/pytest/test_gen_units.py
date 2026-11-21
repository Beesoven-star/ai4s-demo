"""测试 systemd 单元生成器的 cron → OnCalendar 转换"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts._gen_units import cron_to_oncalendar


class TestDailyCron:
    def test_plain_daily(self):
        assert cron_to_oncalendar("0 8 * * *") == "*-*-* 08:00:00"
        assert cron_to_oncalendar("30 17 * * *") == "*-*-* 17:30:00"

    def test_rejects_non_star_dom_month(self):
        with pytest.raises(ValueError, match="day-of-month"):
            cron_to_oncalendar("0 8 1 * *")
        with pytest.raises(ValueError, match="month"):
            cron_to_oncalendar("0 8 * 1 *")

    def test_rejects_bad_minute_hour(self):
        with pytest.raises(ValueError):
            cron_to_oncalendar("*/5 8 * * *")
        with pytest.raises(ValueError):
            cron_to_oncalendar("0 25 * * *")


class TestWeeklyCron:
    def test_dow_mapping(self):
        assert cron_to_oncalendar("0 17 * * 4") == "Thu *-*-* 17:00:00"
        assert cron_to_oncalendar("0 17 * * 1") == "Mon *-*-* 17:00:00"

    def test_sunday_0_and_7(self):
        assert cron_to_oncalendar("0 17 * * 0") == "Sun *-*-* 17:00:00"
        assert cron_to_oncalendar("0 17 * * 7") == "Sun *-*-* 17:00:00"

    def test_rejects_invalid_dow(self):
        with pytest.raises(ValueError, match="day-of-week"):
            cron_to_oncalendar("0 17 * * 8")
        with pytest.raises(ValueError, match="day-of-week"):
            cron_to_oncalendar("0 17 * * 1-5")
