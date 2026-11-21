"""出品のタイトルと商品の詳細（アイテムの項目）を確かめる（読むだけ・手で動かす）。11/21 17:34 オーナー「アイテム詳細ちゃんと埋めてる？タイトル間違いないか確認して」
- 出品中の品（台帳）ごとに、Inventory API の商品（タイトル・項目）とオファー（カテゴリ）を読む。
- eBay のカテゴリごとの「必須」「おすすめ」の項目（Taxonomy API）と比べ、埋まっていない項目を数える。
- タイトルの点検：80字を超える・日本語が入っている・ブランドや型番がタイトルに無い・カテゴリと違う種類の言葉（例：エフェクターなのに Camera）。
結果は data/判定/商品の詳細の確認.json（買い手の情報は扱わない）。店は何も変えない。"""
import collections, json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger

KIND_WORDS = {
    "camera": r"\bcamera\b|\bslr\b|\bdslr\b|mirrorless|rangefinder|\bfilm\b",
    "lens": r"\blens\b|\bmm\b|\bf/?\d",
    "watch": r"\bwatch\b|wristwatch|chronograph",
    "pedal": r"\bpedal\b|effect|overdrive|distortion|delay|reverb|chorus|fuzz|looper|tuner",
    "audio": r"headphone|earphone|speaker|walkman|minidisc|cassette|turntable|amplifier|receiver|audio player",
    "reel": r"\breel\b|spinning|baitcast",
    "drone": r"\bdrone\b",
}
CAT_KIND = {"31388": "camera", "15230": "camera", "3323": "lens", "31387": "watch", "73839": "audio", "112529": "audio", "36147": "reel"}


def main():
    eb = Ebay()
    kinds = json.load(open(os.path.join(ROOT, "data", "判定", "種類.json"), encoding="utf-8"))
    for k, v in kinds.items():
        if isinstance(v, dict) and v.get("言葉") == "Guitar Effects Pedal":
            CAT_KIND.setdefault(k, "pedal")
    need = {}
    def aspects_of(cat):
        if cat in need:
            return need[cat]
        req, rec = [], []
        try:
            _, j = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category?category_id=" + urllib.parse.quote(cat), kind="app")
            for a in j.get("aspects", []):
                c = a.get("aspectConstraint") or {}
                (req if c.get("aspectRequired") else rec if c.get("aspectUsage") == "RECOMMENDED" else []).append(a.get("localizedAspectName"))
        except EbayError:
            pass
        need[cat] = (req, rec)
        return need[cat]
    out = {"時刻": jst(), "見た": 0, "読めなかった": [], "必須が足りない": [], "タイトルの気になる点": [], "おすすめ項目の埋まり方": {}}
    fill = []
    miss_req = collections.Counter()
    miss_rec = collections.Counter()
    for r in read_ledger():
        sku = r.get("SKU", "")
        if r.get("状態") != "出品中" or sku.startswith("STK-"):
            continue
        try:
            it = eb.inventory_item(sku)
            offs = [o for o in eb.offers_of(sku) if o.get("status") == "PUBLISHED"]
        except EbayError as e:
            out["読めなかった"].append(sku)
            continue
        if not offs:
            continue
        out["見た"] += 1
        cat = str(offs[0].get("categoryId", ""))
        p = it.get("product") or {}
        title = p.get("title", "") or r.get("タイトル", "")
        asp = {k: v for k, v in (p.get("aspects") or {}).items() if v and any(str(x).strip() for x in v)}
        req, rec = aspects_of(cat)
        mr = [a for a in req if a not in asp]
        if mr:
            miss_req.update(mr)
            out["必須が足りない"].append({"SKU": sku, "カテゴリ": cat, "タイトル": title, "足りない": mr})
        mrec = [a for a in rec if a not in asp]
        miss_rec.update(mrec)
        if rec:
            fill.append(1 - len(mrec) / len(rec))
        why = []
        if len(title) > 80:
            why.append("80字を超える")
        if re.search(r"[぀-ヿ一-鿿]", title):
            why.append("日本語が入っている")
        b = (asp.get("Brand") or [""])[0]
        if b and b.lower() not in title.lower():
            why.append("ブランド（%s）がタイトルに無い" % b)
        m = (asp.get("Model") or [""])[0]
        if m and re.sub(r"[^0-9a-z]", "", m.lower()) not in re.sub(r"[^0-9a-z]", "", title.lower()):
            why.append("型番（%s）がタイトルに無い" % m)
        own = CAT_KIND.get(cat)
        if own:
            other = [k for k, rx in KIND_WORDS.items() if k != own and re.search(rx, title, re.I)
                     and not (own == "camera" and k == "lens") and not (own == "lens" and k == "camera")]
            if other and not re.search(KIND_WORDS[own], title, re.I):
                why.append("カテゴリ（%s）と違う種類の言葉：%s" % (own, ",".join(other)))
            elif "drone" in other:
                why.append("Drone の言葉")
        if why:
            out["タイトルの気になる点"].append({"SKU": sku, "カテゴリ": cat, "タイトル": title, "なぜ": why})
    out["必須の足りない項目"] = dict(miss_req.most_common())
    out["おすすめで多く空いている項目"] = dict(miss_rec.most_common(20))
    out["おすすめ項目の埋まり方"] = {"平均": round(sum(fill) / len(fill), 2) if fill else None, "品数": len(fill)}
    save_json(os.path.join(ROOT, "data", "判定", "商品の詳細の確認.json"), out)
    print("見た", out["見た"], "／必須が足りない", len(out["必須が足りない"]), "／タイトルの気になる点", len(out["タイトルの気になる点"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
