"""推送平台模块"""

from typing import Dict, Optional

from .base import PushPlatform
from .discord import DiscordPlatform
from .feishu import FeishuPlatform
from .custom import CustomPlatform


def create_platform(name: str, config: Dict) -> Optional[PushPlatform]:
    """工厂函数，创建推送平台实例"""
    platforms = {
        "discord": DiscordPlatform,
        "feishu": FeishuPlatform,
        # 飞书第三个机器人:与 feishu 主机器人完全同构,仅 webhook 不同
        "feishu_1": FeishuPlatform,
        # 飞书第二机器人:同一平台类,经 config 变体(剔除 relevance 面板/归档链接)区分
        "feishu_no_teacher": FeishuPlatform,
        "custom": CustomPlatform,
    }

    if name not in platforms:
        raise ValueError(f"未知推送平台: {name}")

    platform_class = platforms[name]
    platform = platform_class(config)

    if not platform.validate_config(config):
        return None

    return platform


async def send_to_platforms(content: str, push_config: Dict, title: str = None, metadata: Optional[Dict] = None) -> bool:
    """发送内容到所有已启用且配置有效的平台;返回是否至少一个平台推送成功

    返回值供调用方决定是否需要记录「已推送链接」——全部失败时不记录,
    避免未实际送达的内容被永久去重记录误杀。
    """
    sent = False
    for platform_name, platform_conf in push_config.items():
        platform = create_platform(platform_name, platform_conf)
        if platform is None:
            continue

        try:
            await platform.send(content, title, metadata)
            print(f"✅ 已推送到 {platform_name}")
            sent = True
        except Exception as e:
            print(f"❌ 推送到 {platform_name} 失败: {e}")
    return sent
