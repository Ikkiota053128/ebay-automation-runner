"""出品中の品の項目（Item specifics）を、はっきり分かる値だけ埋める（手で動かす）。
11/23 19:30 オーナー「項目を埋めて」（教科書：eBay の検索の絞り込みはこの欄を見る。空欄が多いと検索に出る回数が減る）。
- カテゴリごとに eBay から「入れる項目の一覧」（必ず・おすすめ・選べる値）を読む（Taxonomy API）。
- 値は、タイトル・型番・仕入れ先の商品名と説明（cond_note.source_text）に**書いてあることだけ**から決める。推測しない。
  選べる値が決まっている項目（SELECTION_ONLY）は、その一覧にある値だけを入れる。
- 空いている項目と「Does not apply」の項目だけを埋める。入っている値は変えない。
- data/判定/項目の直し.json：{"本番": false, "件数": 20}。本番 false の間はドライラン（前と後を記録するだけ）。
- 結果は data/判定/項目の直し_結果.json。保存（PUT）のあと読み直して確かめる（10章 3）。"""
import json, os, re, sys, time, unicodedata, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger
import cond_note, title_make

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "項目の直し.json")
RP = os.path.join(ROOT, "data", "判定", "項目の直し_結果.json")
COLORS = [("ブラック|黒", "Black"), ("ホワイト|白", "White"), ("シルバー|銀", "Silver"), ("ゴールド|金色", "Gold"), ("レッド|赤", "Red"),
          ("ブルー|青", "Blue"), ("ネイビー|紺", "Blue"), ("グリーン|緑", "Green"), ("イエロー|黄", "Yellow"), ("ピンク", "Pink"),
          ("オレンジ", "Orange"), ("ブラウン|茶", "Brown"), ("グレー|灰", "Gray"), ("パープル|紫", "Purple"), ("ベージュ", "Beige")]


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def colors_in(t):
    found = {en for rx, en in COLORS if re.search(rx, t)}
    found |= {en for _, en in COLORS if re.search(r"\b%s\b" % en, t, re.I)}
    return found


def facts(title, model, src_name, src):
    """はっきり書いてある事実だけ：{項目の名前の候補: 値}"""
    t_all = nfkc("%s\n%s\n%s" % (title, src_name, src))
    t_name = nfkc("%s %s" % (title, src_name))
    f = {}
    cs = colors_in(t_name)   # 色は商品名だけから（説明はほかの色の話が混ざる）。1色だけのとき
    if len(cs) == 1:
        c = cs.pop()
        watch = re.search(r"watch|腕時計", t_name, re.I)
        for k in (("Dial Color",) if watch else ("Color", "Body Color", "Exterior Color")):   # 時計の名前の色は文字盤の色のことが多い
            f[k] = c
    if re.search(r"ソーラー|タフソーラー|solar", t_all, re.I):
        f["Movement"] = "Solar"
    elif re.search(r"自動巻|オートマチック|automatic", t_all, re.I):
        f["Movement"] = "Automatic"
    elif re.search(r"手巻", t_all):
        f["Movement"] = "Mechanical (Hand-winding)"
    elif re.search(r"クオーツ|クォーツ|quartz", t_all, re.I):
        f["Movement"] = "Quartz"
    if re.search(r"アナデジ|ana-?digi", t_all, re.I):
        f["Display"] = "Analog & Digital"
    elif re.search(r"デジタル(腕)?時計|digital watch", t_all, re.I):
        f["Display"] = "Digital"
    elif re.search(r"アナログ", t_all):
        f["Display"] = "Analog"
    feats = []
    if re.search(r"電波", t_all):
        feats.append("Radio Controlled")
    if re.search(r"\d+\s*(気圧|BAR|bar|m防水|M防水)|\d+\s*m\s*water", t_all, re.I):   # 数字つきの防水だけ
        feats.append("Water Resistant")
    if re.search(r"Bluetooth|ブルートゥース", t_all, re.I):
        feats.append("Bluetooth")
    if feats:
        f["Features"] = feats
    if re.search(r"Bluetooth|ブルートゥース", t_all, re.I):
        f["Connectivity"] = "Bluetooth"
    elif re.search(r"ワイヤレス|wireless", t_name, re.I):
        f["Connectivity"] = "Wireless"
    # ズーム・画素数・液晶の大きさは、説明文のほかの数字を拾ってまちがえることがあるので入れない（ドライランで分かった）
    if re.search(r"フィルムカメラ|film camera|35mm", t_all, re.I):
        f["Film Format"] = "35mm"
    if model and model.lower() not in ("does not apply", "n/a", "na", "unknown") and re.search(r"\d", model) and not re.match(r"(?i)gen\s*\d", model):
        f["MPN"] = model
    return f


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


cfg = load_json(P, {"本番": False, "件数": 20})
live = bool(cfg.get("本番"))
eb = Ebay()
res = load_json(RP, {"品": {}})
done = res.setdefault("品", {})
out = {"時刻": jst(), "本番": live, "直した": [], "予定": [], "失敗": [], "見た": 0}
t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 22))
n_max = int(cfg.get("件数", 20))
meta_cache = {}
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")]
for r in rows:
    if time.time() > t_end:
        out["時間切れ"] = True
        break
    if len(out["直した"]) + len(out["予定"]) >= n_max:
        break
    sku = r["SKU"]
    if sku in set(cfg.get("除く") or []):   # カテゴリのまちがいの品は、カテゴリを直してから
        continue
    d0 = done.get(sku, {})
    if d0.get("直した日時") or d0.get("失敗", 0) >= 2 or (d0.get("足すものなし") and live):
        continue
    out["見た"] += 1
    try:
        it = eb.inventory_item(sku)
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
        cat = o.get("categoryId")
        if cat not in meta_cache:
            _, a = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category?category_id=" + cat)
            meta_cache[cat] = {x["localizedAspectName"]: x for x in (a or {}).get("aspects") or []}
        meta = meta_cache[cat]
        p = it.setdefault("product", {})
        asp = p.setdefault("aspects", {})
        title = p.get("title") or ""
        model = (asp.get("Model") or asp.get("MPN") or [""])[0]
        src = ""
        if r.get("仕入元URL") and not re.search(r"mercari|amazon\.", r["仕入元URL"]):
            src = cond_note.source_text({"url": r["仕入元URL"], "id": sku})
            time.sleep(2)
        fx = facts(title, model, "", src)
        if model:
            s = title_make.series((asp.get("Brand") or [""])[0], model, "")
            if s:
                fx["Series"] = s
        add = {}
        for name, m in meta.items():
            cur = [v for v in (asp.get(name) or []) if v and v != "Does not apply"]
            if cur or name not in fx:
                continue
            v = pick(fx[name], m)
            if v:
                add[name] = v
        if not add:
            done[sku] = dict(d0, 足すものなし=True, 見た日時=jst())
            continue
        if not live:
            out["予定"].append({"SKU": sku, "カテゴリ": cat, "タイトル": title, "足す": add,
                              "今の項目の数": len([1 for v in asp.values() if v and v != ["Does not apply"]])})
            continue
        asp.update(add)
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        chk = (eb.inventory_item(sku).get("product") or {}).get("aspects") or {}
        if not all(chk.get(k) for k in add):
            raise EbayError(0, {"raw": "読み直したら項目が入っていない"})
        done[sku] = {"直した日時": jst(), "足した": add}
        out["直した"].append({"SKU": sku, "足した": add})
    except EbayError as e:
        done[sku] = dict(d0, 失敗=d0.get("失敗", 0) + 1)
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300]})
if live:
    save_json(P, cfg)
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))
