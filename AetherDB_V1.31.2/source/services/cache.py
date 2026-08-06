import time, os
CACHE = {}
ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() == "true"
TTL = int(os.environ.get("CACHE_TTL", "300"))

def cache_get(key):
    if not ENABLED: return None
    entry = CACHE.get(key)
    if entry is None: return None
    val, exp = entry
    if exp and time.time() > exp:
        del CACHE[key]
        return None
    return val

def cache_set(key, value, ttl=None):
    if not ENABLED: return
    t = time.time() + (ttl if ttl is not None else TTL)
    CACHE[key] = (value, t)

def cache_invalidate(pattern):
    if not ENABLED: return
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        for k in list(CACHE):
            if k.startswith(prefix):
                del CACHE[k]
    elif pattern in CACHE:
        del CACHE[pattern]

def cache_stats():
    active = sum(1 for v in CACHE.values()
        if not (v[1] and time.time() > v[1]))
    return {"enabled": ENABLED, "size": active}

def cached(ttl=None, prefix="auto"):
    def deco(func):
        kp = prefix if prefix != "auto" else func.__name__
        from functools import wraps
        @wraps(func)
        def wrapper(*a, **kw):
            if not ENABLED: return func(*a, **kw)
            ck = f"{kp}:" + ":".join(str(x) for x in a)
            cv = cache_get(ck)
            if cv is not None: return cv
            r = func(*a, **kw)
            cache_set(ck, r, ttl)
            return r
        return wrapper
    return deco