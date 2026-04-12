# Ollama Cloud Collector

The Ollama provider scrapes the **Plan & Settings** page at `https://ollama.com/settings` to extract Cloud Usage limits for session and weekly windows.

## Features

- **Plan Badge**: Reads the plan tier (Free/Pro/Max) from the Cloud Usage header.
- **Session & Weekly Usage**: Parses the percent-used values shown in the usage bars.
- **Reset Timestamps**: Extracts ISO timestamps for when usage limits will reset.
- **Browser Cookie Auth**: Automatically imports cookies from your local browser (Chrome/Safari/Firefox/Edge).

## Setup

### Automatic (Recommended)
1. Log in to `https://ollama.com/settings` in your browser (e.g., Chrome).
2. Runway will automatically pick up the session cookie.

### Manual Environment Variable
If you are running Runway in a container or on a headless server, you can provide the session token via an environment variable:

```bash
export OLLAMA_SESSION_TOKEN="your-session-cookie-value"
```

To find your session token:
1. Open `https://ollama.com/settings` in your browser.
2. Open Developer Tools (F12) -> Network tab.
3. Refresh the page and click on the `settings` request.
4. Look for the `Cookie` header and copy the value of the `session` or `ollama_session` cookie.

## How it works

- The collector fetches the HTML from `https://ollama.com/settings`.
- It uses regex to find the usage blocks (labeled "Session usage" or "Weekly usage").
- It parses the percentage used and the `data-time` attribute for the reset timestamp.
- If multiple session cookies are available, it uses the first one found in the registry-defined order.
