"""Tests for the core SSH management module."""

import os
import pytest
from unittest.mock import patch, MagicMock
from persistent_ssh_agent.core import PersistentSSHAgent
import json
import time


@pytest.fixture
def ssh_manager():
    """Create a PersistentSSHAgent instance."""
    return PersistentSSHAgent()


def test_ensure_home_env(ssh_manager):
    """Test HOME environment variable is set correctly."""
    with patch.dict('os.environ', {'USERPROFILE': '/mock/home'}, clear=True):
        ssh_manager._ensure_home_env()
        assert os.environ.get('HOME') == '/mock/home'
        assert os.environ.get('USERPROFILE') == '/mock/home'


def test_parse_ssh_config(ssh_manager, mock_ssh_config, monkeypatch):
    """Test SSH config parsing."""
    monkeypatch.setenv('HOME', os.path.dirname(mock_ssh_config))
    config = ssh_manager._parse_ssh_config()
    
    assert 'github.com' in config
    assert config['github.com']['identityfile'] == '~/.ssh/id_ed25519'
    assert config['github.com']['user'] == 'git'
    
    assert '*.gitlab.com' in config
    assert config['*.gitlab.com']['identityfile'] == '~/.ssh/gitlab_key'


def test_get_identity_file(ssh_manager, mock_ssh_config, monkeypatch):
    """Test identity file resolution."""
    monkeypatch.setenv('HOME', os.path.dirname(mock_ssh_config))
    
    # Test exact match
    identity = ssh_manager._get_identity_file('github.com')
    assert 'id_ed25519' in identity
    
    # Test pattern match
    identity = ssh_manager._get_identity_file('test.gitlab.com')
    assert 'gitlab_key' in identity


def test_extract_hostname(ssh_manager):
    """Test hostname extraction from repository URLs."""
    # Test standard GitHub URL
    hostname = ssh_manager._extract_hostname('git@github.com:user/repo.git')
    assert hostname == 'github.com'
    
    # Test GitLab URL
    hostname = ssh_manager._extract_hostname('git@gitlab.com:group/project.git')
    assert hostname == 'gitlab.com'
    
    # Test custom domain
    hostname = ssh_manager._extract_hostname('git@git.example.com:org/repo.git')
    assert hostname == 'git.example.com'
    
    # Test invalid URLs
    assert ssh_manager._extract_hostname('invalid-url') is None
    assert ssh_manager._extract_hostname('https://github.com/user/repo.git') is None
    assert ssh_manager._extract_hostname('') is None


@patch('subprocess.run')
def test_run_command(mock_run, ssh_manager):
    """Test command execution."""
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = "Success"
    mock_run.return_value = mock_process
    
    result = ssh_manager._run_command(['git', 'status'])
    assert result is not None
    assert result.returncode == 0
    assert result.stdout == "Success"
    
    # Test command failure
    mock_process.returncode = 1
    result = ssh_manager._run_command(['git', 'invalid'])
    assert result is None


@patch('subprocess.run')
def test_start_ssh_agent(mock_run, ssh_manager, temp_dir):
    """Test SSH agent startup."""
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = "SSH_AUTH_SOCK=/tmp/ssh-XXX/agent.123; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=123; export SSH_AGENT_PID;"
    mock_run.return_value = mock_process
    
    result = ssh_manager._start_ssh_agent(os.path.join(temp_dir, 'test_key'))
    assert result is True
    assert 'SSH_AUTH_SOCK' in os.environ
    assert 'SSH_AGENT_PID' in os.environ


@patch('subprocess.run')
def test_setup_ssh(mock_run, ssh_manager, mock_ssh_config, monkeypatch):
    """Test SSH setup."""
    monkeypatch.setenv('HOME', os.path.dirname(mock_ssh_config))
    
    mock_process = MagicMock()
    mock_process.returncode = 1  # GitHub returns 1 for successful auth
    mock_run.return_value = mock_process
    
    result = ssh_manager.setup_ssh('github.com')
    assert result is True


def test_save_load_agent_info(ssh_manager, temp_dir, monkeypatch):
    """Test saving and loading SSH agent information."""
    monkeypatch.setenv('HOME', temp_dir)
    
    # Test saving agent info
    ssh_manager._agent_info_file = os.path.join(temp_dir, '.ssh', 'agent_info.json')
    ssh_manager._save_agent_info('/tmp/ssh.sock', '12345')
    
    assert os.path.exists(ssh_manager._agent_info_file)
    
    # Test loading valid agent info
    with patch('subprocess.run') as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_run.return_value = mock_process
        
        assert ssh_manager._load_agent_info() is True
        assert os.environ.get('SSH_AUTH_SOCK') == '/tmp/ssh.sock'
        assert os.environ.get('SSH_AGENT_PID') == '12345'
    
    # Test loading with missing file
    os.unlink(ssh_manager._agent_info_file)
    assert ssh_manager._load_agent_info() is False
    
    # Test loading with invalid JSON
    with open(ssh_manager._agent_info_file, 'w') as f:
        f.write('invalid json')
    assert ssh_manager._load_agent_info() is False


def test_clone_repository(ssh_manager, temp_dir):
    """Test repository cloning."""
    with patch('subprocess.run') as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_run.return_value = mock_process
        
        # Test successful clone
        assert ssh_manager.clone_repository(
            'git@github.com:user/repo.git',
            os.path.join(temp_dir, 'repo'),
            'main'
        ) is True
        
        # Test clone with invalid URL
        assert ssh_manager.clone_repository(
            'invalid-url',
            os.path.join(temp_dir, 'repo2')
        ) is False


def test_version():
    """Test version import."""
    from persistent_ssh_agent.__version__ import __version__
    assert isinstance(__version__, str)
    assert __version__ != ""


def test_ensure_home_env_edge_cases(ssh_manager, monkeypatch):
    """Test edge cases for HOME environment setup."""
    # Test when USERPROFILE is not set on Windows
    with patch('os.name', 'nt'):
        monkeypatch.delenv('USERPROFILE', raising=False)
        monkeypatch.delenv('HOME', raising=False)
        with patch('os.path.expanduser') as mock_expanduser:
            mock_expanduser.return_value = r'C:\Users\testuser'
            ssh_manager._ensure_home_env()
            assert os.environ.get('HOME') == r'C:\Users\testuser'
    
    # Test Unix-like systems without HOME
    with patch('os.name', 'posix'):
        monkeypatch.delenv('HOME', raising=False)
        with patch('os.path.expanduser') as mock_expanduser:
            mock_expanduser.return_value = '/home/testuser'
            ssh_manager._ensure_home_env()
            assert os.environ.get('HOME') == '/home/testuser'


def test_save_agent_info_errors(ssh_manager, temp_dir, monkeypatch):
    """Test error cases for saving agent info."""
    monkeypatch.setenv('HOME', temp_dir)
    ssh_manager._agent_info_file = os.path.join(temp_dir, '.ssh', 'agent_info.json')
    
    # Test permission error
    with patch('os.makedirs') as mock_makedirs:
        mock_makedirs.side_effect = PermissionError()
        ssh_manager._save_agent_info('/tmp/ssh.sock', '12345')
        # Should not raise exception
    
    # Test file write error
    with patch('builtins.open') as mock_open:
        mock_open.side_effect = IOError()
        ssh_manager._save_agent_info('/tmp/ssh.sock', '12345')
        # Should not raise exception


def test_load_agent_info_edge_cases(ssh_manager, temp_dir, monkeypatch):
    """Test edge cases for loading agent info."""
    monkeypatch.setenv('HOME', temp_dir)
    ssh_manager._agent_info_file = os.path.join(temp_dir, '.ssh', 'agent_info.json')
    
    # Test with expired timestamp
    agent_info = {
        'SSH_AUTH_SOCK': '/tmp/ssh.sock',
        'SSH_AGENT_PID': '12345',
        'timestamp': time.time() - 90000,  # More than 24 hours old
        'platform': os.name
    }
    os.makedirs(os.path.dirname(ssh_manager._agent_info_file), exist_ok=True)
    with open(ssh_manager._agent_info_file, 'w') as f:
        json.dump(agent_info, f)
    
    assert ssh_manager._load_agent_info() is False
    
    # Test with missing required fields
    agent_info = {
        'timestamp': time.time(),
        'platform': os.name
    }
    with open(ssh_manager._agent_info_file, 'w') as f:
        json.dump(agent_info, f)
    
    assert ssh_manager._load_agent_info() is False
    
    # Test with wrong platform
    agent_info = {
        'SSH_AUTH_SOCK': '/tmp/ssh.sock',
        'SSH_AGENT_PID': '12345',
        'timestamp': time.time(),
        'platform': 'wrong_platform'
    }
    with open(ssh_manager._agent_info_file, 'w') as f:
        json.dump(agent_info, f)
    
    assert ssh_manager._load_agent_info() is False


@patch('subprocess.run')
def test_start_ssh_agent_errors(mock_run, ssh_manager, temp_dir):
    """Test error cases for SSH agent startup."""
    # Test SSH agent start failure
    mock_run.return_value = MagicMock(returncode=1, stderr="Failed to start agent")
    assert ssh_manager._start_ssh_agent(os.path.join(temp_dir, 'test_key')) is False
    
    # Test ssh-add failure with proper command sequence
    def mock_run_side_effect(*args, **kwargs):
        if args[0][0] == 'ssh-agent':
            return MagicMock(
                returncode=0,
                stdout='SSH_AUTH_SOCK=/tmp/ssh.sock; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=123; export SSH_AGENT_PID;'
            )
        elif args[0][0] == 'ssh-add':
            return MagicMock(returncode=1, stderr='Failed to add key')
        elif args[0][0] == 'taskkill':
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)
    
    mock_run.side_effect = mock_run_side_effect
    assert ssh_manager._start_ssh_agent(os.path.join(temp_dir, 'test_key')) is False


def test_get_git_ssh_command_errors(ssh_manager):
    """Test error cases for Git SSH command generation."""
    # Test with empty hostname
    assert ssh_manager.get_git_ssh_command('') is None
    
    # Test with setup failure
    with patch.object(ssh_manager, 'setup_ssh', return_value=False):
        assert ssh_manager.get_git_ssh_command('github.com') is None
    
    # Test with nonexistent identity file
    with patch.object(ssh_manager, 'setup_ssh', return_value=True):
        with patch.object(ssh_manager, '_get_identity_file', return_value='/nonexistent/key'):
            assert ssh_manager.get_git_ssh_command('github.com') is None


def test_clone_repository_errors(ssh_manager, temp_dir):
    """Test error cases for repository cloning."""
    # Test command execution error
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = Exception('Command failed')
        result = ssh_manager.clone_repository(
            'git@github.com:user/repo.git',
            os.path.join(temp_dir, 'repo')
        )
        assert result is False
    
    # Test with failed command
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = ssh_manager.clone_repository(
            'git@github.com:user/repo.git',
            os.path.join(temp_dir, 'repo')
        )
        assert result is False
    
    # Test with invalid hostname extraction
    with patch.object(ssh_manager, '_extract_hostname', return_value=None):
        result = ssh_manager.clone_repository(
            'invalid-url',
            os.path.join(temp_dir, 'repo')
        )
        assert result is False
