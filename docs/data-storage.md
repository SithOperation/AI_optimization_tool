# Data storage

Desktop data is rooted at `%LOCALAPPDATA%\AIOptimizationTool\`: SQLite in `database`, structured logs in `logs`, recoverable copies in `backups`, exports in `exports`, disposable artifacts in `cache`, and configuration in `config`. `AIOPT_DATA_DIR` supports controlled tests. Nothing is stored beneath Program Files.

Developer mode uses `database/sqlite/development-data`; Docker uses its named volume. Upgrades do not replace user data and uninstall does not delete it automatically.
