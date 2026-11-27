"""値下げ交渉の返事を eBay の自動にそろえる：GitHub が見ている出品（台帳に offerId・出品中）のオファーに、
自動で断る値段＝最低利益の値段、自動で受け入れる値段＝最低利益の値段＋$0.01 を付ける（GitHub で出す品と同じ）。
最低利益の値段が今の値段以上の品は、値下げ交渉を受けない。1件ずつ読み直して確かめる。
11/28 08:08 オーナー「1と2をやって」：教科書の式（自動で受ける＝利益9%の値段と売値の99%の低いほう・断る＝フロア）。
時刻表 値下げ交渉の設定 → 教科書の式 が false の間はドライラン（eBay は変えず、data/値下げ交渉/教科書の式_ドライラン.json に予定を書く）。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (Ebay, EbayError, err_text, jst, notify, read_ledger, settings, floor_price, num, write_run, mark_started, load_json,
                    save_json, ROOT, is_target, timetable, best_offer_terms)

NAME = "値下げ交渉の設定"
CL = {"Content-Language": "en-US"}


def main():
    cfg, tt = settings(), timetable(NAME)
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready():
        write_run(NAME, False, 0, 1)
        return 0
    done_p = os.path.join(ROOT, "data", "値下げ交渉", "設定済み.json")
    done = load_json(done_p, {})
    rows = [r for r in read_ledger() if is_target(r) and r.get("状態") == "出品中"]
    ok, skip, bad = 0, 0, []
    tb = bool(tt.get("教科書の式"))
    if not tb:   # ドライラン：教科書の式にしたらどうなるか
        plan = []
        for r in rows:
            price = num(r.get("売値(ドル)")) or 0
            fp = floor_price(r, cfg)
            if not fp or not price:
                continue
            t = best_offer_terms(r, cfg, price, fp=fp, textbook=True)
            if t.get("bestOfferEnabled"):
                acc = float(t["autoAcceptPrice"]["value"])
                plan.append({"SKU": r["SKU"], "値段": price, "自動で断る": fp, "今の自動で受ける": round(fp + 0.01, 2), "教科書の自動で受ける": acc,
                             "交渉の幅$": round(acc - fp, 2)})
        save_json(os.path.join(ROOT, "data", "値下げ交渉", "教科書の式_ドライラン.json"), {"時刻": jst(), "交渉を受ける品": len(plan), "品": plan})
        wide = [x for x in plan if x["交渉の幅$"] >= 1]
        print("ドライラン 交渉を受ける品", len(plan), "幅$1以上", len(wide))
    for r in (rows if tb else [])[: int(tt.get("1回の上限_件", 400))]:
        oid = r["offerId"]
        price = num(r.get("売値(ドル)")) or 0
        fp = floor_price(r, cfg)
        if not fp or not price:
            skip += 1
            continue
        want = best_offer_terms(r, cfg, price, fp=fp, textbook=True)
        key = "%s|%.2f|%.2f|%s" % (oid, price, fp, (want.get("autoAcceptPrice") or {}).get("value", "off"))
        if done.get(r["SKU"]) == key:
            continue
        try:
            _, o = eb.call("GET", "/sell/inventory/v1/offer/" + oid)
            pol = o.get("listingPolicies") or {}
            pol["bestOfferTerms"] = want
            o["listingPolicies"] = pol
            for k in ("offerId", "status", "listing", "marketplaceId_"):
                o.pop(k, None)
            eb.call("PUT", "/sell/inventory/v1/offer/" + oid, o, headers=CL)
            _, chk = eb.call("GET", "/sell/inventory/v1/offer/" + oid)
            bt = (chk.get("listingPolicies") or {}).get("bestOfferTerms") or {}
            if bool(bt.get("bestOfferEnabled")) != bool(want.get("bestOfferEnabled")) or \
                    (want.get("bestOfferEnabled") and abs(float((bt.get("autoAcceptPrice") or {}).get("value") or 0) - float(want["autoAcceptPrice"]["value"])) > 0.005):
                raise RuntimeError("読み直したら設定が違う：%s" % bt)
            done[r["SKU"]] = key
            ok += 1
        except (EbayError, RuntimeError) as e:
            bad.append("%s %s" % (r["SKU"], err_text(e)[:200]))
            if len(bad) >= 5:
                break
        time.sleep(0.3)
    save_json(done_p, done)
    msg = "【値下げ交渉の設定】%s %s%d品に自動の受け入れ・断りの値段を付けた（教科書の式）%s" % (jst(), "" if tb else "ドライラン（eBayは変えていない）・", ok, ("／できなかった %d品：%s" % (len(bad), " / ".join(bad[:3]))) if bad else "")
    print(msg)
    notify(msg)
    write_run(NAME, not bad, ok, len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
