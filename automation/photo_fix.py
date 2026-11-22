"""出品中の品の写真を、仕入れ先の写真ぜんぶ（24枚まで）に足し直し、暗い写真は少しだけ明るくする（手で動かす）。
11/22 9:41 オーナー「「1 → 2 → 3」でお願いします。明るくする、1と一緒に」
- 対象：出品中（STK- 以外）で、仕入れ先が機械で読める品（メルカリ・Amazon は開かない。楽天は公式APIが最大3枚なので、この回は外す）。
- 仕入れ先の写真が今の eBay の写真より多い品だけ直す。写真の並びは仕入れ先と同じ（1枚目は同じ写真のまま）。
- 明るく：写真の明るさの平均が「暗い線」より下のときだけ、最大 1.2倍まで上げる（色は変えない・白っぽい写真はそのまま）。
  直した写真は eBay（Media API）に上げて、そのアドレスを使う。
- data/判定/写真の直し.json：{"本番": true, "件数": 20, "明るく": true, "暗い線": 140, "最大の倍率": 1.2, "時間の上限_分": 22}
  本番が false の間はドライラン（直す予定の数だけ記録）。件数は1回に直す品の数（はじめはカナリア20・10章）。
- 商品を読み（GET）→ 写真だけ差しかえ → 保存（PUT）→ 読み直して枚数を確かめる（10章 3）。同じSKUが2回失敗したらくり返さない（10章 4）。
- 結果は data/判定/写真の直し_結果.json（品ごとに 前の枚数・後の枚数・明るくした枚数）。"""
import io, json, os, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, hand_only
import judge_list as jl

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "写真の直し.json")
RP = os.path.join(ROOT, "data", "判定", "写真の直し_結果.json")
TMP = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "photo_fix")


def get_bytes(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (ebay-automation photo)", "Referer": u})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def brighten(u, i, sku, cfg):
    """暗い写真だけ少し明るくして eBay に上げ、新しいアドレスを返す。明るくしない写真は元のアドレスのまま"""
    from PIL import Image, ImageEnhance, ImageStat
    raw = get_bytes(u)
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    mean = sum(ImageStat.Stat(im.convert("L")).mean) / 1.0
    line = float(cfg.get("暗い線", 140))
    if mean >= line:
        return u, False
    f = min(float(cfg.get("最大の倍率", 1.2)), line / max(mean, 1.0))
    im = ImageEnhance.Brightness(im).enhance(f)
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, "%s_%02d.jpg" % (sku.replace("/", "_"), i))
    im.save(p, "JPEG", quality=92)
    return eb.upload_image(p), True


cfg = load_json(P, {"本番": False, "件数": 20, "明るく": True})
live = bool(cfg.get("本番"))
eb = Ebay()
res = load_json(RP, {"品": {}})
done = res.setdefault("品", {})
out = {"時刻": jst(), "本番": live, "直した": [], "直す予定": [], "失敗": [], "見た": 0}
t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 22))
n_max = int(cfg.get("件数", 20))
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")
        and r.get("仕入元URL") and not hand_only(r["仕入元URL"]) and "rakuten" not in r["仕入元URL"]]
for r in rows:
    if time.time() > t_end:
        out["時間切れ"] = True
        break
    if len(out["直した"]) + len(out["直す予定"]) >= n_max:
        break
    sku = r["SKU"]
    d = done.get(sku, {})
    if d.get("直した日時") or d.get("失敗", 0) >= 2 or (d.get("足せる写真なし") and live):
        continue
    out["見た"] += 1
    try:
        it = eb.inventory_item(sku)
    except EbayError as e:
        continue
    p = it.setdefault("product", {})
    cur = p.get("imageUrls") or []
    try:
        src = jl.more_photos({"url": r["仕入元URL"], "id": sku, "photos": []})[:24]
    except Exception:
        src = []
    time.sleep(4)
    sellers = {m.group(1) for m in (jl.SELLER_RX.search(u) for u in cur) if m}
    mixed = len(sellers) > 1   # 今の写真に、ほかの出品者の写真が混ざっている
    if mixed:
        out.setdefault("混ざり", []).append(sku)
    if len(src) <= len(cur) and not (mixed and src):
        done[sku] = dict(d, 足せる写真なし=True, 見た日時=jst(), 枚数=[len(cur), len(src)])
        continue
    if not live:
        out["直す予定"].append({"SKU": sku, "前": len(cur), "後": len(src), "仕入元URL": r["仕入元URL"], "今の写真": cur, "仕入れ先の写真": src})
        continue
    new, nb = [], 0
    try:
        for i, u in enumerate(src):
            if cfg.get("明るく", True):
                try:
                    nu, b = brighten(u, i, sku, cfg)
                except Exception:
                    nu, b = u, False   # 取り込めない写真は元のアドレスのまま（写真は減らさない）
                new.append(nu)
                nb += b
            else:
                new.append(u)
        p["imageUrls"] = new
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:   # 重さ0は保存で断られる（25709）
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        after = len((eb.inventory_item(sku).get("product") or {}).get("imageUrls") or [])
        ok = after == len(new)
    except EbayError as e:
        ok, after = False, None
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)})
    if ok:
        done[sku] = {"直した日時": jst(), "前": len(cur), "後": after, "明るくした": nb, "失敗": 0}
        out["直した"].append({"SKU": sku, "前": len(cur), "後": after, "明るくした": nb, "出品ID": r.get("eBayの出品ID", "")})
    else:
        done[sku] = dict(d, 失敗=d.get("失敗", 0) + 1)
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["直す予定"]), "失敗", len(out["失敗"]))
