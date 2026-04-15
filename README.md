# iie-qq-bot

基于 NoneBot2 + NapCat（OneBot V11）实现每日定时统计指定群人数，并汇总到 PostgreSQL。

## 功能说明

1. 按配置群号列表进行统计。
2. 每日定时执行（默认 `08:00`，时区 `Asia/Shanghai`）。
3. 数据写入表 `group_member_stats`。
4. 同一群同一天使用覆盖更新（UPSERT）：
   - 保留每日历史；
   - 当天重复执行时仅更新为最新人数和时间戳。
5. 提供手动触发命令：`/groupstats_now`。
6. 新增水群活跃统计（按人/按小时聚合）：
   - 手动命令：`/水群榜`（文本榜单）
   - 手动命令：`/水群画像`（Top1 时段分布图 + 全群小时趋势图）
   - 每日自动播报：群人数统计后自动补充当日水群 Top10 摘要。
7. 新增历史归档：
   - 明细数据保留 N 天（默认 30 天）；
   - 超期明细按天聚合归档后清理，降低长期数据量。
8. 新增被 @ 随机坤语音回复（未命中更高优先级命令时触发）：
   - 优先使用 `kun/amr/` 预转换音频（AMR-NB, 8kHz, mono）；
   - 不可用时回退 `kun/converted/` 与 `kun/`。

## 数据表结构

应用启动时自动创建表：`group_member_stats`

核心字段：
- `group_id` 群号
- `group_name` 群名
- `member_count` 群人数
- `stat_date` 统计日期（天粒度）
- `stat_time` 统计时间（秒粒度）
- `created_at` 创建时间
- `updated_at` 更新时间

唯一约束：`(group_id, stat_date)`

## 配置项

在 `.env` 配置（也可由外部环境变量覆盖，外部优先）：

- `PG_HOST` PostgreSQL 主机
- `PG_PORT` PostgreSQL 端口
- `PG_DATABASE` PostgreSQL 数据库名
- `PG_USER` PostgreSQL 用户
- `PG_PASSWORD` PostgreSQL 密码
- `GROUP_STATS_GROUP_IDS` 统计群号（逗号分隔）
- `GROUP_STATS_DAILY_TIME` 每日执行时间（`HH:MM`）
- `GROUP_STATS_TIMEZONE` 时区（如 `Asia/Shanghai`）
- `GROUP_STATS_API_TIMEOUT` 预留超时参数
- `GROUP_STATS_MESSAGE_FLUSH_INTERVAL_SECONDS` 活跃统计缓存刷盘间隔（秒）
- `GROUP_STATS_ARCHIVE_TIME` 每日归档执行时间（`HH:MM`）
- `GROUP_STATS_ARCHIVE_RETENTION_DAYS` 明细保留天数（超过后归档+清理）

示例：

```env
GROUP_STATS_GROUP_IDS=12345678,87654321
GROUP_STATS_DAILY_TIME=08:00
GROUP_STATS_TIMEZONE=Asia/Shanghai
GROUP_STATS_MESSAGE_FLUSH_INTERVAL_SECONDS=30
GROUP_STATS_ARCHIVE_TIME=03:30
GROUP_STATS_ARCHIVE_RETENTION_DAYS=30
```

## 依赖安装

```bash
uv sync
```

或使用 pip：

```bash
pip install -e .
```

## 启动 PostgreSQL + NapCat

```bash
docker compose up -d postgres napcat
```

## NapCat 对接 NoneBot

请在 NapCat 管理端配置 OneBot V11 反向 WebSocket 到 NoneBot：

- 地址示例：`ws://host.docker.internal:8080/onebot/v11/ws`
- 若 NapCat 与 NoneBot 在同一 docker 网络内，请将 `host.docker.internal` 改为服务名或容器可达地址。

## 启动机器人

```bash
python main.py
```

## 手动验证

1. 在 `.env` 设置测试群号。
2. 启动 NapCat 并确保 OneBot 连接成功。
3. 启动 NoneBot。
4. 在任意可接收命令的会话发送：`/groupstats_now`。
5. 在数据库中查询：

```sql
SELECT group_id, group_name, member_count, stat_date, stat_time, updated_at
FROM group_member_stats
ORDER BY stat_date DESC, group_id ASC;
```

## 水群统计验证

1. 在测试群正常发言一段时间（用于生成当日数据）。
2. 群内执行 `/水群榜`，应返回：
   - 当日总消息数
   - Top10 用户消息数及占比
   - Top1 最早/最晚发言时间
3. 群内执行 `/水群画像`，应返回两张图：
   - Top1 用户 24 小时分布图
   - 全群 24 小时活跃趋势图
4. 等待刷盘间隔后（默认 30s）再次查询，数据应持续增长。

## 坤语音预转换（推荐）

若 `kun/` 中是 `.mp3` 或非常规 `.wav`，建议先执行：

```bash
python scripts/convert_kun_audio.py
```

可先 dry-run：

```bash
python scripts/convert_kun_audio.py --dry-run
```

转换完成后会输出到 `kun/amr/`，插件发送语音时将优先使用该目录。

## Docker Compose 说明

`docker-compose.yml` 已包含：
- `napcat` 服务
- `postgres` 服务（含健康检查）

当前仓库未包含 NoneBot 应用容器定义，默认在宿主机（或你自己的 Python 运行环境）启动 `main.py`。
