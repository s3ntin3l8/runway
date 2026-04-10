import os
import json
import logging
import platform
import subprocess
from typing import Optional, Dict, List
from app.core.config import settings, get_platform_config_dir

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


class CredentialProvider:
    """
    Centralized service for discovering credentials from various sources.
    Respects the project's statelessness and Docker rules.
    """

    @staticmethod
    def get_github_token() -> str:
        """Get GitHub token with priority: Env -> File (Runway) -> File (gh CLI)."""
        # Priority 1: Env var
        token = os.getenv("GITHUB_TOKEN", "")
        if token:
            return token

        # Skip local file access if disabled
        if not settings.LOCAL_CREDENTIAL_SCRAPING_ENABLED:
            return ""

        # Priority 2: Stored OAuth token (Runway-specific)
        oauth_path = settings.GITHUB_OAUTH_PATH
        if os.path.exists(oauth_path):
            try:
                with open(oauth_path, "r") as f:
                    data = json.load(f)
                    val = data.get("access_token")
                    if val:
                        return val
            except Exception as e:
                logger.debug(f"Error reading GitHub OAuth token from {oauth_path}: {e}")

        # Priority 3: gh CLI (GitHub CLI)
        if yaml:
            home = os.path.expanduser("~")
            gh_potential_paths = [
                os.path.join(home, ".config", "gh", "hosts.yml"),
                os.path.join(get_platform_config_dir("gh"), "hosts.yml"),
            ]
            
            # Check for Windows-specific paths if on Windows
            if platform.system() == "Windows":
                app_data = os.getenv("APPDATA")
                local_app_data = os.getenv("LOCALAPPDATA")
                if app_data:
                    gh_potential_paths.append(os.path.join(app_data, "gh", "hosts.yml"))
                if local_app_data:
                    gh_potential_paths.append(os.path.join(local_app_data, "gh", "hosts.yml"))

            for gh_path in gh_potential_paths:
                if os.path.exists(gh_path):
                    try:
                        with open(gh_path, "r") as f:
                            data = yaml.safe_load(f)
                            # gh CLI format: github.com: { oauth_token: "..." }
                            if isinstance(data, dict):
                                github_data = data.get("github.com", {})
                                if isinstance(github_data, dict):
                                    val = github_data.get("oauth_token")
                                    if val:
                                        logger.debug(f"Found GitHub token in gh CLI config: {gh_path}")
                                        return val
                    except Exception as e:
                        logger.debug(f"Error parsing gh CLI config {gh_path}: {e}")

        return ""

    @staticmethod
    def get_gemini_credentials_path() -> Optional[str]:
        """Search for Gemini credentials file in standard locations."""
        if not settings.LOCAL_CREDENTIAL_SCRAPING_ENABLED:
            return None

        home = os.path.expanduser("~")
        potential_paths = [
            settings.GEMINI_OAUTH_PATH,
            os.path.join(home, ".gemini", "oauth_creds.json"),
            os.path.join(home, ".config", "gemini", "oauth_creds.json"),
            os.path.join(get_platform_config_dir("gemini"), "oauth_creds.json"),
        ]

        for cred_path in potential_paths:
            if cred_path and os.path.exists(cred_path):
                return cred_path
        
        return None

    @staticmethod
    def get_chatgpt_token() -> str:
        """Get ChatGPT OAuth token from env or auth.json."""
        data = CredentialProvider.get_chatgpt_data()
        return data.get("access_token", "")

    @staticmethod
    def get_chatgpt_data() -> Dict[str, str]:
        """Get full ChatGPT OAuth data from env or auth.json."""
        token = os.getenv("CHATGPT_OAUTH_TOKEN", "")
        account_id = os.getenv("CHATGPT_ACCOUNT_ID", "")
        
        if token:
            return {"access_token": token, "account_id": account_id}

        # Skip local file access if disabled
        if not settings.LOCAL_CREDENTIAL_SCRAPING_ENABLED:
            return {}

        auth_path = settings.CHATGPT_AUTH_PATH
        if os.path.exists(auth_path):
            try:
                with open(auth_path, "r") as f:
                    data = json.load(f)
                    tokens = data.get("tokens", {})
                    return {
                        "access_token": tokens.get("access_token", ""),
                        "refresh_token": data.get("refresh_token", ""),
                        "account_id": data.get("account_id", ""),
                        "last_refresh": data.get("last_refresh", ""),
                    }
            except Exception as e:
                logger.debug(f"Error reading ChatGPT auth from {auth_path}: {e}")

        return {}

    _claude_token_cache: Optional[str] = None

    @classmethod
    def get_claude_token(cls) -> str:
        """Get Claude OAuth token with priority: Env -> File -> Keychain -> Keyring."""
        if cls._claude_token_cache:
            return cls._claude_token_cache

        # Priority 1: Env var
        token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")
        if token:
            cls._claude_token_cache = token
            return token

        # Skip local credential scraping if disabled
        if not settings.LOCAL_CREDENTIAL_SCRAPING_ENABLED:
            return ""

        # Priority 2: Claude Code credentials (search multiple locations)
        home = os.path.expanduser("~")
        potential_paths = [
            os.path.join(home, ".claude", ".credentials.json"),
            os.path.join(get_platform_config_dir("claude"), ".credentials.json"),
        ]

        for cred_path in potential_paths:
            if os.path.exists(cred_path):
                try:
                    with open(cred_path, "r") as f:
                        data = json.load(f)
                        val = data.get("claudeAiOauth", {}).get("accessToken")
                        if val:
                            cls._claude_token_cache = val
                            return val
                except Exception as e:
                    logger.debug(f"Error reading credentials from {cred_path}: {e}")

        # Priority 3: macOS Keychain (skip if in Docker mode)
        if settings.RUN_MODE != "docker" and platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    [
                        "security",
                        "find-generic-password",
                        "-s",
                        "Claude Code-credentials",
                        "-w",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    keychain_data = result.stdout.strip()
                    try:
                        data = json.loads(keychain_data)
                        val = data.get("claudeAiOauth", {}).get("accessToken")
                        if val:
                            logger.debug("Found Claude OAuth token in macOS Keychain")
                            cls._claude_token_cache = val
                            return val
                    except json.JSONDecodeError:
                        if keychain_data.startswith("sk-"):
                            cls._claude_token_cache = keychain_data
                            return keychain_data
            except Exception as e:
                logger.debug(f"Could not read from macOS Keychain: {e}")

        # Priority 4: Python keyring library (skip if in Docker mode)
        if settings.RUN_MODE != "docker":
            try:
                import keyring

                token = keyring.get_password("runway", "claude-oauth-token")
                if token:
                    logger.debug("Found Claude OAuth token in system keyring")
                    cls._claude_token_cache = token
                    return token
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Could not read from keyring: {e}")

        return ""


credential_provider = CredentialProvider()
