import hashlib
import logging
from os import path
import shutil
import pathlib
import time
from typing import Any
from unittest import mock

import pytest
from autoupdater import core


DATA_DIR = pathlib.Path(path.dirname(__file__)) / "data"


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


class TestEnsureVenv:
    def test_happy_path(
        self, venv_spec: core.VenvSpec, base_directory: pathlib.Path
    ) -> None:
        venv = core.ensure_venv(venv_spec)

        assert path.isfile(venv.spec.python_path())
        assert path.isfile(venv.spec.pip_path())
        assert venv.spec.venv_dir() == base_directory / "venv"


class TestLoadRequirementsDigest:
    def test_with_local_file(self, venv_spec: core.VenvSpec) -> None:
        digest = core.load_requirements_digest(venv_spec.requirements_file)

        assert (
            digest
            == hashlib.sha256(
                b"tests/data/some_package/dist/some_package-0.1.0-py3-none-any.whl\n"
            ).digest()
        )

    @pytest.mark.parametrize(
        "requirements_file", ["https://www.example.com/requirements.txt"]
    )
    def test_with_remote_file(self, venv_spec: core.VenvSpec) -> None:
        with mock.patch(
            "requests.get",
            return_value=mock.Mock(
                status_code=200, content=b"some-requirement==1.0.0\n"
            ),
        ):
            digest = core.load_requirements_digest(venv_spec.requirements_file)

        assert digest == hashlib.sha256(b"some-requirement==1.0.0\n").digest()

    @pytest.mark.parametrize(
        "requirements_file", ["https://www.example.com/requirements.txt"]
    )
    def test_with_remote_file_error_9_times(self, venv_spec: core.VenvSpec) -> None:
        with mock.patch(
            "requests.get",
            side_effect=[
                mock.Mock(status_code=500, content=b"some-requirement==1.0.0\n"),
            ]
            * 9
            + [
                mock.Mock(status_code=200, content=b"some-requirement==1.0.0\n"),
            ],
        ):
            digest = core.load_requirements_digest(venv_spec.requirements_file)

        assert digest == hashlib.sha256(b"some-requirement==1.0.0\n").digest()

    @pytest.mark.parametrize(
        "requirements_file", ["https://www.example.com/requirements.txt"]
    )
    def test_with_remote_file_error(self, venv_spec: core.VenvSpec) -> None:
        with mock.patch(
            "requests.get",
            return_value=mock.Mock(
                status_code=500, content=b"some-requirement==1.0.0\n"
            ),
        ):
            digest = core.load_requirements_digest(venv_spec.requirements_file)

        assert digest is None


class TestInitVenv:
    def test_happy_path(
        self, requirements_file: str, base_directory: pathlib.Path
    ) -> None:
        venv = core.init_venv(requirements_file, base_directory)

        assert path.isfile(venv.spec.python_path())
        assert path.isfile(venv.spec.pip_path())
        assert venv.spec.venv_dir() == base_directory / "venv"


class TestRunProgramUntilDeadOrUpdated:
    @pytest.fixture
    def on_post_sleep(self, requirements_file: str) -> None:
        def _callback(seconds: float) -> None:
            with open(requirements_file, "a") as file_:
                file_.write("# force new hash")

        return _callback

    def test_update_on_requirement_file_changed(
        self, venv: core.Venv, module: str, caplog: Any
    ) -> None:
        caplog.set_level(logging.INFO)
        start = time.time()  # this is a frozen time!
        initial_digest = venv.state.installed_digest

        core.run_program_until_dead_or_updated(venv, module, 0.5, 1)

        assert "Update detected!" in [r.message for r in caplog.records]
        # This is essentially counting the calls to time.sleep because of the frozen time
        # The whole test is a little sketchy but seems to do the trick
        assert time.time() - start <= 2
        assert initial_digest != venv.state.installed_digest
