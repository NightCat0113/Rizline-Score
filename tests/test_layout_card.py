from PIL import Image, ImageDraw

from bot.ui.layout_card import _open_avatar_ring


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


def test_other_layouts_keep_a_white_avatar_disk():
    image = _dashed_sun((420, 560), (140, 410), 80)
    opened = _open_avatar_ring(image, "00036")
    assert opened is not None
    assert opened.getpixel((140, 410)) == (255, 255, 255, 255)
