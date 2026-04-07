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
