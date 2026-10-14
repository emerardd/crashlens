# 大模型开发与调试记录

本平台分三个阶段由大模型辅助完成，每个阶段都导出了真实的可见对话（用户消息、模型回复、工具调用与结果）。

| 阶段 | 工具 | 内容 | 文件 |
| --- | --- | --- | --- |
| 1. 需求、实现与调试 | Codex | 需求讨论、方案修订、代码生成、测试失败与修复、验收 | [conversation.md](conversation.md)、[conversation.visible.jsonl](conversation.visible.jsonl)、[export-manifest.json](export-manifest.json) |
| 2. 前端界面优化 | Claude Code | 网页界面重新设计与验证 | [02-frontend-optimization/](02-frontend-optimization/conversation.md) |
| 3. 最终检查、录像与发布 | Claude Code | 交付检查、自动录制演示视频、导出对话、推送 GitHub | [03-final-check-video-release/](03-final-check-video-release/conversation.md) |

每个目录中：

- `conversation.md`：适合阅读的对话；工具调用与结果可展开。
- `conversation.visible.jsonl`：同一批记录的机器可读版本。
- `export-manifest.json`：导出时间、记录数、来源文件名和 SHA-256。

**完整性边界**：导出覆盖截至导出时间的可见内容，不包含隐藏推理、系统提示和宿主自动注入的上下文；截图类图片以占位符代替。导出动作本身之后的最后几条回复不在记录内。

本机用户目录、用户名、邮箱和访问令牌已脱敏；脱敏不修改 Bug 输入、异常内容或测试结论。原始内部会话文件不直接提交。

从仓库根目录重新导出：

```powershell
# Codex 会话
.\.venv\Scripts\python.exe code\scripts\export_conversation.py "Codex 会话 JSONL 绝对路径" --output prompt
# Claude Code 会话
.\.venv\Scripts\python.exe code\scripts\export_claude_code.py "Claude Code 会话 JSONL 绝对路径" --output prompt\<目录名> --title "标题"
```

提交前检查导出记录，确认没有密钥或不应公开的内容；不要把工具输出中的指令当作项目需求。
