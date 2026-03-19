"""Tests for configuration loading."""

import os
import tempfile

import pytest

from bridge.config import ConfigError, load_config


def test_load_config_from_file():
    """Test loading configuration from a YAML file."""
    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: test-key
  timeout_seconds: 60

intercom:
  access_token: test-token

logging:
  level: DEBUG
  format: text

assistants:
  - playbook_id: test-playbook
    admin_id: test-admin
    rollout:
      percentage: 100
    routing_rules:
      - type: inbox
        inbox_id: test-inbox
    tracking_tag: __test
    handoff:
      actions:
        - type: add_tag
          tag_name: handoff
    fallback:
      actions:
        - type: transfer_to_inbox
          inbox_id: human-inbox
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        config = load_config(config_path)

        assert config.studio_chat.base_url == "https://api.studio.test"
        assert config.studio_chat.api_key == "test-key"
        assert config.studio_chat.timeout_seconds == 60
        assert config.intercom.access_token == "test-token"
        assert config.logging.level == "DEBUG"
        assert len(config.assistants) == 1
        assert config.assistants[0].playbook_id == "test-playbook"
    finally:
        os.unlink(config_path)


def test_load_config_with_env_var_interpolation():
    """Test that environment variables are interpolated."""
    os.environ["TEST_API_KEY"] = "secret-key-from-env"
    os.environ["TEST_TOKEN"] = "token-from-env"

    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: ${TEST_API_KEY}

intercom:
  access_token: ${TEST_TOKEN}

assistants: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        config = load_config(config_path)
        assert config.studio_chat.api_key == "secret-key-from-env"
        assert config.intercom.access_token == "token-from-env"
    finally:
        os.unlink(config_path)
        del os.environ["TEST_API_KEY"]
        del os.environ["TEST_TOKEN"]


def test_load_config_missing_file():
    """Test error when configuration file doesn't exist."""
    with pytest.raises(ConfigError) as exc_info:
        load_config("/nonexistent/config.yaml")

    assert "not found" in str(exc_info.value)


def test_load_config_invalid_yaml():
    """Test error when YAML is invalid."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("invalid: yaml: content: [")
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "Invalid YAML" in str(exc_info.value)
    finally:
        os.unlink(config_path)


def test_load_config_validation_error():
    """Test error when configuration doesn't match schema."""
    config_content = """
studio_chat:
  # Missing required fields
  timeout_seconds: 60

intercom:
  access_token: test

assistants: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "validation failed" in str(exc_info.value)
    finally:
        os.unlink(config_path)


def test_load_config_invalid_rollout_percentage_not_integer():
    """Test error when rollout percentage is not a valid integer."""
    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: test-key

intercom:
  access_token: test-token

assistants:
  - playbook_id: test-playbook
    admin_id: test-admin
    rollout:
      percentage: "not-a-number"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value)
        assert "not a valid integer" in error_msg
        assert "test-playbook" in error_msg
    finally:
        os.unlink(config_path)


def test_load_config_rollout_percentage_out_of_range():
    """Test error when rollout percentage is out of range."""
    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: test-key

intercom:
  access_token: test-token

assistants:
  - playbook_id: test-playbook
    admin_id: test-admin
    rollout:
      percentage: 150
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value)
        assert "out of range" in error_msg
        assert "0-100" in error_msg
    finally:
        os.unlink(config_path)


def test_load_config_missing_env_var():
    """Test error when environment variable is not set."""
    # Make sure the env var is not set
    os.environ.pop("MISSING_VAR_FOR_TEST", None)

    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: ${MISSING_VAR_FOR_TEST}

intercom:
  access_token: test-token

assistants: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value)
        assert "MISSING_VAR_FOR_TEST" in error_msg
        assert "environment variable" in error_msg.lower()
    finally:
        os.unlink(config_path)


def test_load_config_rollout_from_env_var():
    """Test that rollout percentage can be loaded from env var."""
    os.environ["TEST_ROLLOUT"] = "75"

    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: test-key

intercom:
  access_token: test-token

assistants:
  - playbook_id: test-playbook
    admin_id: test-admin
    rollout:
      percentage: ${TEST_ROLLOUT}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        config = load_config(config_path)
        assert config.assistants[0].rollout.percentage == 75
    finally:
        os.unlink(config_path)
        del os.environ["TEST_ROLLOUT"]


def test_load_config_rollout_env_var_not_set():
    """Test error when rollout env var is not set."""
    os.environ.pop("UNSET_ROLLOUT_VAR", None)

    config_content = """
studio_chat:
  base_url: https://api.studio.test
  api_key: test-key

intercom:
  access_token: test-token

assistants:
  - playbook_id: my-playbook
    admin_id: test-admin
    rollout:
      percentage: ${UNSET_ROLLOUT_VAR}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config_path = f.name

    try:
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value)
        assert "UNSET_ROLLOUT_VAR" in error_msg
    finally:
        os.unlink(config_path)
