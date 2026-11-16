#!/usr/bin/env python3
"""Account checks that need a running app but no browser: renaming a host, the rules for creating one, and that the optional single
sign-in is invisible while it is off. Run through tests/run_tests.sh (it sets BASE), or  BASE=http://127.0.0.1:5104 python3 tests/test_accounts.py
Uses the test server's admin account h (password pw) and makes its own ordinary host, which it removes at the end."""
import os
import re
import sys

import requests

BASE = os.environ["BASE"].rstrip("/")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


def token(s, path="/login"):
    html = s.get(BASE + path, allow_redirects=True).text
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def post(s, path, data, back="/login"):
    data = dict(data)
    data["csrf_token"] = token(s, back)
    return s.post(BASE + path, data=data, headers={"Origin": BASE}, allow_redirects=False)


def signed_in(user):
    s = requests.Session()
    r = post(s, "/login", {"username": user, "password": "pw", "next": "/host"})
    assert r.status_code == 302, f"could not sign in as {user}: {r.status_code}"
    return s


def users(s):
    return re.findall(r"<td><strong>([^<]+)</strong></td>", s.get(BASE + "/host/admin/users").text)


def uid(s, name):
    html = s.get(BASE + "/host/admin/users").text
    m = re.search(r"<strong>" + re.escape(name) + r"</strong>.*?name=\"user_id\" value=\"(\d+)\"", html, re.S)
    return m.group(1) if m else None


def msg(r):
    return requests.utils.unquote(r.headers.get("location", ""))


anon = requests.Session()
page = anon.get(BASE + "/login").text
check("login page has the password form while single sign-in is off", 'name="password"' in page)
check("login page has no single sign-in button while it is off", "/auth/oidc/login" not in page)
check("the single sign-in routes answer 404 while it is off", anon.get(BASE + "/auth/oidc/login", allow_redirects=False).status_code == 404
      and anon.get(BASE + "/auth/oidc/callback?code=x&state=y", allow_redirects=False).status_code == 404)

h = signed_in("h")
# an ordinary host of our own (other tests may have changed the seeded accounts' passwords): created with a temporary password, then
# the host chooses their own, which is what lifts the "change your password first" hold
post(h, "/host/admin/users/create", {"username": "ta-user", "password": "temp-pass-1"}, "/host/admin/users")
h2 = requests.Session()
post(h2, "/login", {"username": "ta-user", "password": "temp-pass-1", "next": "/host"})
post(h2, "/host/account/password", {"current_password": "temp-pass-1", "new_password": "chosen-pass-2", "new_password2": "chosen-pass-2"}, "/host/account")
check("the admin page lists the accounts", {"h", "ta-user"} <= set(users(h)))
check("the Single sign-in panel is on the admin page and says off while it is not set up", "Single sign-in (optional)" in h.get(BASE + "/host/admin/users").text
      and "off, not set up yet" in h.get(BASE + "/host/admin/users").text)

# admin renames any host
i2 = uid(h, "ta-user")
r = post(h, "/host/admin/users/rename", {"user_id": i2, "new_username": "ta-renamed"}, "/host/admin/users")
check("an admin can rename another host", "ta-renamed" in users(h) and "ta-user" not in users(h), msg(r))
check("the renamed host stays signed in (the session is tied to the account, not the name)", h2.get(BASE + "/host/whoami").json().get("username") == "ta-renamed")
r = post(h, "/host/admin/users/rename", {"user_id": i2, "new_username": "H"}, "/host/admin/users")
check("a name that is taken is refused, in any letter case", "already a host" in msg(r) and "H" not in users(h), msg(r))
r = post(h, "/host/admin/users/rename", {"user_id": i2, "new_username": "Admin"}, "/host/admin/users")
check("nobody can be renamed to admin", "kept for the local admin" in msg(r) and "Admin" not in users(h), msg(r))
r = post(h, "/host/admin/users/rename", {"user_id": i2, "new_username": "x" * 65}, "/host/admin/users")
check("a name longer than 64 characters is refused", "at most 64" in msg(r), msg(r))
r = post(h, "/host/admin/users/rename", {"user_id": i2, "new_username": "  "}, "/host/admin/users")
check("an empty name is refused", "Type the new user name" in msg(r), msg(r))

# an ordinary host renames their own account only
r = post(h2, "/host/account/username", {"new_username": "ta-self"}, "/host/account")
check("a host can rename their own account", h2.get(BASE + "/host/whoami").json().get("username") == "ta-self", msg(r))
r = post(h2, "/host/admin/users/rename", {"user_id": uid(h, "h"), "new_username": "stolen"}, "/host/admin/users")
check("an ordinary host cannot rename anyone through the admin route", r.status_code in (302, 403) and "stolen" not in users(h), str(r.status_code))
check("an ordinary host cannot open the admin page", h2.get(BASE + "/host/admin/users", allow_redirects=False).status_code in (302, 403))

# put the names back for the tests that follow
post(h2, "/host/account/username", {"new_username": "ta-user"}, "/host/account")
check("name put back", h2.get(BASE + "/host/whoami").json().get("username") == "ta-user" and "ta-user" in users(h))

# creating hosts
r = post(h, "/host/admin/users/create", {"username": "nopass", "password": ""}, "/host/admin/users")
check("with single sign-in off a host cannot be created without a password", "nopass" not in users(h))
r = post(h, "/host/admin/users/create", {"username": "ADMIN", "password": "abcd1234xyz"}, "/host/admin/users")
check("a host cannot be created as admin", "kept for the local admin" in msg(r) and "ADMIN" not in users(h), msg(r))
r = post(h, "/host/admin/users/create", {"username": "TA-USER", "password": "abcd1234xyz"}, "/host/admin/users")
check("a host cannot be created with a taken name in another letter case", "already a host" in msg(r), msg(r))
r = post(h, "/host/admin/users/create", {"username": "newhost", "password": "short"}, "/host/admin/users")
check("a password under 8 characters is refused", "at least 8" in msg(r) and "newhost" not in users(h), msg(r))
r = post(h, "/host/admin/users/create", {"username": "newhost", "password": "abcd1234xyz"}, "/host/admin/users")
check("a host with a temporary password is created", "newhost" in users(h))
n = requests.Session()
r = post(n, "/login", {"username": "newhost", "password": "abcd1234xyz", "next": "/host"})
r2 = n.get(BASE + "/host", allow_redirects=False)
check("a temporary password still has to be changed (redirect to the account page)", r2.status_code == 302 and "/host/account" in r2.headers.get("location", ""), str(r2.status_code))
post(h, "/host/admin/users/delete", {"user_id": uid(h, "newhost")}, "/host/admin/users")
check("the test host is removed again", "newhost" not in users(h))
post(h, "/host/admin/users/delete", {"user_id": uid(h, "ta-user")}, "/host/admin/users")
check("the other test host is removed again", "ta-user" not in users(h))

print(f"\n{sum(results)} of {len(results)} checks passed")
sys.exit(0 if all(results) else 1)
