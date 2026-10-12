# CrashLens

**输入软件目录，动态生成测试输入，捕获失败并保存可复现的证据。**

CrashLens 是软件安全课程的本地命令行程序测试平台。平台由大模型辅助开发，提供中文网页界面和命令行入口；运行时不需要模型 API、API Key 或外部服务。

本次实际验收结果见 [验收报告](code/examples/acceptance/readme.md) 和 [测试输出](code/examples/acceptance/test-output.txt)。运行演示录像见 [video/demo.mp4](video/demo.mp4)（说明见 [video/readme.md](video/readme.md)）。仓库结构见文末 [作业交付结构](#作业交付结构)。

> `datacraft-buggy` 是自带的教学程序，包含字段缺失、除零和循环超时等预设缺陷；`datacraft-fixed` 提供对应修复，方便演示发现、复现和回归流程。

## 功能

- 以待测软件目录为入口，读取 `crashlens.toml`，或在网页填写启动方式。
- 通过标准输入或文件路径向目标传递**原始字节**，不依赖 shell 字符串拼接。
- 从正常种子生成边界值、嵌套 JSON 字段与数组元素删除/替换、字节插入/删除/重复等用例。
- 固定随机种子、生成数量、输入大小、运行时间与单次超时预算。
- 真实执行目标进程，分别记录通过、正常拒绝、未捕获异常、进程崩溃、超时、异常退出和输出超限。
- 相似失败归组；保留每个重复失败的原始输入和运行证据。
- 新发现自动重放两次；对稳定的异常/崩溃缩减输入并再次验证，JSON 输入保持可解析的结构。
- 网页重放、修复版本回归、HTML / JSON 报告、原始/缩减输入下载。
- 任务结束后可一键下载完整证据 ZIP：离线报告、配置与环境快照、种子、原始/缩减失败输入、重复失败记录，以及逐文件 SHA-256 校验清单。
- SQLite 保存任务索引，本地目录保存证据；网页刷新后可继续查看进度和历史。
- 正常种子预检、单任务调度、停止与进程清理、数据目录独占锁。

## 支持范围

支持每次接收一份输入、运行后退出的**可信本地命令行程序**，例如解析器、转换器和校验工具。执行层可以启动不同语言的程序；内置堆栈分析当前仅针对 Python，其他程序主要依据退出状态分类。

主要开发与验证环境为 Windows 11 / Python 3.12。源码包含 POSIX 进程组实现，GitHub Actions 配置支持 Windows 和 Ubuntu。

不支持交互式终端、持续运行的服务器、Android 或桌面 GUI 自动探索。不提供覆盖率引导，也不自动判断业务输出是否正确。

**只运行你信任的目标程序。** 超时、进程组和 Windows Job Object 用于生命周期管理，不隔离文件访问、网络、凭据或恶意行为。默认只监听 `127.0.0.1`，不要把此服务暴露到公网。

## 快速开始（Windows PowerShell）

安装 Python 3.11 或更高版本。在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code\requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .\code
.\.venv\Scripts\python.exe -m crashlens serve
```

如果 `python` 不可用但已安装 Windows Python Launcher，将第一条命令中的 `python` 换成 `py -3`；也可以使用已安装解释器的完整路径。本项目无需修改全局 Python 配置或 PowerShell 执行策略。

打开 **http://127.0.0.1:8765**。使用其他端口或数据目录：

```powershell
.\.venv\Scripts\python.exe -m crashlens serve --port 8877 --data-dir .crashlens-demo
```

也可使用依赖范围安装开发版本：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".\code[dev]"
```

`requirements-lock.txt` 固定的是本次本地验证的依赖版本。开发版范围安装可能得到不同版本。

## 第一次演示

1. 点击网页中的 **缺陷演示**，读取 `code/examples/datacraft-buggy/crashlens.toml`。
2. 确认启动命令为 `["{python}", "datacraft.py"]`，保留默认 80 个用例和随机种子 42。
3. 点击 **开始动态测试**。平台先运行两个正常种子，再自动生成输入。
4. 在发现列表查看异常与超时。打开证据，查看输入、错误堆栈、重放结果和缩减结果。
5. 等任务完成后，点击 **重放失败用例**，确认同一输入能再次触发同一失败签名。
6. 返回原任务的发现，在 **修复版本回归** 填写 `code/examples/datacraft-fixed` 的绝对路径，运行相同输入。
7. 对修复版本再运行一次完整的 80 用例测试，检查其他输入的运行结果。
8. 导出 HTML / JSON 报告，下载触发输入。录像与证据说明见 [video/readme.md](video/readme.md)。

平台根据异常类型与调用位置归组。同一处缺少校验可能触发多种异常，因此一个缺陷可能对应多个失败分组。

## 连接自己的软件

建议目录结构：

```text
my-tool/
├── main.py
├── crashlens.toml
└── seeds/
    └── normal.json
```

最小配置：

```toml
[target]
command = ["{python}", "main.py"]
input_mode = "stdin"
timeout_seconds = 1.5
success_codes = [0]
reject_codes = [2]
max_output_bytes = 262144
input_suffix = ".json"

[fuzz]
seed_directory = "seeds"
max_cases = 100
random_seed = 42
max_input_bytes = 16384
max_seconds = 120
minimize = true
minimize_attempts = 16
```

文件输入方式：

```toml
[target]
command = ["{python}", "main.py", "{input_file}"]
input_mode = "file"
input_suffix = ".json"
```

- `{python}` 表示平台正在使用的 Python 解释器。其他虚拟环境或语言请指定相应可执行文件的绝对路径。
- `{input_file}` 是本次输入文件的绝对路径。临时文件在执行结束后清理；不要把日志中的临时路径当作长期复现入口。
- 启动参数使用 JSON/TOML 数组，带空格的路径仍是单个参数。不要填写 `python app.py` 这样的整段 shell 命令。
- `.bat`、`.cmd`、`.ps1` 不接受作为直接入口，请使用真正的解释器或可执行文件。
- `reject_codes` 填写目标程序用于拒绝非法输入的退出码。
- 种子应是能够成功处理的正常输入。正常种子试运行失败会中止任务并保存 `baseline-error.json`，不算自动发现的 Bug。
- 网页重放和修复版本回归先运行正常种子，再执行失败输入。基线执行计入辅助次数，并保存在 `baseline-results.json`。入口、依赖或正常种子检查失败时，任务会提示检查配置后重试。
- 回归结果区分“再次观察到相同失败签名”“此输入已正常处理或拒绝”“出现了不同的失败”“无法得出回归结论”。独立 `crashlens replay` 命令执行一次输入并返回分类；网页回归还会检查正常样例并比较原失败签名。
- 种子目录只读取第一层的 1–128 个文件，且必须在待测目录内。超大种子会被拒绝，不静默截断。
- JSON 结构化策略覆盖嵌套对象、数组元素及布尔/数值/字符串边界。遍历最多 256 个节点、32 层深度，每个容器最多探索前 64 个成员；超出部分仍可由通用字节变异探索。
- 正常种子和基础边界之后，结构化策略在种子与节点之间轮换，并按三个结构化尝试、一个字节尝试交错执行。重复或超限候选会被跳过，因此实际执行比例会变化；小预算下仍能探索不同种子和格式。
- `max_cases` 只计算生成用例，重放/缩减次数另外显示；`max_seconds` 覆盖整项任务，包括辅助执行。
- 输出监控是轮询阈值，磁盘输出可能短暂超过阈值；保留的文本按上限截断，不是磁盘硬配额。

## 命令行使用

```powershell
# 与网页相同的测试引擎
.\.venv\Scripts\python.exe -m crashlens run .\code\examples\datacraft-buggy

# 下载或找到 input.bin 后独立重放
.\.venv\Scripts\python.exe -m crashlens replay .\code\examples\datacraft-buggy .\input.bin
```

CLI 与网页使用同一数据目录时不能同时运行；网页已开启时，可给 CLI 加 `--data-dir .crashlens-cli`。CLI 重放读取目标目录当前配置；网页“原版本重放”使用任务配置快照，并检查命令中可识别源文件的哈希。哈希检查不覆盖整个依赖环境，因此严格复现还需要保留源码和依赖版本。

## 如何解读结果

| 分类 | 含义 |
| --- | --- |
| `passed` | 命中成功退出码，并且没有更强的崩溃证据 |
| `rejected` | 命中配置的正常拒绝码 |
| `exception` | 非零退出，stderr 中出现符合识别规则的 Python traceback |
| `crash` | POSIX 信号终止，或已识别的 Windows 原生崩溃状态 |
| `timeout` | 达到单次执行超时；不直接认定死循环或崩溃 |
| `abnormal_exit` | 未被约定或识别的非零退出，需要人工判断 |
| `output_limit` | 输出超过配置阈值 |
| `launch_error` / `runner_error` | 环境或执行器错误，中止任务 |
| `cancelled` | 用户停止或整项时间预算到期时中止当前用例 |

Python 异常通过非零退出码和标准错误中的 traceback 识别。排查时可以查看完整堆栈，并用保存的输入重放。

自动缩减在配置的次数预算内寻找更短的触发输入，每次接受的修改都保留原失败签名，最后再执行一次验证。JSON 输入通过删除字段或数组片段、缩短字符串、简化数值来缩减，并保持语法有效；其他输入使用字节片段删除。`minimization.method` 记录所用方法，遍历范围与 JSON 变异相同。自动缩减用于稳定的异常和崩溃；超时与普通异常退出保留原始输入供排查。

## 证据布局

```text
.crashlens/
├── index.sqlite3
└── jobs/<job-id>/
    ├── manifest.json        # 初始配置、环境、种子索引、源文件哈希
    ├── summary.json         # 最终统计
    ├── cases.jsonl          # 每个生成用例的策略、哈希、分类
    ├── seeds/               # 原始种子的字节快照
    └── findings/<signature>/
        ├── finding.json    # 首次结果、重放和缩减证据
        ├── input.bin       # 原始触发输入
        ├── minimized.bin   # 仅在缩减后验证通过时产生
        └── occurrences/    # 重复失败的原始输入及结果
```

普通通过/拒绝的用例保存紧凑日志；失败保存输出和输入。HTML 报告可以离线阅读，JSON 用于机器处理；字节输入需单独下载或连同本地证据目录保留。

也可以在任务详情点击 **完整证据 ZIP** 一次下载上述材料。运行中的任务暂不提供 ZIP，避免混入仍在写入的证据；停止或失败的任务也可打包已有证据。包内不含目标软件及其依赖，请另外保留对应版本。`manifest-sha256.json` 记录包内其他文件的长度与 SHA-256；打包上限为原始证据 256 MiB / 20000 文件，超过时请直接复制本地任务目录。

任务记录中的 `completion_reason` 区分用户停止、总时间预算耗尽、达到用例上限、输入集合耗尽和执行错误。正常种子执行期间被取消不会再被标记为种子校验失败。

## 验证与开发

```powershell
.\.venv\Scripts\python.exe -m pytest code\tests -q --basetemp=.pytest-tmp
```

重新生成缺陷/修复版本的独立验收证据：

```powershell
.\.venv\Scripts\python.exe code\scripts\verify_acceptance.py
.\.venv\Scripts\python.exe code\scripts\run_checks.py
```

验收脚本对两个版本各运行 80 个用例，并对每个失败分组额外重放和回归；结果保存在 `code/examples/acceptance/`。

测试覆盖原始字节与文件输入、退出码约定、异常签名、正常种子预检、超时、停止、进程树清理、输出限制、自动生成、输入缩减、修复版本、网页请求保护和后台任务。Windows 原生退出状态与 POSIX 信号测试按平台选择执行。

如果测试提示临时目录不存在，请用仓库根目录下的 `--basetemp=.pytest-tmp`，不要指定不存在的多层父目录。

核心模块：

| 文件 | 职责 |
| --- | --- |
| `config.py` | 配置校验、入口解析和种子检查 |
| `generators.py` | 通用输入生成 |
| `json_tools.py` / `minimizer.py` | 有界 JSON 遍历、结构化和字节输入缩减 |
| `process.py` / `_gate.py` | 进程启动、生命周期管理、日志收集和分类 |
| `engine.py` | 测试任务、归组、验证和缩减 |
| `manager.py` / `store.py` | 工作进程和 SQLite 索引 |
| `web.py` / `templates/` / `static/` | 本地网页及报告 |
| `cli.py` | 命令行入口和数据目录锁 |

Windows 使用等待门控的辅助进程，先加入 Job Object，再启动目标，避免目标在分配前创建子进程。清理时等待 Job 内成员退出。POSIX 使用独立会话的进程组；主动脱离进程组的恶意目标不在支持范围内。

网页服务在 Windows 上也使用 Job Object 约束工作进程：服务异常退出时，工作进程及其待测程序随之终止。工作进程先等待启动许可，避免在保护安装前执行目标。POSIX 工作进程通过专用管道感知服务退出并请求取消；重启服务时，如果旧工作进程尚未释放执行锁，会明确要求稍后重试。恢复检查覆盖全部历史任务，将遗留未完成任务标记为中断，保留已有证据。

## 作业交付结构

```text
readme.md          使用说明
code/              平台源码、测试、教学示例、辅助脚本
video/             实际操作录像与说明
prompt/            真实开发/调试对话及导出说明
LICENSE            MIT 开源许可证
.github/workflows/ 自动化测试配置
```

对话导出不包含系统提示、开发者提示或隐藏推理；保留用户与助手的可见交互以及可见工具调用/结果，见 [prompt/readme.md](prompt/readme.md)。

## 参考与实现依据

- [课程示例：android-testing-platform](https://github.com/jinglingsun/android-testing-platform)：参考“动态测试、捕获、报告、重放”的流程；本项目使用独立实现的 CLI 测试引擎。
- [Python subprocess 文档](https://docs.python.org/3/library/subprocess.html)：参数列表、原始字节 I/O 和进程退出状态。
- [Microsoft Job Objects 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)：Windows 进程组生命周期管理。
- [FastAPI Background Tasks 文档](https://fastapi.tiangolo.com/tutorial/background-tasks/)：本项目的长任务采用独立工作进程，不占用网页请求处理周期。

项目代码采用 [MIT License](LICENSE)。
