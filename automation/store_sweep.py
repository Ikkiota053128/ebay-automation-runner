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
    {"name": "カメラの八百富", "host": "www.yaotomi.co.jp", "search": "https://www.yaotomi.co.jp/search?q={q}&type=product", "link": r"/products/[A-Za-z0-9\-]+", "makers": CAM},
    # フジヤカメラは GitHub からの読み込みを受け付けない（202・中身なし）ので外す（11/18 下調べ）
    {"name": "トレファク", "host": "ec.treasure-f.com", "search": "https://ec.treasure-f.com/search?word={q}", "link": r"/item/\d+", "makers": CAM + "|" + MUS + r"|seiko|citizen|shimano|daiwa"},
]


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
