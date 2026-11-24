"""出品中のタイトルを、本当の言葉だけで80文字に近づける（手で動かす）。
11/25 07:15 オーナー「出品タイトル 80字ギリギリで出品してるか確認して！」・07:16「教科書通り進めて！」。
教科書の形（ブランド＋型番＋シリーズ名＋種類＋特徴＋状態＋付属品＋From Japan・80文字まで・盛らない）のまま、
「特徴」のところに、次の本当の言葉だけを足す：
  1. 型番の続き：タイトルの型番が仕入れ先の商品名の型番の頭だけ（例 V501 → V501-X037）なら、商品名の型番にする
  2. シリーズ名：仕入れ先の商品名にあるシリーズ名（アルバ→Alba など・決まった一覧だけ）・項目の Model/Series/Product Line
  3. 項目の値：Department・Movement・Display・Features・Type・Case Material・Water Resistance・Color・Effect Type・Megapixels など
     （Does not apply・日本語・長すぎる値・もうタイトルにある言葉は足さない）
- 対象：GitHub で出した形（… Used/New/Near Mint… [w/ …] From Japan）で、76文字未満の品。GAS の長いタイトルは変えない。
- data/判定/タイトルを埋める.json：{"本番": false, "件数": 20}。ドライラン → 20品 → オーナーが見て OK → 残り（10章）。
- 保存（PUT）のあと読み直して確かめ、台帳のタイトルも合わせる。結果は data/判定/タイトルを埋める_結果.json。"""
import glob, json, os, re, sys, time, unicodedata, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "タイトルを埋める.json")
RP = os.path.join(ROOT, "data", "判定", "タイトルを埋める_結果.json")
TAIL = re.compile(r"^(.+?) ((?:New|Used|Near Mint|Excellent|Good|Fair|For Parts)(?: w/ \S+| Body Only)* From Japan)$")
SERIES_JP = [("グランドセイコー", "Grand Seiko"), ("アルバ", "Alba"), ("ルキア", "Lukia"), ("プレサージュ", "Presage"), ("プロスペックス", "Prospex"),
             ("ブライツ", "Brightz"), ("ドルチェ", "Dolce"), ("エクセリーヌ", "Exceline"), ("アストロン", "Astron"), ("クレドール", "Credor"),
             ("ティセ", "Tissé"), ("ワイアード", "Wired"), ("オシアナス", "Oceanus"), ("プロトレック", "Pro Trek"), ("エディフィス", "Edifice"),
             ("シーン", "Sheen"), ("ウェーブセプター", "Wave Ceptor"), ("リニエージ", "Lineage"), ("アテッサ", "Attesa"), ("エクシード", "Exceed"),
             ("プロマスター", "Promaster"), ("エコドライブ", "Eco-Drive"), ("クロスシー", "xC"), ("ウィッカ", "Wicca"), ("ロイヤルオリエント", "Royal Orient"),
             ("オリエントスター", "Orient Star"), ("ベビージー", "Baby-G"), ("ジーショック", "G-Shock")]
ASPECTS = ["Model", "Series", "Product Line", "Department", "Movement", "Display", "Features", "Type", "Case Material", "Band Material",
           "Water Resistance", "Effect Type", "Megapixels", "Optical Zoom", "Focal Length", "Maximum Aperture", "Lens Mount", "Film Format",
           "Connectivity", "Form Factor", "Reel Type", "Hand Retrieve", "Color", "Dial Color"]
DEPT = {"men": "Men's", "women": "Women's", "unisex adults": "Unisex", "unisex adult": "Unisex", "boys": "Boys'", "girls": "Girls'"}
BAD = re.compile(r"^(does not apply|not applicable|n/?a|unbranded|unknown|other|see description|none|-|limited edition|usb.*|unisex.*|body only)$", re.I)


def nfk(s):
    return unicodedata.normalize("NFKC", s or "")


def has(title, w):
    t, w = title.lower(), w.lower()
    return w in t or all(x in t for x in re.findall(r"[a-z0-9]+", w))


def full_model(model, name):
    """タイトルの型番が、仕入れ先の商品名の型番の頭だけなら、商品名の型番（例 V501 → V501-X037）"""
    m = re.escape(model)
    hit = re.search(r"(?<![A-Za-z0-9])(%s-[A-Za-z0-9]{2,8})(?![A-Za-z0-9])" % m, nfk(name), re.I)
    return hit.group(1).upper() if hit else ""


def words_for(title, aspects, name):
    out = []
    t0 = title.split(" ")
    brand, model = (t0[0], t0[1]) if len(t0) > 1 else ("", "")
    norm = lambda x: re.sub(r"[^0-9a-z]", "", x.lower())
    for k in ASPECTS:
        for v in aspects.get(k) or []:
            v = re.sub(r"\s*\(.*?\)", "", str(v)).strip()
            if not v or BAD.match(v) or len(v) > 25 or re.search(r"[^\x00-\x7f]", v.replace("é", "")):
                continue
            if v[:1].islower():
                continue   # various など、名前でない言葉
            if brand and brand.lower() in v.lower() or model and norm(model) and norm(model) in norm(v):
                continue   # ブランド名・型番をくり返さない
            if k == "Department":
                v = DEPT.get(v.lower(), "") if re.search(r"watch", title, re.I) else ""
            elif k == "Water Resistance" and re.match(r"^\d+ ?(m|ATM|Bar)", v, re.I):
                v = "%s Water Resistant" % v.replace(" ", "")
            elif k == "Dial Color":
                v = "%s Dial" % v
            elif k == "Megapixels" and re.match(r"^[\d.]+$", v):
                v += "MP"
            if v:
                out.append(v)
    seen, res = set(), []
    for w in out:
        if w.lower() in seen or has(title, w):
            continue
        seen.add(w.lower())
        res.append(w)
    return res


def fill(title, aspects, name):
    m = TAIL.match(title)
    if not m:
        return None
    head, tail = m.group(1), m.group(2)
    parts = head.split(" ")
    if len(parts) > 1:
        fm = full_model(parts[1], name)
        if fm and fm != parts[1].upper():
            parts[1] = fm
    n = nfk(name)
    ser = [en for jp, en in SERIES_JP if jp in n and not has(title, en)]
    if ser and len(parts) > 1:   # シリーズ名は型番のすぐあと（教科書の形）
        parts = parts[:2] + ser[:1] + parts[2:]
    head = " ".join(parts)
    if len(head) + 1 + len(tail) > 80:
        return None
    for w in words_for(head + " " + tail, aspects, name):
        if len(head) + 1 + len(w) + 1 + len(tail) <= 80 and not has(head + " " + tail, w):
            head += " " + w
    return (head + " " + tail)[:80]


def main():
    cfg = load_json(P, {"本番": False, "件数": 20})
    live = bool(cfg.get("本番"))
    eb = Ebay()
    res = load_json(RP, {"品": {}})
    done = res.setdefault("品", {})
    out = {"時刻": jst(), "本番": live, "直した": [], "予定": [], "失敗": [], "見た": 0, "長さ_前": [], "長さ_後": []}
    t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 22))
    n_max = int(cfg.get("件数", 20))
    names = {}
    for f in glob.glob(os.path.join(ROOT, "data", "判定", "記録", "*.json")):
        for x in json.load(open(f, encoding="utf-8")).get("結果", []):
            if x.get("SKU") and x.get("仕入元の商品名"):
                names[x["SKU"]] = x["仕入元の商品名"]
    rows = read_ledger()
    changed = False
    for r in rows:
        if time.time() > t_end:
            out["時間切れ"] = True
            break
        if len(out["直した"]) + len(out["予定"]) >= n_max:
            break
        if r.get("状態") != "出品中" or not r.get("offerId") or r["SKU"].startswith("STK-"):
            continue
        sku = r["SKU"]
        d0 = done.get(sku, {})
        if d0.get("直した日時") or d0.get("失敗", 0) >= 2 or d0.get("変えない"):
            continue
        if len(r.get("タイトル") or "") >= 76:
            continue
        try:
            it = eb.inventory_item(sku)
            p = it.get("product") or {}
            old = p.get("title") or ""
            out["見た"] += 1
            new = fill(old, p.get("aspects") or {}, names.get(sku, ""))
            if not new:
                done[sku] = {"変えない": "GitHub の形のタイトルではない"}
                continue
            if new == old or len(new) <= len(old):
                done[sku] = {"変えない": "足せる本当の言葉が無い"}
                continue
            plan = {"SKU": sku, "前": old, "後": new, "文字数": "%d→%d" % (len(old), len(new)), "出品ID": r.get("eBayの出品ID")}
            if not live:
                out["予定"].append(plan)
                continue
            p["title"] = new
            body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
            pw = body.get("packageWeightAndSize") or {}
            if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
                pw.pop("weight", None)
                if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                    body.pop("packageWeightAndSize", None)
            eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            if ((eb.inventory_item(sku).get("product") or {}).get("title") or "") != new:
                raise EbayError(0, {"raw": "読み直したらタイトルが変わっていない"})
            r["タイトル"] = new
            changed = True
            done[sku] = {"直した日時": jst(), "前": old, "後": new}
            out["直した"].append(plan)
        except EbayError as e:
            done[sku] = dict(d0, 失敗=d0.get("失敗", 0) + 1)
            out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300]})
    if changed:
        save_ledger(rows, ["タイトル"], "タイトルを本当の言葉で80文字に近づける")
    if live:
        cfg["本番"] = False
        save_json(P, cfg)
    save_json(RP, dict(res, 最後=out))
    print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
