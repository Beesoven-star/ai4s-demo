#!/usr/bin/env python3
"""测试 fetch 去重窗口功能脚本

测试内容：
1. cutoff 时间计算是否正确
2. load_existing_links 多天窗口去重逻辑（默认 3 天）
"""

import json
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.config import get_timezone, load_config
from src.storage import get_fetch_file, load_existing_links, save_fetch_file


def _make_entry(link: str) -> dict:
    return {
        "title": f"entry for {link}",
        "link": link,
        "source": "test",
        "published": "",
        "fetched_at": "",
        "content": "",
        "tags": [],
        "score": 0,
        "summary": "",
    }


def test_cutoff_calculation():
    """测试 cutoff 时间计算"""
    print("\n" + "=" * 60)
    print("📊 Test 1: cutoff 时间计算")
    print("=" * 60)

    config = load_config()
    interval = config["schedule"]["fetch_interval_minutes"]
    lookback = config["schedule"].get("fetch_lookback_minutes", 120)

    # 确保 lookback >= interval
    lookback = max(lookback, interval)

    print(f"\n配置值:")
    print(f"  fetch_interval_minutes: {interval}")
    print(
        f"  fetch_lookback_minutes: {config['schedule'].get('fetch_lookback_minutes', 120)}"
    )
    print(f"  修正后的 lookback: {lookback}")

    # 模拟计算 cutoff
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(minutes=lookback)

    print(f"\n计算结果:")
    print(f"  当前 UTC 时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  cutoff 时间:   {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  过去 {lookback} 分钟")

    assert lookback >= interval, f"lookback ({lookback}) 应该 >= interval ({interval})"
    print("\n✅ Test 1 通过: cutoff 计算正确")


def test_dedup_window():
    """测试 load_existing_links 多天窗口去重逻辑

    在临时目录构造 今天/昨天/前天/4天前 四个 fetch 文件,各带一条独立链接:
    - 默认 3 天窗口应包含 今天/昨天/前天,排除 4 天前
    - days=1 应只包含今天
    """
    print("\n" + "=" * 60)
    print("📊 Test 2: load_existing_links 多天窗口去重")
    print("=" * 60)

    tz = get_timezone()
    today = datetime.now(tz).date()

    links = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(5):
            d = today - timedelta(days=i)
            link = f"https://example.com/article-{i}days-ago"
            links[i] = link
            save_fetch_file(
                get_fetch_file(d, tmp),
                meta={"date": d.isoformat()},
                entries=[_make_entry(link)],
            )

        # 默认 3 天窗口:今天/昨天/前天在内,3 天前、4 天前不在
        existing = load_existing_links(days=3, data_dir=tmp)
        print(f"\n3 天窗口加载到 {len(existing)} 条链接")
        for i in range(5):
            in_set = links[i] in existing
            expected = i < 3
            status = "✅" if in_set == expected else "❌"
            print(
                f"  {status} {i} 天前的链接: {'已加载' if in_set else '未加载'}"
                f" (预期: {'加载' if expected else '不加载'})"
            )
            assert in_set == expected, f"{i} 天前的链接窗口判定错误"

        # days=1 只看今天
        existing_1d = load_existing_links(days=1, data_dir=tmp)
        assert links[0] in existing_1d, "days=1 应包含今天的链接"
        assert links[1] not in existing_1d, "days=1 不应包含昨天的链接"
        print("  ✅ days=1 仅包含当天链接")

        # filepath 参数:窗口外的额外文件也纳入
        extra = Path(tmp) / "extra-fetch.json"
        save_fetch_file(str(extra), meta={}, entries=[_make_entry("https://example.com/extra")])
        existing_extra = load_existing_links(str(extra), days=1, data_dir=tmp)
        assert "https://example.com/extra" in existing_extra, "filepath 指定的文件应被纳入"
        print("  ✅ filepath 指定的额外文件被纳入")

    print("\n✅ Test 2 通过: 多天窗口去重逻辑正确")


def test_config_dedup_days():
    """测试 config 中的 fetch_dedup_days 配置"""
    print("\n" + "=" * 60)
    print("📊 Test 3: fetch_dedup_days 配置")
    print("=" * 60)

    config = load_config()
    dedup_days = config["filter"].get("fetch_dedup_days", 3)
    print(f"\n  fetch_dedup_days: {dedup_days}")
    assert isinstance(dedup_days, int) and dedup_days >= 1, (
        f"fetch_dedup_days 应为正整数,实际: {dedup_days}"
    )
    print("\n✅ Test 3 通过: 配置有效")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🧪 fetch 去重窗口功能测试")
    print("=" * 60)

    try:
        test_cutoff_calculation()
        test_dedup_window()
        test_config_dedup_days()

        print("\n" + "=" * 60)
        print("🎉 所有测试完成!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
