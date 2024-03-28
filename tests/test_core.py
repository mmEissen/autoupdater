import logging
from os import path
import shutil
import pathlib
import time
from typing import Any

import pytest
from autoupdater import core


class TestEnsureVenv:
    def test_happy_path(
        self, venv_spec: core.VenvSpec, base_directory: pathlib.Path
    ) -> None:
        venv = core.ensure_venv(venv_spec)

        assert path.isfile(venv.spec.python_path())
        assert path.isfile(venv.spec.pip_path())
        assert venv.spec.venv_dir() == base_directory / "venv"


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
                file_.write("# autoupdater-enforce-digest")

        return _callback

    def test_update_on_requirement_file_changed(
        self, venv: core.Venv, module: str, caplog: Any
    ) -> None:
        caplog.set_level(logging.INFO)
        start = time.time()  # this is a frozen time!
        initial_digest = venv.state.installed_digest

        new_digest = core.run_program_until_dead_or_updated(venv, module, [], 0.5, 1)

        assert "Update detected!" in [r.message for r in caplog.records]
        # This is essentially counting the calls to time.sleep because of the frozen time
        # The whole test is a little sketchy but seems to do the trick
        assert time.time() - start <= 2
        assert initial_digest != new_digest
