# Detailed Implementation Plan: Historical Tracking & Settings Hub

## 1. System Architecture Update

The Runway architecture is evolving from a strictly stateless monitor into a **stateful, local-first application**. This introduces a single local database (`runway.db`) to handle both historical usage snapshots and user-configured credentials, secured via machine-level encryption.

### 1.1 Multi-Page Frontend Structure (MPA)
The single-page dashboard will be upgraded to a multi-page setup using a new **Top Navbar**:
1.  **Dashboard (`index.html`)**: Real-time Limit Cards, active sidecar pings, and immediate burn rate metrics.
2.  **History (`history.html`)**: Chart.js trend visualizations featuring an aggregated stacked area chart and drill-downs for specific providers (token volumes, costs, etc.).
3.  **Settings (`settings.html`)**: Configuration hub for providers, Sidecars, and backups.

---

## 2. Database Schema (`runway.db`)

We will use **SQLite** with **SQLModel**.

### 2.1 The `UsageSnapshot` Table (History)
Stores periodic snapshots of quota limits and usages.
- `id`: Primary key
- `timestamp`: Time of the snapshot (Indexed)
- `provider_id` / `service_name`: Identifier and display name (Indexed)
- `used_value` / `limit_value`: Core metric consumed and total allowed
- `unit_type` / `currency`: e.g., "currency", "USD", "tokens"
- `tokens_prompt` / `tokens_completion` / `tokens_total`: Granular token breakdown
- `data_source` / `error_type`: Collection context
- `raw_metadata`: **JSON Column** for "Max Variant" flexibility (e.g., breakdown by specific LLM models).

### 2.2 The `ProviderConfig` Table (Settings)
Stores user-provided API keys and configurations.
- `provider_id`: Primary key (e.g., "anthropic")
- `api_key_encrypted`: The encrypted API credential.
- `custom_limit`: Optional override for standard limits.
- `enabled_methods`: **JSON Column** defining which collectors are active (e.g., `["oauth", "web_api"]`).

### 2.3 The `SidecarRegistry` Table (Fleet Tracking)
Tracks remote machines submitting data.
- `hostname`: Primary key
- `last_seen`: Timestamp
- `providers_synced`: **JSON Column** (e.g., `{"opencode": "2026-04-11T12:00:00Z"}`)

---

## 3. Security & Machine-Key Encryption

To maintain Docker compatibility (where native keychains are unavailable), Runway will implement **Machine-Key Encryption** for all database secrets.

1.  **First Boot Generation**: On startup, Runway generates a 256-bit encryption key using `cryptography.fernet` and saves it to `~/.runway/.secret.key`.
2.  **Encryption at Rest**: Any API key submitted via the Settings UI is encrypted using this key before being stored in `ProviderConfig.api_key_encrypted`.
3.  **Decryption in Memory**: `CredentialProvider` decrypts the key on-the-fly when making outbound API calls.
4.  **Security Impact**: Protects API keys from casual file snooping or accidental GitHub commits of the `runway.db` file.

---

## 4. Credential Hierarchy Update

The `CredentialProvider` will be updated to respect the following priority:
1.  **Database (UI Configured)**: Highest Priority (Decrypted via `Fernet`).
2.  **Environment Variables (`.env`)**: Legacy/Docker support.
3.  **Local Files / macOS Keychain**: Auto-discovery.

---

## 5. Background Polling Strategy

Runway continues to operate as a **Passive Poller** (no proxy required).
1.  **Unified Trigger**: When `SmartCollector` fetches fresh data (a cache miss), it maps the resulting `LimitCard` to a `UsageSnapshot` and inserts it into the database.
2.  **Background Task**: An `asyncio` task in the FastAPI lifespan loops every 15 minutes to call `collector_manager.get_all()`.
3.  **UI Harmony**: The dashboard's 60-second auto-refresh hits the `/api/limits` endpoint, fetching mostly cached data (respecting TTLs), preventing API rate limits while ensuring the dashboard and background tasks stay synchronized.

---

## 6. Backup & Export Strategy

1.  **Full Folder Backup (Native)**: Users can directly copy the `~/.runway/` directory (containing `runway.db` and `.secret.key`) to migrate a fully functional instance.
2.  **JSON Export (Settings UI)**: 
    - **Export**: Backend endpoint `/api/backup/export` reads `ProviderConfig`, decrypts the keys, and outputs a clean `runway-backup.json` file.
    - **Import**: Backend endpoint `/api/backup/import` reads the JSON, re-encrypts the keys using the *current machine's* `.secret.key`, and upserts the DB.

---

## 7. Next Steps for Implementation

1.  **Backend Foundations**: Install `sqlmodel` & `cryptography`. Scaffold the `runway.db` connection and tables.
2.  **Security Layer**: Build the Fernet key generator and encrypt/decrypt utility functions.
3.  **History Integration**: Implement the 15-minute background loop and the `UsageSnapshot` insert hook inside `SmartCollector`.
4.  **API Expansion**: Create endpoints for `/api/history/trends`, `/api/config/providers`, `/api/sidecars`, and `/api/backup/...`.
5.  **Frontend Overhaul**: Rebuild `index.html` to support the Top Navbar, build `history.html` with Chart.js, and build `settings.html` with forms and sidecar data tables.