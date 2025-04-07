from io import BytesIO

from rembg import remove
from telegram import Update, InputSticker
from PIL.Image import open as img_open

from error import NoEmojiSent
from img_utils import center_crop, down_scale


class DefaultStickerSize:
    WIDTH = 512
    HEIGHT = 512


async def create_new_sticker(update: Update, rembg_session):
    try:
        emoji_list = list(update.message.caption)
    except TypeError:
        raise NoEmojiSent()

    photo = update.message.photo[-1]
    image_file = await photo.get_file()
    image_data = bytes(await image_file.download_as_bytearray())

    with BytesIO(image_data) as bytes_io_image:
        reduced_image = down_scale(img_open(bytes_io_image), DefaultStickerSize.WIDTH, DefaultStickerSize.HEIGHT)
        cropped_image = center_crop(reduced_image, DefaultStickerSize.WIDTH, DefaultStickerSize.HEIGHT)

    image_without_bg = remove(cropped_image, session=rembg_session)

    with BytesIO() as img_buffer:
        image_without_bg.save(img_buffer, format="png")
        img_bytes = img_buffer.getvalue()

    return InputSticker(img_bytes, emoji_list)
