"""写真の明るさの補正（教科書：「出品前に画像の明るさ補正を必ず入れています」）。11/22 11:13 オーナー「教科書に合わせて」
- 全部の写真に、写真ごとにちょうど良い強さで補正する：
  ① 自動コントラスト（いちばん暗い/明るい 0.5% を外して幅を広げる＝くすみを取る）
  ② 明るさ：平均が「目標」より暗いほど強く（最大「最大の倍率」）、もともと明るい写真は「最小の倍率」だけ（白くとばさない）
- 直した写真は eBay（Media API）に上げる。1枚でも失敗したら、その品は元の写真のまま（まぜこぜにしない・25014）。"""
import io, os, urllib.request

TMP = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "photo_bright")


def get_bytes(u):
    # eBay の写真は小さい版（s-l300 など）のアドレスのことがあるので、いちばん大きい版を読む
    import re
    if "ebayimg.com" in u:
        u = re.sub(r"/s-l\d+\.", "/s-l1600.", u)
        u = re.sub(r"/\$_\d+\.(JPG|jpg|PNG|png)", r"/$_57.\1", u)   # $_1 は400ピクセルの版。$_57 がいちばん大きい版
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (ebay-automation photo)", "Referer": u})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def square(im, fill=0.9):
    """1枚目の写真：まわりの余白（背景と同じ色）を切り、背景の色の正方形の中に品を大きく置く（品が枠の9割）。
    11/22 16:17 オーナー「おすすめでお願いします」（一覧は正方形の枠なので、横長だと品が小さく見える）"""
    from PIL import Image, ImageChops
    w, h = im.size
    cs = [im.getpixel(p) for p in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2))]
    bg = tuple(sorted(c[i] for c in cs)[1] for i in range(3))   # 4すみの真ん中あたりの色
    if max(abs(a - b) for c in cs for a, b in zip(c, bg)) > 40:
        return im   # すみの色がばらばら（背景が一色ではない）＝切らない
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L").point(lambda v: 255 if v > 30 else 0)
    bb = diff.getbbox()
    if not bb or (bb[2] - bb[0]) * (bb[3] - bb[1]) < 0.04 * w * h:
        return im   # 品が見つからない・小さすぎる（読みまちがいの恐れ）
    im = im.crop(bb)
    side = int(max(im.size) / fill)
    can = Image.new("RGB", (side, side), bg)
    can.paste(im, ((side - im.size[0]) // 2, (side - im.size[1]) // 2))
    return can


def fix_one(raw, cfg, first=False):
    from PIL import Image, ImageEnhance, ImageOps, ImageStat
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if first and cfg.get("1枚目を正方形", False):   # 11/22 16:30 オーナー「正方形はやめて！」
        im = square(im, float(cfg.get("品の大きさ", 0.9)))
    # eBay は長い辺が500ピクセル未満の写真を断る（25002）。小さい写真は 800 まで拡大する
    if max(im.size) < 500:
        k = 800.0 / max(im.size)
        im = im.resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.LANCZOS)
    im = ImageOps.autocontrast(im, cutoff=float(cfg.get("コントラストの外す割合", 0.5)))
    mean = ImageStat.Stat(im.convert("L")).mean[0]
    f = float(cfg.get("目標", 155)) / max(mean, 1.0)
    f = max(float(cfg.get("最小の倍率", 1.03)), min(float(cfg.get("最大の倍率", 1.25)), f))
    im = ImageEnhance.Brightness(im).enhance(f)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue(), round(mean), round(f, 2)


def long_side(u):
    """eBay の写真のアドレス（.../00/s/<幅X高さ>/...）から、長い辺のピクセルを読む。読めなければ None"""
    import base64, re
    m = re.search(r"/00/s/([A-Za-z0-9=]+)/", str(u))
    try:
        a = base64.b64decode(m.group(1)).decode().upper().split("X")
        return max(int(a[0]), int(a[1]))
    except Exception:
        return None


def brighten_all(urls, eb, sku, cfg=None):
    """全部の写真を補正して eBay に上げたアドレスの一覧を返す。失敗したら None（元の写真のまま使う）"""
    cfg = cfg or {}
    os.makedirs(TMP, exist_ok=True)
    out = []
    try:
        for i, u in enumerate(urls[:24]):
            data, _, _ = fix_one(get_bytes(u), cfg, first=(i == 0))
            p = os.path.join(TMP, "%s_%02d.jpg" % (str(sku).replace("/", "_"), i))
            open(p, "wb").write(data)
            out.append(eb.upload_image(p))
        return out
    except Exception:
        return None
