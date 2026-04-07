import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class Settings:
    PROJECT_NAME: str = "Runway — AI Limits Dashboard"
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    
    @property
    def CLAUDE_CODE_OAUTH_TOKEN(self) -> str:
        # Priority 1: Env var
        token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")
        if token: return token
        
        # Priority 2: ~/.claude/.credentials.json (Claude Code)
        cred_path = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.exists(cred_path):
            try:
                with open(cred_path, "r") as f:
                    data = json.load(f)
                    val = data.get("claudeAiOauth", {}).get("accessToken")
                    if val: return val
            except FileNotFoundError:
                logger.debug(f"Credentials file not found: {cred_path}")
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in credentials file: {cred_path}")
            except Exception as e:
                logger.warning(f"Error reading credentials file: {e}")
        return ""

    OPENCODE_GO_API_KEY: str = os.getenv("OPENCODE_GO_API_KEY", "")
    ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "")
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "")
    INGEST_API_KEY: str = os.getenv("INGEST_API_KEY", "sidecar-default-secret")
    
    # OAuth Credentials (from environment)
    GEMINI_OAUTH_CLIENT_ID: str = os.getenv("GEMINI_OAUTH_CLIENT_ID", "")
    GEMINI_OAUTH_CLIENT_SECRET: str = os.getenv("GEMINI_OAUTH_CLIENT_SECRET", "")
    
    # Path settings
    CLAUDE_PROJECTS_DIR: str = os.path.expanduser("~/.claude/projects")
    GEMINI_SESSIONS_DIR: str = os.path.expanduser("~/.gemini/tmp/sessions")
    GEMINI_OAUTH_PATH: str = os.path.expanduser("~/.gemini/oauth_creds.json")
    CHATGPT_SESSIONS_DIR: str = os.path.expanduser("~/.codex/sessions")
    ANTIGRAVITY_QUOTA_PATH: str = os.path.expanduser("~/.antigravity/state/quota.json")
    OPENCODE_DB_PATH: str = os.path.expanduser("~/.local/share/opencode/opencode.db")
    EXTERNAL_METRICS_PATH: str = os.path.expanduser("~/.usage-tracker/external_metrics.json")

settings = Settings()
