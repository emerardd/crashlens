from pathlib import Path

import pytest

from crashlens.config import Config, Fuzz, Target


@pytest.fixture
def examples():
    return Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def make_target(tmp_path):
    def make(source, **options):
        path = tmp_path / "target.py"
        path.write_text(source, encoding="utf-8")
        config = Config(target=Target(command=["{python}", "target.py"], **options),
                        fuzz=Fuzz(minimize=False))
        return tmp_path, config
    return make

