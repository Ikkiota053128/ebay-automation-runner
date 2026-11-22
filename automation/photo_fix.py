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
ALL = bool(cfg.get("全部の写真を補正"))   # 11/22 11:23 オーナー「他の出品中の写真、これから出品する商品もちゃんと加工して出品して！」
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")
        and (ALL or (r.get("仕入元URL") and not hand_only(r["仕入元URL"]) and "rakuten" not in r["仕入元URL"]))]
first = list(cfg.get("先に直す") or [])
skip = set(cfg.get("外す") or [])
rows = sorted([r for r in rows if r["SKU"] not in skip], key=lambda r: (r["SKU"] not in first, first.index(r["SKU"]) if r["SKU"] in first else 0))
if cfg.get("先に直すだけ"):
    rows = [r for r in rows if r["SKU"] in first]
for r in rows:
    if time.time() > t_end:
        out["時間切れ"] = True
        break
    if len(out["直した"]) + len(out["直す予定"]) >= n_max:
        break
    sku = r["SKU"]
    d = done.get(sku, {})
    redo = sku in set(cfg.get("やり直し") or [])
    hires = sku in set(cfg.get("解像度の直し") or [])   # 11/22 15:40 小さい版（400ピクセル）で上げ直してしまった品を、仕入れ先の元の大きさで直す
    redo = redo or hires or sku in set(cfg.get("1枚目だけ正方形") or []) or sku in set(cfg.get("1枚目と2枚目を入れ替え") or [])
    tail = []
    if not redo and (d.get("直した日時") or d.get("失敗", 0) >= 2 or (d.get("足せる写真なし") and live and not ALL)):
        continue
    out["見た"] += 1
    try:
        it = eb.inventory_item(sku)
    except EbayError as e:
        continue
    p = it.setdefault("product", {})
    cur = p.get("imageUrls") or []
    src = []
    if r.get("仕入元URL") and not hand_only(r["仕入元URL"]) and (hires or sku not in set(cfg.get("1枚目だけ正方形") or []) | set(cfg.get("1枚目と2枚目を入れ替え") or [])):
        try:
            src = jl.more_photos({"url": r["仕入元URL"], "id": sku, "photos": [], "title": r.get("タイトル") or r.get("商品名") or ""})[:24]
        except Exception:
            src = []
        time.sleep(4)
    sellers = {m.group(1) for m in (jl.SELLER_RX.search(u) for u in cur) if m}
    mixed = len(sellers) > 1   # 今の写真に、ほかの出品者の写真が混ざっている
    if mixed:
        out.setdefault("混ざり", []).append(sku)
    if not redo and len(src) <= len(cur) and not (mixed and src) and not cfg.get("全部の写真を補正"):
        done[sku] = dict(d, 足せる写真なし=True, 見た日時=jst(), 枚数=[len(cur), len(src)])
        continue
    if mixed and not src:
        out.setdefault("混ざり・正しい写真が読めない", []).append(sku)   # 写真を空にしない（人に知らせる）
        continue
    if hires and src:
        if "rakuten" in str(r.get("仕入元URL")) and len(src) < len(cur):
            tail = list(cur[len(src):])   # 楽天は公式APIの3枚だけ元の大きさ。4枚目からは今の写真のまま（もう補正済み・eBay の写真なので混ざらない）
    elif hires and not src:
        continue   # 仕入れ先から取り直せない品は、もう一度上げ直さない（今の大きさのまま）
    elif ALL and not (mixed or len(src) > len(cur)):
        if not cur:
            continue
        src = list(cur)   # 仕入れ先から足せない品は、今の写真をそのまま補正する（メルカリ・楽天・前からの品）
    if sku in set(cfg.get("1枚目と2枚目を入れ替え") or []):   # 11/22 16:29 オーナー「1枚目の写真を2番目の写真に変えられない？」→「2品とも」
        if len(cur) < 2: continue
        src = [cur[1], cur[0]] + list(cur[2:])
        hires, tail = False, []
    sq_only = sku in set(cfg.get("1枚目だけ正方形") or []) and not hires
    if sq_only:
        if not cur: continue
        if not live:
            out["直す予定"].append({"SKU": sku, "1枚目だけ正方形": True}); continue
        try:
            import photo_bright as _pb
            from PIL import Image
            im = _pb.square(Image.open(io.BytesIO(_pb.get_bytes(cur[0]))).convert("RGB"), float((cfg.get("補正") or {}).get("品の大きさ", 0.9)))
            os.makedirs(TMP, exist_ok=True); fp = os.path.join(TMP, sku.replace("/", "_") + "_sq.jpg"); im.save(fp, "JPEG", quality=92)
            src = [eb.upload_image(fp)] + list(cur[1:])
        except Exception as e:
            out["失敗"].append({"SKU": sku, "エラー": "正方形にできない " + str(e)[:150]}); continue
        cfg_b = False
    else:
        cfg_b = sku not in set(cfg.get("1枚目と2枚目を入れ替え") or [])   # 入れ替えだけ（補正し直さない）
    if not live:
        out["直す予定"].append({"楽天の残り": len(tail), "仕入れ先から": bool(src) and src is not cur and src != list(cur), "SKU": sku, "前": len(cur), "後": len(src), "仕入元URL": r["仕入元URL"], "今の写真": cur, "仕入れ先の写真": src})
        continue
    new, nb = [], 0
    try:
        # 11/22 11:13 オーナー「教科書に合わせて」：全部の写真に、写真ごとの強さで明るさの補正（photo_bright）
        if cfg_b and cfg.get("明るく", True):
            import photo_bright
            b = photo_bright.brighten_all(src, eb, sku, cfg.get("補正") or {})
            new, nb = (b, len(b)) if b else (list(src), 0)
            if b and tail:
                new = (new + tail)[:24]
        else:
            new = list(src)
        if not new:
            raise EbayError(0, {"raw": "写真が0枚になるので直さない"})
        p["imageUrls"] = new
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:   # 重さ0は保存で断られる（25709）
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        got = (eb.inventory_item(sku).get("product") or {}).get("imageUrls") or []
        after = len(got)
        ok = after == len(new)
        # 11/22 16:17 オーナー「おすすめで」：写真が前より小さくなっていたら、前の写真に戻して知らせる（今日の 400ピクセルの事故を二度と起こさない）
        import photo_bright as _pb
        b4 = max([x for x in map(_pb.long_side, cur) if x] or [0])
        af = max([x for x in map(_pb.long_side, got) if x] or [0])
        if ok and b4 and af and af < b4 * 0.9:
            p["imageUrls"] = cur
            eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            raise EbayError(0, {"raw": "写真が小さくなる（前 %d → 後 %d ピクセル）ので前の写真に戻した" % (b4, af)})
    except EbayError as e:
        ok, after = False, None
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)})
    if ok:
        if redo:
            cfg["やり直し"] = [x for x in cfg.get("やり直し", []) if x != sku]
            cfg["解像度の直し"] = [x for x in cfg.get("解像度の直し", []) if x != sku]
            cfg["1枚目だけ正方形"] = [x for x in cfg.get("1枚目だけ正方形", []) if x != sku]
            cfg["1枚目と2枚目を入れ替え"] = [x for x in cfg.get("1枚目と2枚目を入れ替え", []) if x != sku]
        done[sku] = {"直した日時": jst(), "前": len(cur), "後": after, "明るくした": nb, "失敗": 0}
        out["直した"].append({"SKU": sku, "前": len(cur), "後": after, "明るくした": nb, "出品ID": r.get("eBayの出品ID", "")})
    else:
        done[sku] = dict(d, 失敗=d.get("失敗", 0) + 1)
if live:
    save_json(P, cfg)
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["直す予定"]), "失敗", len(out["失敗"]))
