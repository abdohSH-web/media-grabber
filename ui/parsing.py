import math
import re


def parse_time(text):
    """'90' -> 90.0, '1:30' -> 90.0, '1:02:03' -> 3723.0. Raises ValueError if invalid."""
    parts = text.strip().split(":")
    message = f"'{text}' isn't a valid time. Use seconds, mm:ss or hh:mm:ss."
    if not 1 <= len(parts) <= 3 or any(not part.strip() for part in parts):
        raise ValueError(message)
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise ValueError(message) from None
    # float() also accepts "nan" and "inf": we don't
    if any(n < 0 or not math.isfinite(n) for n in numbers):
        raise ValueError(message)

    seconds = 0.0
    for number in numbers:              # hours, minutes, seconds: each step multiplies by 60
        seconds = seconds * 60 + number
    return seconds


def parse_clip(start_text, end_text, duration=None):
    """Turn the 'From' and 'To' boxes into (start, end) in seconds.
    end is None when the user wants "until the end".
    Returns (None, None) when the result would be the whole video anyway."""
    start = parse_time(start_text) if start_text.strip() else 0.0
    end = parse_time(end_text) if end_text.strip() else None

    if duration:
        if start >= duration:
            raise ValueError("'From' is after the end of the video.")
        if end is not None and end >= duration:
            end = None                  # beyond the end = until the end
    if end is not None and end <= start:
        raise ValueError("'To' must be later than 'From'.")

    if start == 0 and end is None:
        return None, None
    return start, end


def parse_languages(text):
    """'en, ar' -> ('en', 'ar'). Raises ValueError for something that isn't a language code."""
    codes = []
    for part in text.replace(";", ",").split(","):
        code = part.strip()
        if not code:
            continue
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", code):
            raise ValueError(f"'{code}' isn't a language code (examples: en, ar, pt-BR).")
        if code not in codes:
            codes.append(code)
    return tuple(codes)