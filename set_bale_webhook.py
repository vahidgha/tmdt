"""
اجرا کنید تا webhook ربات بله تنظیم شود:
  python set_bale_webhook.py https://your-domain.com

آدرس webhook خواهد بود:
  https://your-domain.com/api/bale/webhook
"""
import sys, os, requests

TOKEN = os.environ.get('BALE_TOKEN', '')
if not TOKEN:
    print('❌ BALE_TOKEN تنظیم نشده. ابتدا در فایل .env یا environment variable قرار دهید.')
    sys.exit(1)

if len(sys.argv) < 2:
    print('استفاده: python set_bale_webhook.py https://your-domain.com')
    sys.exit(1)

base_url = sys.argv[1].rstrip('/')
webhook_url = f'{base_url}/api/bale/webhook'

r = requests.post(
    f'https://tapi.bale.ai/bot{TOKEN}/setWebhook',
    json={'url': webhook_url},
    timeout=10
)

print('پاسخ:', r.status_code, r.text)
if r.ok and r.json().get('ok'):
    print(f'✅ Webhook با موفقیت تنظیم شد:\n   {webhook_url}')
else:
    print('❌ خطا در تنظیم webhook')
