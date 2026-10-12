# 实际验收结果

验证时间：2026-10-10T05:08:51+00:00

该文件由 `code/scripts/verify_acceptance.py` 根据真实执行结果生成。教学缺陷是人工设置的。公开 JSON 中的项目绝对路径替换为 `<PROJECT_ROOT>`，本地原始证据保持不变。

| 目标 | 生成用例 | 正常通过 | 正常拒绝 | 异常 | 超时 | 失败分组 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 缺陷版本 | 80 | 20 | 43 | 15 | 2 | 6 |
| 修复版本 | 80 | 20 | 60 | 0 | 0 | 0 |

每个失败分组都使用代表输入（优先已验证缩减版本）进行了额外独立重放，并在修复版本上执行同一输入。

| 分组 | 类别 | 原始 / 缩减字节 | 原版本重放 | 修复版本 |
| --- | --- | ---: | --- | --- |
| `05ec7f07e5dca637` | exception | 37 / 22 | exception，签名一致 | rejected |
| `1cd8163c0f63a499` | exception | 2 / 2 | exception，签名一致 | rejected |
| `23216176627c06ae` | exception | 37 / 21 | exception，签名一致 | rejected |
| `6690b541ed7de1ee` | exception | 52 / 51 | exception，签名一致 | rejected |
| `876097aa3cbe688e` | exception | 54 / 54 | exception，签名一致 | rejected |
| `f77d1bb58da886e3` | timeout | 48 / — | timeout，签名一致 | rejected |

完整配置、环境、源文件哈希、首次堆栈、自动重放、缩减验证和独立回归结果见 [acceptance.json](acceptance.json)。原始输入与缩减输入在 `inputs/<signature>/`。

复现示例（仓库根目录，替换实际 signature）：

```powershell
.\.venv\Scripts\python.exe -m crashlens replay .\code\examples\datacraft-buggy .\code\examples\acceptance\inputs\<signature>\input.bin --data-dir .crashlens-cli
```

本批用例的结果见上表。失败按异常类型和调用位置归组，可结合触发输入排查具体原因。
