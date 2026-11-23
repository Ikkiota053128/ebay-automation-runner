"""終えた（withdraw した）品を出し直す（手で動かす）。
11/24 08:36 オーナー「Casio DW-6900U G-SHOCK・Nikon L35AWAD フィルムカメラ この2つ以外は在庫ある」：
在庫を確かめられないので 11/24 07:34 に終えたメルカリの品のうち、オーナーがメルカリで在庫を見た品を出し直す。
- data/判定/出し直し.json：{"本番": false, "SKU": [...]}。本番 false はドライラン。
- 未公開のオファーだけを出す。在庫が0なら1にする。値段が最低利益の値段（common.floor_price）より安ければ、その値段まで上げてから出す。
- 出したあと読み直して PUBLISHED を確かめ、台帳の 状態・eBayの出品ID・最後に仕入元を確認した日時・メモ を直す。
- 結果は data/判定/出し直し_結果.json。"""
import os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger, settings, floor_price, num

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "出し直し.json")
RP = os.path.join(ROOT, "data", "判定", "出し直し_結果.json")


def main():
    cfg = load_json(P, {"本番": False, "SKU": []})
    live = bool(cfg.get("本番"))
    sc = settings()
    eb = Ebay()
    rows = read_ledger()
    by = {r["SKU"]: r for r in rows}
    out = {"時刻": jst(), "本番": live, "出した": [], "予定": [], "失敗": []}
    ch = []
    for sku in cfg.get("SKU") or []:
        r = by.get(sku)
        if not r:
            out["失敗"].append({"SKU": sku, "エラー": "台帳に無い"})
            continue
        try:
            offs = eb.offers_of(sku)
            if any(o.get("status") == "PUBLISHED" for o in offs):
                out["失敗"].append({"SKU": sku, "エラー": "もう出品中"})
                continue
            if not offs:
                out["失敗"].append({"SKU": sku, "エラー": "オファーが無い"})
                continue
            o = dict(offs[0])
            oid = o["offerId"]
            price = num((o.get("pricingSummary") or {}).get("price", {}).get("value"))
            fl = floor_price(r, sc)
            new = round(max(price or 0, fl or 0), 2)
            plan = {"SKU": sku, "offerId": oid, "今$": price, "フロア$": fl, "出す$": new, "タイトル": (r.get("タイトル") or "")[:60]}
            if not fl:
                out["失敗"].append(dict(plan, エラー="最低利益の値段が出せない（仕入値・送料などが台帳に無い）"))
                continue
            if not live:
                out["予定"].append(plan)
                continue
            it = eb.inventory_item(sku)
            q = ((it.get("availability") or {}).get("shipToLocationAvailability") or {}).get("quantity") or 0
            if int(q) < 1:
                it.setdefault("availability", {}).setdefault("shipToLocationAvailability", {})["quantity"] = 1
                body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
                pw = body.get("packageWeightAndSize") or {}
                if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
                    pw.pop("weight", None)
                    if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                        body.pop("packageWeightAndSize", None)
                eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
            if price is None or new > price + 0.004:
                o.pop("offerId", None); o.pop("status", None); o.pop("listing", None)
                o.setdefault("pricingSummary", {})["price"] = {"value": "%.2f" % new, "currency": "USD"}
                o["availableQuantity"] = 1
                eb.call("PUT", "/sell/inventory/v1/offer/" + oid, o, headers=CL)
            _, pub = eb.call("POST", "/sell/inventory/v1/offer/%s/publish" % oid, {})
            chk = [x for x in eb.offers_of(sku) if x.get("offerId") == oid]
            if not chk or chk[0].get("status") != "PUBLISHED":
                raise EbayError(0, {"raw": "出したあと読み直したら公開になっていない"})
            lid = (chk[0].get("listing") or {}).get("listingId") or (pub or {}).get("listingId") or r.get("eBayの出品ID")
            r["状態"], r["eBayの出品ID"], r["売値(ドル)"] = "出品中", str(lid), "%.2f" % new
            r["最後に仕入元を確認した日時"] = jst()
            r["メモ"] = ((r.get("メモ") or "") + "・%s 出し直した（オーナーがメルカリで在庫を見た）" % jst())[:500]
            ch.append(r)
            out["出した"].append(dict(plan, 出品ID=lid))
        except EbayError as e:
            out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:400]})
    if live:
        if ch:
            save_ledger(ch, ["状態", "eBayの出品ID", "売値(ドル)", "最後に仕入元を確認した日時", "メモ"], "出し直し")
        cfg["本番"] = False
        cfg["SKU"] = [s for s in cfg.get("SKU") or [] if s not in {x["SKU"] for x in out["出した"]}]
        save_json(P, cfg)
    save_json(RP, out)
    print("本番" if live else "ドライラン", "出した", len(out["出した"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
