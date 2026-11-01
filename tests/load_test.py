"""Load test: N players in one game, all acting at the same moment. Reports how long joining, being admitted, song changes (over
WebSockets), card pages and a burst of bingo claims take. Not part of the normal test run: use tests/load_test.sh N.
Needs `pip install aiohttp websockets`."""
import asyncio, json, os, re, statistics, sys, time
import aiohttp, websockets
BASE=os.environ["BASE"]; N=int(sys.argv[1]); WS=BASE.replace("http","ws",1)
def pct(a, p): a=sorted(a); return a[min(len(a)-1, int(len(a)*p/100))] if a else 0
def summ(name, a): print(f"  {name:34} n={len(a):<4} p50={pct(a,50)*1000:7.0f}ms  p95={pct(a,95)*1000:7.0f}ms  max={max(a)*1000 if a else 0:7.0f}ms")

async def csrf(sess):
    async with sess.get(BASE+"/enter") as r: html=await r.text()
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

async def main():   # BASE: the throwaway server (see load_test.sh)
    host=aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    tok=await csrf(host)
    async with host.post(BASE+"/login", data={"username":"h","password":"pw","next":"/host","csrf_token":tok}, allow_redirects=False) as r: assert r.status in (302,303), r.status
    async with host.post(BASE+"/host/create_game", data={"game_name":"Load","playlist_mode":"paste","playlist_id_or_url":"PLAYLIST75AAAAAAAAAAAA","csrf_token":tok}, allow_redirects=False) as r:
        code=r.headers["Location"].split("/host/game/")[1].split("/")[0]
    print(f"game {code}, {N} players")
    sessions=[aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) for _ in range(N)]
    # --- everyone joins at once
    join_t=[]; errs=[]; nums={}
    async def join(i):
        s=sessions[i]; t=await csrf(s); t0=time.perf_counter()
        try:
            async with s.post(f"{BASE}/game/{code}/join", data={"name":f"P{i}","csrf_token":t}, allow_redirects=False) as r:
                if r.status not in (302,303): errs.append(("join",r.status)); return
                nums[i]=int(r.headers["Location"].rstrip("/").split("/")[-1])
        except Exception as e: errs.append(("join",repr(e)[:60]))
        join_t.append(time.perf_counter()-t0)
    t0=time.perf_counter(); await asyncio.gather(*(join(i) for i in range(N))); total=time.perf_counter()-t0
    summ("join (all at once)", join_t); print(f"  all {N} joins done in {total:.1f}s, errors: {errs[:3]} ({len(errs)})")
    # --- sockets
    received={i:[] for i in range(N)}; ready=asyncio.Event(); opened=[0]
    async def listen(i):
        ck="; ".join(f"{c.key}={c.value}" for c in sessions[i].cookie_jar)
        try:
            async with websockets.connect(f"{WS}/ws/game/{code}", additional_headers={"Cookie":ck,"Origin":BASE}, open_timeout=30, max_size=None) as ws:
                opened[0]+=1
                if opened[0]>=len(nums): ready.set()
                async for m in ws:
                    received[i].append((time.perf_counter(), json.loads(m)))
        except Exception as e: errs.append(("ws",repr(e)[:50]))
    ltasks=[asyncio.create_task(listen(i)) for i in nums]
    await asyncio.wait_for(ready.wait(), 60); await asyncio.sleep(1)
    print(f"  {opened[0]} sockets open")
    htok=await csrf(host)
    async def host_post(path, js=None):
        async with host.post(BASE+path, json=js, headers={"X-CSRF-Token":htok}) as r: return r.status
    # --- admit all: time until every player's socket got "admitted"
    t0=time.perf_counter(); st=await host_post(f"/host/game/{code}/admit_all"); await asyncio.sleep(3)
    lat=[next((t-t0 for t,m in received[i] if m.get("type")=="admitted"), None) for i in nums]; got=[x for x in lat if x is not None]
    print(f"  admit_all status {st}"); summ("admitted -> socket", got); print(f"  players that got 'admitted': {len(got)}/{len(nums)}")
    await host_post(f"/host/game/{code}/start", {"device_id":"dev-1"}); await asyncio.sleep(2)
    # --- card pages while everyone is connected
    page_t=[]
    async def page(i):
        t0=time.perf_counter()
        async with sessions[i].get(f"{BASE}/player/{code}/{nums[i]}", allow_redirects=False) as r: await r.read(); ok=r.status==200
        if not ok: errs.append(("card page", r.status))
        page_t.append(time.perf_counter()-t0 if ok else 99)
    await asyncio.gather(*(page(i) for i in nums)); summ("player card page (all at once)", page_t)
    # --- song changes: latency to every socket
    for n in range(3):
        t0=time.perf_counter(); st=await host_post(f"/host/game/{code}/track_update", {"title":f"Song {n}","track_id":f"t{n}","artist":"Band","position_ms":1000,"paused":False})
        await asyncio.sleep(3)
        lat=[next((t-t0 for t,m in received[i] if m.get("type")=="track" and m.get("title")==f"Song {n}"), None) for i in nums]; got=[x for x in lat if x is not None]
        summ(f"track update {n} -> socket (status {st})", got)
        if len(got)<len(nums): print(f"    missing: {len(nums)-len(got)}")
    # --- host page under load
    t0=time.perf_counter()
    async with host.get(f"{BASE}/host/game/{code}") as r: await r.read(); print(f"  host game page with {N} players: {r.status} in {(time.perf_counter()-t0)*1000:.0f}ms")
    # --- a burst of bingo claims
    claim_t=[]
    async def claim(i):
        s=sessions[i]; t=await csrf(s); t0=time.perf_counter()
        async with s.post(f"{BASE}/player/{code}/{nums[i]}/claim_bingo", json={}, headers={"X-CSRF-Token":t}) as r: await r.read()
        claim_t.append(time.perf_counter()-t0)
    await asyncio.gather(*(claim(i) for i in list(nums)[:min(40,N)])); summ("40 bingo claims at once", claim_t)
    t0=time.perf_counter()
    async with host.get(f"{BASE}/host/game/{code}") as r: await r.read(); print(f"  host game page with claims: {r.status} in {(time.perf_counter()-t0)*1000:.0f}ms")
    print("  other errors:", errs[:4], f"({len(errs)})")
    for t in ltasks: t.cancel()
    for s in sessions+[host]: await s.close()
asyncio.run(main())

