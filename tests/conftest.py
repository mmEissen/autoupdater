from os import path
import pathlib
import shutil
from typing import Callable
from unittest import mock
import freezegun
import pytest

from autoupdater import core


DATA_DIR = pathlib.Path(path.dirname(__file__)) / "data"


@pytest.fixture
def on_post_sleep() -> Callable[[float], None]:
    return lambda s: None


@pytest.fixture(autouse=True)
def frozen_time(on_post_sleep: Callable[[float], None]):
    def fake_sleep(seconds: float) -> None:
        frozen_time.tick(seconds)
        on_post_sleep(seconds)

    with freezegun.freeze_time("2019-01-01 10:01") as frozen_time, mock.patch(
        "time.sleep", new=fake_sleep
    ):
        yield frozen_time


@pytest.fixture
def requirements_file(tmp_path: pathlib.Path) -> str:
    shutil.copy(
        DATA_DIR / "some_package" / "requirements.txt", tmp_path / "requirements.txt"
    )
    return str(tmp_path / "requirements.txt")


@pytest.fixture
def module() -> str:
    return "some_package"


@pytest.fixture
def base_directory(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


@pytest.fixture
def venv_spec(requirements_file: str, base_directory: pathlib.Path) -> core.VenvSpec:
    return core.VenvSpec(
        requirements_file=requirements_file, base_directory=base_directory
    )


@pytest.fixture
def venv(requirements_file: str, base_directory: pathlib.Path) -> core.VenvSpec:
    return core.init_venv(requirements_file, base_directory)
