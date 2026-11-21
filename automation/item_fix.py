"""出品中の品の タイトル・商品の項目（アイテムの詳細）を直す（手で動かす）。11/21 17:47 オーナー「1〜3お願いします」
使い方（data/判定/商品の直し.json）：
  {"本番": false, "タイトル": {SKU: 新しいタイトル}, "項目": {SKU: {項目名: [値]}}, "腕時計の項目を作る": 20}
- 「腕時計の項目を作る」があると、出品中の腕時計（カテゴリ 31387）から、まだ直していない品をその数だけ選び、
  タイトルと仕入れ先の説明（cond_note.source_text）から、はっきり読める項目だけを作って「項目」に足す（ドライラン）。
- 「本番」が true のときだけ eBay を書き換える：商品を読み（GET）→ タイトルを差しかえ／項目は空いているものだけ足す（今ある値は変えない）
  → 商品をまるごと保存（PUT）→ 読み直して本当に変わったか確かめる（10章 3）。同じSKUが2回失敗したらくり返さない（10章 4）。
- 結果は data/判定/商品の直し_結果.json。台帳のタイトルは、本番で直した品だけ合わせる。"""
import json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "商品の直し.json")
RP = os.path.join(ROOT, "data", "判定", "商品の直し_結果.json")


def has(rx, t):
    return re.search(rx, t, re.I) is not None


def watch_aspects(title, text):
    t = "%s\n%s" % (title, text or "")
    a = {}
    if has(r"レディース|ladies|women", t) and not has(r"メンズ|\bmen'?s\b", t):
        a["Department"] = ["Women"]
    elif has(r"メンズ|\bmen'?s\b|\bmen\b", t) and not has(r"レディース|ladies|women", t):
        a["Department"] = ["Men"]
    if has(r"アナデジ|ana-?digi|analog.{0,3}digital", t):
        a["Display"] = ["Analog & Digital"]
    elif has(r"デジタル|\bdigital\b", t) and not has(r"アナログ|\banalog", t):
        a["Display"] = ["Digital"]
    elif has(r"アナログ|\banalog", t) and not has(r"デジタル|\bdigital\b", t):
        a["Display"] = ["Analog"]
    if has(r"自動巻|automatic|オートマチック", t):
        a["Movement"] = ["Mechanical (Automatic)"]
    elif has(r"手巻", t):
        a["Movement"] = ["Mechanical (Hand-winding)"]
    elif has(r"ソーラー|\bsolar\b|eco-?drive|エコ・?ドライブ", t):
        a["Movement"] = ["Solar"]
    elif has(r"キネティック|kinetic", t):
        a["Movement"] = ["Kinetic"]
    elif has(r"クオーツ|クォーツ|\bquartz\b", t):
        a["Movement"] = ["Quartz"]
    f = []
    for rx, en in [(r"電波|radio.?control|atomic|multiband|マルチバンド", "Radio Controlled"), (r"ソーラー|\bsolar\b|eco-?drive", "Solar Powered"),
                   (r"ワールドタイム|world ?time", "World Time"), (r"アラーム|\balarm\b", "Alarm"), (r"ストップウォッチ|stopwatch", "Stopwatch"),
                   (r"クロノグラフ|chronograph", "Chronograph"), (r"ライト|\bled\b|backlight|ルミナス|蓄光|luminous", "Luminous Hands"),
                   (r"bluetooth|ブルートゥース|スマートフォンリンク|smartphone link", "Bluetooth"), (r"カレンダー|デイデイト|day.?date", "Date Indicator")]:
        if has(rx, t):
            f.append(en)
    if f:
        a["Features"] = f[:8]
    m = re.search(r"(\d{2,3})\s*(?:m|メートル)\s*防水|(\d{1,2})\s*(?:気圧|bar|atm)", t, re.I)
    if m:
        atm = int(m.group(2)) if m.group(2) else int(m.group(1)) // 10
        if atm in (3, 5, 10, 20, 30):
            a["Water Resistance"] = ["%d m (%d ATM)" % (atm * 10, atm)]
    for key, words in (("Case Material", r"ケース"), ("Band Material", r"ベルト|バンド|ブレス")):
        for rx, en in [(r"チタン|titanium", "Titanium"), (r"ステンレス|stainless", "Stainless Steel"), (r"樹脂|レジン|resin", "Resin"),
                       (r"ラバー|ウレタン|rubber|silicone|シリコン", "Rubber"), (r"革|レザー|leather", "Leather"), (r"ナイロン|nylon", "Nylon"),
                       (r"カーボン|carbon", "Carbon")]:
            if re.search(r"(?:%s)\s?[:：]\s?(?:%s)|(?:%s)(?:製の?)?(?:%s)" % (words, rx, rx, words), t, re.I):
                a[key] = [en]
                break
    m = re.search(r"(?:文字盤|ダイアル|ダイヤル|dial)[^。\n]{0,6}?(ブラック|黒|ホワイト|白|ブルー|青|ネイビー|グリーン|緑|シルバー|ゴールド|金|赤|レッド|グレー)|"
                  r"\b(black|white|blue|navy|green|silver|gold|red|gray|grey)\s+dial", t, re.I)
    if m:
        c = (m.group(1) or m.group(2) or "").lower()
        cm = {"ブラック": "Black", "黒": "Black", "ホワイト": "White", "白": "White", "ブルー": "Blue", "青": "Blue", "ネイビー": "Blue", "navy": "Blue",
              "グリーン": "Green", "緑": "Green", "シルバー": "Silver", "ゴールド": "Gold", "金": "Gold", "赤": "Red", "レッド": "Red", "グレー": "Gray", "grey": "Gray"}
        a["Dial Color"] = [cm.get(c, c.capitalize())]
    if has(r"本体のみ|箱なし|箱無し", t):
        a["With Original Box/Packaging"] = ["No"]
    elif has(r"元箱|箱付|箱あり|外箱|化粧箱|with box|w/ ?box", t):
        a["With Original Box/Packaging"] = ["Yes"]
    if has(r"保証書|ギャランティ|warranty card|papers", t) and not has(r"保証書[^。\n]{0,6}(なし|無し)", t):
        a["With Papers"] = ["Yes"]
    return a


def main():
    cfg = load_json(P, {})
    live = bool(cfg.get("本番"))
    eb = Ebay()
    rows = read_ledger()
    by = {r["SKU"]: r for r in rows}
    res = load_json(RP, {"品": {}})
    done = res.setdefault("品", {})
    titles = dict(cfg.get("タイトル") or {})
    aspects = {k: dict(v) for k, v in (cfg.get("項目") or {}).items()}
    n_make = int(cfg.get("腕時計の項目を作る") or 0)
    if n_make:
        import cond_note
        made = 0
        for r in rows:
            if made >= n_make:
                break
            sku = r.get("SKU", "")
            if r.get("状態") != "出品中" or sku in aspects or sku in done or sku.startswith("STK-"):
                continue
            try:
                offs = [o for o in eb.offers_of(sku) if o.get("status") == "PUBLISHED"]
                if not offs or str(offs[0].get("categoryId")) != "31387":
                    continue
                it = eb.inventory_item(sku)
            except EbayError:
                continue
            p = it.get("product") or {}
            have = {k for k, v in (p.get("aspects") or {}).items() if v}
            txt = cond_note.source_text({"url": r.get("仕入元URL", ""), "id": sku, "title": p.get("title", "")}) if r.get("仕入元URL") else ""
            a = watch_aspects(p.get("title", ""), txt)
            mdl = (p.get("aspects") or {}).get("Model")
            if mdl and "MPN" not in have:
                a["MPN"] = mdl[:1]
            a = {k: v for k, v in a.items() if k not in have}
            if a:
                aspects[sku] = a
                made += 1
        cfg["項目"] = aspects
        cfg.pop("腕時計の項目を作る", None)
        save_json(P, cfg)
    if cfg.get("全品のMPN"):   # 11/21 18:47 オーナー「1 → 2 → 3」：型番（Model）があって MPN が空いている品に、同じ型番を MPN として足す
        for r in rows:
            sku = r.get("SKU", "")
            if r.get("状態") != "出品中" or sku.startswith("STK-") or sku in aspects:
                continue
            try:
                pa = (eb.inventory_item(sku).get("product") or {}).get("aspects") or {}
            except EbayError:
                continue
            if pa.get("Model") and not pa.get("MPN"):
                aspects[sku] = {"MPN": pa["Model"][:1]}
        cfg["項目"] = aspects
        cfg.pop("全品のMPN", None)
        save_json(P, cfg)
    out = {"時刻": jst(), "本番": live, "直した": [], "失敗": [], "案": {}}
    import time as _t
    t_end = _t.time() + 60 * float(cfg.get("時間の上限_分", 22))   # workflow の30分で切られないように、時間で区切って次の回へ
    for sku in list(dict.fromkeys(list(titles) + list(aspects))):
        if _t.time() > t_end:
            out["時間切れ"] = True
            break
        if done.get(sku, {}).get("失敗", 0) >= 2:
            out["失敗"].append({"SKU": sku, "エラー": "2回続けて失敗したのでくり返さない"})
            continue
        try:
            it = eb.inventory_item(sku)
        except EbayError as e:
            out["失敗"].append({"SKU": sku, "エラー": err_text(e)})
            continue
        p = it.setdefault("product", {})
        old_t = p.get("title", "")
        asp = p.setdefault("aspects", {})
        add = {k: v for k, v in (aspects.get(sku) or {}).items() if not asp.get(k)}
        new_t = titles.get(sku, old_t)[:80]
        out["案"][sku] = {"タイトル": [old_t, new_t] if new_t != old_t else None, "足す項目": add}
        if not live:
            continue
        p["title"] = new_t
        asp.update(add)
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:   # 重さ0は保存で断られる（25709）ので、重さの欄だけ外す
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        try:
            eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            chk = eb.inventory_item(sku).get("product") or {}
            ok = chk.get("title") == new_t and all(chk.get("aspects", {}).get(k) == v for k, v in add.items())
        except EbayError as e:
            ok = False
            out["失敗"].append({"SKU": sku, "エラー": err_text(e)})
        d = done.setdefault(sku, {})
        if ok:
            d.update({"直した日時": jst(), "失敗": 0})
            out["直した"].append(sku)
            if new_t != old_t and sku in by:
                by[sku]["タイトル"] = new_t
        else:
            d["失敗"] = d.get("失敗", 0) + 1
    if live:
        if any(titles.get(s) for s in out["直した"]):
            save_ledger(rows, ["タイトル"], "商品の直し")
        cfg["本番"] = False
        cfg["タイトル"] = {k: v for k, v in titles.items() if k not in out["直した"]}
        cfg["項目"] = {k: v for k, v in aspects.items() if k not in out["直した"]}
        save_json(P, cfg)
    save_json(RP, dict(res, 最後=out))
    print("本番" if live else "ドライラン", "案", len(out["案"]), "直した", len(out["直した"]), "失敗", len(out["失敗"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
