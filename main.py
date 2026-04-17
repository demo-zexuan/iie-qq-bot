"""
iie-qq-bot 启动入口

负责初始化 NoneBot 框架、注册 OneBot V11 适配器并加载本地插件目录。
NapCat 端需要配置 OneBot V11 反向 WebSocket 连接到本服务监听的地址
（默认 ws://host:8080/onebot/v11/ws），具体端口参见 .env 中的 PORT 配置。

@module main
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.log import logger
from pathlib import Path
import os


def setup_file_logging() -> None:
    """配置日志滚动写入，默认按天切分并保留 14 天。"""
    enabled = os.getenv("LOG_FILE_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return

    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / os.getenv("LOG_FILE_NAME", "bot.log"),
        level=os.getenv("LOG_LEVEL", "INFO"),
        rotation=os.getenv("LOG_ROTATION", "00:00"),
        retention=os.getenv("LOG_RETENTION", "14 days"),
        compression=os.getenv("LOG_COMPRESSION", "zip"),
        enqueue=True,
        encoding="utf-8",
    )

# 初始化 NoneBot
nonebot.init()
setup_file_logging()

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 加载本地插件
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()