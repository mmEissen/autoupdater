import pathlib
import click
from autoupdater import core
import logging


@click.command
@click.argument(
    "requirements_file",
    type=str,
)
@click.argument("module", type=str)
@click.argument(
    "args",
    nargs=-1,
    type=str,
)
@click.option(
    "--interval",
    type=int,
    default=60 * 5,
    help="The (minimum) time between checks for updates",
)
@click.option(
    "--sigterm-timeout",
    type=int,
    default=5,
    help=(
        "If an update is available the running process will be sent a SIGTERM. Wait this many seconds before sending a SIGKILL."
    ),
)
def main(
    requirements_file: str,
    module: str,
    args: tuple[str, ...],
    interval: int,
    sigterm_timeout: int,
) -> None:
    logging.basicConfig(level=logging.INFO)
    core.run(
        requirements_file=requirements_file,
        module=module,
        args=list(args),
        base_directory=pathlib.Path("."),
        duration_between_updates=interval,
        termination_timeout=sigterm_timeout,
    )


main()
