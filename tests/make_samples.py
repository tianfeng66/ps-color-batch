"""生成覆盖各种格式 / 模式的测试图。用法：python3 tests/make_samples.py <输出目录>"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms


def gradient(w, h):
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    hue = (x * 6) % 6
    r = np.clip(np.abs(hue - 3) - 1, 0, 1)
    g = np.clip(2 - np.abs(hue - 2), 0, 1)
    b = np.clip(2 - np.abs(hue - 4), 0, 1)
    rgb = np.concatenate([r, g, b], axis=2)
    light = 1 - y
    rgb = np.where(light > 0.5, rgb + (1 - rgb) * (light - 0.5) * 2, rgb * light * 2)
    return (rgb * 255).round().astype(np.uint8)


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    (out / "子文件夹").mkdir(exist_ok=True)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

    im = Image.fromarray(gradient(1200, 800))
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "TestCam"
    im.save(out / "01_带ICC和旋转.jpg", quality=92, icc_profile=srgb, exif=exif.tobytes(), dpi=(300, 300))

    rgba = np.dstack([gradient(900, 600), np.tile(np.linspace(255, 0, 900, dtype=np.uint8), (600, 1))])
    Image.fromarray(rgba).save(out / "02_透明.png")

    Image.fromarray(gradient(1000, 1000)).save(out / "03_LZW.tif", compression="tiff_lzw", dpi=(72, 72))
    Image.fromarray(gradient(800, 600)).convert("L").save(out / "04_灰度.jpg", quality=90)
    Image.fromarray(gradient(800, 600)).convert("CMYK").save(out / "05_CMYK.jpg", quality=90)
    Image.fromarray(gradient(640, 480)).save(out / "子文件夹" / "06_子文件夹里的图.webp", quality=90)
    Image.fromarray(gradient(6000, 4000)).save(out / "07_大图6000x4000.jpg", quality=92)
    print("已生成到", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
