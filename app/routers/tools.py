import asyncio
import re
import socket
import ssl
import ipaddress
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import require_login

router = APIRouter(prefix="/tools")
templates = Jinja2Templates(directory="app/templates")

# ---------- güvenlik: hostname/IP doğrulama ----------
_HOST_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
    r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$|'
    r'^(?:\d{1,3}\.){3}\d{1,3}$'
)

def _is_internal_ip(host: str) -> bool:
    """Block requests to internal/private IP ranges (SSRF protection)."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
    except ValueError:
        pass
    # Resolve hostname and check resolved IP
    try:
        resolved = socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
    except (socket.gaierror, ValueError):
        return False


def _valid_host(host: str) -> bool:
    return bool(host) and len(host) <= 253 and bool(_HOST_RE.match(host))


def _check_ssrf(host: str) -> bool:
    """Return True if host is safe (not internal). False if SSRF risk."""
    return not _is_internal_ip(host)


def _valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


# ---------- Ana sayfa ----------
@router.get("/", response_class=HTMLResponse)
async def tools_index(request: Request):
    user = require_login(request)
    return templates.TemplateResponse("tools/index.html", {"request": request, "user": user})


# ---------- 1. DNS Sorgu ----------
@router.post("/dns")
async def dns_check(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip().lower()
    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    results = {}
    try:
        import dns.resolver
        import dns.exception
        for rtype in ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]:
            try:
                answers = dns.resolver.resolve(host, rtype, lifetime=5)
                results[rtype] = [str(r) for r in answers]
            except (dns.exception.DNSException, Exception):
                results[rtype] = []
    except ImportError:
        try:
            infos = socket.getaddrinfo(host, None)
            results["A"] = list(set(i[4][0] for i in infos if i[0] == socket.AF_INET))
            results["AAAA"] = list(set(i[4][0] for i in infos if i[0] == socket.AF_INET6))
        except Exception:
            return JSONResponse({"error": "DNS çözümleme başarısız"})

    # Reverse DNS
    try:
        ip = socket.gethostbyname(host)
        results["PTR"] = [socket.gethostbyaddr(ip)[0]]
        results["_ip"] = ip
    except Exception:
        pass

    return JSONResponse({"host": host, "results": results})


# ---------- 2. Ping Testi ----------
@router.post("/ping")
async def ping_check(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()
    count = max(1, min(int(body.get("count", 4)), 10))

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", str(count), "-W", "3", host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
        output = stdout.decode(errors="replace")

        packets = {"sent": 0, "received": 0, "loss": "100%"}
        rtt = {}
        for line in output.split("\n"):
            if "packets transmitted" in line:
                parts = line.split(",")
                for p in parts:
                    p = p.strip()
                    if "transmitted" in p:
                        packets["sent"] = int(p.split()[0])
                    elif "received" in p:
                        packets["received"] = int(p.split()[0])
                    elif "packet loss" in p:
                        packets["loss"] = p.strip().split()[0]
            if "rtt" in line or "round-trip" in line:
                nums = line.split("=")[-1].strip().split("/")
                if len(nums) >= 3:
                    rtt = {"min": nums[0].strip(), "avg": nums[1].strip(), "max": nums[2].strip()}

        return JSONResponse({
            "host": host, "output": output,
            "packets": packets, "rtt": rtt,
            "success": proc.returncode == 0
        })
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Zaman aşımı (35sn)"})
    except FileNotFoundError:
        return JSONResponse({"error": "ping komutu bulunamadı"})
    except Exception:
        return JSONResponse({"error": "Ping işlemi başarısız"})


# ---------- 3. Port Tarama ----------
PORT_NAMES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 465: "SMTPS",
    587: "SMTP-TLS", 993: "IMAPS", 995: "POP3S", 1433: "MSSQL",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
    6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 27017: "MongoDB",
    9200: "Elasticsearch", 11211: "Memcached",
}

@router.post("/port")
async def port_check(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()
    ports_raw = body.get("ports", "22,80,443,3306,5432,6379,8080,8443,27017")

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        ports = [int(p.strip()) for p in str(ports_raw).split(",")
                 if p.strip().isdigit() and 1 <= int(p.strip()) <= 65535][:50]
    except Exception:
        return JSONResponse({"error": "Geçersiz port listesi"}, status_code=400)

    async def check_port(port):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=3
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {"port": port, "status": "open", "name": PORT_NAMES.get(port, "")}
        except Exception:
            return {"port": port, "status": "closed", "name": PORT_NAMES.get(port, "")}

    results = await asyncio.gather(*[check_port(p) for p in ports])
    results = sorted(results, key=lambda x: x["port"])
    return JSONResponse({"host": host, "results": list(results)})


# ---------- 4. SSL Sertifika ----------
@router.post("/ssl")
async def ssl_check(request: Request):
    require_login(request)
    body = await request.json()
    raw = body.get("host", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    host = raw.split(":")[0]
    port = int(body.get("port", 443))

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        ctx = ssl.create_default_context()
        conn = ctx.wrap_socket(socket.socket(socket.AF_INET), server_hostname=host)
        conn.settimeout(10)
        conn.connect((host, port))
        cert = conn.getpeercert()
        conn.close()

        fmt = "%b %d %H:%M:%S %Y %Z"
        not_after = cert.get("notAfter", "")
        not_before = cert.get("notBefore", "")
        expiry_dt = datetime.strptime(not_after, fmt) if not_after else None
        issue_dt = datetime.strptime(not_before, fmt) if not_before else None
        days_left = (expiry_dt - datetime.utcnow()).days if expiry_dt else None

        sans = [val for key, val in cert.get("subjectAltName", []) if key == "DNS"]
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))

        status = "critical" if (days_left is not None and days_left < 14) else \
                 "warning" if (days_left is not None and days_left < 30) else "ok"

        return JSONResponse({
            "host": host, "port": port, "valid": True,
            "subject": subject, "issuer": issuer,
            "not_before": str(issue_dt), "not_after": str(expiry_dt),
            "days_left": days_left, "sans": sans[:20],
            "status": status,
        })
    except ssl.SSLCertVerificationError:
        return JSONResponse({"host": host, "valid": False, "error": "SSL sertifika doğrulama hatası"})
    except Exception:
        return JSONResponse({"error": "SSL kontrolü başarısız"})


# ---------- 5. HTTP Başlıkları ----------
@router.post("/headers")
async def http_headers(request: Request):
    require_login(request)
    body = await request.json()
    url = body.get("url", "").strip()
    follow = body.get("follow_redirects", True)

    if not url:
        return JSONResponse({"error": "URL boş olamaz"}, status_code=400)
    if not url.startswith("http"):
        url = "https://" + url
    if not _valid_url(url):
        return JSONResponse({"error": "Geçersiz URL"}, status_code=400)

    # SSRF: extract host from URL and check
    from urllib.parse import urlparse
    _parsed = urlparse(url)
    _url_host = _parsed.hostname or ""
    if _url_host and not _check_ssrf(_url_host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        async with httpx.AsyncClient(follow_redirects=follow, timeout=15, verify=False) as client:
            resp = await client.get(url)

        headers = dict(resp.headers)
        history = [{"url": str(r.url), "status": r.status_code} for r in resp.history]
        elapsed = int(resp.elapsed.total_seconds() * 1000) if resp.elapsed else None

        # Güvenlik başlıkları analizi
        security = {
            "Strict-Transport-Security": "hsts" in headers,
            "X-Frame-Options": "x-frame-options" in headers,
            "X-Content-Type-Options": "x-content-type-options" in headers,
            "Content-Security-Policy": "content-security-policy" in headers,
            "X-XSS-Protection": "x-xss-protection" in headers,
            "Referrer-Policy": "referrer-policy" in headers,
        }

        return JSONResponse({
            "url": str(resp.url), "status_code": resp.status_code,
            "reason": resp.reason_phrase, "http_version": resp.http_version,
            "headers": headers, "history": history,
            "elapsed_ms": elapsed, "security": security,
        })
    except Exception:
        return JSONResponse({"error": "HTTP başlık sorgusu başarısız"})


# ---------- 6. Traceroute ----------
@router.post("/traceroute")
async def traceroute(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        proc = await asyncio.create_subprocess_exec(
            "traceroute", "-m", "20", "-w", "2", "-n", host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode(errors="replace")
        hops = [l.strip() for l in output.strip().split("\n")[1:] if l.strip()]
        return JSONResponse({"host": host, "hops": hops, "raw": output})
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Traceroute zaman aşımı (60sn)"})
    except FileNotFoundError:
        return JSONResponse({"error": "traceroute komutu bulunamadı"})
    except Exception:
        return JSONResponse({"error": "Traceroute başarısız"})


# ---------- 7. WHOIS Sorgu ----------
@router.post("/whois")
async def whois_check(request: Request):
    require_login(request)
    body = await request.json()
    raw = body.get("host", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    host = raw.split(":")[0]

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    try:
        proc = await asyncio.create_subprocess_exec(
            "whois", host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode(errors="replace")

        # Önemli alanları ayıkla
        fields = {}
        keys = ["Registrar", "Creation Date", "Registry Expiry Date", "Updated Date",
                "Name Server", "Registrant Organization", "Registrant Country", "Domain Status"]
        for line in output.split("\n"):
            for k in keys:
                if line.strip().lower().startswith(k.lower() + ":"):
                    val = line.split(":", 1)[-1].strip()
                    if k not in fields:
                        fields[k] = val
                    elif isinstance(fields[k], list):
                        fields[k].append(val)
                    else:
                        fields[k] = [fields[k], val]

        return JSONResponse({"host": host, "fields": fields, "raw": output[:4000]})
    except FileNotFoundError:
        return JSONResponse({"error": "whois komutu bulunamadı"})
    except asyncio.TimeoutError:
        return JSONResponse({"error": "WHOIS zaman aşımı"})
    except Exception:
        return JSONResponse({"error": "WHOIS sorgusu başarısız"})


# ---------- 8. Subnet Hesaplayıcı ----------
@router.post("/subnet")
async def subnet_calc(request: Request):
    require_login(request)
    body = await request.json()
    cidr = body.get("cidr", "").strip()

    try:
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = list(net.hosts())
        return JSONResponse({
            "network": str(net.network_address),
            "broadcast": str(net.broadcast_address) if net.version == 4 else "-",
            "netmask": str(net.netmask) if net.version == 4 else str(net.prefixlen),
            "wildcard": str(net.hostmask) if net.version == 4 else "-",
            "prefix": net.prefixlen,
            "total_hosts": net.num_addresses,
            "usable_hosts": len(hosts),
            "first_host": str(hosts[0]) if hosts else "-",
            "last_host": str(hosts[-1]) if hosts else "-",
            "version": net.version,
            "is_private": net.is_private,
            "cidr": str(net),
        })
    except ValueError as e:
        return JSONResponse({"error": f"Geçersiz CIDR: {e}"}, status_code=400)


# ---------- 9. IP Geolokasyon ----------
@router.post("/geoip")
async def geoip_check(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)
    if not _check_ssrf(host):
        return JSONResponse({"error": "Internal/private adreslere erişim engellendi"}, status_code=403)

    # Resolve hostname to IP first
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = host

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query")
            data = resp.json()

        if data.get("status") == "fail":
            return JSONResponse({"error": data.get("message", "Sorgu başarısız")})

        return JSONResponse({
            "ip": data.get("query", ip),
            "hostname": host if host != ip else None,
            "country": data.get("country"),
            "country_code": data.get("countryCode"),
            "region": data.get("regionName"),
            "city": data.get("city"),
            "zip": data.get("zip"),
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "timezone": data.get("timezone"),
            "isp": data.get("isp"),
            "org": data.get("org"),
            "as": data.get("as"),
        })
    except Exception:
        return JSONResponse({"error": "GeoIP sorgusu başarısız"})


# ---------- 10. Reverse DNS ----------
@router.post("/rdns")
async def reverse_dns(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)

    results = {}
    try:
        # Forward: hostname → IP
        try:
            infos = socket.getaddrinfo(host, None)
            ipv4 = list(set(i[4][0] for i in infos if i[0] == socket.AF_INET))
            ipv6 = list(set(i[4][0] for i in infos if i[0] == socket.AF_INET6))
            results["forward"] = {"ipv4": ipv4, "ipv6": ipv6}
        except Exception:
            results["forward"] = {"error": "Çözümleme başarısız"}

        # Reverse: IP → hostname
        try:
            ip = socket.gethostbyname(host)
            hostinfo = socket.gethostbyaddr(ip)
            results["reverse"] = {
                "hostname": hostinfo[0],
                "aliases": hostinfo[1],
                "ip": ip,
            }
        except Exception:
            results["reverse"] = {"error": "Ters DNS çözümleme başarısız"}

        # CNAME check
        try:
            import dns.resolver
            answers = dns.resolver.resolve(host, "CNAME", lifetime=5)
            results["cname"] = [str(r) for r in answers]
        except Exception:
            results["cname"] = []

        # MX check
        try:
            import dns.resolver
            answers = dns.resolver.resolve(host, "MX", lifetime=5)
            mx_list = []
            for r in answers:
                mx_host = str(r.exchange).rstrip(".")
                try:
                    mx_ip = socket.gethostbyname(mx_host)
                except Exception:
                    mx_ip = None
                mx_list.append({"host": mx_host, "priority": r.preference, "ip": mx_ip})
            results["mx"] = mx_list
        except Exception:
            results["mx"] = []

        return JSONResponse({"host": host, "results": results})
    except Exception:
        return JSONResponse({"error": "Reverse DNS sorgusu başarısız"})


# ---------- 11. Banner Grab ----------
@router.post("/banner")
async def banner_grab(request: Request):
    require_login(request)
    body = await request.json()
    host = body.get("host", "").strip()
    ports_raw = body.get("ports", "21,22,25,80,110,143,443,587,993,995,3306,3389")

    if not _valid_host(host):
        return JSONResponse({"error": "Geçersiz hostname/IP"}, status_code=400)

    try:
        ports = [int(p.strip()) for p in str(ports_raw).split(",")
                 if p.strip().isdigit() and 1 <= int(p.strip()) <= 65535][:30]
    except Exception:
        return JSONResponse({"error": "Geçersiz port listesi"}, status_code=400)

    async def grab_one(port):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            banner = ""
            try:
                # For HTTP ports, send a minimal request
                if port in (80, 8080, 8443):
                    writer.write(f"HEAD / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
                    await writer.drain()
                data = await asyncio.wait_for(reader.read(1024), timeout=3)
                banner = data.decode(errors="replace").strip()
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {"port": port, "status": "open", "banner": banner[:500], "name": PORT_NAMES.get(port, "")}
        except Exception:
            return {"port": port, "status": "closed", "banner": "", "name": PORT_NAMES.get(port, "")}

    results = await asyncio.gather(*[grab_one(p) for p in ports])
    results = sorted(results, key=lambda x: x["port"])
    return JSONResponse({"host": host, "results": list(results)})


# ---------- 12. HTTP Performans Testi ----------
@router.post("/httpperf")
async def http_performance(request: Request):
    require_login(request)
    body = await request.json()
    url = body.get("url", "").strip()
    method = body.get("method", "GET").upper()

    if not url:
        return JSONResponse({"error": "URL boş olamaz"}, status_code=400)
    if not url.startswith("http"):
        url = "https://" + url
    if not _valid_url(url):
        return JSONResponse({"error": "Geçersiz URL"}, status_code=400)
    if method not in ("GET", "HEAD", "POST", "OPTIONS"):
        return JSONResponse({"error": "Geçersiz metod"}, status_code=400)

    try:
        import time

        # DNS resolution time
        parsed_host = url.split("//")[1].split("/")[0].split(":")[0]
        dns_start = time.monotonic()
        try:
            ip = socket.gethostbyname(parsed_host)
            dns_time = round((time.monotonic() - dns_start) * 1000, 1)
        except Exception:
            ip = None
            dns_time = None

        # TCP connect time
        tcp_time = None
        port = 443 if url.startswith("https") else 80
        if ip:
            tcp_start = time.monotonic()
            try:
                s = socket.create_connection((ip, port), timeout=5)
                tcp_time = round((time.monotonic() - tcp_start) * 1000, 1)
                s.close()
            except Exception:
                pass

        # TLS handshake + full request
        total_start = time.monotonic()
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, verify=False) as client:
            if method == "HEAD":
                resp = await client.head(url)
            elif method == "POST":
                resp = await client.post(url)
            elif method == "OPTIONS":
                resp = await client.options(url)
            else:
                resp = await client.get(url)

        total_time = round((time.monotonic() - total_start) * 1000, 1)
        ttfb = round(resp.elapsed.total_seconds() * 1000, 1) if resp.elapsed else None

        content_length = resp.headers.get("content-length")
        content_type = resp.headers.get("content-type", "")
        server = resp.headers.get("server", "")
        encoding = resp.headers.get("content-encoding", "")

        redirect_chain = [{"url": str(r.url), "status": r.status_code} for r in resp.history]

        return JSONResponse({
            "url": str(resp.url),
            "method": method,
            "status_code": resp.status_code,
            "reason": resp.reason_phrase,
            "resolved_ip": ip,
            "timing": {
                "dns_ms": dns_time,
                "tcp_ms": tcp_time,
                "ttfb_ms": ttfb,
                "total_ms": total_time,
            },
            "content_length": int(content_length) if content_length else len(resp.content),
            "content_type": content_type,
            "server": server,
            "encoding": encoding,
            "http_version": resp.http_version,
            "redirects": redirect_chain,
            "redirect_count": len(redirect_chain),
        })
    except Exception:
        return JSONResponse({"error": "Redirect analizi başarısız"})
