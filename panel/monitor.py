import psutil

from . import systemd_manager


def project_stats(project_name):
    pid = systemd_manager.get_pid(project_name)
    if not pid:
        return None
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_info().rss / (1024 * 1024)  # MB
            threads = proc.num_threads()
        return {
            "pid": pid,
            "cpu_percent": round(cpu, 1),
            "ram_mb": round(mem, 1),
            "threads": threads,
        }
    except psutil.NoSuchProcess:
        return None


def system_stats():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
    }
