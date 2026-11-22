"""出品中の写真の大きさと「品が写真の中でどれくらいの広さか」を読むだけ（手で動かす・eBay は変えない）。
11/22 15:40 オーナー「なぜ写真がこんなに小さい？どうにかならない？」の原因調べ。
- data/判定/写真の大きさ_対象.json の SKU（無ければ出品中から40品）の1枚目の写真を読む。
- 結果は data/判定/写真の大きさ.json、見本の小さい写真は data/ログ/写真の大きさ/。"""
import io, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, jst, load_json, save_json, read_ledger
from PIL import Image, ImageChops

def get(u):
    if "ebayimg.com" in u:
        u = re.sub(r"/s-l\d+\.", "/s-l1600.", u)
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()

def measure(im):
    im = im.convert("RGB")
    w, h = im.size
    bg = Image.new("RGB", im.size, im.getpixel((2, 2)))
    diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 30 else 0)
    bb = diff.getbbox() or (0, 0, w, h)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    return {"幅": w, "高さ": h, "品の幅の割合": round(bw / w, 2), "品の高さの割合": round(bh / h, 2),
            "品の広さの割合": round(bw * bh / (w * h), 2), "背景の色": im.getpixel((2, 2))}

eb = Ebay()
want = load_json(os.path.join(ROOT, "data", "判定", "写真の大きさ_対象.json"), [])
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and not r["SKU"].startswith("STK-")]
skus = want or [r["SKU"] for r in rows][-40:]
od = os.path.join(ROOT, "data", "ログ", "写真の大きさ"); os.makedirs(od, exist_ok=True)
out = {"時刻": jst(), "品": {}}
for s in skus:
    try:
        urls = (eb.inventory_item(s).get("product") or {}).get("imageUrls") or []
        if not urls: continue
        im = Image.open(io.BytesIO(get(urls[0])))
        m = measure(im); m["枚数"] = len(urls)
        out["品"][s] = m
        t = im.convert("RGB"); t.thumbnail((500, 500)); t.save(os.path.join(od, s + ".jpg"), quality=80)
    except Exception as e:
        out["品"][s] = {"エラー": str(e)[:200]}
v = [x for x in out["品"].values() if "品の広さの割合" in x]
if v:
    out["まとめ"] = {"品数": len(v), "広さの平均": round(sum(x["品の広さの割合"] for x in v) / len(v), 2),
                  "横長(幅/高さ>1.2)": sum(1 for x in v if x["幅"] / x["高さ"] > 1.2),
                  "長い辺1000未満": sum(1 for x in v if max(x["幅"], x["高さ"]) < 1000)}
save_json(os.path.join(ROOT, "data", "判定", "写真の大きさ.json"), out)
print("見た", len(out["品"]))
