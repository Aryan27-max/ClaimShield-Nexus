"""Theme state (not styling): the visitor's explicit Light / Dark choice from ?theme=, remembered in session state
and kept in the URL; without a choice the app follows the browser / system theme."""
import streamlit as st

THEMES = ("light", "dark")


def chosen_theme() -> str | None:
    """Explicit theme from ?theme= (light | dark), remembered in session state; None = follow the system."""
    try:
        q = st.query_params.get("theme")
        if q in THEMES:
            st.session_state["theme"] = q
        return st.session_state.get("theme")
    except Exception:  # outside a Streamlit script run
        return None


def keep_theme_in_url() -> None:
    """Sidebar navigation drops query params and Streamlit won't set embed_options from Python, so a tiny script puts
    ?theme=…&embed_options=…_theme back (no reload) to keep the choice across refreshes. If the native theme differs
    (e.g. a hand-typed ?theme=dark), it reloads once into the matching native theme."""
    t = chosen_theme()
    if not t:
        return
    n = st.session_state["theme_runs"] = st.session_state.get("theme_runs", 0) + 1  # new content => script re-runs
    st.html(f"""<script>/* run {n} */ (() => {{
      const t = "{t}", u = new URL(window.location.href);
      if (u.searchParams.get("theme") === t && u.searchParams.get("embed_options") === t + "_theme") return;
      u.searchParams.set("theme", t); u.searchParams.set("embed_options", t + "_theme");
      const app = document.querySelector(".stApp"), scheme = app ? getComputedStyle(app).colorScheme : "";
      if (scheme && scheme !== t) window.location.replace(u.toString());
      else window.history.replaceState(window.history.state, "", u.toString());
    }})();</script>""", unsafe_allow_javascript=True)


def mode() -> str:
    """Active theme: the explicit choice, else the browser's (system) theme, else light."""
    t = chosen_theme()
    if t:
        return t
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # no browser context
        return "light"
