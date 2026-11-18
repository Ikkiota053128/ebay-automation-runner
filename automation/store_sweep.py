"""店のサイトの地引網（GASに頼んでいたブラウザの地引網を GitHub で）：イシバシ楽器・カメラの八百富・フジヤカメラ・トレファクの検索ページを、型番リストの型番ごとに見る。

- robots.txt を守る（ハードオフの /search/ は禁止なので見ない。マップカメラ・キタムラ・セカンドストリートは GitHub からは断られる）。
- 店ごとに、その店で扱う種類のメーカーの型番だけ探す。1回に1店あたり「1回に見る型番の数」まで。アクセスは「間隔_秒」に1回。
- 検索結果の商品リンクのそばに型番がある品だけ、商品ページを開いて JSON-LD（商品名・値段・在庫・写真）を読む。
- 残す条件は店の地引網と同じ（仕入れ上限以下・在庫あり・レンタル／ジャンク／付属品でない・商品名に型番）。前に見た品は14日間見ない。
- 本番では「送る待ち」に入れ、GitHub の判定と出品（judge_list.py）が判定・出品する。GitHub が扱えない品だけ GAS へ。実行 false の間はドライラン。
"""
import json, os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flea_sweep import gas_get_models, gas_post, compile_models, now, notify
from shop_sweep import keep
from stock_watch import fetch
from common import ROOT, load_json, save_json, write_run, mark_started, jst, timetable

NAME = "店のサイトの地引網"
CAM = r"nikon|canon|sony|olympus|pentax|fujifilm|fuji|panasonic|ricoh|leica|minolta|konica|mamiya|contax|tamron|sigma|tokina|voigtlander|hasselblad|casio|zeiss"
MUS = r"boss|roland|mxr|maxon|ibanez|korg|yamaha|electro-harmonix|ehx|tc electronic|zoom|line 6|digitech|jim dunlop|dunlop|strymon|walrus|xotic|fulltone|keeley|one control|free the tone|vemuram|providence|akai|behringer|teenage engineering|audio-technica"
STORES = [
    {"name": "イシバシ楽器", "host": "store.ishibashi.co.jp", "search": "https://store.ishibashi.co.jp/search?q={q}&limit=72&sort=Score", "link": r"https://store\.ishibashi\.co\.jp/view/item/\d+", "makers": MUS},
    # 11/18 22:28 オーナー「はい」（新しい仕入れ先の開拓）：大貫カメラ・荻窪カメラのさくらや・オーディオユニオン
    {"name": "大貫カメラ", "host": "www.camera-ohnuki.com", "search": "https://www.camera-ohnuki.com/search?q={q}&type=product&options%5Bunavailable_products%5D=hide", "link": r"/products/[a-z0-9\-%]+", "makers": CAM},
    {"name": "荻窪カメラのさくらや", "host": "www.ogisaku.com", "search": "https://www.ogisaku.com/products/list.php?mode=search&name={q}", "link": r"(?:https://www\.ogisaku\.com)?/products/detail\.php\?product_id=\d+", "makers": CAM},
    {"name": "オーディオユニオン", "host": "www.audiounion.jp", "search": "https://www.audiounion.jp/shop/goods/search.aspx?search=x&keyword={q}", "link": r"/shop/g/g[0-9A-Za-z]+/?", "makers": r"sony|technics|pioneer|marantz|denon|yamaha|accuphase|luxman|onkyo|kenwood|sansui|audio-technica|nakamichi|teac|tascam|akai|victor|aiwa|stax|fostex|ortofon|shure|sennheiser|beyerdynamic|akg"},
    # カメラの八百富は外す（11/18 オーナー承認）：規約 第16条で、写真・文章の無断の複製・転載を禁止しているため
    # フジヤカメラは GitHub からの読み込みを受け付けない（202・中身なし）ので外す（11/18 下調べ）
    # トレファクは型番の検索ではなく、分類ごとの新着を見る（11/18 21:46 オーナー「ここの仕入れ先もこうやって」）→ treasure_cates
]


HO_CATES = [("デジタル・フィルムカメラ", "000100030002"), ("交換レンズ", "000100030001"), ("ギター・ベース周辺機器", "000100050010"),
            ("単品オーディオ", "000100010001"), ("腕時計", "000500010001")]


def hardoff_cates(models, seen, stat, why, gap):
    """ハードオフ（オフモール）：検索ページは robots.txt で禁止なので、カテゴリの新着ページ（/cate/<番号>/・許可されている）を見る（GAS の hoCateTick と同じ）"""
    out = []
    st = stat.setdefault("ハードオフ", {"検索": 0, "商品ページ": 0, "候補": 0, "読めない": 0})
    from flea_sweep import match
    for nm, cid in HO_CATES:
        code, html = fetch("https://netmall.hardoff.co.jp/cate/%s/" % cid)
        st["検索"] += 1
        time.sleep(gap)
        if code != 200:
            st["読めない"] += 1
            continue
        for part in html.split('<div class="itemcolmn_item')[1:]:
            m_id = re.search(r"netmall\.hardoff\.co\.jp/product/(\d+)/", part)
            if not m_id:
                continue
            g = lambda cls: re.sub(r"<[^>]+>|\s+", " ", (re.search(r'class="' + cls + r'"[^>]*>([\s\S]*?)</div>', part) or [None, ""])[1]).strip()
            name = " ".join(x for x in (g("item-brand-name"), g("item-name"), g("item-code")) if x)
            price = int((re.search(r"item-price-en[^>]*>\s*([\d,]+)", part) or [None, "0"])[1].replace(",", "") or 0)
            url = "https://netmall.hardoff.co.jp/product/%s/" % m_id.group(1)
            key = "ハードオフ:" + url
            if key in seen or re.search(r"sold|売り切れ|SOLD OUT", part, re.I):
                continue
            seen[key] = now().timestamp()
            m = match(name, models)
            if not m:
                continue
            it = {"id": key, "title": name, "price": price, "url": url, "photos": [u for u in re.findall(r'<img[^>]+src="(https://[^"]*imageflux\.jp[^"]+)"', part)][:1]}
            r = keep(it, m)
            if r:
                why[r] = why.get(r, 0) + 1
                continue
            it.update({"型番": m["model"], "メーカー": m["maker"], "src": "ハードオフ", "cap": m["cap"]})
            out.append(it)
            st["候補"] += 1
    return out


TF_CATES = [("エフェクター・アンプ", "category=1011&category2=1124"), ("リール", "category=1046&category2=1052&category3=1219"),
            ("モニタースピーカー・ヘッドホン", "category=1011&category2=1099&category3=1398"), ("オーディオインターフェース", "category=1011&category2=1099&category3=1396")]


def treasure_cates(models, seen, stat, why, gap):
    """トレファク：分類ごとの新着（新着順・1ページ90品）を見る（ハードオフのカテゴリの新着と同じ考え方）"""
    out = []
    st = stat.setdefault("トレファク", {"検索": 0, "商品ページ": 0, "候補": 0, "読めない": 0})
    from flea_sweep import match
    for nm, q in TF_CATES:
        code, html = fetch("https://ec.treasure-f.com/search?%s&order=newarrival&number=90&step=1" % q)
        st["検索"] += 1
        time.sleep(gap)
        if code != 200:
            st["読めない"] += 1
            continue
        for part in html.split('<li class="pj-search_item">')[1:]:
            m_id = re.search(r'href="/item/(\d+)"', part)
            if not m_id:
                continue
            title = " ".join(re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in re.findall(r'<p class="cm-typo_body_a cm-itemlist_text">([\s\S]*?)</p>', part))
            price = int((re.search(r"cm-itemlist_price[^>]*>\s*[￥¥]\s*([\d,]+)", part) or [None, "0"])[1].replace(",", "") or 0)
            url = "https://ec.treasure-f.com/item/%s" % m_id.group(1)
            key = "トレファク:" + url
            if key in seen or re.search(r"SOLD|売り切れ", part, re.I):
                continue
            seen[key] = now().timestamp()
            m = match(title, models)
            if not m:
                continue
            img = re.findall(r'<img src="(/images/[^"]+)"', part)
            it = {"id": key, "title": title, "price": price, "url": url, "photos": ["https://ec.treasure-f.com" + u for u in img][:1]}
            r = keep(it, m)
            if r:
                why[r] = why.get(r, 0) + 1
                continue
            it.update({"型番": m["model"], "メーカー": m["maker"], "src": "トレファク", "cap": m["cap"]})
            out.append(it)
            st["候補"] += 1
    return out


def ld_product(html):
    """JSON-LD の Product から（名前・値段・在庫・写真）"""
    for b in re.findall(r"<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>", html, re.I):
        try:
            j = json.loads(b.strip())
        except Exception:
            continue
        for o in (j if isinstance(j, list) else j.get("@graph", [j]) if isinstance(j, dict) else []):
            if not isinstance(o, dict) or "Product" not in str(o.get("@type", "")):
                continue
            off = o.get("offers") or {}
            off = off[0] if isinstance(off, list) and off else off
            img = o.get("image") or []
            img = [img] if isinstance(img, str) else [i.get("url", "") if isinstance(i, dict) else str(i) for i in img]
            try:
                price = int(float(str(off.get("price") or off.get("lowPrice") or 0).replace(",", "")))
            except Exception:
                price = 0
            return {"title": str(o.get("name", "")), "price": price, "avail": str(off.get("availability", "")), "photos": [u for u in img if u.startswith("http")][:12]}
    # JSON-LD が無い店（EC-CUBE など）：og:title／title と、最初の「◯円」、og:image で読む
    t = (re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html) or re.search(r"<title>([\s\S]*?)</title>", html) or [None, ""])[1]
    pm = re.search(r"(?:販売価格|価格|税込)[^0-9]{0,40}([\d,]{3,9})\s*円", html) or re.search(r"([\d,]{3,9})\s*円", html)
    if t and pm:
        imgs = re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        sold = re.search(r"SOLD\s?OUT|売り切れ|品切れ|在庫なし", html, re.I)
        return {"title": re.sub(r"\s+", " ", t).strip(), "price": int(pm.group(1).replace(",", "")), "avail": "OutOfStock" if sold else "",
                "photos": [u for u in imgs if u.startswith("http")][:12]}
    return None


def main():
    tt = timetable(NAME)
    live = bool(tt.get("実行"))
    mark_started(NAME)
    d = gas_get_models()
    if not d:
        write_run(NAME, False, 0, 1)
        return 1
    models = [m for m in compile_models(d["models"]) if not m["listed"]]
    per = int(tt.get("1回に見る型番の数", 30))
    gap = float(tt.get("間隔_秒", 3))
    seen_p = os.path.join(ROOT, "data", "店のサイトの地引網", "見た品.json")
    seen = {k: v for k, v in load_json(seen_p, {}).items() if v >= now().timestamp() - 14 * 86400}
    cur_p = os.path.join(ROOT, "data", "店のサイトの地引網", "順番.json")
    cur = load_json(cur_p, {})
    t_end = time.time() + 60 * float(tt.get("時間の上限_分", 25)) - 60
    cands, stat, why = [], {}, {}
    for s in STORES:
        mine = [m for m in models if re.search(s["makers"], m["maker"] + " " + m["model"], re.I)]
        if not mine:
            continue
        i0 = cur.get(s["name"], 0) % len(mine)
        todo = (mine[i0:] + mine[:i0])[:per]
        st = stat.setdefault(s["name"], {"検索": 0, "商品ページ": 0, "候補": 0, "読めない": 0})
        for m in todo:
            if time.time() > t_end:
                break
            cur[s["name"]] = cur.get(s["name"], 0) + 1
            q = urllib.parse.quote((m["maker"] + " " + m["model"]).strip() if s["name"] == "トレファク" else m["model"])
            code, html = fetch(s["search"].format(q=q))
            st["検索"] += 1
            time.sleep(gap)
            if code != 200:
                st["読めない"] += 1
                if code in (403, 429):
                    why["%s HTTP %s（この店は今回やめた）" % (s["name"], code)] = 1
                    break
                continue
            links = []
            for mm in re.finditer(s["link"], html):
                u = mm.group(0)
                near = re.sub(r"<[^>]+>", " ", html[max(0, mm.start() - 800): mm.end() + 3000])
                if m["rx"].search(near.upper().replace("‐", "-")) and u not in links:
                    links.append(u)
            for u in links[:4]:
                full = u if u.startswith("http") else "https://" + s["host"] + u
                key = s["name"] + ":" + full.split("?")[0]
                if key in seen:
                    continue
                seen[key] = now().timestamp()
                c2, h2 = fetch(full.split("?")[0])
                st["商品ページ"] += 1
                time.sleep(gap)
                p = ld_product(h2) if c2 == 200 else None
                if not p or not p["price"]:
                    why["商品ページの値段が読めない"] = why.get("商品ページの値段が読めない", 0) + 1
                    continue
                if p["avail"] and not re.search(r"InStock|LimitedAvailability", p["avail"], re.I):
                    why["売り切れ"] = why.get("売り切れ", 0) + 1
                    continue
                it = {"id": key, "title": p["title"], "price": p["price"], "url": full.split("?")[0], "photos": p["photos"]}
                r = keep(it, m)
                if r:
                    why[r] = why.get(r, 0) + 1
                    continue
                it.update({"型番": m["model"], "メーカー": m["maker"], "src": s["name"], "cap": m["cap"]})
                cands.append(it)
                st["候補"] += 1
    try:
        cands += treasure_cates(models, seen, stat, why, gap)
    except Exception as e:
        why["トレファクを読めなかった：%s" % type(e).__name__] = 1
    try:
        cands += hardoff_cates(models, seen, stat, why, gap)
    except Exception as e:
        why["ハードオフを読めなかった：%s" % type(e).__name__] = 1
    save_json(seen_p, seen)
    save_json(cur_p, cur)
    # 本番：候補を「送る待ち」に入れる → GitHub の判定と出品（judge_list.py）が判定して出品する。GitHub が扱えない品だけ、判定と出品が GAS へ送る
    sent = 0
    if live and cands:
        back_p = os.path.join(ROOT, "data", "店のサイトの地引網", "送る待ち.json")
        back = {c["id"]: c for c in load_json(back_p, []) if c.get("t", 0) >= now().timestamp() - 3 * 86400}
        for c in cands:
            c["t"] = now().timestamp()
            c["ratio"] = round(c["price"] / c["cap"], 3) if c.get("cap") else 1.0
            back.setdefault(c["id"], c)
        save_json(back_p, list(back.values()))
        sent = len(cands)
    save_json(os.path.join(ROOT, "data", "店のサイトの地引網", now().strftime("%Y%m%d_%H%M%S") + ".json"),
              {"時刻": jst(), "本番": live, "数": stat, "外した理由": why, "候補": [{k: c[k] for k in ("src", "型番", "price", "title", "url")} for c in cands], "送った": sent})
    msg = ["【店のサイトの地引網】%s %s" % (jst(), "本番" if live else "ドライラン")]
    msg += ["%s：検索 %d・商品ページ %d・候補 %d・読めない %d" % (k, v["検索"], v["商品ページ"], v["候補"], v["読めない"]) for k, v in stat.items()]
    if why:
        msg.append("外した理由：" + "・".join("%s %d" % kv for kv in sorted(why.items(), key=lambda x: -x[1])[:6]))
    msg.append(("GitHubの判定と出品へ渡した %d品" % sent) if live else ("候補 %d品（ドライランなのでGASには送っていない）" % len(cands)))
    print("\n".join(msg))
    notify("\n".join(msg))
    write_run(NAME, True, len(cands), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
