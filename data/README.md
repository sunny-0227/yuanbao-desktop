# 旧数据迁移目录

新版运行数据默认保存在 `%LOCALAPPDATA%\Yuanbao`，不会写入仓库。

这个目录只用于从旧版导入数据：首次启动时，如果这里存在 `notes.json`、`todos.json` 或 `user_custom_entries.json`，程序会导入用户目录，并保留原文件。笔记与提醒成功迁移后会记录标记，避免重复导入。

目录中的运行文件已通过 `.gitignore` 排除，不应作为发布资源提交。旧版 `command_rules.json` 已废弃，本地指令由 `services/command_router.py` 统一识别。
