"""Native Streamlit Google OIDC integration without shared student state."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.util import find_spec
from typing import NoReturn
from urllib.parse import urlsplit

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
from streamlit.errors import StreamlitAPIException

from modules.ui import render_shell
from storage.auth import login_google_account
from storage.database import session_scope


GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


@dataclass(frozen=True)
class GoogleLoginSettings:
    """Public readiness metadata only; credentials remain in Streamlit Secrets."""

    available: bool = False
    provider: str | None = "google"


def google_login_settings() -> GoogleLoginSettings:
    """Disable incomplete setup without disrupting password or demo sign-in."""
    try:
        auth = st.secrets.get("auth", {})
        if not isinstance(auth, Mapping):
            return GoogleLoginSettings()
        provider = "google" if "google" in auth else None
        google = auth.get("google", {}) if provider else auth
        if not isinstance(google, Mapping):
            return GoogleLoginSettings()
        fields = [
            auth.get("redirect_uri"), auth.get("cookie_secret"),
            google.get("client_id"), google.get("client_secret"),
        ]
        if any(
            not isinstance(value, str) or not value.strip()
            or value.lower().startswith(("replace", "your-", "xxx"))
            for value in fields
        ):
            return GoogleLoginSettings()
        redirect, cookie_secret, client_id, _client_secret = fields
        url = urlsplit(redirect)
        valid_url = (
            bool(url.hostname) and not url.username and not url.password
            and not url.query and not url.fragment
            and url.path.endswith("/oauth2callback")
            and (url.scheme == "https" or (
                url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
            ))
        )
        if (
            not valid_url or len(cookie_secret) < 32
            or not client_id.endswith(".apps.googleusercontent.com")
            or google.get("server_metadata_url") != GOOGLE_METADATA_URL
            or find_spec("authlib") is None
        ):
            return GoogleLoginSettings()
        return GoogleLoginSettings(available=True, provider=provider)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return GoogleLoginSettings()


def clear_login_state() -> None:
    """Drop the old student's forms and identifiers, retaining appearance flags."""
    force_mock = bool(st.session_state.get("ai_force_mock", False))
    theme = st.session_state.get("ui_theme", "Light")
    st.session_state.clear()
    st.session_state["ai_force_mock"] = force_mock
    st.session_state["ui_theme"] = theme
    st.session_state["logged_in"] = False
    st.session_state["auth_mode"] = "Log in"
    try:
        st.query_params.pop("session", None)
    except Exception:
        pass


def logout_current_session() -> None:
    """Clear both app state and the native identity cookie for Google sign-ins."""
    native_login = st.user.get("is_logged_in", False) is True
    clear_login_state()
    if native_login:
        st.logout()
        st.stop()
    st.rerun()


def _reject_google_login(message: str) -> NoReturn:
    """Stop before loading any student record if the native identity is unusable."""
    clear_login_state()
    render_shell()
    st.error(message)
    if st.button("Return to sign in", icon=":material/logout:"):
        st.logout()
    st.stop()


def sync_google_login() -> None:
    """Restore the private account from Streamlit's verified identity on reruns."""
    if st.user.get("is_logged_in", False) is not True:
        if st.session_state.get("auth_provider") == "google":
            clear_login_state()
        return
    if not google_login_settings().available:
        _reject_google_login("Google sign-in is currently unavailable. Please sign in again later.")
    try:
        with session_scope() as session:
            result = login_google_account(session, st.user)
    except ValueError:
        _reject_google_login(
            "Your Google sign-in has expired or could not be verified. "
            "Please sign in again."
        )
    except SQLAlchemyError as error:
        logging.getLogger("student_twin.auth").warning(
            "event=google_sign_in_failed error_type=%s", type(error).__name__
        )
        _reject_google_login(
            "Google sign-in could not finish saving your account. "
            "Please try again later."
        )
    if not result.ok or not result.user_id:
        _reject_google_login(result.message)
    if (
        st.session_state.get("user_id") != result.user_id
        or st.session_state.get("auth_provider") != "google"
    ):
        clear_login_state()
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = result.user_id
    st.session_state["auth_provider"] = "google"
    try:
        from storage.session_token import create_session_token

        st.query_params["session"] = create_session_token(result.user_id)
    except Exception:
        pass


def render_google_login() -> None:
    """Render the Google command, disabled until the deployment is configured."""
    settings = google_login_settings()
    if st.button(
        "Continue with Google", key="google_sign_in", icon=":material/login:",
        width="stretch", disabled=not settings.available,
        help=None if settings.available else (
            "Google sign-in has not been configured by the app administrator."
        ),
    ):
        try:
            st.login(settings.provider)
        except StreamlitAPIException:
            st.error("Google sign-in could not start. Please contact the app administrator.")
    if not settings.available:
        st.caption("Google sign-in is currently unavailable.")
    st.divider()
