import pathlib
import click
from autoupdater import core


@click.command
@click.argument("install_string", type=str)
@click.argument("module", type=str)
def main(install_string: str, module: str) -> None:
    core.run(install_string, pathlib.Path("."))


main()
