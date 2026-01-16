import typer

from .cmd.default_config import cmd_default_config_app  # Import the Typer instance for the default-config command

# Import commands from the .cmd subpackage
from .cmd.generate import cmd_generate_app  # Import the Typer instance for the generate command
from .cmd.version import cmd_version_app  # Import the Typer instance for the version command

app = typer.Typer(
    help="A CLI tool for Hetzner Inventory.",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,  # More direct way to show help when no args/command
)

# Add the version Typer application as a subcommand named "version"
app.add_typer(cmd_version_app, name="version")

# Add the default-config Typer application as a subcommand named "default-config"
app.add_typer(cmd_default_config_app, name="default-config")

# Add the generate Typer application as a subcommand named "generate"
app.add_typer(cmd_generate_app, name="generate")


if __name__ == "__main__":
    app()
