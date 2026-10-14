# CrashLens

**输入待测软件目录 → 动态执行 → 捕获崩溃与异常 → 输出可复现的 Bug 报告。**

CrashLens 是软件测试课程的本地命令行程序测试平台，由大模型辅助开发，提供中文网页界面和命令行两种入口，运行时不需要任何模型 API。

- 演示录像：[video/demo.mp4](video/demo.mp4)（[说明](video/readme.md)）
- 大模型对话记录：[prompt/](prompt/readme.md)
- 验收结果：[code/examples/acceptance](code/examples/acceptance/readme.md)

```text
readme.md   使用说明
code/       平台源码、测试、示例待测软件（datacraft-buggy / datacraft-fixed）、脚本
video/      平台运行录像
prompt/     与大模型交互开发、调试本平台的完整对话
```

## 功能

- **输入**：待测软件目录，读取其中的 `crashlens.toml`（也可在网页上填写启动方式）。
- **动态执行**：从正常种子生成边界值、JSON 结构变异和字节变异输入，通过标准输入或文件传给目标程序，真实启动进程执行。
- **捕获失败**：识别未捕获异常、进程崩溃、超时、异常退出和输出超限，按异常类型与调用位置归组。
- **验证证据**：每个新发现自动重放两次，并尝试把触发输入缩减到最小。
- **输出**：发现列表、错误堆栈、HTML / JSON 报告、触发输入下载、完整证据 ZIP；支持一键重放和修复版本回归。

## 快速开始（Windows，Python 3.11+）

在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code\requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .\code
.\.venv\Scripts\python.exe -m crashlens serve
```

打开 **http://127.0.0.1:8765**。可用 `--port`、`--data-dir` 修改端口和数据目录。

### 第一次演示

1. 点击 **缺陷演示**，平台读取 `code/examples/datacraft-buggy` 的配置（含除零、字段缺失、死循环等预设缺陷）。
2. 点击 **开始动态测试**，默认运行 80 个用例。
3. 在 **发现与证据** 中点击 **查看证据**，查看触发输入、错误堆栈和缩减后的输入。
4. 点击 **重放失败用例**，确认 Bug 可以稳定复现。
5. 在 **修复版本回归** 中填入 `code/examples/datacraft-fixed` 的路径，验证同一输入不再触发异常。
6. 导出 HTML / JSON 报告。

## 测试自己的软件

在待测软件目录中放入 `crashlens.toml` 和一个装有正常输入样例的 `seeds/` 目录：

```toml
[target]
command = ["{python}", "main.py"]   # 文件输入时写成 ["{python}", "main.py", "{input_file}"]
input_mode = "stdin"                # 或 "file"
timeout_seconds = 1.5
success_codes = [0]
reject_codes = [2]                  # 程序正常拒绝非法输入时使用的退出码

[fuzz]
seed_directory = "seeds"
max_cases = 100
random_seed = 42
max_seconds = 120
minimize = true
```

- `{python}` 指平台使用的解释器；其他语言请写可执行文件的绝对路径。命令必须是参数数组，不能是整段 shell 命令。
- 种子必须是程序能正常处理的输入；种子预检失败时任务中止，不计为 Bug。
- 支持每次读取一份输入后退出的命令行程序。堆栈解析针对 Python，其他语言按退出状态分类。不支持交互式程序、服务器或 GUI。
- **只测试你信任的程序**：平台管理进程生命周期，但不做安全隔离。

## 命令行

```powershell
.\.venv\Scripts\python.exe -m crashlens run .\code\examples\datacraft-buggy
.\.venv\Scripts\python.exe -m crashlens replay .\code\examples\datacraft-buggy .\input.bin
```

## 结果分类

| 分类 | 含义 |
| --- | --- |
| `passed` / `rejected` | 正常通过 / 按约定退出码拒绝输入 |
| `exception` | 非零退出，且 stderr 中有 Python traceback |
| `crash` | 被信号终止或 Windows 原生崩溃 |
| `timeout` | 超过单次执行时限 |
| `abnormal_exit` | 未约定的非零退出，需人工判断 |
| `output_limit` | 输出超过上限 |

证据保存在 `.crashlens/jobs/<任务 ID>/`，每个失败分组都有 `finding.json`（结果、重放和缩减记录）、`input.bin`（原始触发输入）以及 `minimized.bin`（验证通过的最小输入）。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".\code[dev]"
.\.venv\Scripts\python.exe -m pytest code\tests -q --basetemp=.pytest-tmp
.\.venv\Scripts\python.exe code\scripts\verify_acceptance.py
```

| 模块 | 职责 |
| --- | --- |
| `config.py` | 配置校验与种子检查 |
| `generators.py` / `json_tools.py` | 输入生成与 JSON 结构变异 |
| `process.py` / `_gate.py` | 进程执行、超时、进程树清理与结果分类 |
| `engine.py` / `minimizer.py` | 测试流程、归组、重放与输入缩减 |
| `manager.py` / `store.py` | 后台任务与 SQLite 索引 |
| `web.py` / `cli.py` | 网页界面、报告与命令行入口 |

参考示例：[android-testing-platform](https://github.com/jinglingsun/android-testing-platform)。项目采用 [MIT License](LICENSE)。
