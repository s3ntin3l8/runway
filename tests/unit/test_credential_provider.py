import os
import json
import yaml
from unittest.mock import patch, mock_open, MagicMock
from app.services.credential_provider import CredentialProvider
from app.core.config import settings

def test_github_token_env():
    """Test discovering GitHub token from environment."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "env_token"}):
        token = CredentialProvider.get_github_token()
        assert token == "env_token"

def test_github_token_runway_json():
    """Test discovering GitHub token from Runway's oauth.json."""
    mock_data = json.dumps({"access_token": "runway_token"})
    with patch.dict(os.environ, {"GITHUB_TOKEN": ""}), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_data)):
        token = CredentialProvider.get_github_token()
        assert token == "runway_token"

def test_github_token_gh_cli():
    """Test discovering GitHub token from gh CLI's hosts.yml."""
    mock_yaml = "github.com:\n  oauth_token: gho_cli_token\n  user: test"
    
    # Need to patch os.path.exists for both Runway path (return False) and gh path (return True)
    def exists_side_effect(path):
        if "hosts.yml" in path:
            return True
        return False

    with patch.dict(os.environ, {"GITHUB_TOKEN": ""}), \
         patch("os.path.exists", side_effect=exists_side_effect), \
         patch("builtins.open", mock_open(read_data=mock_yaml)), \
         patch("app.services.credential_provider.yaml", MagicMock(safe_load=lambda f: yaml.safe_load(f))):
        token = CredentialProvider.get_github_token()
        assert token == "gho_cli_token"

def test_gemini_path_discovery():
    """Test discovering Gemini credentials path."""
    def exists_side_effect(path):
        if ".gemini/oauth_creds.json" in path:
            return True
        return False

    with patch("os.path.exists", side_effect=exists_side_effect), \
         patch("os.path.expanduser", return_value="/home/user"):
        path = CredentialProvider.get_gemini_credentials_path()
        assert path is not None
        assert ".gemini/oauth_creds.json" in path

def test_disabled_scraping():
    """Test that discovery returns empty/None if scraping is disabled."""
    with patch.object(settings, "LOCAL_CREDENTIAL_SCRAPING_ENABLED", False), \
         patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
        assert CredentialProvider.get_github_token() == ""
        assert CredentialProvider.get_gemini_credentials_path() is None
