# Windows code-signing preparation

Public Windows artifacts should be Authenticode-signed with an organization-controlled code-signing certificate. Development and internal RC builds remain unsigned when no certificate is configured.

## Signing points

1. Sign `src-tauri/target/release/ai-optimization-tool.exe` after Tauri compilation and before NSIS packaging.
2. Sign the packaged backend executable before it is embedded in the Tauri resources.
3. Sign the final `src-tauri/target/release/bundle/nsis/*-setup.exe` after NSIS finishes.
4. Recalculate the published SHA-256 checksum only after the final installer signature is applied.

Use SHA-256 file digests and an RFC 3161 timestamp service. Timestamping is required so signatures remain verifiable after certificate expiration.

## Certificate and CI handling

Store the certificate in a managed signing service or an encrypted GitHub Actions secret. Never commit a PFX, password, private key, or decoded certificate. Limit signing secrets to protected release environments and intentional tags. Mask secrets and remove temporary certificate files in an `always()` cleanup step.

The signing step must be conditional: if signing inputs are absent, CI logs an unsigned-RC notice and continues; if signing was explicitly requested and signing or timestamping fails, the release job fails and must not upload a public artifact.

Verify both executable and installer signatures with:

```powershell
Get-AuthenticodeSignature .\src-tauri\target\release\ai-optimization-tool.exe
Get-AuthenticodeSignature '.\src-tauri\target\release\bundle\nsis\AI Optimization Tool_0.13.0_x64-setup.exe'
```

Both must report `Valid`, the expected signer subject, and a trusted timestamp before public distribution.
