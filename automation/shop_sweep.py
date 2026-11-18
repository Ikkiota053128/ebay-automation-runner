"""店の地引網（教科書 第3章「地引網」）：楽天市場・Yahoo!ショッピングを、型番リストの型番ごとに公式APIで見て回る。

- 型番リストは GAS から読む（page=models。仕入れ上限 cap・出品中かどうか listed つき）。出品中の型番は見ない（同じ型番を2品出さない）。
- 楽天は新着順（-updateTimestamp）、Yahoo!ショッピングは安い順。どちらも「仕入れ上限以下・在庫あり」だけ。
- 商品名に型番がはっきり入っている品だけ残す。ジャンク・付属品・レンタルは外す。前に見た品は14日間見ない。
- 時刻表.json の「実行」が false の間はドライラン（集めて数えて記録・通知するだけ。GASには送らない）。
  本番では GAS に送り、GAS が今までどおり利益・送料・eBayの相場・検査をして GO を決める（フリマ新着の地引網と同じ受け取り口）。
- 節度：楽天は1.5秒に1回・Yahoo!は1秒に1回まで。429 が来たら、その回はそのAPIをやめる。
- 秘密は環境変数（GitHub Secrets）からだけ読む。ログに出さない。
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flea_sweep import gas_get_models, gas_post, compile_models, match, NG, ACC, ACC_OK, now, notify
from common import ROOT, load_json, save_json, write_run, mark_started, jst, timetable

NAME = "店の地引網"
RK = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
YS = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
RENTAL = re.compile(r"レンタル|貸出|貸し出し|\d泊\d日|\brental\b", re.I)
UA = "ebay-automation shop sweep"


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return None, {}


def rakuten(m, key):
    q = {"format": "json", "formatVersion": 2, "applicationId": key["id"], "keyword": (m["maker"] + " " + m["model"]).strip()[:60],
         "sort": "-updateTimestamp", "availability": 1, "hits": 30, "page": 1}
    if m["cap"] > 0:
        q["maxPrice"] = m["cap"]
    if key.get("relay"):   # 楽天のアプリは「許可されたIP」を中継（固定IP）だけにしているので、GASと同じ中継を通す
        code, j = get_json(key["relay"].rstrip("/") + "/search?" + urllib.parse.urlencode(q),
                           {"accessKey": key["access"], "X-Relay-Token": key.get("relay_token", "")})
    else:
        code, j = get_json(RK + "?" + urllib.parse.urlencode(q), {"accessKey": key["access"]})
    items = []
    for it in j.get("items", []) or j.get("Items", []):
        it = it.get("Item", it)
        imgs = [u.get("imageUrl", u) if isinstance(u, dict) else u for u in (it.get("mediumImageUrls") or [])]
        items.append({"id": "rk:" + str(it.get("itemCode", "")), "title": str(it.get("itemName", "")), "price": int(it.get("itemPrice") or 0),
                      "url": str(it.get("itemUrl", "")).split("?")[0], "photos": [str(u).split("?")[0] for u in imgs if u]})
    return code, items


def yahoo(m, appid):
    q = {"appid": appid, "query": (m["maker"] + " " + m["model"]).strip(), "results": 50, "sort": "+price", "in_stock": "true"}
    if m["cap"] > 0:
        q["price_to"] = m["cap"]
    code, j = get_json(YS + "?" + urllib.parse.urlencode(q))
    items = []
    for h in j.get("hits", []):
        img = (h.get("exImage") or {}).get("url") or (h.get("image") or {}).get("medium") or ""
        items.append({"id": "ys:" + str(h.get("code", "")), "title": str(h.get("name", "")), "price": int(h.get("price") or 0),
                      "url": str(h.get("url", "")), "photos": [img] if img else []})
    return code, items


def keep(it, m):
    t = it["title"]
    if not it["price"] or (m["cap"] and it["price"] > m["cap"]):
        return "上限より高い"
    if RENTAL.search(t):
        return "レンタル"
    if NG.search(t):
        return "ジャンク・付属品の言葉"
    if ACC.search(t) and not ACC_OK.search(t):
        return "付属品"
    hit = match(t, [m])
    if not hit:
        return "型番が商品名に無い"
    return ""


def main():
    tt = timetable(NAME)
    live = bool(tt.get("実行"))
    mark_started(NAME)
    rk = {"id": os.environ.get("RAKUTEN_APP_ID", "").strip(), "access": os.environ.get("RAKUTEN_ACCESS_KEY", "").strip(),
          "relay": os.environ.get("RAKUTEN_RELAY_URL", "").strip(), "relay_token": os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()}
    ya = os.environ.get("YAHOO_CLIENT_ID", "").strip()
    d = gas_get_models()
    if not d:
        notify("【店の地引網】GAS から型番リストを読めなかったので、何もしていません")
        write_run(NAME, False, 0, 1)
        return 1
    models = [m for m in compile_models(d["models"]) if not m["listed"]]
    per = int(tt.get("1回に見る型番の数", 120))
    cur_p = os.path.join(ROOT, "data", "店の地引網", "順番.json")
    cur = load_json(cur_p, {"i": 0})
    start = cur["i"] % max(len(models), 1)
    todo = (models[start:] + models[:start])[:per]
    seen_p = os.path.join(ROOT, "data", "店の地引網", "見た品.json")
    seen = {k: v for k, v in load_json(seen_p, {}).items() if v >= (now().timestamp() - 14 * 86400)}
    t_end = time.time() + 60 * float(tt.get("時間の上限_分", 20)) - 60
    stat = {"楽天": {"見た": 0, "残った": 0, "API": 0}, "Yahoo!": {"見た": 0, "残った": 0, "API": 0}}
    why, cands, stop, done = {}, [], set(), 0
    last = {"楽天": 0.0, "Yahoo!": 0.0}
    gap = {"楽天": float(tt.get("楽天の間隔_秒", 1.5)), "Yahoo!": float(tt.get("Yahooの間隔_秒", 3.0))}
    for m in todo:
        if time.time() > t_end:
            break
        for src, fn, ok in (("楽天", lambda mm: rakuten(mm, rk), rk["id"] and rk["access"]), ("Yahoo!", lambda mm: yahoo(mm, ya), ya)):
            if not ok or src in stop:
                continue
            w = last[src] + gap[src] - time.time()
            if w > 0:
                time.sleep(w)
            code, items = fn(m)
            last[src] = time.time()
            stat[src]["API"] += 1
            if code == 429:   # GAS も同じ鍵で使っている → 少し待って1回だけやり直す
                time.sleep(15)
                code, items = fn(m)
                last[src] = time.time()
                stat[src]["API"] += 1
            if code in (429, 403, 503) or code is None:
                stop.add(src)
                why["%s を止めた（HTTP %s）" % (src, code)] = 1
                continue
            for it in items:
                if it["id"] in seen:
                    continue
                stat[src]["見た"] += 1
                seen[it["id"]] = now().timestamp()
                r = keep(it, m)
                if r:
                    why[r] = why.get(r, 0) + 1
                    continue
                stat[src]["残った"] += 1
                it.update({"型番": m["model"], "メーカー": m["maker"], "src": src, "cap": m["cap"]})
                cands.append(it)
        done += 1
    cur["i"] = (start + done) % max(len(models), 1)
    save_json(cur_p, cur)
    save_json(seen_p, seen)
    # 送る順番：仕入値が上限より大きく安い品（もうかる見込みが高い品）から。送りきれない品は「送る待ち」に残して次の回へ（3日で捨てる）
    for c in cands:
        c["ratio"] = round(c["price"] / c["cap"], 3) if c.get("cap") else 1.0
        c["t"] = now().timestamp()
    back_p = os.path.join(ROOT, "data", "店の地引網", "送る待ち.json")
    back = {c["id"]: c for c in load_json(back_p, []) if c.get("t", 0) >= now().timestamp() - 3 * 86400}
    for c in cands:
        back.setdefault(c["id"], c)
    queue = sorted(back.values(), key=lambda c: c["ratio"])[: int(tt.get("送る待ちの上限_件", 1500))]
    n_send = int(tt.get("1回に送る上限_件", 30))
    if live and not tt.get("カナリア済み"):
        n_send = min(n_send, int(tt.get("カナリアの件数", 20)))
    cands = queue[:n_send] if live else cands
    sent = 0
    if live and cands:
        for src, host, site in (("楽天", "item.rakuten.co.jp", "楽天市場（GitHubの地引網）"), ("Yahoo!", "store.shopping.yahoo.co.jp", "Yahoo!ショッピング（GitHubの地引網）")):
            part = [c for c in cands if c["src"] == src]
            for i in range(0, len(part), 15):
                txt = gas_post({"kind": "search", "perItem": True, "noAi": True, "keyword": "", "url": "https://" + host + "/", "site": site,
                                "items": [{"url": c["url"], "title": c["title"][:200], "price": c["price"], "sold": False, "thumb": "\n".join(c["photos"]),
                                           "model": c["型番"], "maker": c["メーカー"]} for c in part[i:i + 15]]})
                if "合言葉が一致しません" in txt or "送信できませんでした" in txt:
                    raise SystemExit("GASが受け取りを断った")
                sent += len(part[i:i + 15])
                time.sleep(3)
    sent_ids = {c["id"] for c in cands} if live else set()
    save_json(back_p, [c for c in queue if c["id"] not in sent_ids])
    rec = {"時刻": jst(), "本番": live, "送る待ち": len(queue) - len(sent_ids), "見た型番": done, "型番の数": len(models), "数": stat, "外した理由": why,
           "候補": [{k: c[k] for k in ("src", "型番", "price", "title", "url")} for c in cands], "送った": sent}
    save_json(os.path.join(ROOT, "data", "店の地引網", now().strftime("%Y%m%d_%H%M") + ".json"), rec)
    msg = ["【店の地引網】%s %s：型番 %d／%d個を見た" % (jst(), "本番" if live else "ドライラン", done, len(models))]
    for s, v in stat.items():
        msg.append("%s：API %d回・新しく見た品 %d・候補 %d" % (s, v["API"], v["見た"], v["残った"]))
    if why:
        msg.append("外した理由：" + "・".join("%s %d" % kv for kv in sorted(why.items(), key=lambda x: -x[1])[:6]))
    msg.append(("GASへ送った %d品（仕入値が上限より安い順）・送る待ち %d品" % (sent, len(queue) - len(sent_ids))) if live else ("候補 %d品（ドライランなのでGASには送っていない）" % len(cands)))
    write_run(NAME, True, len(cands), len(stop))
    print("\n".join(msg))
    if live or now().hour in (9, 13, 18, 22) or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":   # ドライランの知らせは1日4回だけ
        notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
