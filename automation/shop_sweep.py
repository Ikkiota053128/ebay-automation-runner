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
                      "url": str(it.get("itemUrl", "")).split("?")[0], "photos": [str(u).split("?")[0] for u in imgs if u],
                      "dom": 0 if int(it.get("postageFlag") or 0) == 0 else 2000})   # 楽天 postageFlag 0＝送料込み。送料別は安全値2,000円
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
                      "url": str(h.get("url", "")), "photos": [img] if img else [],
                      "dom": 0 if int(((h.get("shipping") or {}).get("code")) or 0) == 2 else 2000})   # Yahoo! shipping.code 2＝送料無料
    return code, items


def rakuten_shop(shop, kw, page, maxp, key):
    """楽天：1店の中をメーカー名で（新着順）"""
    q = {"format": "json", "formatVersion": 2, "applicationId": key["id"], "keyword": kw, "shopCode": shop,
         "sort": "-updateTimestamp", "availability": 1, "hits": 30, "page": page}
    if maxp:
        q["maxPrice"] = maxp
    if key.get("relay"):
        code, j = get_json(key["relay"].rstrip("/") + "/search?" + urllib.parse.urlencode(q),
                           {"accessKey": key["access"], "X-Relay-Token": key.get("relay_token", "")})
    else:
        code, j = get_json(RK + "?" + urllib.parse.urlencode(q), {"accessKey": key["access"]})
    items = []
    for it in j.get("items", []) or j.get("Items", []):
        it = it.get("Item", it)
        imgs = [u.get("imageUrl", u) if isinstance(u, dict) else u for u in (it.get("mediumImageUrls") or [])]
        items.append({"id": "rk:" + str(it.get("itemCode", "")), "title": str(it.get("itemName", "")), "price": int(it.get("itemPrice") or 0),
                      "url": str(it.get("itemUrl", "")).split("?")[0], "photos": [str(u).split("?")[0] for u in imgs if u],
                      "dom": 0 if int(it.get("postageFlag") or 0) == 0 else 2000})
    return code, items


def yahoo_shop(seller, kw, start, maxp, appid):
    """Yahoo!ショッピング：1店の中をメーカー名で（新着順）"""
    q = {"appid": appid, "query": kw, "seller_id": seller, "results": 50, "start": start, "in_stock": "true", "sort": "-update_time"}
    if maxp:
        q["price_to"] = maxp
    code, j = get_json(YS + "?" + urllib.parse.urlencode(q))
    items = []
    for h in j.get("hits", []):
        img = (h.get("exImage") or {}).get("url") or (h.get("image") or {}).get("medium") or ""
        items.append({"id": "ys:" + str(h.get("code", "")), "title": str(h.get("name", "")), "price": int(h.get("price") or 0),
                      "url": str(h.get("url", "")), "photos": [img] if img else [],
                      "dom": 0 if int(((h.get("shipping") or {}).get("code")) or 0) == 2 else 2000})
    return code, items


GENRE = {"カメラ": r"nikon|canon|sony|olympus|pentax|fuji|panasonic|ricoh|leica|minolta|konica|mamiya|contax|tamron|sigma|tokina|voigtlander|hasselblad|zeiss|casio",
         "エフェクター": r"boss|roland|mxr|maxon|ibanez|korg|yamaha|electro|ehx|tc electronic|zoom|line 6|digitech|dunlop|strymon|walrus|xotic|fulltone|keeley|one control|free the tone|vemuram|providence|akai|behringer",
         "リール": r"shimano|daiwa|abu|penn|megabass|evergreen|olympic|tailwalk",
         "オーディオ": r"sony|technics|pioneer|marantz|denon|yamaha|accuphase|luxman|onkyo|kenwood|sansui|audio-technica|nakamichi|teac|tascam|akai|victor|aiwa"}


def store_makers(models, name, n):
    """店の名前の（ ）にある種類に合うメーカーを、型番リストの数の多い順に n 社（教科書：決まった店の中を深く探す）"""
    gs = [v for k, v in GENRE.items() if k in name]
    cnt, cap = {}, {}
    for m in models:
        mk = str(m.get("maker", "")).strip()
        if len(mk) < 2 or (gs and not any(re.search(g, mk, re.I) for g in gs)):
            continue
        cnt[mk] = cnt.get(mk, 0) + 1 + (3 if (m.get("cap") or 0) >= 15000 else 0)
        cap[mk] = max(cap.get(mk, 0), int(m.get("cap") or 0))
    return [(mk, cap[mk]) for mk in sorted(cnt, key=lambda k: -cnt[k])[:n]]


def store_sweep_part(models, tt, rk, ya, seen, why, t_end):
    """登録した店の中を、メーカー名で探す（7割）。1店につき「1店のメーカーの数」社まで、1メーカー「1メーカーで見る品の数」品まで。
    沖縄への送料が分かる店から先に。楽天は店の中の検索に先に回数を使う"""
    from flea_sweep import match
    stores = [s for s in load_json(os.path.join(ROOT, "data", "判定", "登録した店.json"), {}).get("店", [])]
    bad = set(load_json(os.path.join(ROOT, "data", "判定", "使わない店.json"), {}).get("店", []))
    stores = [s for s in stores if "%s:%s" % (s["src"], s["id"]) not in bad and (s["src"] == "R" and rk["id"] or s["src"] == "Y" and ya)]
    stores.sort(key=lambda s: (s.get("dom") is None, s["src"] != "R"))
    nmk, nitem = int(tt.get("1店のメーカーの数", 8)), int(tt.get("1メーカーで見る品の数", 300))
    tasks = [(s, mk, cap) for s in stores for mk, cap in store_makers(models, s["名前"], nmk)]
    cur_p = os.path.join(ROOT, "data", "店の地引網", "店の順番.json")
    cur = load_json(cur_p, {"i": 0})
    i0 = cur["i"] % max(len(tasks), 1)
    tasks = tasks[i0:] + tasks[:i0]
    st = {"店": len(stores), "メーカーの作業": len(tasks), "した作業": 0, "API": 0, "見た": 0, "残った": 0}
    cands, last = [], {"R": 0.0, "Y": 0.0}
    gap = {"R": float(tt.get("楽天の間隔_秒", 1.5)), "Y": float(tt.get("Yahooの間隔_秒", 3.0))}
    stop = set()
    for s, mk, cap in tasks:
        if time.time() > t_end:
            break
        if s["src"] in stop:
            continue
        st["した作業"] += 1
        per = 30 if s["src"] == "R" else 50
        for pg in range(1, nitem // per + 1):
            w = last[s["src"]] + gap[s["src"]] - time.time()
            if w > 0:
                time.sleep(w)
            if s["src"] == "R":
                code, items = rakuten_shop(s["id"], mk, pg, cap, rk)
            else:
                code, items = yahoo_shop(s["id"], mk, 1 + (pg - 1) * 50, cap, ya)
            last[s["src"]] = time.time()
            st["API"] += 1
            if code in (429, 403, 503) or code is None:
                stop.add(s["src"])
                why["店の中の検索：%s を止めた（HTTP %s）" % ("楽天" if s["src"] == "R" else "Yahoo!", code)] = 1
                break
            for it in items:
                if it["id"] in seen:
                    continue
                seen[it["id"]] = now().timestamp()
                st["見た"] += 1
                m = match(it["title"], models)
                if not m:
                    why["店の中：型番リストに無い"] = why.get("店の中：型番リストに無い", 0) + 1
                    continue
                r = keep(it, m)
                if r:
                    why[r] = why.get(r, 0) + 1
                    continue
                if s.get("dom") is not None and it.get("dom"):
                    it["dom"] = s["dom"]
                st["残った"] += 1
                it.update({"型番": m["model"], "メーカー": m["maker"], "src": "楽天" if s["src"] == "R" else "Yahoo!", "cap": m["cap"], "店": s["名前"]})
                cands.append(it)
            if len(items) < per:
                break
        cur["i"] = cur["i"] + 1
    save_json(cur_p, cur)
    return cands, st


_BAD_SHOPS = None


def bad_shop(url):
    """楽天・Yahoo!の店の規約で使わない店（mall_terms.py が data/判定/使わない店.json に書く）"""
    global _BAD_SHOPS
    if _BAD_SHOPS is None:
        from common import ROOT as _R, load_json as _lj
        _BAD_SHOPS = set(_lj(os.path.join(_R, "data", "判定", "使わない店.json"), {}).get("店", []))
    from mall_terms import shop_of
    return shop_of(url) in _BAD_SHOPS


def keep(it, m):
    if bad_shop(it.get("url")):
        return "店の規約で使わない店（転売の購入を断る・転載の禁止）"
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


def shadow_judge(cands, n):
    """影の運転：GitHub の判定（judge.py）を、出品したことのある型番の候補 n 品にかけて記録だけする（GAS の答えと比べるため）"""
    if n <= 0 or not cands:
        return ""
    try:
        from common import Ebay, settings, read_ledger, browse_stopped
        import judge
        profs, st = judge.materials()
        todo = [c for c in cands if judge.profile_for(c["型番"], profs)][:n]
        if not todo or browse_stopped():
            return "判定の影：対象 0品" if not todo else "判定の影：検索の回数上限で止めている"
        eb, cfg = Ebay(), settings()
        if not eb.ready():
            return ""
        me = cfg.get("店", {}).get("セラー名", "").lower()
        my_ids = {r.get("eBayの出品ID") for r in read_ledger()}
        qs = {"floorYen": 1500, "floorRate": 0.05, "tol": 0.30, "high": 100, "overMax": 1.4}
        qs.update(cfg.get("判定", {}).get("値付け", {}))
        fx = float(cfg.get("判定", {}).get("為替", 152))
        out = []
        for c in todo:
            try:
                out.append(judge.judge(eb, c, profs, st, qs, me, my_ids, fx))
            except Exception as e:   # 1品の失敗で全体を止めない
                out.append({"url": c["url"], "型番": c["型番"], "結論": "エラー", "理由": str(e)[:300]})
        save_json(os.path.join(ROOT, "data", "判定", "影", now().strftime("%Y%m%d_%H%M%S") + ".json"), out)
        go = sum(1 for x in out if x["結論"] == "GO")
        return "判定の影：%d品を判定 → GO %d・見送り %d（記録だけ。GASの答えと比べる）" % (len(out), go, len(out) - go)
    except Exception as e:
        return "判定の影でエラー：" + str(e)[:200]


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
    # 1) 登録した店の中をメーカー名で（7割の時間）
    store_st = {}
    try:
        t_store = time.time() + (t_end - time.time()) * float(tt.get("店の中の検索の割合", 0.7))
        sc, store_st = store_sweep_part(models, tt, rk, ya, seen, why, t_store)
        cands += sc
    except Exception as e:
        why["店の中の検索でエラー：%s" % str(e)[:80]] = 1
    # 2) 楽天・Yahoo!の全体を型番で（3割：新しい店を見つける役目）
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
    # GitHub の判定（判定と出品）が GO・見送りにした品は GAS に送らない（「GASへ」にした品だけ今までどおり送る）
    gdone = load_json(os.path.join(ROOT, "data", "判定", "判定済み.json"), {})
    for k in [k for k in back if k in gdone]:
        back.pop(k)
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
    shadow = shadow_judge(cands if live else queue, int(tt.get("判定の影_件", 10)))
    sent_ids = {c["id"] for c in cands} if live else set()
    save_json(back_p, [c for c in queue if c["id"] not in sent_ids])
    rec = {"時刻": jst(), "本番": live, "送る待ち": len(queue) - len(sent_ids), "見た型番": done, "型番の数": len(models), "数": stat, "外した理由": why,
           "候補": [{k: c[k] for k in ("src", "型番", "price", "title", "url")} for c in cands], "送った": sent}
    save_json(os.path.join(ROOT, "data", "店の地引網", now().strftime("%Y%m%d_%H%M%S") + ".json"), rec)
    msg = ["【店の地引網】%s %s：型番 %d／%d個を見た" % (jst(), "本番" if live else "ドライラン", done, len(models))]
    for s, v in stat.items():
        msg.append("%s：API %d回・新しく見た品 %d・候補 %d" % (s, v["API"], v["見た"], v["残った"]))
    if store_st:
        msg.append("登録した店の中（メーカー名）：%d店・作業 %d／%d・API %d回・見た品 %d・候補 %d" % (store_st["店"], store_st["した作業"], store_st["メーカーの作業"], store_st["API"], store_st["見た"], store_st["残った"]))
    if why:
        msg.append("外した理由：" + "・".join("%s %d" % kv for kv in sorted(why.items(), key=lambda x: -x[1])[:6]))
    msg.append(("GASへ送った %d品（仕入値が上限より安い順）・送る待ち %d品" % (sent, len(queue) - len(sent_ids))) if live else ("候補 %d品（ドライランなのでGASには送っていない）" % len(cands)))
    if shadow:
        msg.append(shadow)
    write_run(NAME, True, len(cands), len(stop))
    print("\n".join(msg))
    if live or now().hour in (9, 13, 18, 22) or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":   # ドライランの知らせは1日4回だけ
        notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
