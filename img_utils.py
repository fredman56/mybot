from PIL.Image import Image


def down_scale(img: Image, target_width: int, target_height: int) -> Image:
    width, height = img.size

    if (width / target_width) >= 2.0 or (height / target_height) >= 2.0:
        return img.reduce(2)

    return img


def center_crop(img: Image, new_width: int = None, new_height: int = None) -> Image:
    width, height = img.size

    if new_width is None:
        new_width = min(width, height)

    if new_height is None:
        new_height = min(width, height)

    left = int((width - new_width) / 2)
    top = int((height - new_height) / 2)
    right = int((width + new_width) / 2)
    bottom = int((height + new_height) / 2)

    return img.crop((left, top, right, bottom))
