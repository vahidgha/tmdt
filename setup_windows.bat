@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo.
echo ══════════════════════════════════════════════════════
echo   هیئت امنای مسکن دادگستری زنجان — راه‌اندازی ویندوز
echo ══════════════════════════════════════════════════════
echo.

:: ─── 1. بررسی Python ───────────────────────────────────
echo [1/7] بررسی Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  خطا: Python پیدا نشد!
    echo  لطفاً Python 3.9 یا بالاتر از python.org دانلود و نصب کنید.
    echo  https://www.python.org/downloads/
    echo  دقت کنید گزینه "Add Python to PATH" را تیک بزنید.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %PYVER% پیدا شد

:: ─── 2. Virtual Environment ────────────────────────────
echo.
echo [2/7] Virtual Environment...
if exist venv\ (
    echo     venv از قبل موجود است
) else (
    echo     در حال ساخت venv...
    python -m venv venv
    if errorlevel 1 (
        echo  خطا در ساخت venv
        pause
        exit /b 1
    )
    echo     venv ساخته شد
)

:: فعال‌سازی venv
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  خطا در فعال‌سازی venv
    pause
    exit /b 1
)
echo     venv فعال شد

:: ─── 3. نصب وابستگی‌ها ─────────────────────────────────
echo.
echo [3/7] نصب وابستگی‌ها...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo  خطا در نصب وابستگی‌ها
    pause
    exit /b 1
)
python -m pip install --quiet pytest
echo     همه وابستگی‌ها نصب شدند

:: ─── 4. ساخت فولدرها ───────────────────────────────────
echo.
echo [4/7] ساختار فولدرها...
if not exist static\uploads\projects  mkdir static\uploads\projects
if not exist static\uploads\members   mkdir static\uploads\members
if not exist static\uploads\receipts  mkdir static\uploads\receipts
if not exist static\uploads\slides    mkdir static\uploads\slides
if not exist static\uploads\announcements mkdir static\uploads\announcements
if not exist static\uploads\requests  mkdir static\uploads\requests
if not exist static\icons             mkdir static\icons
if not exist static\img               mkdir static\img
echo     فولدرها ساخته شدند

:: ساخت آیکون‌های PWA
if not exist static\icons\icon-192.png (
    echo     در حال ساخت آیکون‌های PWA...
    python -c "from PIL import Image,ImageDraw;import os;os.makedirs('static/icons',exist_ok=True);[([img:=Image.new('RGB',(s,s),'#0E1B32'),draw:=ImageDraw.Draw(img),draw.ellipse([s*.08,s*.08,s*.92,s*.92],fill='#1A2E50'),draw.polygon([(s*.2,s*.52),(s*.5,s*.22),(s*.8,s*.52)],fill='#C8A456'),draw.rectangle([s*.28,s*.52,s*.72,s*.76],fill='#C8A456'),img.save(p,'PNG')]) for s,p in [(192,'static/icons/icon-192.png'),(512,'static/icons/icon-512.png'),(180,'static/icons/apple-touch-icon.png')]]" 2>nul
    echo     آیکون‌ها ساخته شدند
)

:: عکس رهبران (placeholder)
if not exist static\img\leader1.jpg (
    python -c "from PIL import Image,ImageDraw;[([img:=Image.new('RGB',(100,100),'#0E1B32'),draw:=ImageDraw.Draw(img),draw.ellipse([5,5,95,95],fill='#1A2E50'),img.save(p)]) for p in ['static/img/leader1.jpg','static/img/leader2.jpg']]" 2>nul
)

:: ─── 5. فایل .env ──────────────────────────────────────
echo.
echo [5/7] تنظیمات محیطی...
if not exist .env (
    (
        echo SECRET_KEY=local-dev-secret-key-change-in-production
        echo DATABASE_URL=sqlite:///noyan.db
        echo FLASK_ENV=development
        echo FLASK_DEBUG=1
    ) > .env
    echo     فایل .env ساخته شد
) else (
    echo     فایل .env از قبل موجود است
)

:: ─── 6. راه‌اندازی دیتابیس ────────────────────────────
echo.
echo [6/7] راه‌اندازی دیتابیس...
python -c "from app import create_app; app = create_app(); print('    جداول ساخته شدند')"
if errorlevel 1 (
    echo  خطا در راه‌اندازی دیتابیس
    pause
    exit /b 1
)

:: ─── 7. اجرای تست‌ها ───────────────────────────────────
echo.
echo [7/7] اجرای تست‌ها...
python -m pytest tests\test_full.py -q --tb=short 2>&1
if errorlevel 1 (
    echo.
    echo  هشدار: برخی تست‌ها ناموفق بودند
) else (
    echo     همه تست‌ها موفق بودند
)

:: ─── خلاصه ─────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════════════
echo   راه‌اندازی کامل شد
echo ══════════════════════════════════════════════════════
echo.
echo   آدرس:       http://localhost:5000
echo   نام کاربری: admin
echo   رمز عبور:   admin123
echo.
echo   برای اجرای مجدد برنامه:
echo     venv\Scripts\activate
echo     python run.py
echo.
echo ══════════════════════════════════════════════════════
echo   در حال راه‌اندازی سرور...
echo   برای متوقف کردن: Ctrl+C را فشار دهید
echo ══════════════════════════════════════════════════════
echo.

python run.py

pause
