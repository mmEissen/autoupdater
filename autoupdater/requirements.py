import hashlib
import re
import time
from typing import Optional

import requests

import logging

log = logging.getLogger(__name__)


def diff(
    pip_freeze_content: str, requirements_content: str
) -> tuple[list[str], list[str]]:
    target_requirements = [
        (normalize_line(line), strip_line(line))
        for line in requirements_content.split("\n")
        if normalize_line(line)
    ]
    clean_target_requirements = [r[0] for r in target_requirements]
    installed_requirements = [
        normalize_line(line)
        for line in pip_freeze_content.split("\n")
        if normalize_line(line)
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


def digest_from_requirements_file(requirements_file: str) -> Optional[bytes]:
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

    text = data.decode("utf-8")

    def clean_line(line: str) -> bool:
        if line.startswith("# autoupdater-enforce-digest"):
            return line
        return strip_line(line)

    meaningful_lines = [clean_line(l) for l in text.split("\n") if clean_line(l)]
    data = "\n".join(meaningful_lines).encode("utf-8")

    return hashlib.sha256(data).digest()


def strip_line(line: str) -> str:
    """Remove comments and whitespaces from a requirements line"""
    return line.split("#", maxsplit=1)[0].strip()


def normalize_line(line: str) -> str:
    """normalize package name and remove conditions"""
    clean = strip_line(line).split(";", maxsplit=1)[0].strip()
    if "==" not in clean:
        return clean
    name, version = clean.split("==")
    normalized_name = re.sub(r"[-_.]+", "-", name).lower()
    return f"{normalized_name}=={version}"
