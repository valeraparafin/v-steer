import pytest

from vsteer.ui.icon import ACTIVE_SCHEME, SCHEMES, IconState, render

# Sample points on the 256 px image (geometry is a 512-unit canvas, halved).
ARROW_TIP = (222, 135)  # right arrow, just inside its tip
V_ARM = (96, 108)  # on the left arm of the V
OUTLINE = (128, 6)  # top edge, inside the outline stroke


def _near(rgba, hex_colour: str, tolerance: int = 40) -> bool:
    want = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= tolerance for a, b in zip(rgba[:3], want))


@pytest.mark.parametrize("size", [16, 32, 256])
@pytest.mark.parametrize("state", list(IconState))
def test_every_state_renders_at_tray_and_file_sizes(state, size):
    img = render(state, size)
    assert img.size == (size, size) and img.mode == "RGBA"


def test_d_prime_is_the_default_scheme():
    assert ACTIVE_SCHEME == "D'"


def test_ready_is_the_normal_icon():
    img = render(IconState.READY, 256)
    assert _near(img.getpixel(ARROW_TIP), "#FF7A1A") and _near(img.getpixel(V_ARM), "#FFFFFF")
    assert _near(img.getpixel(OUTLINE), "#16181D")


def test_partial_is_grey_with_a_yellow_outline():
    img = render(IconState.PARTIAL, 256)
    assert _near(img.getpixel(V_ARM), "#8B8F98") and _near(img.getpixel(ARROW_TIP), "#6B6F78")
    assert _near(img.getpixel(OUTLINE), "#F2C230")


def test_idle_has_no_outline():
    img = render(IconState.IDLE, 256)
    assert _near(img.getpixel(V_ARM), "#8B8F98") and _near(img.getpixel(OUTLINE), "#16181D")


def test_error_has_red_arrows_and_outline():
    img = render(IconState.ERROR, 256)
    assert _near(img.getpixel(ARROW_TIP), "#E5484D") and _near(img.getpixel(OUTLINE), "#E5484D")
    assert _near(img.getpixel(V_ARM), "#FFFFFF")


def test_scheme_d_outlines_ready_in_green():
    assert _near(render(IconState.READY, 256, "D").getpixel(OUTLINE), "#3FB950")


def test_scheme_b_shows_a_dot():
    assert _near(render(IconState.PARTIAL, 256, "B").getpixel((210, 210)), "#F2C230")


@pytest.mark.parametrize("scheme", ["A", "B", "C", "D", "D'"])
def test_every_kept_scheme_renders_every_state(scheme):
    assert set(SCHEMES[scheme]) == set(IconState)
    for state in IconState:
        render(state, 32, scheme)
