import requests, json, urllib3
urllib3.disable_warnings()

url = "http://inv-veri.com/check?fpdm=&fphm=26442000007766995501&date=20260708&code=777.35&channel=yd"

r = requests.get(url, timeout=30, verify=False)
raw = r.content

print("Redirect history:", [x.url for x in r.history])
print("Final URL:", r.url)
print("Status:", r.status_code)
print("Content-Type:", r.headers.get("Content-Type"))
print()

for enc in ["gbk", "gb2312", "gb18030", "utf-8"]:
    try:
        text = raw.decode(enc)
        data = json.loads(text)
        d = data.get("data", {})
        xfmc = d.get("xfmc_dzfp", "")
        gfmc = d.get("gfmc_dzfp", "")
        print("%10s: code=%s" % (enc, data.get("code")))
        print("%10s: 销方=%s" % ("", xfmc))
        print("%10s: 购方=%s" % ("", gfmc))
        # Show repr and raw bytes
        idx = raw.find(b"xfmc_dzfp")
        if idx > 0:
            print("%10s: raw bytes around xfmc: %s" % ("", raw[idx:idx+60]))
        print("%10s: repr(xfmc)=%s" % ("", repr(xfmc)))
        # Print full response under 200 chars
        print("%10s: response=%s" % ("", text[:300]))
    except UnicodeDecodeError as e:
        print("%10s: UnicodeDecodeError" % enc)
    except json.JSONDecodeError as e:
        print("%10s: JSON error: %s" % (enc, str(e)[:80]))
