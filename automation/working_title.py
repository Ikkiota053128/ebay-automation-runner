"""出品中の品で、仕入れ先が「動作確認済み」と書いた品のタイトルに Tested Working が入っているか確かめて、無ければ入れる。
11/28 09:27 オーナー「仕入先で動作確認済みの商品は出品タイトルに必ず動作確認済みときさいして！出品中の商品ちゃんと記載されているか確認して」
- 動作確認済みの見分け：出品の状態の説明（conditionDescription）か説明文に「Reported working in the Japanese listing」がある品
  （出品したときに仕入れ先の商品名・説明から cond_note が書いた文。ジャンク・For Parts の品は外す）。
- 直し方：title_make.add_working（状態の前に Tested Working・80文字を超えるときは特徴の言葉を後ろから外す。ブランド・型番は残す）。
- data/判定/動作確認のタイトル.json：{"本番": false, "件数": 20}。本番 false はドライラン。保存のあと読み直して確かめ、台帳のタイトルも合わせる。
- 結果は data/判定/動作確認のタイトル_結果.json。"""
import os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger, notify
import title_make

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "動作確認のタイトル.json")
RP = os.path.join(ROOT, "data", "判定", "動作確認のタイトル_結果.json")
cfg = load_json(P, {"本番": False, "件数": 20})
live, cap = bool(cfg.get("本番")), int(cfg.get("件数", 20))
eb = Ebay()
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")]
out = {"時刻": jst(), "本番": live, "見た": 0, "動作確認済み": 0, "入っている": 0, "入っていない": 0, "読めない": 0, "予定": [], "直した": [], "失敗": []}
changed = []
for r in rows:
    sku = r["SKU"]
    try:
        it = eb.inventory_item(sku)
        o = [x for x in eb.offers_of(sku) if x.get("offerId") == r["offerId"]]
        desc = (o[0].get("listingDescription") if o else "") or ""
    except EbayError as e:
        out["読めない"] += 1
        continue
    out["見た"] += 1
    p = it.get("product") or {}
    title = p.get("title") or ""
    txt = (it.get("conditionDescription") or "") + " " + desc
    if "Reported working in the Japanese listing" not in txt or re.search(r"\bfor parts\b|\bjunk\b", title, re.I):
        continue
    out["動作確認済み"] += 1
    if re.search(r"\btested\b|\bworking\b", title, re.I):
        out["入っている"] += 1
        continue
    out["入っていない"] += 1
    new = title_make.add_working(title)
    plan = {"SKU": sku, "前": title, "後": new, "出品ID": r.get("eBayの出品ID")}
    if not live or len(out["直した"]) >= cap:
        out["予定"].append(plan)
        continue
    try:
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
        changed.append(r)
        out["直した"].append(plan)
    except EbayError as e:
        out["失敗"].append(dict(plan, エラー=err_text(e)[:300]))
    time.sleep(0.3)
if changed:
    save_ledger(changed, ["タイトル"], "動作確認のタイトル")
if live:
    cfg["本番"] = False
    save_json(P, cfg)
save_json(RP, out)
msg = "【動作確認済みのタイトル】%s %s：見た%d品・仕入れ先が動作確認済み %d品（Tested Working 入っている %d・入っていない %d）%s" % (
    jst(), "本番" if live else "ドライラン", out["見た"], out["動作確認済み"], out["入っている"], out["入っていない"],
    ("・直した %d・失敗 %d" % (len(out["直した"]), len(out["失敗"]))) if live else "")
print(msg)
notify(msg)
