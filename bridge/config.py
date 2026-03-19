"""Configuration loader with YAML parsing and environment variable interpolation.

Configuration Sources (in order of priority)
--------------------------------------------
1. CONFIG_YAML environment variable
   - Contains the raw YAML content directly
   - Useful for platforms like Railway, Render, Heroku where mounting files is difficult
   - Example: CONFIG_YAML='studio_chat:\\n  api_key: ${STUDIO_CHAT_API_KEY}\\n...'

2. CONFIG_PATH environment variable
   - Path to a YAML configuration file
   - Example: CONFIG_PATH=/etc/myapp/config.yaml

3. ./config.yaml (default)
   - Looks for config.yaml in the current working directory
   - Best for local development

Environment Variable Interpolation
----------------------------------
All string values in the YAML support ${VAR_NAME} syntax for environment variable
interpolation. This allows secrets to be kept in environment variables:

    studio_chat:
      api_key: ${STUDIO_CHAT_API_KEY}  # Replaced with env var value at load time

If a referenced environment variable is not set, configuration loading will fail
with a descriptive error message.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig


class ConfigError(Exception):
    """Raised when configuration loading fails."""

    pass


def _interpolate_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""
    pattern = r"\$\{([^}]+)\}"
    missing_vars: list[str] = []

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            missing_vars.append(var_name)
            return match.group(0)  # Keep original placeholder for error reporting
        return env_value

    result = re.sub(pattern, replacer, value)

    # If there are missing vars, we return the result with placeholders intact
    # This allows downstream validation to catch it with better context
    return result


def _check_missing_env_vars(obj: Any, path: str = "") -> list[str]:
    """Find any unresolved ${VAR} patterns in the config."""
    missing: list[str] = []
    pattern = r"\$\{([^}]+)\}"

    if isinstance(obj, dict):
        for key, value in obj.items():
            new_path = f"{path}.{key}" if path else key
            missing.extend(_check_missing_env_vars(value, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            missing.extend(_check_missing_env_vars(item, f"{path}[{i}]"))
    elif isinstance(obj, str):
        matches = re.findall(pattern, obj)
        for var_name in matches:
            missing.append(f"{path}: ${{{var_name}}} (environment variable not set)")

    return missing


def _process_config_values(
    obj: dict[str, Any] | list[Any] | str | int | float | bool | None,
) -> dict[str, Any] | list[Any] | str | int | float | bool | None:
    """Recursively process config values to interpolate environment variables."""
    if isinstance(obj, dict):
        return {key: _process_config_values(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_process_config_values(item) for item in obj]
    elif isinstance(obj, str):
        return _interpolate_env_vars(obj)
    else:
        return obj


def _validate_and_convert_rollout(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and convert rollout percentages after env var interpolation."""
    assistants = config.get("assistants", [])

    for i, assistant in enumerate(assistants):
        playbook_id = assistant.get("playbook_id", f"assistant[{i}]")
        rollout = assistant.get("rollout", {})

        if "percentage" in rollout:
            value = rollout["percentage"]

            # Check for unresolved env var
            if isinstance(value, str) and "${" in value:
                raise ConfigError(
                    f"Assistant '{playbook_id}': rollout.percentage references "
                    f"unset environment variable: {value}"
                )

            # Convert string to int
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    raise ConfigError(
                        f"Assistant '{playbook_id}': rollout.percentage is empty. "
                        f"Must be an integer 0-100."
                    )
                try:
                    value = int(value)
                    rollout["percentage"] = value
                except ValueError:
                    raise ConfigError(
                        f"Assistant '{playbook_id}': rollout.percentage '{value}' "
                        f"is not a valid integer. Must be 0-100."
                    )

            # Validate range
            if isinstance(value, int):
                if value < 0 or value > 100:
                    raise ConfigError(
                        f"Assistant '{playbook_id}': rollout.percentage {value} "
                        f"is out of range. Must be 0-100."
                    )

    return config


def _format_validation_error(error: ValidationError) -> str:
    """Format Pydantic validation errors into human-readable messages."""
    messages: list[str] = []

    for err in error.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = err["msg"]
        messages.append(f"  - {loc}: {msg}")

    return "Configuration validation failed:\n" + "\n".join(messages)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from YAML.

    Configuration is loaded from (in order of priority):
    1. CONFIG_YAML environment variable (raw YAML content)
    2. config_path argument or CONFIG_PATH environment variable (file path)
    3. ./config.yaml (default file path)

    Args:
        config_path: Path to the configuration file. If not provided, checks
                    CONFIG_YAML env var first, then CONFIG_PATH, then ./config.yaml

    Returns:
        Validated AppConfig object

    Raises:
        ConfigError: If configuration is not found or invalid
    """
    raw_config: dict[str, Any] | None = None
    config_source: str = ""

    # Priority 1: CONFIG_YAML environment variable (raw YAML content)
    config_yaml_env = os.environ.get("CONFIG_YAML")
    if config_yaml_env:
        try:
            raw_config = yaml.safe_load(config_yaml_env)
            config_source = "CONFIG_YAML environment variable"
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in CONFIG_YAML environment variable: {e}") from e

    # Priority 2 & 3: File path (argument, CONFIG_PATH env, or default)
    if raw_config is None:
        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", "./config.yaml")

        path = Path(config_path)
        config_source = str(path)

        if not path.exists():
            raise ConfigError(
                f"Configuration file not found: {path}\n"
                "You can provide configuration via:\n"
                "  1. CONFIG_YAML environment variable (raw YAML content)\n"
                "  2. CONFIG_PATH environment variable (path to YAML file)\n"
                "  3. ./config.yaml file in the current directory"
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in configuration file: {e}") from e

    if raw_config is None:
        raise ConfigError(f"Configuration is empty (source: {config_source})")

    if not isinstance(raw_config, dict):
        raise ConfigError(
            f"Configuration must be a YAML mapping/dictionary, got {type(raw_config).__name__} "
            f"(source: {config_source}). First 200 chars: {str(raw_config)[:200]}"
        )

    # Process environment variable interpolation
    processed_config = _process_config_values(raw_config)
    assert isinstance(processed_config, dict)  # guaranteed since raw_config is dict

    # Check for missing environment variables
    missing_vars = _check_missing_env_vars(processed_config)
    if missing_vars:
        raise ConfigError(
            "Missing required environment variables:\n  - " + "\n  - ".join(missing_vars)
        )

    # Validate and convert rollout percentages
    processed_config = _validate_and_convert_rollout(processed_config)

    try:
        return AppConfig.model_validate(processed_config)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(e)) from e


def get_config() -> AppConfig:
    """
    Get the application configuration.

    This is a convenience function that loads the configuration from the default path.
    For production use, consider caching the result.

    Returns:
        Validated AppConfig object
    """
    return load_config()
