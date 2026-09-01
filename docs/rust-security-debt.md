# Rust security debt

The v0.13 Windows release is reviewed with `cargo audit --file src-tauri/Cargo.lock` and target-specific `cargo tree` queries. Advisories are not globally suppressed.

## Triage

| Advisory group | Classification | Windows relevance | Disposition |
| --- | --- | --- | --- |
| `atk`, `atk-sys`, `gdk`, `gdk-sys`, `gdkwayland-sys`, `gdkx11`, `gdkx11-sys`, `gtk`, `gtk-sys`, `gtk3-macros` | Unmaintained, cross-platform transitive | Not present in `cargo tree --target x86_64-pc-windows-msvc`; Linux GTK/WebKit only | Upstream Tauri dependency debt; retain until Tauri removes GTK3 support dependencies. |
| `glib` RUSTSEC-2024-0429 | Unsound iterator implementation, cross-platform transitive | Not present in the Windows target graph | Upstream Linux dependency debt. No affected iterator is used by this application. |
| `proc-macro-error` RUSTSEC-2024-0370 | Unmaintained build/procedural dependency | Not present in the Windows target graph | Upstream macro dependency debt; no runtime code shipped on Windows. |
| `unic-char-property`, `unic-char-range`, `unic-common`, `unic-ucd-ident`, `unic-ucd-version` | Unmaintained dependency | Present through `urlpattern` → `tauri-utils` | Upstream dependency debt. These warnings do not describe an exploitable vulnerability; monitor Tauri/urlpattern upgrades. |

The audit currently returns no blocking vulnerability exit and 17 allowed warnings. Dependency replacement is not forced locally because these crates are selected by Tauri and overriding them would destabilize the desktop framework. Re-run the audit on every release and remove this debt when upstream Tauri releases permit it.
