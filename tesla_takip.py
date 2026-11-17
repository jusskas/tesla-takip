#!/usr/bin/env python3
"""
Tesla Türkiye ikinci el Model Y takipçisi.
Tesla'nın envanter API'sini sorgular, yeni ilan çıkınca Telegram'dan haber verir.
Cron ile her 5 dakikada bir çalıştırılır.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "durum.json"
ENV_FILE = BASE / ".env"

PAGE_URL = "https://www.tesla.com/tr_TR/inventory/used/my?arrangeby=plh&zip=06420&range=0"
API_URL = "https://www.tesla.com/coinorder/api/v4/inventory-results"
QUERY = {
    "query": {
        "model": "my",
        "condition": "used",
        "options": {},
        "arrangeby": "Price",
        "order": "asc",
        "market": "TR",
        "language": "tr",
        "super_region": "north america",
        "zip": "06420",
        "range": 0,
    },
    "offset": 0,
    "count": 50,
    "outsideOffset": 0,
    "outsideSearch": False,
}

HATA_BILDIRIM_ARALIGI = 3 * 3600   # aynı hata için en fazla 3 saatte bir mesaj
GUNLUK_RAPOR_SAATI = 10             # her gün bu saatte "çalışıyorum" mesajı


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def http_get(url, headers=None, timeout=30):
    """Önce curl_cffi (gerçek Chrome gibi görünür), yoksa requests."""
    try:
        from curl_cffi import requests as creq
        return creq.get(url, headers=headers, timeout=timeout, impersonate="chrome")
    except ImportError:
        import requests
        return requests.get(url, headers=headers, timeout=timeout)


def telegram(text):
    import requests
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        # Chat ID verilmemişse bota en son yazan kişiyi kullan
        upd = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
        ids = [u["message"]["chat"]["id"] for u in upd.get("result", []) if "message" in u]
        if not ids:
            raise RuntimeError("Chat ID bulunamadı: Telegram'da bota bir mesaj yazın")
        chat_id = str(ids[-1])
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "false"},
        timeout=20,
    )
    r.raise_for_status()


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"gorulen": {}, "son_hata": 0, "hata_sayisi": 0, "son_rapor_gunu": ""}


def save_state(s):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1))


def fetch_cars():
    url = API_URL + "?query=" + urllib.parse.quote(json.dumps(QUERY, separators=(",", ":")))
    headers = {
        "Accept": "application/json",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Referer": PAGE_URL,
    }
    r = http_get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Tesla HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception:
        raise RuntimeError("Tesla JSON yerine başka bir şey döndü (engellenmiş olabilir)")
    res = data.get("results", [])
    if isinstance(res, dict):
        cars = (res.get("exact") or []) + (res.get("approximate") or [])
    else:
        cars = res or []
    total = int(data.get("total_matches_found") or len(cars))
    return total, cars


def fmt_price(v):
    try:
        return f"{int(v):,}".replace(",", ".") + " TL"
    except Exception:
        return "?"


def car_text(c):
    vin = c.get("VIN", "?")
    trim = c.get("TrimName") or "Model Y"
    yil = c.get("Year", "")
    km = c.get("Odometer")
    renk = ", ".join(c.get("PAINT") or [])
    sehir = c.get("City") or ""
    fiyat = fmt_price(c.get("InventoryPrice") or c.get("Price"))
    link = f"https://www.tesla.com/tr_TR/my/order/{vin}"
    parts = [f"🚗 <b>{trim}</b> {yil}", f"💰 {fiyat}"]
    if km is not None:
        parts.append(f"📏 {int(km):,} km".replace(",", "."))
    if renk:
        parts.append(f"🎨 {renk}")
    if sehir:
        parts.append(f"📍 {sehir}")
    parts.append(f'<a href="{link}">İlana git</a>')
    return "\n".join(parts)


def main():
    load_env()
    st = load_state()
    now = time.time()

    try:
        total, cars = fetch_cars()
    except Exception as e:
        st["hata_sayisi"] = st.get("hata_sayisi", 0) + 1
        # 3 ardışık hatadan sonra haber ver (geçici aksaklıklarda rahatsız etmesin)
        if st["hata_sayisi"] >= 3 and now - st.get("son_hata", 0) > HATA_BILDIRIM_ARALIGI:
            try:
                telegram(f"⚠️ Tesla takip: kontrol yapılamıyor ({st['hata_sayisi']} kez üst üste).\nHata: {e}")
                st["son_hata"] = now
            except Exception:
                pass
        save_state(st)
        print(datetime.now().isoformat(timespec="seconds"), "HATA", e, file=sys.stderr)
        return 1

    if st.get("hata_sayisi", 0) >= 3 and st.get("son_hata"):
        telegram("✅ Tesla takip: kontrol tekrar çalışıyor.")
    st["hata_sayisi"] = 0

    gorulen = st.setdefault("gorulen", {})
    yeniler = [c for c in cars if c.get("VIN") and c["VIN"] not in gorulen]

    if yeniler:
        ilk_acilis = len(gorulen) == 0
        baslik = ("🚨🚨 <b>TESLA İKİNCİ EL MODEL Y SATIŞI AÇILDI!</b> 🚨🚨"
                  if ilk_acilis else f"🆕 <b>{len(yeniler)} yeni ikinci el Model Y</b>")
        msg = f"{baslik}\nToplam ilan: {total}\n\n"
        msg += "\n\n".join(car_text(c) for c in yeniler[:10])
        if len(yeniler) > 10:
            msg += f"\n\n… ve {len(yeniler) - 10} araç daha"
        msg += f'\n\n<a href="{PAGE_URL}">Tüm liste</a>'
        telegram(msg)
        for c in yeniler:
            gorulen[c["VIN"]] = int(now)

    # Günlük "hayattayım" raporu
    bugun = datetime.now().strftime("%Y-%m-%d")
    if datetime.now().hour >= GUNLUK_RAPOR_SAATI and st.get("son_rapor_gunu") != bugun:
        telegram(f"🟢 Tesla takip çalışıyor. Şu an ikinci el Model Y ilanı: {total}")
        st["son_rapor_gunu"] = bugun

    save_state(st)
    print(datetime.now().isoformat(timespec="seconds"), f"OK toplam={total} yeni={len(yeniler)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        load_env()
        total, _ = fetch_cars()
        telegram(f"✅ Tesla takip kuruldu ve çalışıyor.\nŞu an ikinci el Model Y ilanı: {total}\n"
                 "İlan çıktığı an buraya haber gelecek.")
        if not os.environ.get("TELEGRAM_CHAT_ID", "").strip():
            import requests
            tok = os.environ["TELEGRAM_TOKEN"]
            upd = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
            cid = [u["message"]["chat"]["id"] for u in upd.get("result", []) if "message" in u][-1]
            telegram(f"🔑 Chat ID'niz: <code>{cid}</code>\nBunu GitHub'da TELEGRAM_CHAT_ID olarak kaydedin.")
        print("Test mesajı gönderildi. Tesla toplam:", total)
    else:
        main()  # hata olsa da 0 ile cik (GitHub her seferinde e-posta atmasin)
