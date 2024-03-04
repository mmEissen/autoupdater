from typing import Callable
from unittest import mock
import freezegun
import pytest


@pytest.fixture
def on_post_sleep() -> Callable[[float], None]:
    return lambda s: None


@pytest.fixture(autouse=True)
def frozen_time(on_post_sleep: Callable[[float], None]):
    def fake_sleep(seconds: float) -> None:
        frozen_time.tick(seconds)
        on_post_sleep(seconds)

    with freezegun.freeze_time("2019-01-01 10:01") as frozen_time, mock.patch(
        "time.sleep", new=fake_sleep
    ):
        yield frozen_time
