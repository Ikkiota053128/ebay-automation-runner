# 今の出品（Trading APIで出したもの）を Inventory API へ移す（CLAUDE.md 13章・14章）
#  bulkMigrateListing：POST /sell/inventory/v1/bulk_migrate_listing、本文 {"requests":[{"listingId":…}]}、1回5件まで（公式で確認 2026-11-18）
#  返事は1件ずつ statusCode・inventoryItems[].sku・offerId（成功のときだけ）・errors を見る。
#  移したら getOffers で読み直し、PUBLISHED で出品IDが同じことを確かめてから台帳に offerId を書く。
#  順番：カナリア5件 → 20件 → 残り。人が手で動かす（workflow_dispatch の「件数」）。
#  移すのは、新しい在庫の監視が見られる仕入元（種類 A と C）の品だけ。フリマ（B）は確認リストができるまで GAS のまま。
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, Ebay, EbayError, err_text, now, jst, settings, timetable, notify, read_ledger, save_ledger,
                    write_run, load_json, save_json)
from stock_watch import kind_of

NAME = "今の出品の移行"
LIST = os.path.join(ROOT, "data", "移行", "移した出品.json")


# 出さない決まりの品（店のルール：キャラクター・コラボ・ゲーム）は移さない。終えるかはオーナーが決める
RULE_OUT = re.compile(r"\b(PS[2-5]|PlayStation|Nintendo Switch|Switch|Xbox|Game Software|Video Game|Treasure Box|Limited Edition Game|"
                      r"Famicom|Super Famicom|Game ?Boy|Mega Drive|Pokemon|Pok[eé]mon|Zelda|Mario|Demon Slayer|Ghibli|Totoro|One Piece|"
                      r"Dragon Ball|Gundam|Sanrio|Hello Kitty|Disney|Marvel|Star Wars|Anime|Figure)\b", re.I)


def candidates(ledger, cfg):
    stk = cfg.get("有在庫の目印_SKUの頭", "STK-")
    return [r for r in ledger if r.get("SKU") and not r["SKU"].startswith(stk) and not r["SKU"].startswith("要付与-")
            and not r.get("offerId")   # 11/18 夜：ゲーム・キャラクターの今の出品も移す（値段の調整だけ。新しくは出さない決めごとAはそのまま）
            and r.get("eBayの出品ID") and r.get("状態") == "出品中"   # 11/18 夜：メルカリの品も移す（値段の調整・値下げ交渉だけ。在庫は機械で見ない）
            and (kind_of(r.get("仕入元URL"), cfg) in ("A", "B", "C") or not r.get("仕入元URL"))]   # 11/18 夜：B（1日1回）と、仕入元URLの無い古い出品（値段の調整だけ）も移す


def main():
    cfg, tt = settings(), timetable(NAME)
    live = bool(tt.get("実行"))
    want = int(os.environ.get("MIGRATE_COUNT") or 0) or int(tt.get("カナリアの件数", 5))
    if not tt.get("カナリア済み"):
        want = min(want, int(tt.get("カナリアの件数", 5)))
    elif not tt.get("20件済み"):
        want = min(want, int(tt.get("次の件数", 20)))
    ledger = read_ledger()
    cand = candidates(ledger, cfg)
    nosku = [r for r in ledger if r.get("SKU", "").startswith("要付与-") and r.get("状態") == "出品中"]
    ruled = [r for r in ledger if r.get("状態") == "出品中" and RULE_OUT.search(r.get("タイトル", ""))]
    msg = ["【今の出品の移行】%s %s：移せる品 %d件・今回 %d件まで" % (jst(), "本番" if live else "ドライラン", len(cand), want)]
    if nosku:
        msg.append("SKUが無いので移せない品 %d件（先にSKUを付けます）" % len(nosku))
    if ruled:
        msg.append("出さない決まり（ゲーム・キャラクターなど）に当たるので移さない品 %d件：%s" % (len(ruled), ", ".join(r["SKU"] for r in ruled[:15])))
    pick = cand[:want]
    if not live:
        msg.append("移す予定：" + ", ".join("%s(%s)" % (r["SKU"], r["eBayの出品ID"]) for r in pick))
        eb = Ebay()
        if eb.ready():   # 読むだけ：鍵が使えるか・まだ移していないか
            for r in pick:
                try:
                    o = eb.offers_of(r["SKU"])
                    msg.append("・%s %s" % (r["SKU"], "まだ移していない（OK）" if not o else "もうオファーがある：%s" % o[0].get("offerId")))
                except EbayError as e:
                    msg.append("・%s 読めない：%s" % (r["SKU"], err_text(e)))
        write_run(NAME, True, len(pick), 0)
        notify("\n".join(msg))
        return 0
    eb = Ebay()
    if not eb.ready():
        notify("【今の出品の移行】GitHub に eBay の鍵が無いので、何もしていません")
        write_run(NAME, False, 0, 1)
        return 1
    moved = load_json(LIST, {})
    done, bad, ended = [], [], []
    for i in range(0, len(pick), 5):
        part = pick[i:i + 5]
        try:
            _, j = eb.call("POST", "/sell/inventory/v1/bulk_migrate_listing",
                           {"requests": [{"listingId": r["eBayの出品ID"]} for r in part]})
        except EbayError as e:
            j = e.body or {}
            if not j.get("responses"):
                bad += [(r["SKU"], err_text(e)) for r in part]
                continue
        got = {str(x.get("listingId")): x for x in j.get("responses", [])}
        for r in part:
            x = got.get(r["eBayの出品ID"], {})
            items = x.get("inventoryItems") or []
            oid = items[0].get("offerId") if items else None
            sku = items[0].get("sku") if items else r["SKU"]
            if x.get("statusCode") != 200 or not oid:
                et = err_text(x) or "返事に入っていない"
                if "already migrated" in et:   # 前の回で移っていた（読み直しが間に合わなかった）→ SKUで照会して確かめる
                    offs = [o for o in eb.offers_of(r["SKU"]) if str((o.get("listing") or {}).get("listingId")) == r["eBayの出品ID"]]
                    if offs and offs[0].get("status") in ("PUBLISHED", "UNPUBLISHED"):
                        oid, sku = offs[0]["offerId"], r["SKU"]
                if not oid:
                    bad.append((r["SKU"], et))
                    continue
            offs = [o for o in eb.offers_of(sku) if o.get("offerId") == oid]   # 読み直して確かめる
            if offs and offs[0].get("status") == "UNPUBLISHED":   # eBayではもう終わっていた出品（台帳が古かった）
                r["offerId"], r["移した日時"], r["状態"] = oid, jst(), "終了"
                r["メモ"] = (r.get("メモ", "") + " 移したら eBay ではもう終わっていた（未公開のオファー）。出し直さない").strip()
                moved[r["SKU"]] = {"出品ID": r["eBayの出品ID"], "offerId": oid, "移した日時": jst(), "メモ": "eBayでは終了済み"}
                ended.append(r)
                continue
            if not offs or offs[0].get("status") != "PUBLISHED" or str((offs[0].get("listing") or {}).get("listingId")) != r["eBayの出品ID"]:
                bad.append((r["SKU"], "移したあとの読み直しで、出品中のオファーが見つからない"))
                continue
            r["offerId"], r["移した日時"] = oid, jst()
            if not r.get("出品日"):
                r["メモ"] = (r.get("メモ", "") + " 出品日が不明のため、売れない日数は移した日から数える").strip()
            moved[r["SKU"]] = {"出品ID": r["eBayの出品ID"], "offerId": oid, "移した日時": jst()}
            done.append(r)
    save_json(LIST, moved)
    if done:
        save_ledger(done, ["offerId", "移した日時", "メモ"], NAME)
    if ended:
        save_ledger(ended, ["offerId", "移した日時", "状態", "メモ"], NAME)
    msg.append("移した %d件・失敗 %d件%s" % (len(done), len(bad), "・eBayではもう終わっていた %d件（台帳を終了に）：%s" % (len(ended), ", ".join(r["SKU"] for r in ended)) if ended else ""))
    msg += ["失敗 %s：%s" % b for b in bad[:10]]
    if done:
        msg.append("公開ページで、値段・送料・写真が変わっていないか、最初の数件を目で見てください")
    if bad:
        save_json(os.path.join(ROOT, "data", "移行", "失敗_" + now().strftime("%Y%m%d_%H%M") + ".json"), [{"SKU": s, "エラー": e} for s, e in bad])
    write_run(NAME, not bad, len(done), len(bad))
    print("\n".join(msg))
    notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
