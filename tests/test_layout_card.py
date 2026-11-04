from PIL import Image, ImageDraw

from bot.ui.layout_card import _neon_core_frac, _open_avatar_ring, _quad_matching_content


def _dashed_sun(size: tuple[int, int], center: tuple[int, int], radius: int) -> Image.Image:
    image = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    cx, cy = center
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    for start in range(0, 360, 30):
        draw.arc(box, start, start + 14, fill=(0, 0, 0, 255), width=12)
    return image


def test_layout_31_avatar_ring_interior_is_transparent():
    image = _dashed_sun((420, 560), (140, 410), 80)
    opened = _open_avatar_ring(image, "00031")
    assert opened is not None
    assert opened.getpixel((140, 410))[3] == 0
    assert opened.getpixel((20, 20)) == (255, 255, 255, 255)
    dash = opened.getpixel((140 + 80, 410))
    assert dash[3] == 255 and dash[0] < 40


def test_neon_core_is_the_solid_lines_not_the_bloom():
    image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 5, 89, 74), fill=(255, 0, 126, 20))
    draw.rectangle((20, 15, 79, 18), fill=(255, 253, 253, 255))
    draw.rectangle((20, 60, 79, 63), fill=(255, 253, 253, 255))
    frac = _neon_core_frac(image)
    assert frac is not None
    left, top, right, bottom = frac
    assert abs(left - 0.20) < 0.02
    assert abs(top - 15 / 80) < 0.02
    assert abs(right - 0.80) < 0.02
    assert abs(bottom - 64 / 80) < 0.02


def test_plate_quad_lands_on_the_neon_lines():
    corners = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 200.0, 0.0), (0.0, 200.0, 0.0)]
    fitted = _quad_matching_content(corners, (0.1, 0.1, 0.9, 0.9), (0.2, 0.3, 0.8, 0.7))
    # Visible content is the inner 80% of the fitted quad, and that lands on the target.
    bottom_left, _bottom_right, top_right, top_left = fitted
    content_left = top_left[0] + (top_right[0] - top_left[0]) * 0.1
    content_top = top_left[1] + (bottom_left[1] - top_left[1]) * 0.1
    content_right = top_left[0] + (top_right[0] - top_left[0]) * 0.9
    content_bottom = top_left[1] + (bottom_left[1] - top_left[1]) * 0.9
    assert abs(content_left - 20) < 0.01
    assert abs(content_right - 80) < 0.01
    assert abs(content_top - 140) < 0.01
    assert abs(content_bottom - 60) < 0.01


def test_other_layouts_keep_a_white_avatar_disk():
    image = _dashed_sun((420, 560), (140, 410), 80)
    opened = _open_avatar_ring(image, "00036")
    assert opened is not None
    assert opened.getpixel((140, 410)) == (255, 255, 255, 255)
