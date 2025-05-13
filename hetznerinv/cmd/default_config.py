import collections.abc
from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any

import typer

# Attempt to import yaml and handle ImportError
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from hetznerinv.config import HetznerConfigSchema


def _deep_merge_dicts(
    base_dict: MutableMapping[Any, Any], update_dict: MutableMapping[Any, Any]
) -> MutableMapping[Any, Any]:
    """
    Deeply merges update_dict into base_dict.
    The base_dict is modified in place.
    """
    for key, value in update_dict.items():
        if isinstance(value, collections.abc.Mapping):
            base_dict[key] = _deep_merge_dicts(base_dict.get(key, {}), value)  # type: ignore
        else:
            base_dict[key] = value
    return base_dict


cmd_default_config_app = typer.Typer(
    help="Display the application configuration in YAML format. Can merge with an existing config file.",
    add_completion=False,
)


@cmd_default_config_app.callback(invoke_without_command=True)
def default_config_main(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help=(
                "Path to an existing YAML configuration file. Its values will be merged with and override the defaults."
            ),
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
):
    """
    Prints the application configuration to stdout in YAML format.
    If --config is provided, merges the specified file's values with the defaults.
    """
    if ctx.invoked_subcommand is not None:
        return

    if yaml is None:
        typer.secho(
            "Error: PyYAML is required to output the configuration. "
            "Please install it (e.g., 'pip install pyyaml' or 'poetry add pyyaml').",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 1. Get programmatic defaults as a JSON-like dictionary.
    # This also considers environment variables if HetznerConfigSchema is a BaseSettings model.
    try:
        default_settings_instance = HetznerConfigSchema()
        # mode='json' ensures complex types are dict/list/primitive compatible for merging & YAML
        current_config_dict = default_settings_instance.model_dump(mode="json")
    except Exception as e:
        typer.secho(f"Error initializing default configuration: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if config_path:
        loaded_user_config: dict[str, Any] | None = None
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded_user_config = yaml.safe_load(f)

            if loaded_user_config is not None:
                if not isinstance(loaded_user_config, dict):
                    typer.secho(
                        f"Error: Configuration file '{config_path}' must contain a YAML mapping (dictionary).",
                        fg=typer.colors.RED,
                        err=True,
                    )
                    raise typer.Exit(code=1)
                # 2. Deep merge user's config into the current config dict (which started as defaults)
                # Make a copy to avoid modifying the original dict in-place if it's used elsewhere (good practice).
                current_config_dict = _deep_merge_dicts(current_config_dict.copy(), loaded_user_config)
            # If loaded_user_config is None (e.g., empty file), current_config_dict remains as it was (defaults).
        except yaml.YAMLError as e:
            typer.secho(f"Error parsing YAML from '{config_path}': {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from e
        except FileNotFoundError:  # Should be caught by typer.Option(exists=True) but as a fallback.
            typer.secho(f"Error: Configuration file not found at '{config_path}'.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from None
        except Exception as e:  # Catch other potential file I/O or unexpected errors
            typer.secho(f"Error processing configuration file '{config_path}': {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from e

    try:
        # 3. Create final instance from the (potentially merged) dictionary.
        # This step also validates the merged structure against the Pydantic model.
        final_config_instance = HetznerConfigSchema.model_validate(current_config_dict)
    except Exception as e:  # Catch Pydantic validation errors
        typer.secho(f"Error validating final configuration data: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    # Convert the validated Pydantic model instance to a dictionary suitable for YAML dumping.
    # mode='json' is generally good for ensuring serializable types.
    config_dict_to_dump = final_config_instance.model_dump(mode="json")

    try:
        # Dump the dictionary to YAML format
        yaml_output = yaml.dump(config_dict_to_dump, sort_keys=False, indent=2, allow_unicode=True)
        typer.echo(yaml_output)
    except Exception as e:
        typer.secho(f"Error generating YAML output: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
