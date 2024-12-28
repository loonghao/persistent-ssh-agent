"""Tests for the core SSH management module."""

# Import built-in modules
import os

# Import third-party modules
from persistent_ssh_agent.core import PersistentSSHAgent
import pytest


@pytest.fixture
def ssh_manager():
    """Create a PersistentSSHAgent instance."""
    return PersistentSSHAgent()


def test_ensure_home_env(ssh_manager):
    """Test HOME environment variable setup."""
    # Save original environment
    original_env = os.environ.copy()

    try:
        # Remove HOME if it exists
        if "HOME" in os.environ:
            del os.environ["HOME"]

        # Get expected home directory
        expected_home = os.path.expanduser("~")

        # Test HOME environment setup
        ssh_manager._ensure_home_env()
        assert os.environ["HOME"] == expected_home

        # Test that existing HOME is not modified
        test_home = "/test/home"
        os.environ["HOME"] = test_home
        ssh_manager._ensure_home_env()
        assert os.environ["HOME"] == test_home

    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def test_parse_ssh_config(ssh_manager, mock_ssh_config, monkeypatch):
    """Test SSH config parsing."""
    monkeypatch.setenv("HOME", str(mock_ssh_config.parent))
    ssh_manager._ssh_dir = mock_ssh_config  # Update ssh_dir to use mock config
    config = ssh_manager._parse_ssh_config()

    assert "github.com" in config
    assert isinstance(config["github.com"]["identityfile"], list)
    assert config["github.com"]["identityfile"] == ["~/.ssh/id_ed25519"]
    assert config["github.com"]["user"] == "git"

    assert "*.gitlab.com" in config
    assert isinstance(config["*.gitlab.com"]["identityfile"], list)
    assert config["*.gitlab.com"]["identityfile"] == ["gitlab_key"]
    assert config["*.gitlab.com"]["user"] == "git"


def test_extract_hostname(ssh_manager):
    """Test hostname extraction from repository URLs."""
    # Test standard GitHub URL
    hostname = ssh_manager._extract_hostname("git@github.com:user/repo.git")
    assert hostname == "github.com"

    # Test GitLab URL
    hostname = ssh_manager._extract_hostname("git@gitlab.com:group/project.git")
    assert hostname == "gitlab.com"

    # Test custom domain
    hostname = ssh_manager._extract_hostname("git@git.example.com:org/repo.git")
    assert hostname == "git.example.com"

    # Test invalid URLs
    assert ssh_manager._extract_hostname("invalid-url") is None
    assert ssh_manager._extract_hostname("https://github.com/user/repo.git") is None
    assert ssh_manager._extract_hostname("") is None


def test_is_valid_hostname(ssh_manager):
    """Test hostname validation."""
    # Test valid hostnames
    assert ssh_manager.is_valid_hostname("github.com") is True
    assert ssh_manager.is_valid_hostname("git.example.com") is True
    assert ssh_manager.is_valid_hostname("sub1.sub2.example.com") is True
    assert ssh_manager.is_valid_hostname("test-host.com") is True
    assert ssh_manager.is_valid_hostname("192.168.1.1") is True

    # Test invalid hostnames
    assert ssh_manager.is_valid_hostname("") is False
    assert ssh_manager.is_valid_hostname("a" * 256) is False  # Too long
    assert ssh_manager.is_valid_hostname("invalid_hostname") is False  # Contains underscore
    assert ssh_manager.is_valid_hostname("host@name") is False  # Contains @
    assert ssh_manager.is_valid_hostname("host:name") is False  # Contains :


def test_start_ssh_agent_reuse(ssh_manager, mocker):
    """Test SSH agent reuse functionality."""
    # Mock necessary methods
    mock_load_agent = mocker.patch.object(ssh_manager, "_load_agent_info")
    mock_verify_key = mocker.patch.object(ssh_manager, "_verify_loaded_key")
    mock_run_command = mocker.patch.object(ssh_manager, "run_command")
    mock_add_key = mocker.patch.object(ssh_manager, "_add_ssh_key")
    mock_logger = mocker.patch("persistent_ssh_agent.core.logger")

    # Mock run_command to return a successful result with proper stdout
    class MockResult:
        returncode = 0
        stdout = "SSH_AUTH_SOCK=/tmp/ssh-XXX/agent.123; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=123; export SSH_AGENT_PID;"
    mock_run_command.return_value = MockResult()

    # Mock successful key operations
    mock_add_key.return_value = True

    # Test case 1: Successfully reuse existing agent
    mock_load_agent.return_value = True
    mock_verify_key.return_value = True
    identity_file = "~/.ssh/id_rsa"

    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_logger.debug.assert_called_with("Using existing agent with loaded key: %s", identity_file)

    # Test case 2: Found agent but key not loaded
    mock_verify_key.return_value = False
    mock_logger.debug.reset_mock()  # Reset mock to clear previous calls

    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_logger.debug.assert_has_calls([
        mocker.call("Existing agent found but key not loaded"),
        mocker.call("Saved agent info to: %s", ssh_manager._agent_info_file),
        mocker.call("Adding key to agent: %s", identity_file)
    ], any_order=False)

    # Test case 3: No valid agent found
    mock_load_agent.return_value = False
    mock_logger.debug.reset_mock()

    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_logger.debug.assert_has_calls([
        mocker.call("No valid existing agent found"),
        mocker.call("Saved agent info to: %s", ssh_manager._agent_info_file),
        mocker.call("Adding key to agent: %s", identity_file)
    ], any_order=False)

    # Test case 4: Agent reuse disabled
    ssh_manager._reuse_agent = False
    mock_logger.debug.reset_mock()

    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_logger.debug.assert_has_calls([
        mocker.call("Agent reuse disabled, starting new agent"),
        mocker.call("Saved agent info to: %s", ssh_manager._agent_info_file),
        mocker.call("Adding key to agent: %s", identity_file)
    ], any_order=False)


def test_start_ssh_agent_platform_specific(ssh_manager, mocker):
    """Test platform-specific SSH agent startup."""
    mock_run_command = mocker.patch.object(ssh_manager, "run_command")
    mock_os = mocker.patch("persistent_ssh_agent.core.os")
    mock_verify_key = mocker.patch.object(ssh_manager, "_verify_loaded_key")
    mock_add_key = mocker.patch.object(ssh_manager, "_add_ssh_key")

    # Mock run_command to return a successful result with proper stdout
    class MockResult:
        returncode = 0
        stdout = "SSH_AUTH_SOCK=/tmp/ssh-XXX/agent.123; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=123; export SSH_AGENT_PID;"
    mock_run_command.return_value = MockResult()

    # Mock successful key operations
    mock_verify_key.return_value = False  # Key not loaded initially
    mock_add_key.return_value = True  # Key added successfully

    # Test Windows (nt) platform
    mock_os.name = "nt"
    ssh_manager._reuse_agent = False  # Disable reuse to test agent startup
    identity_file = "~/.ssh/id_rsa"

    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_run_command.assert_called_with(["ssh-agent", "-s"])

    # Test Unix platform
    mock_os.name = "posix"
    assert ssh_manager._start_ssh_agent(identity_file) is True
    mock_run_command.assert_called_with(["ssh-agent"])


def test_start_ssh_agent_failure(ssh_manager, mocker):
    """Test SSH agent startup failure cases."""
    mock_run_command = mocker.patch.object(ssh_manager, "run_command")
    mock_logger = mocker.patch("persistent_ssh_agent.core.logger")

    # Mock run_command to return a failed result
    class MockResult:
        returncode = 1
    mock_run_command.return_value = MockResult()

    ssh_manager._reuse_agent = False  # Disable reuse to test agent startup
    identity_file = "~/.ssh/id_rsa"

    assert ssh_manager._start_ssh_agent(identity_file) is False
    mock_logger.error.assert_called()
