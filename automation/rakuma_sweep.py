"""楽天ラクマの地引網（GitHub の中のブラウザ・Playwright）。
11/24 09:01 オーナー「楽天ラクマ 規約承知済み！仕入れ先入れて！」。11/24 09:04 の試しで、GitHub から検索・商品ページ・写真が読めた。
- 型番リスト（data/型番リスト_スナップショット.csv）を順番に、1回 時刻表 ラクマの地引網 → 1回の型番_件 ずつ「メーカー 型番」で検索（販売中だけ）。
- 一覧の品を、店の地引網と同じ決まり（shop_sweep.keep：型番が商品名にある・付属品/ジャンク/レンタルでない・仕入れ上限以下）で選ぶ。
- 選んだ品は商品ページを開いて写真（この品の写真だけ）を集め、data/ラクマ/送る待ち.json に入れる → 判定と出品（judge_list）が判定して出品（SKU の頭 GRM）。
- ページを開く間は 品の間_秒（はじめ 20〜35秒）。ロボットの確認・アクセス制限が出たらその場でやめる。
- 在庫の見回りは mercari_watch（ラクマも見る）。"""
import json, os, random, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, load_json, save_json, read_ledger, timetable, notify
from flea_sweep import load_models
from shop_sweep import keep

tt = timetable("ラクマの地引網") or {}
if tt.get("実行") is False:
    print("止めている")
    sys.exit(0)
SP = os.path.join(ROOT, "data", "ラクマ", "状態.json")
QP = os.path.join(ROOT, "data", "ラクマ", "送る待ち.json")
st = load_json(SP, {"i": 0, "見た": {}})
models = load_models()
listed = {re.sub(r"[^A-Z0-9]", "", (r.get("タイトル") or "").split(" ")[1].upper()) for r in read_ledger()
          if r.get("状態") == "出品中" and len((r.get("タイトル") or "").split(" ")) > 1}
n = int(tt.get("1回の型番_件", 20))
gap = tt.get("品の間_秒", [20, 35])
pick_max = int(tt.get("1回に選ぶ上限_件", 15))
i0 = int(st.get("i", 0)) % max(1, len(models))
todo = [m for m in (models[i0:] + models[:i0]) if re.sub(r"[^A-Z0-9]", "", m["model"].upper()) not in listed][:n]
st["i"] = (i0 + n) % max(1, len(models))
out = {"時刻": jst(), "検索": 0, "一覧の品": 0, "選んだ": [], "止めた": ""}
q = {c["id"]: c for c in load_json(QP, [])}
now_t = time.time()
q = {k: v for k, v in q.items() if now_t - v.get("t", 0) < 3 * 86400}   # 3日で捨てる

from playwright.sync_api import sync_playwright


def wait():
    time.sleep(random.uniform(float(gap[0]), float(gap[1])))


def blocked(txt):
    return bool(re.search(r"ロボットではありません|captcha|アクセスが集中|アクセスを制限|しばらくしてから", txt, re.I))


picked = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    for k, m in enumerate(todo):
        if k:
            wait()
        kw = ("%s %s" % (m["maker"], m["model"])).strip()
        try:
            pg.goto("https://fril.jp/s?query=%s&transaction=selling" % urllib.parse.quote(kw), wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(5000)
            if blocked(pg.inner_text("body")[:5000]):
                out["止めた"] = "ロボットの確認・アクセス制限（検索）"
                break
            html = pg.content()
            cards = []
            for tag in re.findall(r'<a [^>]*class="link_search_image"[^>]*>', html):
                h = re.search(r'href="(https://item\.fril\.jp/[0-9a-f]+)"', tag)
                nm = re.search(r'data-rat-item_name="([^"]*)"', tag)
                pr = re.search(r'data-rat-price="(\d+)"', tag)
                if h and nm and pr:
                    cards.append({"href": h.group(1), "name": nm.group(1).replace("&amp;", "&"), "text": "¥" + pr.group(1)})
            tot = re.search(r'data-rat-cp-totalresults="(\d+)"', html)
            out.setdefault("件数", {})[kw] = int(tot.group(1)) if tot else -1
            if not out.get("見本"):
                out["見本"] = cards[:3]
        except Exception as e:
            continue
        out["検索"] += 1
        seen_href = set()
        for c in cards:
            href = c["href"].split("?")[0]
            if href in seen_href or href in st["見た"]:
                continue
            seen_href.add(href)
            txt = c.get("text") or ""
            if re.search(r"SOLD ?OUT", txt):
                continue
            pm = re.search(r"¥\s?([\d,]+)", txt)
            title = (c.get("name") or "").replace("\n", " ").strip() or re.sub(r"¥\s?[\d,]+", "", txt).replace("\n", " ").strip()
            if not pm or not title:
                continue
            out["一覧の品"] += 1
            it = {"title": title[:200], "price": int(pm.group(1).replace(",", "")), "url": href}
            if keep(it, m) or it["price"] < int(tt.get("仕入れの下限_円", 3000)):
                continue
            if sum(1 for _, mm in picked if mm["model"] == m["model"]) >= int(tt.get("1型番に選ぶ上限_件", 2)):
                continue   # 同じ型番ばかり選ばない（11/24 15:05）
            picked.append((it, m))
        if len(picked) >= pick_max:
            break
    # 選んだ品は商品ページを開いて、この品の写真と販売中かを確かめる
    for it, m in picked[:pick_max]:
        if out["止めた"]:
            break
        wait()
        try:
            pg.goto(it["url"], wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(5000)
            t = pg.inner_text("body")[:40000]
            html = pg.content()
        except Exception:
            continue
        if blocked(t[:5000]):
            out["止めた"] = "ロボットの確認・アクセス制限（商品ページ）"
            break
        st["見た"][it["url"]] = jst()
        if re.search(r"SOLD ?OUT", t[:4000]) or "購入に進む" not in t:
            continue
        # 11/24 09:54 オーナー「楽天ラクマは即買い可能と審査の物がある？それは注意して出品して！」：
        # 購入申請（出品者の承認が要る）の品は出さない。「すぐに購入可」の品だけ
        if "購入申請" in t:
            out.setdefault("購入申請で外した", []).append(it["url"])
            continue
        og = (re.findall(r'property="og:image"[^>]*content="([^"]+)"', html) or re.findall(r'content="([^"]+)"[^>]*property="og:image"', html) or [""])[0]
        mid = re.search(r"img\.fril\.jp/img/(\d+)/", og)
        photos = []
        for u in re.findall(r"https://img\.fril\.jp/img/\d+/l/[^\"'\s?]+", html):
            if (not mid or "/img/%s/" % mid.group(1) in u) and u not in photos:
                photos.append(u)
        if len(photos) < 3:
            continue
        name = (pg.title() or "").split("の通販")[0]
        cid = "rm:" + it["url"].rsplit("/", 1)[-1]
        q[cid] = {"id": cid, "title": name or it["title"], "price": it["price"], "url": it["url"], "photos": photos[:24],
                  "dom": 0 if "送料込" in t else int(tt.get("送料別の国内送料_円", 1000)), "型番": m["model"], "メーカー": m["maker"],
                  "src": "ラクマ", "cap": int(m.get("cap") or 0), "ratio": 1.0, "t": time.time()}
        out["選んだ"].append({"型番": m["model"], "値段": it["price"], "URL": it["url"]})
    b.close()
st["見た"] = dict(list(st["見た"].items())[-5000:])
save_json(SP, st)
save_json(QP, sorted(q.values(), key=lambda c: -c["t"])[: int(tt.get("送る待ちの上限_件", 600))])
save_json(os.path.join(ROOT, "data", "ラクマ", "最後.json"), out)
msg = "【ラクマの地引網】%s 検索 %d回・一覧 %d品・送る待ちに %d品（待ち合計 %d）" % (jst(), out["検索"], out["一覧の品"], len(out["選んだ"]), len(q))
if out["止めた"]:
    msg += "\n⛔ 止めた：" + out["止めた"]
    notify(msg)
print(msg)
