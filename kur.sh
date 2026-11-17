#!/data/data/com.termux/files/usr/bin/bash
# Tesla ikinci el Model Y takip - Termux kurulumu
set -e
echo ">> Paketler kuruluyor (birkaç dakika sürebilir)..."
yes | pkg update >/dev/null 2>&1 || true
pkg install -y python curl >/dev/null
pip install -q requests

mkdir -p ~/tesla && cd ~/tesla
curl -sL -o tesla_takip.py https://raw.githubusercontent.com/jusskas/tesla-takip/main/tesla_takip.py

echo
echo ">> BotFather'ın verdiği bot token'ını yapıştırıp Enter'a basın:"
read -r TOKEN < /dev/tty
echo ">> Telegram'da @ilker_tesla_takip_bot'a 'merhaba' yazdığınızdan emin olun, chat ID aranıyor..."
CHAT_ID=$(python - "$TOKEN" <<'PY'
import sys, requests
r = requests.get(f"https://api.telegram.org/bot{sys.argv[1]}/getUpdates", timeout=20).json()
ids = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
print(ids[-1] if ids else "")
PY
)
if [ -z "$CHAT_ID" ]; then
  echo "!! Chat ID bulunamadı. Telegram'da bota 'merhaba' yazın ve komutu tekrar çalıştırın."
  exit 1
fi
printf 'TELEGRAM_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT_ID" > .env
chmod 600 .env

cat > calis.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/tesla
termux-wake-lock 2>/dev/null || true
while true; do
  python tesla_takip.py >> log.txt 2>&1
  tail -n 200 log.txt > log.tmp && mv log.tmp log.txt
  sleep 300
done
EOF
chmod +x calis.sh

# Termux her açıldığında takip çalışmıyorsa başlat
grep -q "tesla/calis.sh" ~/.bashrc 2>/dev/null || \
  echo 'pgrep -f tesla/calis.sh >/dev/null || (nohup ~/tesla/calis.sh >/dev/null 2>&1 &)' >> ~/.bashrc

echo ">> Test ediliyor..."
python tesla_takip.py test
pgrep -f tesla/calis.sh >/dev/null || (nohup ~/tesla/calis.sh >/dev/null 2>&1 &)
echo
echo "✅ Kurulum tamam. Telegram'a test mesajı gelmiş olmalı."
echo "   Takip her 5 dakikada bir arka planda çalışıyor. Termux'u kapatmayın (arka planda kalabilir)."
