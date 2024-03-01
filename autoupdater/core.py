from os import path
import os
import pathlib
import venv
import subprocess


class BaseException(Exception):
    pass


def run(*, requirements_file: str, module: str, base_directory: pathlib.Path) -> None:
    get_venv()
    if requirements_file.startswith("https://") or requirements_file.startswith(
        "http://"
    ):
        requirements_path = download_requirements(requirements_file)
    else:
        requirements_path = pathlib.Path(requirements_file)


def get_venv(base_directory: pathlib.Path) -> pathlib.Path:
    venv_path = _venv_path(base_directory)
    if not path.isdir(venv_path):
        return create_venv(base_directory)
    if not path.isdir(_pip_bin(venv_path)):
        return recreate_venv(base_directory)
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


def install_package(requirements_path: pathlib.Path, venv: pathlib.Path) -> None:
    subprocess.run(
        [_pip_bin(venv).absolute(), "install", "-r", requirements_path.absolute()],
        cwd=path.dirname(requirements_path.absolute()),
    )


def download_requirements(requirements_url: str) -> pathlib.Path:
    pass
