from autoupdater import core, requirements


import pytest


import hashlib
from unittest import mock


class TestDigestFromRequirementsFile:
    def test_with_local_file(self, venv_spec: core.VenvSpec) -> None:
        digest = requirements.digest_from_requirements_file(venv_spec.requirements_file)

        assert (
            digest
            == hashlib.sha256(
                b"tests/data/some_package/dist/some_package-0.1.0-py3-none-any.whl"
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
            digest = requirements.digest_from_requirements_file(
                venv_spec.requirements_file
            )

        assert digest == hashlib.sha256(b"some-requirement==1.0.0").digest()

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
            digest = requirements.digest_from_requirements_file(
                venv_spec.requirements_file
            )

        assert digest == hashlib.sha256(b"some-requirement==1.0.0").digest()

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
            digest = requirements.digest_from_requirements_file(
                venv_spec.requirements_file
            )

        assert digest is None


class TestDiff:
    def test_no_new_requirements(self) -> None:
        requirements_content = (
            'unicorn==1.0.0 ; python_version >= "3.11" # some comment\n'
            'sparkle==1.0.0 ; python_version >= "3.11"\n'
            "pink==1.0.0 # some comment\n"
            "love-hearts==1.0.0\n"
        )
        pip_freeze_content = (
            "unicorn==1.0.0\n" "sparkle==1.0.0\n" "pink==1.0.0\n" "Love.Hearts==1.0.0\n"
        )

        remove, install = requirements.diff(pip_freeze_content, requirements_content)

        assert remove == []
        assert install == []

    def test_remove_bad_vibes(self) -> None:
        requirements_content = (
            'unicorn==1.0.0 ; python_version >= "3.11" # some comment\n'
            'sparkle==1.0.0 ; python_version >= "3.11"\n'
            "pink==1.0.0 # some comment\n"
            "hearts==1.0.0\n"
        )
        pip_freeze_content = (
            "unicorn==1.0.0\n"
            "sparkle==1.0.0\n"
            "pink==1.0.0\n"
            "hearts==1.0.0\n"
            "bad-vibes==1.0.0\n"
        )

        remove, install = requirements.diff(pip_freeze_content, requirements_content)

        assert remove == ["bad-vibes==1.0.0"]
        assert install == []

    def test_add_flair(self) -> None:
        requirements_content = (
            'flair==1.0.0 ; python_version >= "3.11" # some comment\n'
            'unicorn==1.0.0 ; python_version >= "3.11" # some comment\n'
            'sparkle==1.0.0 ; python_version >= "3.11"\n'
            "pink==1.0.0 # some comment\n"
            "hearts==1.0.0\n"
        )
        pip_freeze_content = (
            "unicorn==1.0.0\n" "sparkle==1.0.0\n" "pink==1.0.0\n" "hearts==1.0.0\n"
        )

        remove, install = requirements.diff(pip_freeze_content, requirements_content)

        assert remove == []
        assert install == ['flair==1.0.0 ; python_version >= "3.11"']
