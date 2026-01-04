import psutil
import shutil
import os

def get_system_metrics():
    """Returns a dictionary with RAM, Disk, and CPU info."""
    # RAM
    ram = psutil.virtual_memory()
    ram_total = ram.total / (1024**3)
    ram_used = ram.used / (1024**3)
    ram_percent = ram.percent
    
    # Disk (of current directory)
    disk = shutil.disk_usage(os.getcwd())
    disk_total = disk.total / (1024**3)
    disk_used = disk.used / (1024**3)
    disk_free = disk.free / (1024**3)
    disk_percent = (disk.used / disk.total) * 100
    
    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)
    
    return {
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_percent": ram_percent,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_percent": disk_percent,
        "cpu_percent": cpu_percent
    }

def format_system_metrics():
    """Returns a formatted string of system metrics."""
    metrics = get_system_metrics()
    return (
        f"📊 **System Metrics**\n"
        f"• **RAM**: {metrics['ram_used']:.1f}/{metrics['ram_total']:.1f} GB ({metrics['ram_percent']}%)\n"
        f"• **Disk**: {metrics['disk_used']:.1f}/{metrics['disk_total']:.1f} GB ({metrics['disk_percent']:.1f}% free: {metrics['disk_free']:.1f} GB)\n"
        f"• **CPU**: {metrics['cpu_percent']}%"
    )
