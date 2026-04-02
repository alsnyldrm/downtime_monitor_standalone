import asyncio
import logging
import time
import socket
from datetime import datetime, timezone
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import SessionLocal
from app.models.monitor import Monitor, MonitorStatus, MonitorType
from app.models.monitor_log import MonitorLog, LogStatus
from app.models.incident import Incident
from app.firebase_helper import send_push_notification

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def check_http(url: str, timeout: int, keyword: str = None, method: str = "GET", follow_redirects: bool = True):
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects, verify=False) as client:
            resp = await client.request(method.upper(), url)
            elapsed = round((time.time() - start) * 1000, 2)
            if keyword and keyword not in resp.text:
                return False, elapsed, resp.status_code, f"Anahtar kelime bulunamadı: {keyword}"
            if resp.status_code >= 400:
                return False, elapsed, resp.status_code, f"HTTP {resp.status_code}"
            return True, elapsed, resp.status_code, None
    except Exception as e:
        elapsed = round((time.time() - start) * 1000, 2)
        return False, elapsed, None, str(e)


async def check_ping(host: str, timeout: int):
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(timeout), host,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        elapsed = round((time.time() - start) * 1000, 2)
        if proc.returncode == 0:
            return True, elapsed, None, None
        return False, elapsed, None, "Ping başarısız"
    except Exception as e:
        elapsed = round((time.time() - start) * 1000, 2)
        return False, elapsed, None, str(e)


async def check_port(host: str, port: int, timeout: int):
    start = time.time()
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        elapsed = round((time.time() - start) * 1000, 2)
        return True, elapsed, None, None
    except Exception as e:
        elapsed = round((time.time() - start) * 1000, 2)
        return False, elapsed, None, str(e)


async def check_monitor(monitor: Monitor):
    method = getattr(monitor, 'http_method', 'GET') or 'GET'
    follow_redir = getattr(monitor, 'follow_redirects', True)
    if follow_redir is None:
        follow_redir = True
    if monitor.type in (MonitorType.http, MonitorType.https):
        return await check_http(monitor.url, monitor.timeout, None, method, follow_redir)
    elif monitor.type == MonitorType.keyword:
        return await check_http(monitor.url, monitor.timeout, monitor.keyword, method, follow_redir)
    elif monitor.type == MonitorType.ping:
        host = monitor.url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        return await check_ping(host, monitor.timeout)
    elif monitor.type == MonitorType.port:
        host = monitor.url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        return await check_port(host, monitor.port or 80, monitor.timeout)
    return False, 0, None, "Bilinmeyen monitör tipi"


# Aynı anda en fazla 20 monitör kontrol et (ağ tıkanıklığını önle)
_check_semaphore = asyncio.Semaphore(20)


async def _check_single_monitor(mon_id: int, mon_name: str, mon_type, mon_url: str,
                                 mon_port, mon_timeout: int, mon_keyword,
                                 mon_http_method, mon_follow_redirects,
                                 mon_old_status):
    """Tek bir monitörü kontrol et ve sonuçları DB'ye yaz (bağımsız session)."""
    async with _check_semaphore:
        # Önce kontrolü yap (DB session dışında, paralel çalışsın)
        try:
            # Build a lightweight object for check_monitor
            class _Mon:
                pass
            m = _Mon()
            m.type = mon_type
            m.url = mon_url
            m.port = mon_port
            m.timeout = mon_timeout
            m.keyword = mon_keyword
            m.http_method = mon_http_method
            m.follow_redirects = mon_follow_redirects
            is_up, response_time, status_code, error_msg = await check_monitor(m)
        except Exception as e:
            logger.error(f"Monitör check hatası ({mon_name}): {e}")
            return

    # Sonucu DB'ye yaz (her monitör kendi session'ını kullanır)
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        log_status = LogStatus.up if is_up else LogStatus.down
        log = MonitorLog(
            monitor_id=mon_id,
            status=log_status,
            response_time=response_time,
            status_code=status_code,
            error_message=error_msg,
            checked_at=now,
        )
        db.add(log)

        mon = db.query(Monitor).filter(Monitor.id == mon_id).first()
        if not mon:
            return

        old_status = mon.status
        mon.status = MonitorStatus.up if is_up else MonitorStatus.down
        mon.last_checked_at = now
        mon.last_response_time = response_time

        total_logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == mon_id).count()
        up_logs = db.query(MonitorLog).filter(
            MonitorLog.monitor_id == mon_id, MonitorLog.status == LogStatus.up
        ).count()
        mon.uptime_percentage = round((up_logs / total_logs) * 100, 2) if total_logs > 0 else 100.0

        if old_status != MonitorStatus.down and mon.status == MonitorStatus.down:
            incident = Incident(monitor_id=mon_id, started_at=now, reason=error_msg)
            db.add(incident)
            send_push_notification(mon.name, is_down=True, reason=error_msg)
        elif old_status == MonitorStatus.down and mon.status == MonitorStatus.up:
            open_incident = db.query(Incident).filter(
                Incident.monitor_id == mon_id, Incident.ended_at == None
            ).first()
            if open_incident:
                open_incident.ended_at = now
                started = open_incident.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                diff = (now - started).total_seconds()
                open_incident.duration_seconds = int(diff)
            send_push_notification(mon.name, is_down=False)

        db.commit()
    except Exception as e:
        logger.error(f"Monitör DB güncelleme hatası ({mon_name}): {e}")
        db.rollback()
    finally:
        db.close()


async def run_checks():
    db = SessionLocal()
    try:
        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        now = datetime.now(timezone.utc)

        tasks = []
        for mon in monitors:
            # Her monitörün kendi interval'ine göre kontrol zamanı geldi mi?
            if mon.last_checked_at is not None:
                lc = mon.last_checked_at
                if lc.tzinfo is None:
                    lc = lc.replace(tzinfo=timezone.utc)
                elapsed = (now - lc).total_seconds()
                if elapsed < mon.interval:
                    continue

            tasks.append(_check_single_monitor(
                mon_id=mon.id,
                mon_name=mon.name,
                mon_type=mon.type,
                mon_url=mon.url,
                mon_port=mon.port,
                mon_timeout=mon.timeout,
                mon_keyword=mon.keyword,
                mon_http_method=mon.http_method,
                mon_follow_redirects=mon.follow_redirects,
                mon_old_status=mon.status,
            ))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"run_checks hatası: {e}")
    finally:
        db.close()


def start_scheduler():
    # Her 5 saniyede bir çalışır; her monitör kendi interval'ine göre filtrelenir
    scheduler.add_job(run_checks, "interval", seconds=5, id="monitor_checks", replace_existing=True)
    scheduler.start()
