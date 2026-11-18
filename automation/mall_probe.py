"""中古の専門店が楽天・Yahoo!ショッピングに店を持っているか（読むだけ・公式API）：店のコードごとに「中古」の品の数を数える。
結果：data/店の下調べ/モールの専門店.json（11/18 22:56 オーナー「エフェクター、時計、カメラ…仕入先さがして」）"""
import json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from shop_sweep import get_json, RK, YS

CANDS = {
    "カメラ": [("フジヤカメラ", ["fujiya-camera", "fujiyacamera"]), ("マップカメラ", ["mapcamera"]), ("カメラのキタムラ", ["emedama", "kitamura-camera"]),
              ("カメラのナニワ", ["naniwa"]), ("三宝カメラ", ["sanpou", "sanpoucamera"]), ("チャンプカメラ", ["champcamera"]), ("レモン社", ["lemonsha"]),
              ("大貫カメラ", ["ohnuki", "camera-ohnuki"]), ("カメラのアルプス堂", ["alps-dou", "alpsdo"]), ("ホットミーティア", ["hotmeteor"]),
              ("カメラFanks", ["camera-fanksproshop11", "camera-fanksproshop22", "camera-fanksproshop"]), ("ファイブスターカメラ", ["five-star-camera", "fivestarreuse"])],
    "エフェクター": [("イシバシ楽器", ["ishibashi-shops"]), ("イケベ楽器", ["ikebe", "ikebe-gakki"]), ("チューヤ", ["chuya-online"]), ("クロサワ楽器", ["kurosawagakki", "kurosawa"]),
                 ("島村楽器", ["shimamura-used", "shimamura"]), ("ギタープラネット", ["guitarplanet"]), ("イケシブ", ["ikeshibu"]), ("ワンダーレックス", ["wonderrex", "wonderrex-ec"]),
                 ("ワットマン", ["wattmann"]), ("Qsic", ["qsic"]), ("スリフト", ["thrift-webshop"]), ("パプリカ", ["paprica-music"]), ("ミュージックプラント", ["musicplant"]),
                 ("ジングル", ["jingle-store"]), ("ムジカ&フェリーチェ", ["mujica-felice"]), ("サウンドハウス", ["soundhouse"])],
    "時計": [("ジャックロード", ["jackroad"]), ("なんぼや", ["nanboya", "nanboya-online"]), ("ブランドオフ", ["brandoff"]), ("コメ兵", ["komehyo-online", "komehyo"]),
            ("大黒屋", ["daikokuya78", "daikokuya"]), ("銀蔵", ["ginzo", "ginzo-net"]), ("ギャラリーレア", ["galleryrare"]), ("ブランディア", ["brandear"]),
            ("エコリング", ["ecoring"]), ("ブランドリバリュー", ["brandrevalue"]), ("ラクマ公式", ["rakuma"]), ("かんてい局", ["kanteikyoku"]), ("質屋かんてい局", ["kanteikyoku-shop"])],
}
rid, acc = os.environ.get("RAKUTEN_APP_ID", "").strip(), os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
relay, tok = os.environ.get("RAKUTEN_RELAY_URL", "").strip(), os.environ.get("RAKUTEN_RELAY_TOKEN", "").strip()
ya = os.environ.get("YAHOO_CLIENT_ID", "").strip()
out = {}
for g, lst in CANDS.items():
    for name, codes in lst:
        r = {}
        for code in codes:
            q = {"format": "json", "formatVersion": 2, "applicationId": rid, "keyword": "中古", "shopCode": code, "hits": 1}
            c, j = get_json(relay.rstrip("/") + "/search?" + urllib.parse.urlencode(q), {"accessKey": acc, "X-Relay-Token": tok}) if relay else (None, {})
            n = j.get("count") or j.get("hits") or 0
            if c == 200 and (j.get("items") or j.get("Items")):
                it = (j.get("items") or j.get("Items"))[0]; it = it.get("Item", it)
                r["R:" + code] = {"中古の品": n, "店の名前": it.get("shopName", "")}
            time.sleep(1.6)
            c2, j2 = get_json(YS + "?" + urllib.parse.urlencode({"appid": ya, "query": "中古", "seller_id": code, "results": 1}))
            if c2 == 200 and j2.get("hits"):
                r["Y:" + code] = {"中古の品": j2.get("totalResultsAvailable", 0), "店の名前": (j2["hits"][0].get("seller") or {}).get("name", "")}
            time.sleep(1.1)
        out.setdefault(g, {})[name] = r
        print(g, name, r)
save_json(os.path.join(ROOT, "data", "店の下調べ", "モールの専門店.json"), {"時刻": jst(), "店": out})
