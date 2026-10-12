from __future__ import annotations

import hashlib
import shutil
import sys
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


class Target(BaseModel):
    command: list[str] = Field(min_length=1, max_length=64)
    input_mode: str = "stdin"
    timeout_seconds: float = Field(default=1.5, ge=0.1, le=60)
    success_codes: list[int] = Field(default_factory=lambda: [0])
    reject_codes: list[int] = Field(default_factory=lambda: [2])
    max_output_bytes: int = Field(default=262144, ge=1024, le=10485760)
    input_suffix: str = ".bin"

    @field_validator("input_mode")
    @classmethod
    def mode(cls, value):
        if value not in {"stdin", "file"}:
            raise ValueError("input_mode 必须是 stdin 或 file")
        return value

    @field_validator("command")
    @classmethod
    def args(cls, value):
        if any(not arg or "\x00" in arg for arg in value):
            raise ValueError("命令参数不能为空或包含 NUL")
        return value

    @field_validator("input_suffix")
    @classmethod
    def suffix(cls, value):
        if not value.startswith(".") or len(value) > 16 or any(c in value for c in '/\\:'):
            raise ValueError("input_suffix 应为 .json 等扩展名")
        return value

    @model_validator(mode="after")
    def validate_codes(self):
        if set(self.success_codes) & set(self.reject_codes):
            raise ValueError("成功退出码与正常拒绝退出码不能重叠")
        if self.input_mode == "file" and not any("{input_file}" in a for a in self.command):
            raise ValueError("文件输入模式的 command 需要 {input_file} 占位符")
        return self


class Fuzz(BaseModel):
    seed_directory: str = "seeds"
    max_cases: int = Field(default=80, ge=1, le=10000)
    random_seed: int = 42
    max_input_bytes: int = Field(default=16384, ge=1, le=1048576)
    max_seconds: float = Field(default=120, ge=1, le=3600)
    minimize: bool = True
    minimize_attempts: int = Field(default=16, ge=0, le=200)


class Config(BaseModel):
    target: Target
    fuzz: Fuzz = Field(default_factory=Fuzz)


def load_config(directory: str, override: dict | None = None) -> tuple[Path, Config]:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("待测软件目录不存在")
    if override is not None:
        data = override
    else:
        path = root / "crashlens.toml"
        if not path.is_file():
            raise ValueError("目录没有 crashlens.toml，请在网页填写配置")
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    config = Config.model_validate(data)
    return root, config


def resolve_command(root: Path, config: Config, input_file: Path) -> list[str]:
    args = [a.replace("{python}", sys.executable).replace("{input_file}", str(input_file))
            for a in config.target.command]
    candidate = root / args[0]
    exe = str(candidate.resolve()) if candidate.is_file() else shutil.which(args[0])
    if not exe:
        raise ValueError(f"找不到可执行程序：{args[0]}")
    if Path(exe).suffix.lower() in {".bat", ".cmd", ".ps1"}:
        raise ValueError("请直接指定解释器或可执行文件，不接受 shell 脚本作为可执行入口")
    args[0] = exe
    return args


def seed_files(root: Path, config: Config) -> list[Path]:
    folder = (root / config.fuzz.seed_directory).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("种子目录必须位于待测软件目录内")
    if not folder.is_dir():
        raise ValueError("种子目录不存在，请至少提供一个正常样例")
    files = sorted(p for p in folder.iterdir() if p.is_file())
    if not files or len(files) > 128:
        raise ValueError("种子目录需要包含 1–128 个文件")
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ValueError("种子文件不能链接到软件目录以外")
        if path.stat().st_size > config.fuzz.max_input_bytes:
            raise ValueError(f"种子文件超过输入大小限制：{path.name}")
    return files


def inspect_directory(directory: str) -> dict:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("目录不存在")
    path = root / "crashlens.toml"
    config = load_config(str(root))[1].model_dump() if path.is_file() else None
    candidates = [p.name for p in sorted(root.iterdir())
                  if p.is_file() and p.suffix.lower() in {".py", ".exe"}][:30]
    return {"directory": str(root), "config": config, "candidates": candidates}


def source_hashes(root: Path, config: Config) -> dict:
    result = {}
    for arg in config.target.command:
        path = root / arg
        if path.is_file() and path.stat().st_size <= 10 * 1024 * 1024:
            result[arg] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

