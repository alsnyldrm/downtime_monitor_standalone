# CLAUDE.md — Downtime Monitor Standalone Proje Talimatları

## Dil
- Kullanıcıya **daima Türkçe** cevap ver.
- Kod içi yorumlar ve commit mesajları da Türkçe olabilir.

---

## Proje Bilgileri
- **Proje:** FBU Downtime Monitor Standalone (Fenerbahçe Üniversitesi IT altyapı izleme)
- **Framework:** FastAPI (Python 3.12)
- **Veritabanı:** MySQL 8.0 (SQLAlchemy ORM)
- **Migration:** Alembic (sıralı: `001_`, `002_`, `003_` ...)
- **Template:** Jinja2 (auto-escaping aktif)
- **Auth:** SAML 2.0 (Azure AD) + JWT (mobil API)
- **Push Bildirim:** Firebase Cloud Messaging
- **Scheduler:** APScheduler (AsyncIOScheduler)
- **Deploy:** Docker Compose + Nginx reverse proxy

---

## Yerel ve Uzak Sunucu Bilgileri

| Özellik | Değer |
|---------|-------|
| **Yerel proje yolu** | `D:\OneDrive - Fenerbahçe Üniversitesi\claude_code\downtime_monitor_standalone` |
| **Uzak sunucu IP** | `20.229.148.197` |
| **Uzak sunucu kullanıcı** | `alisan` |
| **SSH key yolu** | `D:\OneDrive - Fenerbahçe Üniversitesi\PC SYSTEM PACTH\Belgeler\.vscode\KEY\id_ed25519` |
| **Uzak sunucu proje yolu** | `/opt/downtime_monitor_standalone` |
| **GitHub repo** | `alsnyldrm/downtime_monitor_standalone` (master branch) |

---

## Git & Deploy Akışı (ZORUNLU)

Her kod değişikliği sonrası aşağıdaki sırayı takip et:

1. **Yerel commit & push:**
   ```powershell
   cd "D:\OneDrive - Fenerbahçe Üniversitesi\claude_code\downtime_monitor_standalone"
   git add -A
   git commit -m "açıklayıcı commit mesajı"
   git push origin master
   ```

2. **Uzak sunucuda git pull & docker rebuild:**
   ```powershell
   ssh -i "D:\OneDrive - Fenerbahçe Üniversitesi\PC SYSTEM PACTH\Belgeler\.vscode\KEY\id_ed25519" alisan@20.229.148.197 "cd /opt/downtime_monitor_standalone && git pull origin master && sg docker -c 'cd docker && docker compose down && docker compose up -d --build'"
   ```

3. **Deploy sonrası kontrol:**
   ```powershell
   ssh -i "D:\OneDrive - Fenerbahçe Üniversitesi\PC SYSTEM PACTH\Belgeler\.vscode\KEY\id_ed25519" alisan@20.229.148.197 "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/login"
   ```
   HTTP 200 dönmeli.

### YASAKLAR
- **SFTP ile dosya transfer etme.** Tüm dosya aktarımları GitHub üzerinden (git push → git pull) yapılır.
- **Sunucuda doğrudan dosya düzenleme yapma.** Değişiklikler her zaman yerel projede yapılır, git ile sync edilir.

---

## Proje Yapısı

```
├── main.py                  # FastAPI app entry, startup logic, middleware
├── alembic.ini              # Alembic config (DB URL env'den okunur)
├── requirements.txt         # Python bağımlılıkları
├── ARCHITECTURE.md          # Detaylı mimari doküman
├── CLAUDE.md                # Bu dosya
│
├── app/
│   ├── __init__.py          # Shared Jinja2Templates + localtime filtresi
│   ├── config.py            # Ortam değişkenleri (DATABASE_URL, SECRET_KEY, SAML)
│   ├── database.py          # SQLAlchemy engine, session factory, Base
│   ├── dependencies.py      # Auth guard'lar (require_login, require_editor, require_admin)
│   ├── monitor_service.py   # Asenkron izleme motoru (APScheduler, semaphore=20)
│   ├── firebase_helper.py   # FCM push bildirim
│   ├── saml_helper.py       # SAML 2.0 yardımcıları
│   │
│   ├── models/              # SQLAlchemy ORM modelleri
│   │   ├── user.py          # User (admin, editor, readonly)
│   │   ├── monitor.py       # Monitor (http, https, ping, port, keyword)
│   │   ├── monitor_log.py   # MonitorLog
│   │   ├── incident.py      # Incident
│   │   ├── monitor_group.py # MonitorGroup
│   │   └── fcm_token.py     # FcmToken
│   │
│   ├── routers/             # FastAPI router'ları
│   │   ├── auth.py          # SAML login/logout, JWT
│   │   ├── dashboard.py     # Pano, tercihler, profil
│   │   ├── monitors.py      # Monitör CRUD (web)
│   │   ├── users.py         # Kullanıcı yönetimi (admin)
│   │   ├── groups.py        # Grup yönetimi
│   │   ├── reports.py       # Raporlar & export
│   │   ├── tools.py         # Ağ araçları (DNS, ping, port, SSL, HTTP)
│   │   ├── notifications.py # Push bildirim
│   │   └── api.py           # RESTful JSON API (/api/v1/, JWT auth)
│   │
│   ├── templates/           # Jinja2 HTML şablonları (base.html extend)
│   └── static/              # CSS, JS, görseller
│
├── alembic/                 # DB migration'ları
│   ├── env.py               # DATABASE_URL env var'dan okur
│   └── versions/            # Sıralı migration dosyaları
│
└── docker/
    ├── Dockerfile           # Python 3.12-slim, uvicorn --workers 1
    ├── docker-compose.yml   # app + db (MySQL 8.0) servisleri
    └── nginx.conf           # Reverse proxy
```

---

## Kodlama Kuralları

### Genel
- Credential'lar `.env`'den okunur, kaynak koda **asla** hardcode edilmez.
- Tüm secret'lar `app/config.py` üzerinden erişilir.
- `openapi_url=None` — Swagger/ReDoc üretimde kapalı.

### Veritabanı
- Şema değişiklikleri **Alembic migration** ile yapılır. Direkt `ALTER TABLE` yasak.
- Migration dosyaları `001_`, `002_`, `003_` prefix alır.
- `get_db()` dependency ile session sağlanır.
- FK'lar ve tarih sütunları **indexed** olmalı.

### Router & Endpoint
- Web UI → HTML (`TemplateResponse`), prefix yok.
- API → JSON, `/api/v1/` prefix, JWT auth.
- Template'ler `app/__init__.py`'deki ortak `templates` nesnesi ile render edilir. Router'da ayrı `Jinja2Templates` oluşturulmaz.
- Auth guard: `require_login` / `require_editor` / `require_admin` (`dependencies.py`).

### Template & Frontend
- Tüm sayfalar `base.html`'i extend eder.
- Tarihler **`localtime(dt, fmt, offset)`** Jinja2 filtresi ile gösterilir. Ham `.strftime()` yasak.
- Dark/Light tema CSS variables ile (`[data-theme]` selector).
- jQuery yok, vanilla JS kullanılır.

### Güvenlik
- SSRF koruması: `tools.py`'de internal IP'ler engellenir (10.x, 172.x, 192.168.x, 127.x).
- XSS: Jinja2 auto-escaping aktif. `|safe` dikkatli kullanılır.
- Session: `httponly=True`, `samesite=lax`, `max_age=86400`.
- Şifre: `bcrypt` hash. Lokal login production'da devre dışı (sadece SAML).
- Security headers: `SecurityHeadersMiddleware` (X-Frame-Options, CSP, HSTS).

### Docker & Deploy
- **Tek worker** (`--workers 1`) — APScheduler duplicate job önlemi.
- DNS: Container'lar `8.8.8.8`, `8.8.4.4` kullanır.
- Restart: `unless-stopped`.

---

## Ortam Değişkenleri (.env)

| Değişken | Zorunlu | Açıklama |
|----------|:-------:|----------|
| `DATABASE_URL` | ✅ | MySQL bağlantı string'i |
| `SECRET_KEY` | ✅ | Session ve JWT imza anahtarı |
| `APP_URL` | ❌ | Uygulama URL'i (varsayılan: https://downtime.fbu.edu.tr) |
| `SAML_DEBUG` | ❌ | SAML debug (true/false) |

---

## Geliştirme Kontrol Listesi

Yeni özellik/değişiklik yaparken:
- [ ] Model değişikliği → Alembic migration yaz
- [ ] Router ekliyorsan → `main.py`'ye kayıt et
- [ ] Yetki → `require_login` / `require_editor` / `require_admin`
- [ ] Tarih gösterimi → `localtime` filtresi
- [ ] Template → `base.html` extend et
- [ ] API endpoint → `/api/v1/` prefix + JWT guard
- [ ] Dış istek → SSRF kontrolü (internal IP engelle)
- [ ] Yeni env var → `config.py`'ye tanımla
- [ ] Push bildirim → `firebase_helper.py` kullan
- [ ] Değişiklik bitti → git commit + push + sunucuda pull + docker rebuild
