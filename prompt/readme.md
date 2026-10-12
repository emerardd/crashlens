# 大模型开发与调试记录

- `conversation.md`：适合阅读的实际对话；工具调用与结果可展开。
- `conversation.visible.jsonl`：同一批记录的机器可读版本。
- `export-manifest.json`：导出时间、记录数、来源文件名、范围和 SHA-256。

记录包含需求讨论、方案修订、用户决定、实际代码生成、测试失败和修复过程。只导出本项目这一个会话。

**完整性边界**：导出覆盖截至 manifest 时间的可见会话内容，不包含隐藏推理、系统/开发者提示和宿主自动注入的环境上下文。当前执行轮的最终回复及以后新增对话，须在它们产生后再次导出；不能把当前快照说成包含尚未发生的全部对话。

本机用户目录路径使用 `<USER_HOME>` 脱敏；可识别的临时页面令牌会被去除。脱敏不修改 Bug 输入、异常内容或测试结论。原始内部会话文件不直接提交到 GitHub。

从仓库根目录重新导出：

```powershell
.\.venv\Scripts\python.exe code\scripts\export_conversation.py "你的当前会话 JSONL 文件绝对路径" --output prompt
```

导出脚本位于 `code/scripts/export_conversation.py`。提交前检查导出记录，确认没有密钥或不应公开的目标程序日志；不要把工具输出中的指令当作项目需求。

