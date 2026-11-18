# ③ 在庫の監視（教科書 第6章・CLAUDE.md 5章・10章・14章）
#  仕入元のページを読み、「ある／ない／読めなかった」の3つに分ける。「読めなかった」は売り切れにしない。
#  ない → eBayの在庫を0（bulkUpdatePriceQuantity）→ getInventoryItem で0を読み直してから台帳を「在庫ゼロ」に。
#  在庫ゼロの品が戻った → 最初は人に聞く（通知で一覧を出す。戻すのは data/答え/ の「在庫を戻す」の答えが来てから）。
#  売れた品の仕入元が売り切れ → 事故としてすぐ知らせる。
#  扱うのは Inventory API へ移し終えた品（台帳に offerId がある品）・仕入元の種類 A と C だけ（B は確認リスト）。
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, Ebay, EbayError, err_text, num, now, jst, settings, timetable, notify, notify_once_a_day, read_ledger, save_ledger,
                    is_target, write_run, mark_started, usual_ok, usual_add, load_json, save_json)

NAME = "在庫の監視"
UA = "Mozilla/5.0 (compatible; ebay-automation stock check)"
SOLD_TXT = re.compile(r"在庫切れ|売り切れ|SOLD\s?OUT|品切れ|在庫がありません|販売を終了|販売終了|お取り扱いできません|入荷待ち|"
                      r"このオークションは終了しています|オークションは終了|出品者により削除|この商品は削除されました|ページが見つかりません", re.I)
CART_TXT = re.compile(r"カートに入れる|カートへ入れる|購入手続きへ|買い物かごに入れる|購入する|入札する|今すぐ落札")


def kind_of(url, cfg):
    m = re.match(r"https?://([^/]+)", url or "")
    return cfg.get("仕入元の種類_ドメインごと", {}).get(m.group(1) if m else "", "") if m else ""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # 通信の失敗は「読めなかった」
        return None, str(e)[:120]


def rakuten_stock(url):
    """楽天のページは GitHub から読めない（アクセスを断られる）ので、楽天の公式API（商品コードで探す・売り切れも含む）で見る。
    返事：(ある=True／ない=False／読めなかった=None, 理由)。中継（RAKUTEN_RELAY_URL）を通す（アプリが許可したIPだけ）"""
    m = re.match(r"https?://item\.rakuten\.co\.jp/([^/?#]+)/([^/?#]+)", url or "")
    rid, acc = os.environ.get("RAKUTEN_APP_ID", "").strip(), os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
    relay, tok = os.environ.get("RAKUTEN_RELAY_URL", "").strip(), os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()
    if not m or not (rid and acc and relay):
        return "skip", ""
    q = {"format": "json", "formatVersion": 2, "applicationId": rid, "itemCode": "%s:%s" % (m.group(1), m.group(2)), "availability": 0, "hits": 1}
    req = urllib.request.Request(relay.rstrip("/") + "/search?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": UA, "accessKey": acc, "X-Relay-Token": tok})
    j = None
    for k in range(3):   # 楽天のAPIは GAS・店の地引網と同じ鍵 → 429 なら少し待ってやり直す
        try:
            j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and k < 2:
                time.sleep(6 * (k + 1))
                continue
            try:
                body = e.read().decode("utf-8", "replace")[:120]
            except Exception:
                body = ""
            return None, "楽天API HTTP %s %s" % (e.code, body)
        except Exception as e:
            return None, "楽天API %s" % str(e)[:80]
    if j is None:
        return None, "楽天API 返事なし"
    if False:
        pass
    items = j.get("items") or j.get("Items") or []
    if not items:
        return None, "楽天APIで商品が見つからない（消えた可能性）"
    it = items[0].get("Item", items[0])
    return (True, "在庫あり（楽天API）") if int(it.get("availability") or 0) == 1 else (False, "売り切れ（楽天API）")


def judge(code, html):
    """返事：(ある=True／ない=False／読めなかった=None, 理由)"""
    if code in (404, 410):
        return False, "商品ページがなくなった（%s）" % code
    if code != 200:
        return None, "HTTP %s" % code
    av = [a for b in re.findall(r"<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>", html, re.I)
          for a in re.findall(r'"availability"\s*:\s*"([^"]+)"', b)]
    if any(re.search(r"InStock|LimitedAvailability|OnlineOnly", a, re.I) for a in av):
        return True, "在庫あり（ページのデータ）"
    if av and all(re.search(r"OutOfStock|SoldOut|Discontinued", a, re.I) for a in av):
        return False, "売り切れ（ページのデータ）"
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    if SOLD_TXT.search(text):
        return False, "ページに売り切れの表示"
    if CART_TXT.search(text):
        return True, "ページに「カートに入れる」"
    return None, "在庫を判断できない"


def main():
    cfg, tt = settings(), timetable(NAME)
    live = bool(tt.get("実行"))
    scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    gap = float(tt.get("アクセスの間隔_秒", 3))
    t_end = time.time() + 60 * float(tt.get("時間の上限_分", 30)) - 120
    eb = Ebay()
    mark_started(NAME)
    if not eb.ready():
        notify_once_a_day("鍵なし_在庫の監視", "【在庫の監視】GitHub に eBay の鍵が無いので、何もしていません")
        write_run(NAME, False, 0, 1)
        return 0   # 鍵が入るまでは毎回赤くしない（知らせは1日1回）
    ledger = read_ledger()
    today = jst()[:10]
    # A・C は毎回。B（個人のフリマ・オークション）は1品1日1回だけ（2026-11-18 オーナー承認：プログラムが見る）
    rows = [r for r in ledger if is_target(r) and r.get("状態") in ("出品中", "在庫ゼロ", "売れた")
            and (kind_of(r.get("仕入元URL"), cfg) in ("A", "C")
                 or (kind_of(r.get("仕入元URL"), cfg) == "B" and "mercari" not in str(r.get("仕入元URL"))   # メルカリは機械で見ない（オーナーの決めごと）
                     and not str(r.get("最後に仕入元を確認した日時", "")).startswith(today)))]
    rows.sort(key=lambda r: r.get("最後に仕入元を確認した日時", ""))   # 長く見ていない品から
    unk = load_json(os.path.join(ROOT, "data", "在庫の監視", "読めない回数.json"), {})
    out = {"ある": [], "ない": [], "読めない": []}
    why_unk = {}
    zero, back, accident, gone404, alerts = [], [], [], [], []
    for r in rows:
        if time.time() > t_end:
            break
        ok, why = rakuten_stock(r["仕入元URL"])
        code = None
        if ok == "skip":
            code, html = fetch(r["仕入元URL"])
            ok, why = judge(code, html)
        else:
            time.sleep(1.5)   # 楽天APIの節度（1.5秒に1回）
        r["最後に仕入元を確認した日時"] = jst()
        if ok is None:
            unk[r["SKU"]] = unk.get(r["SKU"], 0) + 1
            out["読めない"].append(r["SKU"])
            why_unk[why[:60]] = why_unk.get(why[:60], 0) + 1
            if unk[r["SKU"]] == 3:
                alerts.append("読めない状態が3回続いた %s（%s）" % (r["SKU"], why))
        else:
            unk.pop(r["SKU"], None)
            out["ある" if ok else "ない"].append(r["SKU"])
            if code in (404, 410):
                gone404.append(r["SKU"])
            if r["状態"] == "売れた" and not ok:
                accident.append("%s（%s）" % (r["SKU"], why))
            elif r["状態"] == "出品中" and not ok:
                zero.append(r)
            elif r["状態"] == "在庫ゼロ" and ok:
                back.append(r["SKU"])
        time.sleep(gap)
    save_json(os.path.join(ROOT, "data", "在庫の監視", "読めない回数.json"), unk)
    if accident:   # 事故はすぐ知らせる（第6章）
        notify("【在庫の監視・事故】売れたのに仕入元に無い：\n" + "\n".join(accident))
    msg = ["【在庫の監視】%s %s：見た %d品（ある %d・ない %d・読めなかった %d）" %
           (jst(), "本番" if live else "ドライラン", len(out["ある"]) + len(out["ない"]) + len(out["読めない"]),
            len(out["ある"]), len(out["ない"]), len(out["読めない"]))]
    # 予備の仕入れ先（GAS の ysBackup_ と同じ考え方）：仕入元で売り切れた品は、楽天・Yahoo!ショッピングで同じ型番の在庫ありの品を探す。
    # 仕入値が前の仕入値以下（＝利益が減らない）で、商品名に型番がはっきりある品が見つかれば、仕入元を付け替えて在庫を0にしない
    switched = []
    if zero:
        try:
            from price_adjust import model_of
            from shop_sweep import rakuten, yahoo, keep
            from flea_sweep import compile_models
            rk = {"id": os.environ.get("RAKUTEN_APP_ID", "").strip(), "access": os.environ.get("RAKUTEN_ACCESS_KEY", "").strip(),
                  "relay": os.environ.get("RAKUTEN_RELAY_URL", "").strip(), "relay_token": os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()}
            ya = os.environ.get("YAHOO_CLIENT_ID", "").strip()
            keep_zero = []
            for r in zero:
                md = model_of(r.get("タイトル"))
                cost = num(r.get("仕入値(円)")) or 0
                if not md or not cost:
                    keep_zero.append(r)
                    continue
                m = compile_models([{"maker": (r.get("タイトル") or "").split(" ")[0], "model": md, "cap": int(cost)}])[0]
                best = None
                for fn, ok in ((lambda mm: rakuten(mm, rk), rk["id"] and rk["access"]), (lambda mm: yahoo(mm, ya), ya)):
                    if not ok:
                        continue
                    code, items = fn(m)
                    time.sleep(3)
                    for it in items:
                        if it["url"] != r.get("仕入元URL") and not keep(it, m) and it["price"] <= cost and (not best or it["price"] < best["price"]):
                            best = it
                if best:
                    switched.append({"SKU": r["SKU"], "仕入元URL": best["url"], "仕入値(円)": best["price"],
                                     "メモ": ((r.get("メモ") or "") + "・%s 予備の仕入れ先に付け替え（前：%s %s円）" % (jst(), r.get("仕入元URL"), int(cost)))[:500]})
                else:
                    keep_zero.append(r)
            zero = keep_zero
            if switched:
                if live:
                    save_ledger(switched, ["仕入元URL", "仕入値(円)", "メモ"], NAME)
                msg.append("予備の仕入れ先に付け替え%s %d品：%s" % ("" if live else "（案）", len(switched), ", ".join(x["SKU"] for x in switched[:10])))
        except Exception as e:
            msg.append("予備の仕入れ先を探せなかった：%s" % str(e)[:120])
    cap = int(tt.get("1回に在庫ゼロにする上限_件", 20))
    done, bad = [], []
    if zero:
        pass
    if why_unk:
        msg.append("読めなかった理由：" + "・".join("%s %d" % kv for kv in sorted(why_unk.items(), key=lambda x: -x[1])[:4]))
    if zero:
        msg.append("在庫を0にする%s %d件：%s" % ("" if live else "案", len(zero), ", ".join(r["SKU"] for r in zero[:20])))
    if live and zero:
        ok, why = usual_ok(NAME, len(zero))
        if len(zero) > cap or not ok:
            msg.append("止めました（上限 %d件 / %s）。多すぎるので人が確かめてください" % (cap, why))
            zero = []
        res = eb.bulk_update([{"sku": r["SKU"], "shipToLocationAvailability": {"quantity": 0}} for r in zero]) if zero else {}
        for r in zero:
            okp, body = res.get(r["SKU"], (False, {}))
            if okp:
                try:
                    q = eb.inventory_item(r["SKU"]).get("availability", {}).get("shipToLocationAvailability", {}).get("quantity")
                    okp = q == 0
                    body = {"errors": [{"message": "読み直した在庫が %s" % q}]} if not okp else body
                except EbayError as e:
                    okp, body = False, {"errors": [{"message": err_text(e)}]}
            if okp:
                r["状態"] = "在庫ゼロ"
                done.append(r)
            else:
                bad.append((r["SKU"], err_text(body)))
        msg.append("在庫を0にした %d件・失敗 %d件" % (len(done), len(bad)))
        for s, e in bad[:5]:
            msg.append("失敗 %s：%s" % (s, e))
    if back:
        msg.append("仕入元に在庫が戻った（出品に戻すか聞きます。戻すなら「SKU○○を出品に戻して」と伝えてください）：" + ", ".join(back[:30]))
    if gone404:
        msg.append("仕入元のページが無くなった（404）：" + ", ".join(gone404[:20]))
    msg += alerts
    usual_add(NAME, len(out["ない"]), scheduled)
    # 台帳：確認日時（全部）と状態（0にできた品だけ）
    save_ledger(rows, ["最後に仕入元を確認した日時"], NAME)
    if done:
        save_ledger(done, ["状態"], NAME)
    save_json(os.path.join(ROOT, "data", "在庫の監視", now().strftime("%Y%m%d_%H%M") + ".json"),
              {"時刻": jst(), "本番": live, "ある": out["ある"], "ない": out["ない"], "読めない": out["読めない"],
               "在庫を0にした": [r["SKU"] for r in done], "失敗": bad, "戻った": back, "事故": accident, "読めない理由": why_unk})
    write_run(NAME, not bad, len(rows), len(bad) + len(alerts))
    notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
