#!/usr/bin/env python3
"""Refresh Claude OAuth tokens for all team members (no quota consumption)."""
import json
import time
from pathlib import Path

import httpx


_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_REFRESH_BUFFER_MS = 5 * 60 * 1000


def refresh_token(refresh_token: str) -> bool:
    """Attempt to refresh a single token. Returns True if successful."""
    token = str(refresh_token or "").strip()
    if not token:
        return False
    try:
        resp = httpx.post(
            _TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "xcg-bot/1.0"},
            data={"grant_type": "refresh_token", "refresh_token": token},
            timeout=10.0,
        )
    except Exception:
        return False
    
    if not resp.is_success:
        return False
    
    try:
        payload = resp.json()
    except ValueError:
        return False
    
    return bool(payload.get("access_token"))


def persist_tokens(creds_path: Path, access_token: str, refresh_token: str | None, expires_at_ms: int | None) -> None:
    """Save refreshed tokens to credentials file."""
    try:
        creds = json.loads(creds_path.read_text())
    except (OSError, ValueError):
        return
    
    oauth = creds.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return
    
    oauth["accessToken"] = access_token
    if refresh_token:
        oauth["refreshToken"] = refresh_token
    if expires_at_ms:
        oauth["expiresAt"] = expires_at_ms
    
    try:
        creds_path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    except OSError:
        return


def refresh_all_tokens():
    """Refresh OAuth tokens for all team members without hitting usage API."""
    members_file = Path(__file__).parent.parent.parent / "members.json"
    members_data = json.loads(members_file.read_text())
    
    for member in members_data.get("members", []):
        profile_dir = Path(member["profile_dir"]).expanduser()
        for sub in member.get("subscriptions", []):
            if sub["type"] == "claude_oauth":
                creds_path = profile_dir / ".credentials.json"
                if not creds_path.exists():
                    continue
                
                try:
                    creds = json.loads(creds_path.read_text())
                except (OSError, ValueError):
                    continue
                
                oauth = creds.get("claudeAiOauth", {})
                refresh_token_val = str(oauth.get("refreshToken") or "").strip()
                expires_at_ms = oauth.get("expiresAt", 0)
                now_ms = int(time.time() * 1000)
                
                # Only refresh if token is close to expiry or already expired
                if expires_at_ms and expires_at_ms <= (now_ms + _REFRESH_BUFFER_MS):
                    if refresh_token_val:
                        # Try to refresh
                        result = httpx.post(
                            _TOKEN_URL,
                            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "xcg-bot/1.0"},
                            data={"grant_type": "refresh_token", "refresh_token": refresh_token_val},
                            timeout=10.0,
                        )
                        
                        if result.is_success:
                            try:
                                payload = result.json()
                                access_token = str(payload.get("access_token") or "").strip()
                                new_refresh = str(payload.get("refresh_token") or "").strip() or None
                                expires_in = payload.get("expires_in")
                                refreshed_expires_at = (
                                    int(time.time() * 1000) + int(float(expires_in) * 1000)
                                    if isinstance(expires_in, (int, float)) and float(expires_in) > 0
                                    else None
                                )
                                if access_token:
                                    persist_tokens(creds_path, access_token, new_refresh, refreshed_expires_at)
                            except (ValueError, TypeError):
                                pass


if __name__ == "__main__":
    refresh_all_tokens()
