"""Bootstrap entry point for the Runway sidecar desktop app."""

import logging
import threading
import traceback

from sidecar_app import __version__
from sidecar_app.config import (
    get_config_path,
    load_config,
    setup_logging,
    watch_config,
    write_template_config,
)
from sidecar_app.daemon import TrayDaemon
from sidecar_app.tray import SidecarTray
from sidecar_app.updater import UpdateChecker

_FALLBACK_CONFIG: dict = {
    "api_url": "http://localhost:8765",
    "api_key": "",
    "interval_seconds": 1800,
}


def main() -> None:
    # 0. Enable logging to file
    setup_logging(log_level="INFO", file_enabled=True)

    # 1. Find config path
    config_path = get_config_path()

    # 2. Load config (handle missing without calling sys.exit)
    needs_setup_notification = False
    if not config_path.exists():
        write_template_config(config_path)
        config = dict(_FALLBACK_CONFIG)
        needs_setup_notification = True
    else:
        try:
            config = load_config(str(config_path))
        except SystemExit:
            # load_config calls sys.exit on validation errors; treat as broken config
            config = dict(_FALLBACK_CONFIG)
        except Exception:
            config = dict(_FALLBACK_CONFIG)

    # 3. Inject runtime metadata into config before handing to daemon
    config["sidecar_version"] = __version__

    # 4. Create daemon + tray
    daemon = TrayDaemon(config)
    tray = SidecarTray(daemon, config, config_path)

    # 5. Wire status change callback
    daemon.on_status_change = tray._update_icon

    # 6. Wire update checker
    def on_update_available(current: str, latest: str) -> None:
        tray.set_update_available(True)

    checker = UpdateChecker(on_update_available=on_update_available)
    checker.start()

    # 7. Wire config hot-reload (file watcher + manual "Reload Config" menu item)
    _watcher_stop = threading.Event()

    def _on_config_change(new_config: dict) -> None:
        new_config["sidecar_version"] = __version__
        old_key = config.get("api_key", "")
        new_key = new_config.get("api_key", "")
        old_url = config.get("api_url", "")
        new_url = new_config.get("api_url", "")
        old_interval = config.get("interval_seconds", 1800)
        new_interval = new_config.get("interval_seconds", 1800)

        config.update(new_config)
        daemon._runner._config = new_config
        daemon._runner._interval = new_interval

        credentials_changed = (new_key != old_key) or (new_url != old_url)
        if credentials_changed:
            logging.info("Config reloaded: credentials changed — restarting daemon")
            daemon.stop()
            if new_key and new_key != "REPLACE_ME":
                daemon._runner._stop_event.clear()
                daemon.start()
        elif new_interval != old_interval:
            logging.info(f"Config reloaded: interval changed to {new_interval}s")
        else:
            logging.info("Config reloaded (no credentials change)")

    def _manual_reload() -> None:
        """Called when the user clicks 'Reload Config' in the tray menu."""
        try:
            new_config = load_config(str(config_path))
            _on_config_change(new_config)
        except Exception as e:
            logging.warning(f"Manual config reload failed: {e}")

    tray._on_reload_config = _manual_reload
    watch_config(config_path, _on_config_change, _watcher_stop)

    # 8. Start daemon only when credentials are present
    api_key = config.get("api_key", "")
    if api_key and api_key != "REPLACE_ME":
        daemon.start()

    # 9. Run tray — blocks main thread
    if needs_setup_notification:

        def notify_setup() -> None:
            if tray._icon is not None:
                try:
                    tray._icon.notify(
                        "Edit config.json to connect to your Runway server, then restart.",
                        "Runway Sidecar — Setup Required",
                    )
                except Exception:
                    pass  # notifications not supported on all platforms

        tray.run(after_start=notify_setup)
    else:
        tray.run()

    # 10. Tray exited — stop background threads
    checker.stop()
    _watcher_stop.set()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
