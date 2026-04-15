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

# 初始化 NoneBot
nonebot.init()

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 加载本地插件
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()