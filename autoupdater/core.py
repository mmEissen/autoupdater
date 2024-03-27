import contextlib
import hashlib
from os import path
import os
import pathlib
from typing import Callable, Iterator, Optional, TypeVar
import venv as venv_module
import subprocess
import logging
import tempfile
import re

import requests
import time
import dataclasses


log = logging.getLogger(__name__)


class BaseException(Exception):
    pass


_MIN_TIME_BETWEEN_ATTEMPTS = 10


@dataclasses.dataclass(
    frozen=True,
)
class VenvSpec:
    requirements_file: str
    base_directory: pathlib.Path

    def venv_dir(self) -> pathlib.Path:
        return self.base_directory / "venv"

    def pip_path(self) -> pathlib.Path:
        return self.venv_dir() / "bin" / "pip"

    def python_path(self) -> pathlib.Path:
        return self.venv_dir() / "bin" / "python"


@dataclasses.dataclass()
class VenvState:
    installed_digest: bytes = b""
    last_updated_timestamp: float = 0
    when_last_update_attempt: float = 0


@dataclasses.dataclass()
class Venv:
    spec: VenvSpec
    state: VenvState


@dataclasses.dataclass()
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
            log.exception(f"Unexpected error. Retrying in {delay} seconds")
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

    while True:
        try:
            new_digest = run_program_until_dead_or_updated(
                venv, module, args, duration_between_updates, termination_timeout
            )
        except Exception:
            log.exception("Unexpected error! Program will be restart shortly...")
            new_digest = retry_forever(lambda: maybe_new_requirements_digest(venv))
            retry_forever(lambda: ensure_digest_installed(venv, new_digest))
        else:
            if new_digest is not None:
                retry_forever(lambda: ensure_digest_installed(venv, new_digest))


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
) -> Optional[bytes]:
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
    command = [
        venv.spec.python_path().absolute(),
        "-u",
        "-m",
        module,
    ] + args
    log.info("Starting process '%s'", " ".join(str(arg) for arg in command))
    process = subprocess.Popen(command)
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


def maybe_new_requirements_digest(venv: Venv) -> Optional[bytes]:
    remote_digest = load_requirements_digest(venv.spec.requirements_file)
    if remote_digest != venv.state.installed_digest:
        return remote_digest
    return None


def diff_requirements(
    pip_freeze_content: str, requirements_content: str
) -> tuple[list[str], list[str]]:
    def no_comments(line: str) -> str:
        return line.split("#", maxsplit=1)[0].strip()

    def normalized(line: str) -> str:
        clean = no_comments(line).split(";", maxsplit=1)[0].strip()
        if "==" not in clean:
            return clean
        name, version = clean.split("==")
        normalized_name = re.sub(r"[-_.]+", "-", name).lower()
        return f"{normalized_name}=={version}"

    target_requirements = [
        (normalized(line), no_comments(line))
        for line in requirements_content.split("\n")
        if normalized(line)
    ]
    clean_target_requirements = [r[0] for r in target_requirements]
    installed_requirements = [
        normalized(line) for line in pip_freeze_content.split("\n") if normalized(line)
    ]
    requirements_to_remove = [
        line for line in installed_requirements if line not in clean_target_requirements
    ]

    requirements_to_install = [
        line
        for clean_requirement, line in target_requirements
        if clean_requirement not in installed_requirements
    ]
    return requirements_to_remove, requirements_to_install


def ensure_digest_installed(venv: Venv, target_digest: bytes) -> None:
    if target_digest == venv.state.installed_digest:
        return venv

    time_since_last_attempt = time.time() - venv.state.when_last_update_attempt
    if time_since_last_attempt < _MIN_TIME_BETWEEN_ATTEMPTS:
        time.sleep(_MIN_TIME_BETWEEN_ATTEMPTS - time_since_last_attempt)
    venv.state.when_last_update_attempt = time.time()

    log.info("Calculating requirements...")

    with open(venv.spec.requirements_file, "r") as f:
        requirements_content = f.read()

    pip_freeze = subprocess.run(
        [venv.spec.pip_path().absolute(), "freeze"],
        check=True,
        capture_output=True,
        text=True,
    )

    requirements_to_remove, requirements_to_install = diff_requirements(
        pip_freeze.stdout, requirements_content
    )

    log.info(
        "Remove:\n%s\n\nInstall:\n%s",
        "\n".join(requirements_to_remove),
        "\n".join(requirements_to_install),
    )

    if requirements_to_remove:
        # for some items the syntax is a bit different in requirements files so better to do it this way
        with tempfile.TemporaryDirectory() as tmp_dir:
            requirements_file = path.join(tmp_dir, "requirements.txt")
            with open(requirements_file, "w") as f:
                f.write("\n".join(requirements_to_remove))
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

    log.info("Installing new requirements...")
    if requirements_to_install:
        with tempfile.TemporaryDirectory() as tmp_dir:
            requirements_file = path.join(tmp_dir, "requirements.txt")
            with open(requirements_file, "w") as f:
                f.write("\n".join(requirements_to_install))
            subprocess.run(
                [
                    venv.spec.pip_path().absolute(),
                    "install",
                    "-r",
                    requirements_file,
                ],
                check=True,
            )

    # Technically we might have just installed something else than this digest
    # In that case the update will be triggered again, but will be mostly noop
    venv.state.installed_digest = target_digest
    venv.state.last_updated_timestamp = time.time()


def load_requirements_digest(requirements_file: str) -> Optional[bytes]:
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


def _load_file_from_web(requirements_file: str, retries: int = 10) -> Optional[bytes]:
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
