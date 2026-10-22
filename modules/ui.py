"""Shared presentation helpers; no student data or theme is stored globally."""

from __future__ import annotations

from base64 import b64encode
from html import escape
from pathlib import Path
from typing import Iterable

import streamlit as st


def theme_colors(mode: str) -> dict[str, str]:
    """Return a fresh accessible palette for the selected appearance."""
    if mode == "Dark":
        return {
            "scheme": "dark",
            "bg": "#25292e",
            "surface": "#30353b",
            "sidebar": "#2b3035",
            "text": "#edf2f4",
            "muted": "#bac5cb",
            "border": "#6a7d92",
            "accent": "#61d5bf",
            "accent_soft": "#304b46",
            "coral": "#f4a094",
            "gold": "#e9c16d",
            "blue": "#9abce9",
            "button_text": "#173832",
        }
    return {
        "scheme": "light",
        "bg": "#f7f9fb",
        "surface": "#ffffff",
        "sidebar": "#eef3f2",
        "text": "#263641",
        "muted": "#60717d",
        "border": "#d7e0e5",
        "accent": "#087f72",
        "accent_soft": "#e3f2ee",
        "coral": "#c55346",
        "gold": "#947019",
        "blue": "#476fa6",
        "button_text": "#ffffff",
    }


def current_colors() -> dict[str, str]:
    """Read only a UI preference from this Streamlit session."""
    return theme_colors(st.session_state.get("ui_theme", "Light"))


def render_shell() -> None:
    """Apply light/dark appearance and reduced-motion-aware interaction styles."""
    assets = Path(__file__).resolve().parents[1] / "assets"
    logo = b64encode((assets / "studentreplica-logo.png").read_bytes()).decode("ascii")
    brand = (
        '<img class="brand-logo" src="data:image/png;base64,'
        f'{logo}" width="44" height="44" alt="" aria-hidden="true">'
        '<span class="brand-word">Student<span>Replica</span></span>'
    )
    with st.sidebar:
        st.markdown(
            f'<div class="sidebar-brand brand-lockup">{brand}</div>',
            unsafe_allow_html=True,
        )
        st.radio("Appearance", ["Light", "Dark"], horizontal=True, key="ui_theme")
    colors = current_colors()
    variables = ";".join(f"--tc-{key}:{value}" for key, value in colors.items())
    css = (assets / "app.css").read_text(encoding="utf-8")
    st.markdown(f"<style>:root{{{variables}}}{css}</style>", unsafe_allow_html=True)
    st.markdown(
        f'<header class="app-brand"><div class="brand-lockup">{brand}</div>'
        '<div class="brand-context">Student workspace</div></header>',
        unsafe_allow_html=True,
    )


def render_bullets(items: Iterable[str], *, empty: str = "Nothing flagged.") -> None:
    """Render untrusted AI/student strings as escaped readable list items."""
    values = [str(item) for item in items if item]
    if not values:
        st.caption(empty)
        return
    body = "".join(f"<li>{escape(item)}</li>" for item in values)
    st.markdown(f'<ul class="readable-list">{body}</ul>', unsafe_allow_html=True)


def insight_group(title: str, items: Iterable[str], tone: str) -> None:
    """A compact unframed insight column, without raw JSON or nested cards."""
    tone = tone if tone in ("positive", "attention", "risk") else "attention"
    st.markdown(
        f'<h4 class="insight-heading {tone}">{escape(title)}</h4>',
        unsafe_allow_html=True,
    )
    render_bullets(items)
