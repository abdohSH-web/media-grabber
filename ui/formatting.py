def format_duration(seconds):
    """83 -> '1:23', 3725 -> '1:02:05'"""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)       
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_speed(bytes_per_second):
    """Bytes per second -> '2.3 MB/s' or '640 KB/s'"""
    megabytes = bytes_per_second / (1024 * 1024)
    if megabytes >= 1:
        return f"{megabytes:.1f} MB/s"
    return f"{bytes_per_second / 1024:.0f} KB/s"


def format_eta(seconds):
    """Seconds left -> '1:05'"""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"