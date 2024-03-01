import pathlib
import click
from autoupdater import core


@click.command
@click.argument("requirements_file", type=str)
@click.argument("module", type=str)
def main(requirements_file: str, module: str) -> None:
    core.run(
        requirements_file=requirements_file,
        module=module,
        base_directory=pathlib.Path("."),
    )


main()
