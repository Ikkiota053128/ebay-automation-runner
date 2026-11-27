"""届いた値下げ交渉（ベストオファー）に、教科書どおりフロアで返事をする（第8章 型②）。11/28 08:08 オーナー「1と2をやって」。
- 自動で受ける金額（教科書の式）以上 → 受ける（ふつうは eBay が自動で受ける）
- フロア以上・自動で受ける金額より下 → 自動で受ける金額でカウンターオファー（一度出した額は動かさない：同じ品はいつも同じ額）
- フロアより下 → 断る（ふつうは eBay が自動で断る）
- data/値下げ交渉/返事.json：{"本番": false} の間はドライラン（返事はせず、予定だけ記録して知らせる）。
- 買い手のID・名前・メッセージは読まない・記録しない（4章）。記録するのは SKU・金額・オファーの番号だけ。"""
import os, re, sys, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, jst, load_json, save_json, read_ledger, settings, floor_price, best_offer_terms, num, notify, write_run, mark_started

NAME = "値下げ交渉の返事"
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
MSG = "Thank you for your offer! This is our best price. Ships from Okinawa, Japan with tracking."


def main():
    mark_started(NAME)
    cfg_p = os.path.join(ROOT, "data", "値下げ交渉", "返事.json")
    live = bool(load_json(cfg_p, {"本番": False}).get("本番"))
    st, eb = settings(), Ebay()
    by_lid = {r.get("eBayの出品ID"): r for r in read_ledger() if r.get("eBayの出品ID")}
    log_p = os.path.join(ROOT, "data", "値下げ交渉", "返事の記録.json")
    log = load_json(log_p, {"返事した": {}})
    did = log.setdefault("返事した", {})
    out = {"時刻": jst(), "本番": live, "来ている": 0, "予定": [], "返事した": [], "失敗": []}
    x = eb.trading("GetBestOffers", "<BestOfferStatus>Active</BestOfferStatus><DetailLevel>ReturnAll</DetailLevel>")
    root = ET.fromstring(x)
    ack = root.findtext("e:Ack", "", NS)
    if ack not in ("Success", "Warning"):
        m = root.findtext(".//e:Errors/e:LongMessage", "", NS)
        if "No Best Offers" in m or "Not Found" in m:
            ack = "Success"
        else:
            out["失敗"].append({"どこ": "GetBestOffers", "エラー": m[:400]})
    for ib in root.findall(".//e:ItemBestOffers", NS):
        lid = ib.findtext("e:Item/e:ItemID", "", NS)
        r = by_lid.get(lid)
        for bo in ib.findall(".//e:BestOffer", NS):
            if bo.findtext("e:Status", "", NS) != "Pending":
                continue
            out["来ている"] += 1
            bid = bo.findtext("e:BestOfferID", "", NS)
            op = num(bo.findtext("e:Price", "", NS)) or 0
            if bid in did:
                continue
            if not r:
                out["失敗"].append({"出品ID": lid, "エラー": "台帳に無い出品（人が Seller Hub で返事）"})
                continue
            price, fp = num(r.get("売値(ドル)")) or 0, floor_price(r, st)
            t = best_offer_terms(r, st, price, fp=fp, textbook=True) if fp else {}
            if not fp or not t.get("bestOfferEnabled"):
                out["失敗"].append({"SKU": r["SKU"], "エラー": "フロアが出せない・交渉を受けない値段（人が返事）", "オファー$": op})
                continue
            acc = float(t["autoAcceptPrice"]["value"])
            if op >= acc:
                act, cp = "Accept", None
            elif op >= fp:
                act, cp = "Counter", acc
            else:
                act, cp = "Decline", None
            plan = {"SKU": r["SKU"], "オファーの番号": bid, "オファー$": op, "値段$": price, "フロア$": fp, "返事": {"Accept": "受ける", "Counter": "カウンター", "Decline": "断る"}[act],
                    "カウンター$": cp}
            if not live:
                out["予定"].append(plan)
                continue
            body = "<ItemID>%s</ItemID><BestOfferID>%s</BestOfferID><Action>%s</Action>" % (lid, bid, act)
            if cp:
                body += '<CounterOfferPrice currencyID="USD">%.2f</CounterOfferPrice><CounterOfferQuantity>1</CounterOfferQuantity><SellerResponse>%s</SellerResponse>' % (cp, MSG)
            y = eb.trading("RespondToBestOffer", body)
            if re.search(r"<Ack>(Success|Warning)</Ack>", y):
                did[bid] = dict(plan, 日時=jst())
                out["返事した"].append(plan)
            else:
                out["失敗"].append(dict(plan, エラー=(re.search(r"<LongMessage>([^<]*)", y) or [None, y[:300]])[1][:400]))
    log["最後"] = out
    save_json(log_p, log)
    lines = ["%s $%.2f → %s%s" % (p["SKU"], p["オファー$"], p["返事"], (" $%.2f" % p["カウンター$"]) if p.get("カウンター$") else "") for p in (out["返事した"] or out["予定"])]
    if lines or out["失敗"]:
        notify("【値下げ交渉の返事】%s %s 来ている%d件・%s%d件%s\n%s" % (jst(), "本番" if live else "ドライラン（返事はしていない）", out["来ている"],
                                                         "返事した" if live else "予定", len(lines), ("・失敗%d件" % len(out["失敗"])) if out["失敗"] else "", "\n".join(lines[:15])))
    print("本番" if live else "ドライラン", "来ている", out["来ている"], "予定", len(out["予定"]), "返事した", len(out["返事した"]), "失敗", len(out["失敗"]))
    write_run(NAME, not out["失敗"], len(out["返事した"]), len(out["失敗"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
