"""同じ型番の競合の項目とタイトルの言葉で、出品中の品の項目とタイトルを埋める（手で動かす）。
11/23 21:23 オーナー「1と2全てやり直して、埋めて！」
1：同じ型番の競合（Browse の検索 → getItem の localizedAspects）を最大4品読み、2品以上で同じ値の「型番で決まる仕様」だけを、
   空いている項目・Does not apply の項目に入れる。色・状態・箱・付属品・ベルトなど品ごとにちがう項目は入れない。
   選べる値が決まっている項目（SELECTION_ONLY）は、その一覧にある値だけ。
2：同じ型番の競合のタイトルに2品以上で出てくる「仕様の言葉」だけを、タイトルの種類の言葉の前に足す（80文字まで）。
   項目と食いちがう言葉（Quartz の品に Solar など）・フィルムカメラに Digital などは足さない。盛った言葉は足さない。
- data/判定/競合で埋める.json：{"本番": false, "件数": 20, "時間の上限_分": 25, "除く": []}。本番 false はドライラン。
- 結果は data/判定/競合で埋める_結果.json。保存（PUT）のあと読み直して確かめる（10章 3）。
- Browse の残りが下限（時刻表 判定と出品 → Browseの残りの下限・ふだん300）＋100 を切ったら止める。"""
import collections, os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger, settings, timetable
import judge, title_make

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "競合で埋める.json")
RP = os.path.join(ROOT, "data", "判定", "競合で埋める_結果.json")
KINDS = os.path.join(ROOT, "data", "判定", "種類.json")
HD = {"X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=10001"}

# 品ごとにちがう・型番で決まらない項目は入れない
SKIP_ASPECT = re.compile(r"colou?r|condition|box|packag|paper|bundle|includ|accessor|warrant|year|vintage|modif|custom|person|sign|handmade|"
                         r"country|region|prop 65|unit|ship|seller|band|strap|lug|weight|height|length|width|serial|upc|ean|isbn|^mpn$|^model$|"
                         r"^brand$|department|gender|style|theme|character|occasion|pattern|sport|label|certif|service|return|reference|"
                         r"original|reproduction|kit|manual|booklet|closure|handed|cable|charger|battery included|item type|signed|autograph|franchise|tv|movie|video game", re.I)
# タイトルに足してよい仕様の言葉（競合2品以上が使っているときだけ）
WORDS = ["Tough Solar", "Solar", "Radio", "Atomic", "Multiband 6", "Multiband", "Bluetooth", "Waterproof", "Shockproof", "Digital", "Analog",
         "Ana-Digi", "Quartz", "Automatic", "Mechanical", "Chronograph", "Diver", "Titanium", "Stainless Steel", "World Time", "Alarm",
         "Compact", "Mirrorless", "DSLR", "SLR", "Rangefinder", "Point & Shoot", "Zoom", "Wide", "Telephoto", "Macro", "Autofocus",
         "Overdrive", "Distortion", "Delay", "Reverb", "Fuzz", "Chorus", "Phaser", "Flanger", "Compressor", "Looper", "Tuner", "Booster",
         "Wah", "Equalizer", "Noise Cancelling", "Wireless", "Hi-Res", "Stereo", "Portable", "Rechargeable", "Full HD", "4K", "HD",
         "35mm", "Instant", "Underwater", "Speedlite", "Pancake", "Standard", "Fisheye", "Vari-Angle", "Wi-Fi", "GPS", "Touchscreen"]
PAT = [r"\d{1,2}(\.\d)?\s?MP", r"\d{1,2}(\.\d)?x(?= )", r"\d{1,3}-\d{1,3}mm", r"\d{1,3}mm"]
PARTS = re.compile(r"\bspool\b|\bhandle\b|\bknob\b|box only|manual only|case only|lens cap|replacement|\bparts?\b|for repair", re.I)   # 部品・付属品だけの出品
CONFLICT = {"Movement": ["Solar", "Tough Solar", "Quartz", "Automatic", "Mechanical"], "Display": ["Digital", "Analog", "Ana-Digi"]}


def pick(val, meta):
    """選べる値が決まっている項目は、その一覧にある値だけ"""
    vals = [v.get("localizedValue") for v in (meta.get("aspectValues") or [])]
    mode = (meta.get("aspectConstraint") or {}).get("aspectMode")
    want = val if isinstance(val, list) else [val]
    out = []
    for w in want:
        if mode == "SELECTION_ONLY" or vals:
            hit = next((v for v in vals if v and v.lower() == str(w).lower()), None) or \
                  next((v for v in vals if v and re.sub(r"[^a-z0-9]", "", v.lower()) == re.sub(r"[^a-z0-9]", "", str(w).lower())), None)
            if hit:
                out.append(hit)
            elif mode != "SELECTION_ONLY":
                out.append(str(w))
        else:
            out.append(str(w))
    multi = (meta.get("aspectConstraint") or {}).get("itemToAspectCardinality") == "MULTI"
    return out if multi else out[:1]


def model_rx(m):
    m = m.upper()
    body = "".join(("[-\\s]?" if c in "- " else re.escape(c)) for c in m)
    return re.compile(r"(?<![A-Z0-9])" + body + r"(?![A-Z0-9])")


def comps(eb, brand, model, cat, me, my_ids):
    rx = model_rx(model)
    items = eb.browse("%s %s" % (brand, model), "buyingOptions:{FIXED_PRICE}", limit=50, category=cat) if cat else []
    if len([1 for it in items if rx.search((it.get("title") or "").upper())]) < 2:
        items = eb.browse("%s %s" % (brand, model), "buyingOptions:{FIXED_PRICE}", limit=50)
    out = []
    for it in items:
        if (it.get("seller") or {}).get("username", "").lower() == me or str(it.get("legacyItemId", "")) in my_ids:
            continue
        t = it.get("title", "")
        if not rx.search(t.upper()) or judge.JUNK.search(t) or judge.is_acc(t, model) or PARTS.search(t):
            continue
        out.append(it)
    return out[:4]


def words_in(t):
    found = []
    for w in WORDS:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", t, re.I):
            found.append(w)
    for p in PAT:
        for m in re.finditer(r"(?<![A-Za-z0-9.])" + p + r"(?![A-Za-z0-9])", t):
            found.append(re.sub(r"\s", "", m.group(0)).replace("mp", "MP"))
    # 長い言葉に入っている短い言葉は数えない（Tough Solar の Solar など）
    return {w for w in found if not any(w != x and w.lower() in x.lower() for x in found)}


def main():
    cfg = load_json(P, {"本番": False, "件数": 20})
    live = bool(cfg.get("本番"))
    eb = Ebay()
    rows = read_ledger()
    by = {r["SKU"]: r for r in rows}
    me = (settings().get("店", {}) or {}).get("セラー名", "ihdj_81").lower()
    my_ids = {r.get("eBayの出品ID") for r in rows}
    kinds = load_json(KINDS, {})
    kind_words = sorted({v.get("言葉") for v in kinds.values() if isinstance(v, dict) and v.get("言葉")}, key=len, reverse=True)
    floor = int((timetable("判定と出品") or {}).get("Browseの残りの下限", 300)) + 100
    rem = eb.browse_remaining() or {}
    left = int(rem.get("remaining") or 0)
    res = load_json(RP, {"品": {}})
    done = res.setdefault("品", {})
    out = {"時刻": jst(), "本番": live, "直した": [], "予定": [], "失敗": [], "見た": 0, "Browseの残り_始め": left}
    t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 25))
    n_max = int(cfg.get("件数", 20))
    skip = set(cfg.get("除く") or [])
    meta_cache = {}
    for r in rows:
        if r.get("状態") != "出品中" or not r.get("offerId") or r["SKU"].startswith("STK-") or r["SKU"] in skip:
            continue
        if time.time() > t_end:
            out["時間切れ"] = True
            break
        if len(out["直した"]) + len(out["予定"]) >= n_max:
            break
        if left - eb.browse_n < floor:
            out["Browseの下限で止めた"] = True
            break
        sku = r["SKU"]
        d0 = done.get(sku, {})
        if d0.get("直した日時") or d0.get("失敗", 0) >= 2 or (live and d0.get("足すものなし")):
            continue
        out["見た"] += 1
        try:
            it = eb.inventory_item(sku)
            _, o = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
            cat = str(o.get("categoryId") or "")
            if cat not in meta_cache:
                _, a = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category?category_id=" + cat)
                meta_cache[cat] = {x["localizedAspectName"]: x for x in (a or {}).get("aspects") or []}
            meta = meta_cache[cat]
            p = it.setdefault("product", {})
            asp = p.setdefault("aspects", {})
            title = p.get("title") or ""
            brand = (asp.get("Brand") or [""])[0]
            model = (asp.get("Model") or asp.get("MPN") or [""])[0]
            if not brand or not model or not re.search(r"\d", model) or model.lower() == "does not apply":
                done[sku] = dict(d0, 足すものなし=True, 理由="ブランドか型番が無い")
                continue
            cs = comps(eb, brand, model, cat, me, my_ids)
            if len(cs) < 2:
                done[sku] = dict(d0, 足すものなし=True, 理由="同じ型番の競合が2品未満")
                continue
            # 1：競合の項目
            vals = collections.defaultdict(list)
            for c in cs:
                try:
                    eb.browse_n += 1
                    _, g = eb.call("GET", "/buy/browse/v1/item/" + urllib.parse.quote(c["itemId"], safe=""), kind="app", headers=HD)
                except EbayError:
                    continue
                seen = {}
                for x in g.get("localizedAspects") or []:
                    seen.setdefault(x.get("name"), []).append(str(x.get("value") or "").strip())
                for k, v in seen.items():
                    vals[k].append(v)
                time.sleep(0.3)
            add = {}
            lens = "lens" in title.lower()
            for name, m in meta.items():
                if SKIP_ASPECT.search(name) or name not in vals:
                    continue
                if not lens and re.search(r"focal|aperture", name, re.I):   # 本体にセットのレンズの値を入れない
                    continue
                if re.search(r"spool|part|accessor", " ".join(x for lst in vals[name] for x in lst), re.I):
                    continue
                cur = [v for v in (asp.get(name) or []) if v and v != "Does not apply"]
                if cur:
                    continue
                multi = (m.get("aspectConstraint") or {}).get("itemToAspectCardinality") == "MULTI"
                lists = vals[name]
                cnt = collections.Counter()
                for lst in lists:
                    for v in {s.strip() for x in lst for s in (x.split(",") if multi else [x]) if s.strip()}:
                        if v.lower() not in ("does not apply", "n/a", "na", "unknown", "-", "see description", "none"):
                            cnt[v.lower()] += 1
                if not cnt:
                    continue
                orig = {}
                for lst in lists:
                    for x in lst:
                        for s in (x.split(",") if multi else [x]):
                            orig.setdefault(s.strip().lower(), s.strip())
                if multi:
                    want = [orig[v] for v, n in cnt.items() if n >= 2]
                else:
                    (top, n), = cnt.most_common(1)
                    have_n = len([1 for lst in lists if any(s.strip() for s in lst)])
                    want = [orig[top]] if n >= 2 and n * 3 >= have_n * 2 else []   # 2品以上・3分の2以上が同じ値
                if not want:
                    continue
                v = pick(want if multi else want[0], m)
                if v and len(v[0]) <= 65:
                    add[name] = v
            # 2：競合のタイトルの言葉
            after = {k: [x.lower() for x in v] for k, v in asp.items()}
            after.update({k: [x.lower() for x in v] for k, v in add.items()})
            wc = collections.Counter()
            for c in cs:
                for w in words_in(c.get("title", "")):
                    wc[w.lower()] += 1
            low = title.lower()
            kind = next((k for k in kind_words if re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![A-Za-z])", title)), "")
            film = "film" in kind.lower()
            new_words = []
            for w, n in wc.most_common():
                word = next((x for x in WORDS if x.lower() == w), w)
                if n < 2 or re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
                    continue
                if any(w in [x.lower() for x in lst] and asp_name in after and not any(w in v for v in after[asp_name]) for asp_name, lst in CONFLICT.items()):
                    continue   # 項目と食いちがう
                if film and re.search(r"digital|mp$|mirrorless|dslr|hd|4k|wi-fi|gps|touchscreen", w):
                    continue
                if not film and "camera" in kind.lower() and w in ("35mm", "slr", "rangefinder"):
                    continue
                if re.search(r"\d+mm$", w) and not ("lens" in kind.lower() or (film and w == "35mm")):
                    continue   # セットのレンズの長さは足さない
                if re.match(r"^\d", w):
                    word = w.replace("mp", "MP")
                new_words.append(word)
            new_t = title
            if kind and new_words and len(title) < 78:
                i = title.find(kind)
                head, tail = title[:i].rstrip(), title[i:]
                for w in new_words:
                    cand = "%s %s %s" % (head, w, tail)
                    if len(cand) <= 80:
                        head = head + " " + w
                new_t = re.sub(r"\s+", " ", "%s %s" % (head, tail)).strip()
            if not add and new_t == title:
                done[sku] = dict(d0, 足すものなし=True, 理由="競合と同じ値・言葉が無い")
                continue
            plan = {"SKU": sku, "出品ID": r.get("eBayの出品ID"), "競合": len(cs), "足す項目": add,
                    "タイトル": [title, new_t] if new_t != title else None}
            if not live:
                out["予定"].append(plan)
                continue
            asp.update(add)
            p["title"] = new_t
            body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
            pw = body.get("packageWeightAndSize") or {}
            if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
                pw.pop("weight", None)
                if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                    body.pop("packageWeightAndSize", None)
            eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            chk = eb.inventory_item(sku).get("product") or {}
            if chk.get("title") != new_t or not all((chk.get("aspects") or {}).get(k) for k in add):
                raise EbayError(0, {"raw": "読み直したら入っていない"})
            done[sku] = {"直した日時": jst(), "足した": add, "タイトル": plan["タイトル"]}
            out["直した"].append(plan)
            if new_t != title and sku in by:
                by[sku]["タイトル"] = new_t
        except EbayError as e:
            done[sku] = dict(d0, 失敗=d0.get("失敗", 0) + 1)
            out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300]})
    out["Browseを使った"] = eb.browse_n
    if live:
        if any(x.get("タイトル") for x in out["直した"]):
            save_ledger(rows, ["タイトル"], "競合で埋める")
        cfg["本番"] = bool(out.get("時間切れ"))   # 時間切れなら次の回も本番で続ける
        save_json(P, cfg)
    save_json(RP, dict(res, 最後=out))
    print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["予定"]),
          "失敗", len(out["失敗"]), "Browse", eb.browse_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
