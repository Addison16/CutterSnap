from conftest import iou

from cuttersnap.segment import segment


def test_iced_star_traced_at_biscuit_edge(star_photo):
    img, truth = star_photo
    mask = segment(img, (130, 50, 540, 520))
    assert iou(mask, truth) > 0.95


def test_whole_frame_when_no_box(star_photo):
    img, truth = star_photo
    assert iou(segment(img), truth) > 0.93


def test_white_on_white_follows_rim(white_on_white):
    img, truth = white_on_white
    mask = segment(img, (60, 80, 380, 390), fg=[(250, 250)])
    assert iou(mask, truth) > 0.95
