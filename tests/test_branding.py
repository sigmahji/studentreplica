"""Product identity and transparent logo checks without student data."""

from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest


def test_logo_is_nonblank_with_a_transparent_background() -> None:
    logo = Path(__file__).resolve().parents[1] / "assets" / "studentreplica-logo.png"
    with Image.open(logo) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.width == image.height
        assert image.getchannel("A").getextrema() == (0, 255)
        assert image.getchannel("A").getbbox() is not None


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_header_and_sidebar_use_studentreplica_in_both_themes(theme: str) -> None:
    app = AppTest.from_string("from modules.ui import render_shell\nrender_shell()")
    app.session_state["ui_theme"] = theme
    app.run()
    assert not app.exception
    markup = [element.value for element in app.markdown]
    assert sum("Student<span>Replica</span>" in item for item in markup) == 2
    assert sum('class="brand-logo"' in item for item in markup) == 2
    assert sum("data:image/png;base64," in item for item in markup) == 2
    assert all("TwinCareer" not in item for item in markup)
    assert app.session_state["ui_theme"] == theme
