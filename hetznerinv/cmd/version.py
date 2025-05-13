import json
from enum import Enum
from typing import Annotated

import typer

# Relative import for VERSION from the parent package
from ..version import VERSION

# Attempt to import yaml and handle ImportError for _echo_yaml_output
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
    yaml = "yaml"


def _echo_text_output(all_info_flag: bool) -> None:
    if all_info_flag:
        typer.echo(VERSION.text())
    else:
        typer.echo(str(VERSION.app_version))


def _echo_json_output(all_info_flag: bool) -> None:
    if all_info_flag:
        data_to_display = VERSION.to_dict()
    else:
        data_to_display = {"version": str(VERSION.app_version)}
    typer.echo(json.dumps(data_to_display, indent=2))


def _echo_yaml_output(all_info_flag: bool) -> None:
    # Relies on the module-level 'yaml' import which is either the real module or None
    if yaml is None:
        typer.secho(
            "Error: PyYAML is required for YAML output. "
            "Please install it (e.g., 'pip install pyyaml' or 'poetry add pyyaml --group dev').",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from None

    if all_info_flag:
        data_to_display = VERSION.to_dict()
    else:
        data_to_display = {"version": str(VERSION.app_version)}
    typer.echo(yaml.dump(data_to_display, sort_keys=False))


# This Typer instance will be added to the main application.
cmd_version_app = typer.Typer(
    help="Display the application version.",
    add_completion=False,  # Inherit from the main app or set as needed
)


@cmd_version_app.callback(invoke_without_command=True)
def version_main(
    ctx: typer.Context,
    all_info: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Display all version information (includes Python, system, and git SHA).",
        ),
    ] = False,
    output: Annotated[
        OutputFormat | None,
        typer.Option(
            "--output",
            "-o",
            help="Output format. If --all is used, defaults to 'json'. Otherwise, defaults to 'text'.",
            case_sensitive=False,
        ),
    ] = None,
):
    """
    Display the application version.
    """
    if ctx.invoked_subcommand is not None:
        return  # Should not happen if no subcommands are added to cmd_version_app

    effective_output_format: OutputFormat
    if output is None:
        effective_output_format = OutputFormat.json if all_info else OutputFormat.text
    else:
        effective_output_format = output

    if effective_output_format == OutputFormat.text:
        _echo_text_output(all_info)
    elif effective_output_format == OutputFormat.json:
        _echo_json_output(all_info)
    elif effective_output_format == OutputFormat.yaml:
        _echo_yaml_output(all_info)
    else:
        # This case should ideally not be reached if Typer's enum validation works,
        # but as a fallback for exhaustiveness.
        typer.secho(
            f"Internal error: Unexpected output format '{effective_output_format}'. "
            "Choose from 'text', 'json', 'yaml'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
