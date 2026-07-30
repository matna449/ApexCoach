---
status: accepted
---

# Derive the token-storage Fernet key from a dedicated APEX_ENCRYPTION_KEY, not WHOOP_CLIENT_SECRET

API Integration Contract §2.1's security note says `oauth_tokens` is "encrypted at rest using Fernet symmetric encryption. The encryption key is derived from WHOOP_CLIENT_SECRET — no separate key management required." Building F10.2 (`db/token_repository.py`) surfaced two problems with this as written: SDD §6.3 documents `WHOOP_CLIENT_SECRET` and `STRAVA_CLIENT_SECRET` as two separate per-provider values, so literally following the security note would mean Strava's tokens are confidentiality-dependent on WHOOP's OAuth app secret — an odd coupling with no stated reason. Separately, a raw OAuth client secret is not itself a valid Fernet key (Fernet requires a 32-byte url-safe base64-encoded value), and no key-derivation function was specified.

We're introducing a new `.env` variable, `APEX_ENCRYPTION_KEY` (an athlete-generated passphrase, set once at setup), and deriving the actual Fernet key from it via `PBKDF2HMAC` (`cryptography.hazmat.primitives.kdf.pbkdf2`) with a fixed, application-specific salt constant. One key encrypts both providers' rows — v1.0 is a single local SQLite file for a single athlete, so per-provider key separation would add complexity without a corresponding threat it defends against. The fixed salt (rather than a random per-installation salt) is deliberate: this is a single-secret, single-machine KDF input, not a password hash defending against rainbow-table attacks across many users, so the salt's job here is domain separation, not per-user uniqueness.

Alternative considered: follow the docs literally and derive the key from `WHOOP_CLIENT_SECRET` via the same KDF. Rejected because tying local database encryption to a third-party OAuth app secret means rotating that secret (e.g. after re-registering the WHOOP app) silently invalidates every stored token, and a future reader would reasonably ask why Strava's confidentiality depends on WHOOP at all.
