import subprocess
import platform
import threading
import logging
import os
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Global cache for keychain secrets to avoid multiple macOS prompts during a session
_KEYCHAIN_CACHE: Dict[str, str] = {}
_KEYCHAIN_LOCK = threading.Lock()

def get_keychain_secret(service: str, account: Optional[str] = None, force_refresh: bool = False) -> Optional[str]:
    """
    Fetch a secret from the macOS Keychain with in-memory caching.
    Ensures that the user is only prompted once per unique secret per session.
    """
    if platform.system() != "Darwin":
        return None

    cache_key = f"{service}:{account}" if account else service
    
    if not force_refresh:
        with _KEYCHAIN_LOCK:
            if cache_key in _KEYCHAIN_CACHE:
                return _KEYCHAIN_CACHE[cache_key]
    else:
        logger.debug(f"🔄 Bypassing cache for keychain lookup: {service}")

    try:
        logger.info(f"🔑 Requesting macOS Keychain access for service: {service}...")
        
        # We try -w (password only) first as it is the most standard
        cmd = ["security", "find-generic-password", "-s", service]
        if account:
            cmd.extend(["-a", account])
        cmd.append("-w")

        # Set environment to allow interaction
        env = os.environ.copy()
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        if result.returncode == 0:
            secret = result.stdout.strip()
            if secret:
                with _KEYCHAIN_LOCK:
                    _KEYCHAIN_CACHE[cache_key] = secret
                return secret
        
        # If -w fails, try with -g (which often puts password in stderr)
        cmd_g = ["security", "find-generic-password", "-s", service]
        if account: cmd_g.extend(["-a", account])
        cmd_g.append("-g")
        
        result_g = subprocess.run(cmd_g, capture_output=True, text=True, timeout=30, env=env)
        if result_g.returncode == 0:
            output = result_g.stdout + result_g.stderr
            import re
            match = re.search(r'password: "(.*)"', output)
            if match:
                secret = match.group(1)
                with _KEYCHAIN_LOCK:
                    _KEYCHAIN_CACHE[cache_key] = secret
                return secret

        # Log specific reason for failure
        err = result.stderr.strip() or result_g.stderr.strip()
        if "The specified item could not be found" in err:
            logger.debug(f"Keychain service '{service}' not found.")
        elif "User interaction is not allowed" in err:
            logger.warning(f"❌ Keychain access denied: User interaction not allowed for '{service}'. Try running in a visible terminal.")
        else:
            logger.warning(f"❌ Keychain lookup failed for {service}: {err}")
        
        return None
    except Exception as e:
        logger.error(f"Error accessing macOS Keychain for {service}: {e}")
        return None

def clear_keychain_cache():
    """Clear the in-memory cache."""
    with _KEYCHAIN_LOCK:
        _KEYCHAIN_CACHE.clear()
