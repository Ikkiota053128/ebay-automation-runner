"""出品中の品で、仕入れ先が「動作確認済み」と書いた品のタイトルに Tested Working が入っているか確かめて、無ければ入れる。
11/28 09:27 オーナー「仕入先で動作確認済みの商品は出品タイトルに必ず動作確認済みときさいして！出品中の商品ちゃんと記載されているか確認して」
- 動作確認済みの見分け：出品の状態の説明（conditionDescription）か説明文に「Reported working in the Japanese listing」がある品
  （出品したときに仕入れ先の商品名・説明から cond_note が書いた文。ジャンク・For Parts の品は外す）。
- 直し方：title_make.add_working（状態の前に Tested Working・80文字を超えるときは特徴の言葉を後ろから外す。ブランド・型番は残す）。
- data/判定/動作確認のタイトル.json：{"本番": false, "件数": 20}。本番 false はドライラン。保存のあと読み直して確かめ、台帳のタイトルも合わせる。
- 結果は data/判定/動作確認のタイトル_結果.json。
- 11/28 10:36 オーナー「25品直して」：{"SKU": [...]} があるときは、その品（仕入れ先を読み直して動作確認済みと分かった品・src_working_check）だけを直す。
  タイトルに加えて、説明文と状態の説明の「Not tested」の文を「Reported working in the Japanese listing (not tested by us).」に直す（食いちがいをなくす）。"""
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
ONLY = set(cfg.get("SKU") or [])
if cfg.get("外す") and not ONLY:
    ONLY = {"(なし)"}   # 外すだけの回は、入れる品を見ない
if ONLY:
    rows = [r for r in rows if r["SKU"] in ONLY]
REP = "Reported working in the Japanese listing (not tested by us)."
NT = re.compile(r"NOT TESTED - we have not tested this item and its function is not confirmed\.|Not tested\. Please check the photos\.|Not tested\.(?! /)", re.I)
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
    if (not ONLY and "Reported working in the Japanese listing" not in txt) or re.search(r"\bfor parts\b|\bjunk\b", title, re.I):
        continue
    out["動作確認済み"] += 1
    need_desc = bool(ONLY) and (bool(NT.search(desc)) or bool(NT.search(it.get("conditionDescription") or "")))
    if re.search(r"\btested\b|\bworking\b", title, re.I) and not need_desc:
        out["入っている"] += 1
        continue
    out["入っていない"] += 1
    new = title_make.add_working(title) if not re.search(r"\btested\b|\bworking\b", title, re.I) else title
    plan = {"SKU": sku, "前": title, "後": new, "出品ID": r.get("eBayの出品ID")}
    if not live or len(out["直した"]) >= cap:
        out["予定"].append(plan)
        continue
    try:
        p["title"] = new
        if ONLY and it.get("conditionDescription"):
            it["conditionDescription"] = NT.sub(REP, it["conditionDescription"])
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        if ((eb.inventory_item(sku).get("product") or {}).get("title") or "") != new:
            raise EbayError(0, {"raw": "読み直したらタイトルが変わっていない"})
        if need_desc and o:   # 説明文の「Not tested」の文も直す
            of = dict(o[0])
            of["listingDescription"] = NT.sub(REP, desc)
            for k in ("offerId", "status", "listing"):
                of.pop(k, None)
            eb.call("PUT", "/sell/inventory/v1/offer/" + r["offerId"], of, headers=CL)
            chk = [x for x in eb.offers_of(sku) if x.get("offerId") == r["offerId"]]
            if not chk or REP not in (chk[0].get("listingDescription") or ""):
                raise EbayError(0, {"raw": "読み直したら説明文が変わっていない"})
            plan["説明も直した"] = True
        r["タイトル"] = new
        changed.append(r)
        out["直した"].append(plan)
    except EbayError as e:
        out["失敗"].append(dict(plan, エラー=err_text(e)[:300]))
    time.sleep(0.3)
# 11/28 11:44 オーナー「案どおりやって」：根拠の無かった品・不具合の書いてある品から Tested Working を外し、説明を Not tested に戻す
REM = set(cfg.get("外す") or [])
NT_DESC, NT_COND = "Not tested. Please check the photos.", "NOT TESTED - we have not tested this item and its function is not confirmed."
out["外した"] = []
for r in [x for x in read_ledger() if x["SKU"] in REM and x.get("offerId")] if live else []:
    sku = r["SKU"]
    try:
        it = eb.inventory_item(sku)
        p = it.get("product") or {}
        old = p.get("title") or ""
        p["title"] = re.sub(r"\s+", " ", re.sub(r"\bTested Working\b|\bTested\b", "", old)).strip()
        if it.get("conditionDescription"):
            it["conditionDescription"] = it["conditionDescription"].replace(REP, NT_COND)
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        o = [x for x in eb.offers_of(sku) if x.get("offerId") == r["offerId"]]
        if o and REP in (o[0].get("listingDescription") or ""):
            of = dict(o[0])
            of["listingDescription"] = of["listingDescription"].replace(REP, NT_DESC)
            for k in ("offerId", "status", "listing"):
                of.pop(k, None)
            eb.call("PUT", "/sell/inventory/v1/offer/" + r["offerId"], of, headers=CL)
        if re.search(r"\bTested\b", (eb.inventory_item(sku).get("product") or {}).get("title") or ""):
            raise EbayError(0, {"raw": "読み直したら Tested が残っている"})
        r["タイトル"] = p["title"]
        changed.append(r)
        out["外した"].append({"SKU": sku, "前": old, "後": p["title"]})
    except EbayError as e:
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:300]})
if changed:
    save_ledger(changed, ["タイトル"], "動作確認のタイトル")
if live:
    cfg["本番"] = False
    cfg.pop("SKU", None)
    cfg.pop("外す", None)
    save_json(P, cfg)
save_json(RP, out)
msg = "【動作確認済みのタイトル】%s %s：見た%d品・仕入れ先が動作確認済み %d品（Tested Working 入っている %d・入っていない %d）%s" % (
    jst(), "本番" if live else "ドライラン", out["見た"], out["動作確認済み"], out["入っている"], out["入っていない"],
    ("・直した %d・失敗 %d" % (len(out["直した"]), len(out["失敗"]))) if live else "")
msg += "・外した %d" % len(out.get("外した", []))
print(msg)
notify(msg)
