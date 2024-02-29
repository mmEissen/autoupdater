from os import path
import os
import pathlib
import venv
import subprocess


class BaseException(Exception):
    pass


class VenvNotFound(BaseException):
    pass


class VenvBroken(BaseException):
    pass


def run(install_string: str, module: str, base_directory: pathlib.Path) -> None:
    try:
        venv = get_venv(base_directory)
    except VenvNotFound:
        venv = create_venv(base_directory)
    except VenvBroken:
        venv = recreate_venv(base_directory)


def get_venv(base_directory: pathlib.Path) -> pathlib.Path:
    venv_path = _venv_path(base_directory)
    if not path.isdir(venv_path):
        raise VenvNotFound()
    if not path.isdir(_pip_bin(venv_path)):
        raise VenvBroken()
    return venv_path


def create_venv(base_directory: pathlib.Path) -> pathlib.Path:
    venv_path = _venv_path(base_directory)
    venv.create(venv_path.absolute(), with_pip=True)
    return venv_path


def recreate_venv(base_directory: pathlib.Path) -> pathlib.Path:
    # Weak form of what should be shutil.rmtree. But because that is a bit dangerous
    # and should probably be behind a `--force-venv` flag or something I will only
    # delete empty directories for now...
    os.rmdir(_venv_path(base_directory))
    return create_venv(base_directory)


def _venv_path(base_directory: pathlib.Path) -> pathlib.Path:
    return base_directory / "venv"


def _pip_bin(venv: pathlib.Path) -> pathlib.Path:
    return venv / "bin" / "pip"


def install_package(install_string: str, venv: pathlib.Path) -> None:
    subprocess.run([_pip_bin(venv).absolute(), "install", install_string])
