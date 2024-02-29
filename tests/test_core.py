from os import path
import os
import pathlib

import pytest
from autoupdater import core


DATA_DIR = pathlib.Path(path.dirname(__file__)) / "data"


class TestCreateVenv:
    def test_happy_path(self, tmp_path: pathlib.Path) -> None:
        venv_path = core.create_venv(tmp_path)

        assert path.isfile(tmp_path / "venv" / "bin" / "pip")
        assert venv_path == tmp_path / "venv"


class TestInstallPackage:
    @pytest.fixture
    def venv_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
        return core.create_venv(tmp_path)

    @staticmethod
    def _find_site_packages(venv_path: pathlib.Path) -> pathlib.Path:
        lib_path = venv_path / "lib"
        subdirs = os.listdir(lib_path)
        assert len(subdirs) == 1
        return lib_path / subdirs[0] / "site-packages"

    def test_happy_path(self, venv_path: pathlib.Path) -> None:
        whl_filename = (
            DATA_DIR / "some_package" / "dist" / "some_package-0.1.0-py3-none-any.whl"
        )
        core.install_package(whl_filename, venv_path)

        site_packages = self._find_site_packages(venv_path)
        assert path.isfile(site_packages / "some_package.py")
