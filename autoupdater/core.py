import contextlib
import hashlib
from os import path
import os
import pathlib
from typing import Iterator
import venv as venv_module
import subprocess
import logging

import requests
import time
import dataclasses


log = logging.getLogger(__name__)


class BaseException(Exception):
    pass


@dataclasses.dataclass(frozen=True, kw_only=True)
class VenvSpec:
    requirements_file: str
    base_directory: pathlib.Path

    def venv_dir(self) -> pathlib.Path:
        return self.base_directory / "venv"

    def pip_path(self) -> pathlib.Path:
        return self.venv_dir() / "bin" / "pip"

    def python_path(self) -> pathlib.Path:
        return self.venv_dir() / "bin" / "python"


@dataclasses.dataclass(kw_only=True)
class VenvState:
    installed_digest: bytes = b""
    last_updated_timestamp: float = 0


@dataclasses.dataclass(kw_only=True)
class Venv:
    spec: VenvSpec
    state: VenvState


@dataclasses.dataclass(kw_only=True)
class Program:
    process: subprocess.Popen
    venv: Venv
    when_last_update_check: float

    def is_running(self) -> bool:
        return self.process.poll() is None

    def stop(self, time_before_kill: float) -> None:
        log.info("Terminating program...")
        self.process.terminate()
        try:
            self.process.communicate(timeout=time_before_kill)
        except subprocess.TimeoutExpired:
            log.info("Program did not respond to SIGTERM, using SIGKILL...")
            self.process.kill()
            self.process.communicate()
            log.info("Program killed!")
        else:
            log.info("Program terminated successfully!")


def run(
    *,
    requirements_file: str,
    module: str,
    args: list[str],
    base_directory: pathlib.Path,
    duration_between_updates: float,
    termination_timeout: float = 30,
) -> None:
    venv = init_venv(requirements_file, base_directory)

    while True:
        try:
            run_program_until_dead_or_updated(
                venv, module, args, duration_between_updates, termination_timeout
            )
        except Exception:
            log.exception("Unexpected error! Program will be restart shortly...")


def init_venv(requirements_file: str, base_directory: pathlib.Path):
    venv_spec = VenvSpec(
        requirements_file=requirements_file, base_directory=base_directory
    )
    venv = ensure_venv(venv_spec)
    new_digest = maybe_new_requirements_digest(venv)
    ensure_digest_installed(venv, new_digest)
    return venv


def run_program_until_dead_or_updated(
    venv: Venv,
    module: str,
    args: list[str],
    duration_between_updates: float,
    termination_timeout: float,
) -> None:
    with launch(venv, module, args) as program:
        while program.is_running():
            if time.time() - program.when_last_update_check > duration_between_updates:
                program.when_last_update_check = time.time()
                if (new_digest := maybe_new_requirements_digest(venv)) is not None:
                    log.info("Update detected!")
                    program.stop(termination_timeout)
                    ensure_digest_installed(venv, new_digest)
                    return
            time.sleep(1)


@contextlib.contextmanager
def launch(
    venv: Venv,
    module: str,
    args: list[str],
) -> Iterator[Program]:
    process = subprocess.Popen(
        [
            venv.spec.python_path().absolute(),
            "-m",
            module,
        ]
        + args
    )
    program = Program(
        process=process,
        venv=venv,
        when_last_update_check=venv.state.last_updated_timestamp,
    )
    yield program
    if program.is_running:
        program.process.kill()


def ensure_venv(venv_spec: VenvSpec) -> Venv:
    if not path.isdir(venv_spec.venv_dir()):
        log.info("Creating new venv in %s", venv_spec.venv_dir())
        return _create_venv(venv_spec)
    if not path.isdir(venv_spec.pip_path()):
        log.info(
            "Found a venv in %s, but it is missing pip. Recreating",
            venv_spec.venv_dir(),
        )
        return _recreate_venv(venv_spec)
    log.info("Using existing venv in %s", venv_spec.venv_dir())
    return Venv(
        spec=venv_spec,
        state=VenvState(),
    )


def _create_venv(venv_spec: VenvSpec) -> Venv:
    venv_module.create(venv_spec.venv_dir().absolute(), with_pip=True)
    return Venv(spec=venv_spec, state=VenvState())


def _recreate_venv(venv_spec: VenvSpec) -> Venv:
    # Weak form of what should be shutil.rmtree. But because that is a bit dangerous
    # and should probably be behind a `--force-venv` flag or something I will only
    # delete empty directories for now...
    os.rmdir(venv_spec.venv_dir().absolute())
    return _create_venv(venv_spec)


def maybe_new_requirements_digest(venv: Venv) -> bytes | None:
    remote_digest = load_requirements_digest(venv.spec.requirements_file)
    if remote_digest != venv.state.installed_digest:
        return remote_digest
    return None


def ensure_digest_installed(venv: Venv, target_digest: bytes) -> None:
    if target_digest == venv.state.installed_digest:
        return venv
    log.info("Installing requirements...")
    subprocess.run(
        [
            venv.spec.pip_path().absolute(),
            "install",
            "-r",
            venv.spec.requirements_file,
        ],
        check=True,
    )
    # Technically the requirements_to_install might be out of date at this point.
    # However this will at worst result in another automatic no-op update later.
    venv.state.installed_digest = target_digest
    venv.state.last_updated_timestamp = time.time()


def load_requirements_digest(requirements_file: str) -> bytes | None:
    if requirements_file.startswith("https://") or requirements_file.startswith(
        "http://"
    ):
        data = _load_file_from_web(requirements_file)
    else:
        try:
            with open(requirements_file, "rb") as file_:
                data = file_.read()
        except OSError:
            data = None
    if data is None:
        return None
    return hashlib.sha256(data).digest()


def _load_file_from_web(requirements_file: str, retries: int = 10) -> bytes | None:
    for try_ in range(retries):
        response = requests.get(requirements_file)
        if response.status_code == 200:
            break
        time.sleep(30)
    else:
        log.error(
            "Could not load the requirements from %s: Status code %s",
            requirements_file,
            response.status_code,
        )
        return None
    return response.content
