# 演示录像

**[demo.mp4](demo.mp4)**（约 2 分 10 秒，1440×900，带中文字幕，无配音）

录像是 CrashLens 网页界面的真实运行过程：由 `code/scripts/record_demo.py` 用 Playwright 驱动本机 Edge 浏览器操作平台并录屏，没有剪辑或预置结果。被测软件是自带的教学程序 DataCraft（`code/examples/datacraft-buggy`，含预设缺陷）。

## 录像内容

| 时间 | 内容 |
| --- | --- |
| 0:00 | 平台介绍：输入待测软件目录 → 动态执行 → 捕获崩溃/异常 → 输出 Bug 报告 |
| 0:08 | **输入**：点击“缺陷演示”填入待测软件目录，平台读取 `crashlens.toml`（启动命令、标准输入、80 个用例、随机种子 42） |
| 0:20 | **动态执行**：开始测试，平台真实启动目标进程，从正常种子生成边界值、JSON 结构变异和字节变异输入，实时统计结果 |
| 0:50 | **捕获结果**：80 个用例中发现 6 个失败分组（KeyError、ZeroDivisionError、TypeError 等未捕获异常及超时），每组均 2/2 重放一致 |
| 1:05 | **Bug 证据**：ZeroDivisionError 的触发输入、退出状态、完整堆栈（`datacraft.py` 第 28 行）、自动缩减后的最小输入 |
| 1:20 | **重放**：一键重放，再次观察到相同失败签名 |
| 1:30 | **修复版本回归**：同一输入在 `datacraft-fixed` 上被正常拒绝，原异常不再出现 |
| 1:40 | **输出**：导出离线 HTML 报告，逐个查看在待测软件中找到的 Bug 及证据 |

## 重新录制

在已安装平台的虚拟环境中额外安装 Playwright（录像依赖，不是平台运行依赖），然后从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install ffmpeg
.\.venv\Scripts\python.exe code\scripts\record_demo.py
ffmpeg -i video\raw\video-out\<生成的文件>.webm -c:v libx264 -crf 26 -pix_fmt yuv420p -movflags +faststart video\demo.mp4
```

脚本使用本机已安装的 Microsoft Edge，启动一个独立的平台服务（端口 8791，数据写入 `video/raw/`，该目录已被 `.gitignore` 忽略）。
