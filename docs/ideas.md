# Future Ideas & Improvements

## Claude Collector
- [ ] **Claude OAuth Token Refreshing**: Implement automatic token refreshing via `refreshToken` in `~/.claude/.credentials.json` if the primary `accessToken` is expired (typically expires after a few hours/days). Note: This would require writing back to the credentials file, which needs careful handling of file permissions and potential race conditions.

## GitHub Collector
- [ ] **GitHub OAuth Device Flow**: Replace manual `GITHUB_TOKEN` entry with the official [Device Flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow). 
    - Display user code in frontend.
    - Poll for access token in background.
    - Particularly useful for headless/Docker environments where browser redirects are difficult.
## ChatGPT Collector
- [ ] **Web Dashboard Scraping**: Implement optional scraping of `https://chatgpt.com/codex/settings/usage` to get rate limits, credits, and detailed usage charts.
    - Support manual `Cookie:` header input for headless environments.
    - Support automatic cookie extraction from Safari/Chrome/Firefox on macOS (experimental).
    - *Inspiration: CodexBar's web scraping path.*

## OpenCode Collector
- [ ] **Multi-Browser Cookie Support**: Currently only Chrome is supported for automatic cookie extraction. Add support for:
    - Firefox (cookies.sqlite database)
    - Safari (binary plist format)
    - Edge (Chromium-based, similar to Chrome)
    - Priority: Low (Chrome covers 80%+ of users)

## Sidecar & Ingestion
- [ ] **Auto-Updating Sidecar**: Enable the sidecar to self-update by checking against the main Runway server's version or a remote Git repository.
- [ ] **Daemon Mode**: Support a `--daemon` flag to run as a persistent process with a configurable sleep interval, providing more real-time updates than 30m crontab tasks.
- [ ] **Offline Queuing**: If the ingestion API is unreachable, cache collected metrics in a local SQLite/JSON file and retry upon the next successful connection.
- [ ] **Binary Sidecar**: Distribute the sidecar as a single-binary (using PyInstaller or Go) to avoid Python dependency issues on host machines.
