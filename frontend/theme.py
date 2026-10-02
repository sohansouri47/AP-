"""Theme manager for ZAMP Accounts Payable frontend.

Provides high-contrast Light mode (default) and polished Charcoal Dark mode.
"""

from __future__ import annotations

import streamlit as st


def init_theme():
    """Ensure theme state is initialized."""
    if "theme_mode" not in st.session_state:
        st.session_state["theme_mode"] = "Light"
    if "theme_mode_segmented_ctrl" not in st.session_state:
        st.session_state["theme_mode_segmented_ctrl"] = st.session_state["theme_mode"]


def _on_theme_toggle_change():
    """Callback fired immediately when user switches Light or Dark."""
    val = st.session_state.get("theme_mode_segmented_ctrl")
    if val in ("Light", "Dark"):
        st.session_state["theme_mode"] = val


def set_theme(theme: str):
    """Set theme mode and rerun."""
    if theme in ("Light", "Dark") and theme != st.session_state.get("theme_mode"):
        st.session_state["theme_mode"] = theme
        st.session_state["theme_mode_segmented_ctrl"] = theme
        st.rerun()


def get_theme_css() -> str:
    """Generate dynamic CSS tokens and element rules based on theme."""
    is_dark = st.session_state.get("theme_mode", "Light") == "Dark"

    if is_dark:
        # Polished Charcoal Dark Mode
        return """
        <style>
        :root {
            --bg-app: #0f172a;
            --bg-card: #1e293b;
            --bg-card-subtle: #273549;
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --border-strong: #475569;
            --primary: #3b82f6;
            --primary-hover: #60a5fa;

            --badge-green-bg: rgba(6, 78, 59, 0.45);
            --badge-green-text: #4ade80;
            --badge-green-border: #059669;

            --badge-amber-bg: rgba(120, 53, 15, 0.45);
            --badge-amber-text: #fbbf24;
            --badge-amber-border: #d97706;

            --badge-red-bg: rgba(127, 29, 29, 0.45);
            --badge-red-text: #f87171;
            --badge-red-border: #dc2626;

            --badge-blue-bg: rgba(30, 58, 138, 0.45);
            --badge-blue-text: #93c5fd;
            --badge-blue-border: #2563eb;

            --badge-gray-bg: #1e293b;
            --badge-gray-text: #94a3b8;
        }

        .stApp {
            background-color: #0f172a !important;
            color: #f8fafc !important;
        }

        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
        .stApp p, .stApp span, .stApp label, .stApp div {
            color: #f8fafc;
        }

        /* Stepper circle overrides for Dark Mode */
        .stepper-circle-completed {
            background-color: rgba(6, 78, 59, 0.4) !important;
            border-color: #059669 !important;
            color: #4ade80 !important;
        }

        .stepper-circle-warning {
            background-color: rgba(120, 53, 15, 0.4) !important;
            border-color: #d97706 !important;
            color: #fbbf24 !important;
        }

        .stepper-circle-failed {
            background-color: rgba(127, 29, 29, 0.4) !important;
            border-color: #dc2626 !important;
            color: #f87171 !important;
        }

        .stepper-circle-future {
            background-color: #1e293b !important;
            border-color: #334155 !important;
            color: #64748b !important;
        }

        .stepper-message-warning {
            color: #fbbf24 !important;
        }

        .stepper-message-failed {
            color: #f87171 !important;
        }

        /* Header transparent background */
        header[data-testid="stHeader"] {
            background: transparent !important;
        }

        /* Secondary buttons */
        button[kind="secondary"] {
            background-color: #1e293b !important;
            color: #f8fafc !important;
            border: 1px solid #334155 !important;
        }

        button[kind="secondary"]:hover {
            background-color: #334155 !important;
            color: #ffffff !important;
            border-color: #475569 !important;
        }

        button[kind="primary"] {
            background-color: #2563eb !important;
            color: #ffffff !important;
            border: 1px solid #2563eb !important;
        }

        /* Segmented Controls Dark Styling */
        div[role="radiogroup"],
        div[data-testid="stSegmentedControl"],
        div[data-baseweb="button-group"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }

        button[data-variant="segmented_control"],
        div[data-testid="stSegmentedControl"] button,
        div[data-baseweb="button-group"] button {
            background-color: transparent !important;
            border: none !important;
        }

        button[data-variant="segmented_control"] *,
        button[data-variant="segmented_control"],
        div[data-testid="stSegmentedControl"] button *,
        div[data-testid="stSegmentedControl"] button,
        div[data-baseweb="button-group"] button * {
            color: #94a3b8 !important;
        }

        button[data-variant="segmented_control"]:hover *,
        div[data-testid="stSegmentedControl"] button:hover *,
        div[data-baseweb="button-group"] button:hover * {
            color: #f8fafc !important;
        }

        button[data-variant="segmented_control"][data-selected="true"],
        button[data-variant="segmented_control"][aria-checked="true"],
        div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        div[data-baseweb="button-group"] button[aria-checked="true"] {
            background-color: #2563eb !important;
        }

        button[data-variant="segmented_control"][data-selected="true"] *,
        button[data-variant="segmented_control"][aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] button[aria-checked="true"] *,
        div[data-baseweb="button-group"] button[aria-checked="true"] * {
            color: #ffffff !important;
            font-weight: 600 !important;
        }

        /* Popover Dark Styling */
        div[data-testid="stPopoverBody"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            color: #f8fafc !important;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4) !important;
        }

        div[data-testid="stPopoverBody"] * {
            color: #f8fafc !important;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] {
            background-color: #1e293b !important;
            color: #f8fafc !important;
            border: 1px solid #334155 !important;
        }

        div[data-baseweb="popover"], div[data-baseweb="menu"], ul[role="listbox"] {
            background-color: #1e293b !important;
            color: #f8fafc !important;
            border: 1px solid #334155 !important;
        }

        ul[role="listbox"] li {
            background-color: #1e293b !important;
            color: #f8fafc !important;
        }

        ul[role="listbox"] li:hover {
            background-color: #334155 !important;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stExpander"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stExpander"] summary {
            color: #f8fafc !important;
        }

        div[data-testid="stMetricValue"] {
            color: #f8fafc !important;
        }

        div[data-testid="stMetricLabel"] {
            color: #94a3b8 !important;
        }
        </style>
        """
    else:
        # Crisp Light Mode (default)
        return """
        <style>
        :root {
            --bg-app: #f8fafc;
            --bg-card: #ffffff;
            --bg-card-subtle: #f1f5f9;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --border-color: #e2e8f0;
            --border-strong: #cbd5e1;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;

            --badge-green-bg: #f0fdf4;
            --badge-green-text: #166534;
            --badge-green-border: #bbf7d0;

            --badge-amber-bg: #fffbeb;
            --badge-amber-text: #b45309;
            --badge-amber-border: #fde68a;

            --badge-red-bg: #fef2f2;
            --badge-red-text: #991b1b;
            --badge-red-border: #fecaca;

            --badge-blue-bg: #eff6ff;
            --badge-blue-text: #1d4ed8;
            --badge-blue-border: #bfdbfe;

            --badge-gray-bg: #f8fafc;
            --badge-gray-text: #475569;
        }

        .stApp {
            background-color: #f8fafc !important;
            color: #0f172a !important;
        }

        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
        .stApp p, .stApp span, .stApp label, .stApp div {
            color: #0f172a;
        }

        /* Header transparent background */
        header[data-testid="stHeader"] {
            background: transparent !important;
        }

        button[kind="secondary"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #e2e8f0 !important;
        }

        button[kind="secondary"]:hover {
            background-color: #f1f5f9 !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
        }

        button[kind="primary"] {
            background-color: #2563eb !important;
            color: #ffffff !important;
            border: 1px solid #2563eb !important;
        }

        /* Segmented Controls Light Styling */
        div[role="radiogroup"],
        div[data-testid="stSegmentedControl"],
        div[data-baseweb="button-group"] {
            background-color: #f1f5f9 !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
        }

        button[data-variant="segmented_control"],
        div[data-testid="stSegmentedControl"] button,
        div[data-baseweb="button-group"] button {
            background-color: transparent !important;
            border: none !important;
        }

        button[data-variant="segmented_control"] *,
        button[data-variant="segmented_control"],
        div[data-testid="stSegmentedControl"] button *,
        div[data-testid="stSegmentedControl"] button,
        div[data-baseweb="button-group"] button * {
            color: #475569 !important;
        }

        button[data-variant="segmented_control"]:hover *,
        div[data-testid="stSegmentedControl"] button:hover *,
        div[data-baseweb="button-group"] button:hover * {
            color: #0f172a !important;
        }

        button[data-variant="segmented_control"][data-selected="true"],
        button[data-variant="segmented_control"][aria-checked="true"],
        div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        div[data-baseweb="button-group"] button[aria-checked="true"] {
            background-color: #2563eb !important;
        }

        button[data-variant="segmented_control"][data-selected="true"] *,
        button[data-variant="segmented_control"][aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] button[aria-checked="true"] *,
        div[data-baseweb="button-group"] button[aria-checked="true"] * {
            color: #ffffff !important;
            font-weight: 600 !important;
        }

        /* Popover Light Styling */
        div[data-testid="stPopoverBody"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            color: #0f172a !important;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08) !important;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #e2e8f0 !important;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stExpander"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stExpander"] summary {
            color: #0f172a !important;
        }

        div[data-testid="stMetricValue"] {
            color: #0f172a !important;
        }

        div[data-testid="stMetricLabel"] {
            color: #475569 !important;
        }
        </style>
        """


def render_theme_toggle():
    """Render a crystal-clear Light / Dark segmented control toggle."""
    init_theme()

    if "theme_mode_segmented_ctrl" not in st.session_state:
        st.session_state["theme_mode_segmented_ctrl"] = st.session_state["theme_mode"]

    def _on_theme_toggle_change():
        val = st.session_state.get("theme_mode_segmented_ctrl")
        if val in ("Light", "Dark"):
            st.session_state["theme_mode"] = val

    st.segmented_control(
        "Theme mode",
        options=["Light", "Dark"],
        format_func=lambda x: "☀️ Light" if x == "Light" else "🌙 Dark",
        selection_mode="single",
        required=True,
        key="theme_mode_segmented_ctrl",
        label_visibility="collapsed",
        on_change=_on_theme_toggle_change,
    )
