import contextlib
import hashlib
from os import path
import os
import pathlib
from typing import Callable, Iterator, ParamSpec, TypeVar
import venv as venv_module
import subprocess
import logging
import tempfile

import requests
import time
import dataclasses


log = logging.getLogger(__name__)


class BaseException(Exception):
    pass


_MIN_TIME_BETWEEN_ATTEMPTS = 10


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
    when_last_update_attempt: float = 0


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


R = TypeVar("R")


def retry_forever(fn: Callable[[], R], delay: int = _MIN_TIME_BETWEEN_ATTEMPTS) -> R:
    while True:
        try:
            return fn()
        except Exception:
            time.sleep(delay)


def run(
    *,
    requirements_file: str,
    module: str,
    args: list[str],
    base_directory: pathlib.Path,
    duration_between_updates: float,
    termination_timeout: float = 30,
) -> None:
    venv = retry_forever(lambda: init_venv(requirements_file, base_directory))

    def loop() -> None:
        try:
            new_digest = run_program_until_dead_or_updated(
                venv, module, args, duration_between_updates, termination_timeout
            )
        except Exception:
            log.exception("Unexpected error! Program will be restart shortly...")
            new_digest = maybe_new_requirements_digest(venv)
            ensure_digest_installed(venv, new_digest)
        else:
            if new_digest is not None:
                ensure_digest_installed(venv, new_digest)

    retry_forever(loop)


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
) -> bytes | None:
    with launch(venv, module, args) as program:
        while program.is_running():
            if time.time() - program.when_last_update_check > duration_between_updates:
                program.when_last_update_check = time.time()
                if (new_digest := maybe_new_requirements_digest(venv)) is not None:
                    log.info("Update detected!")
                    program.stop(termination_timeout)
                    return new_digest
            time.sleep(1)
        log.info("Process completed, restarting")


@contextlib.contextmanager
def launch(
    venv: Venv,
    module: str,
    args: list[str],
) -> Iterator[Program]:
    log.info("Starting process")
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
    if not path.isfile(venv_spec.pip_path()):
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
    log.info("Uninstalling old requirements...")
    pip_freeze = subprocess.run(
        [venv.spec.pip_path().absolute(), "freeze"],
        check=True,
        capture_output=True,
    )
    if pip_freeze.stdout:
        with tempfile.TemporaryDirectory() as tmp_dir:
            requirements_file = path.join(tmp_dir, "requirements.txt")
            with open(requirements_file, "wb") as f:
                f.write(pip_freeze.stdout)
            subprocess.run(
                [
                    venv.spec.pip_path().absolute(),
                    "uninstall",
                    "-r",
                    requirements_file,
                    "-y",
                ],
                check=True,
            )

    time_since_last_attempt = time.time() - venv.state.when_last_update_attempt
    if time_since_last_attempt < _MIN_TIME_BETWEEN_ATTEMPTS:
        time.sleep(_MIN_TIME_BETWEEN_ATTEMPTS - time_since_last_attempt)
    venv.state.when_last_update_attempt = time.time()

    log.info("Installing new requirements...")
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
