import os
import sys
import platform
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_platform_data_dir, get_platform_config_dir
from app.core.chrome_cookies import get_all_chrome_cookies_paths

def test_paths():
    print(f"Current System: {platform.system()}")
    print("-" * 40)
    
    # Test current system paths
    print(f"Core Data Dir (runway): {get_platform_data_dir('runway')}")
    print(f"Core Config Dir (runway): {get_platform_config_dir('runway')}")
    
    from app.core.config import settings
    print(f"OpenCode DB Path: {settings.OPENCODE_DB_PATH}")
    print(f"Claude Projects Dir: {settings.CLAUDE_PROJECTS_DIR}")
    
    cookies = get_all_chrome_cookies_paths()
    print(f"Chrome Cookie Paths found: {len(cookies)}")
    for c in cookies[:3]:
        print(f"  - {c}")
    if len(cookies) > 3:
        print(f"  ... and {len(cookies) - 3} more")
    print("-" * 40)

def test_mocked_platforms():
    print("Testing Mocked Platforms:")
    
    with patch("platform.system") as mock_sys, \
         patch("os.path.expanduser") as mock_expand:
        
        mock_expand.side_effect = lambda x: x.replace("~", "/home/user")
        
        # Windows
        mock_sys.return_value = "Windows"
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\user\\AppData\\Local", "APPDATA": "C:\\Users\\user\\AppData\\Roaming"}):
            data_dir = get_platform_data_dir("testapp")
            config_dir = get_platform_config_dir("testapp")
            print(f"Windows Data: {data_dir}")
            print(f"Windows Config: {config_dir}")
            
        # macOS
        mock_sys.return_value = "Darwin"
        data_dir = get_platform_data_dir("testapp")
        print(f"macOS Data: {data_dir}")
        
        # Linux
        mock_sys.return_value = "Linux"
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data", "XDG_CONFIG_HOME": "/custom/config"}):
            data_dir = get_platform_data_dir("testapp")
            config_dir = get_platform_config_dir("testapp")
            print(f"Linux (XDG) Data: {data_dir}")
            print(f"Linux (XDG) Config: {config_dir}")

if __name__ == "__main__":
    test_paths()
    test_mocked_platforms()
