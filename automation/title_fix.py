"""出品中の品のタイトルを、教科書の形に直す（手で動かす）。11/23 20:34 オーナー「出品中の商品タイトルもすべてかえて」。
- 対象：GitHub で出したタイトル（「ブランド 型番 種類 Used/New From Japan」の形）の品。GAS で出した長いタイトルの品は、もう言葉が多いので変えない。
- 新しいタイトルは title_make.build（ブランド＋型番＋シリーズ名＋種類＋状態＋付属品＋From Japan）。状態と付属品は仕入れ先の説明から（cond_note）。
- 型番は今のタイトルの型番のまま（変えない）。
- data/判定/タイトルの直し.json：{"本番": false, "件数": 20}。ドライラン → 20品 → オーナーが見て OK → 残り（10章）。
- 保存（PUT）のあと読み直して確かめ、台帳のタイトルも合わせる。結果は data/判定/タイトルの直し_結果.json。"""
import os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger
import cond_note, title_make, glob, json

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "タイトルの直し.json")
RP = os.path.join(ROOT, "data", "判定", "タイトルの直し_結果.json")
PAT = re.compile(r"^(\S+) (\S+) (.+?) (Used|New) From Japan$")

cfg = load_json(P, {"本番": False, "件数": 20})
live = bool(cfg.get("本番"))
eb = Ebay()
res = load_json(RP, {"品": {}})
done = res.setdefault("品", {})
out = {"時刻": jst(), "本番": live, "直した": [], "予定": [], "失敗": [], "見た": 0}
t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 22))
n_max = int(cfg.get("件数", 20))
rows = read_ledger()
changed = False
# 11/23 20:40：状態と付属品は仕入れ先の「商品名」だけから（判定の記録の 仕入元の商品名）。無い品は Used のまま
names = {}
for f in glob.glob(os.path.join(ROOT, "data", "判定", "記録", "*.json")):
    for x in json.load(open(f, encoding="utf-8")).get("結果", []):
        if x.get("SKU") and x.get("仕入元の商品名"):
            names[x["SKU"]] = x["仕入元の商品名"]
kind_words = {str(v.get("言葉")) for v in load_json(os.path.join(ROOT, "data", "判定", "種類.json"), {}).values() if isinstance(v, dict) and v.get("言葉")}
undo = cfg.get("元に戻す") or {}
for r in rows:
    if time.time() > t_end:
        out["時間切れ"] = True
        break
    if len(out["直した"]) + len(out["予定"]) >= n_max:
        break
    if r.get("状態") != "出品中" or not r.get("offerId") or r["SKU"].startswith("STK-"):
        continue
    sku = r["SKU"]
    if sku in undo:   # まちがえて変えた品を前のタイトルに戻す
        try:
            it = eb.inventory_item(sku)
            it["product"]["title"] = undo[sku]
            body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
            pw = body.get("packageWeightAndSize") or {}
            if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
                pw.pop("weight", None)
                if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                    body.pop("packageWeightAndSize", None)
            eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            r["タイトル"] = undo[sku]
            changed = True
            done[sku] = {"戻した日時": jst()}
            out.setdefault("戻した", []).append(sku)
        except EbayError as e:
            out["失敗"].append({"SKU": sku, "エラー": "戻せない " + err_text(e)[:200]})
        continue
    d0 = done.get(sku, {})
    if d0.get("直した日時") or d0.get("失敗", 0) >= 2 or d0.get("変えない"):
        continue
    try:
        it = eb.inventory_item(sku)
        p = it.get("product") or {}
        old = p.get("title") or ""
        m = PAT.match(old)
        if not m:
            done[sku] = {"変えない": "GAS の長いタイトル・形が違う"}
            continue
        out["見た"] += 1
        brand, model, kind_word = m.group(1), m.group(2), m.group(3)
        if kind_word not in kind_words:   # GitHub で作った形のタイトルだけ（GAS の長いタイトルは変えない）
            done[sku] = {"変えない": "GitHub の形のタイトルではない"}
            continue
        cond = 1000 if m.group(4) == "New" else 3000
        nm = names.get(sku, "")
        new = title_make.build(brand, model, kind_word, cond, cond_note.notes("", nm) if nm else {}, nm)
        if new == old:
            done[sku] = {"変えない": "同じタイトル"}
            continue
        if not live:
            out["予定"].append({"SKU": sku, "前": old, "後": new, "出品ID": r.get("eBayの出品ID")})
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
        out["直した"].append({"SKU": sku, "前": old, "後": new, "出品ID": r.get("eBayの出品ID")})
    except EbayError as e:
        done[sku] = dict(d0, 失敗=d0.get("失敗", 0) + 1)
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300]})
if changed:
    save_ledger(rows, ["タイトル"], "出品中のタイトルを教科書の形に")
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))
