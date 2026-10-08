#!/usr/bin/env python3
"""Regression checks for guest crawl ownership, admin-only debug routes, proxy
headers, .env loading, bind address and robots.txt handling.

Plain script, like fixture_tests.py:  python tests/regression_tests.py
Prints PASS/FAIL per check and exits non-zero if any check fails.

Each check runs in a throwaway copy of the app. Database paths are fixed relative
to the code, so importing main from the repo would write test users into the
real data/ directory.
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATHS = ('main.py', 'src', 'web')
CLEARED_ENV = (
    'LOCAL_MODE', 'DANGEROUSLY_SKIP_AUTH', 'REGISTRATION_DISABLED', 'DISABLE_GUEST', 'DEMO_MODE',
    'TRUST_PROXY', 'BIND_HOST', 'LOCAL_MODE_ALLOW_LAN', 'SECRET_KEY', 'SMTP_PORT', 'MAIN_APP_URL',
    'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy',
)


def copy_app():
    tmp = tempfile.mkdtemp(prefix='librecrawl-regression-')
    for name in APP_PATHS:
        src = os.path.join(ROOT, name)
        dst = os.path.join(tmp, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(src, dst)
    return tmp


def run_snippet(snippet, env=None, files=None):
    """Run Python source inside a fresh copy of the app. Returns (exit code, stdout, stderr)."""
    tmp = copy_app()
    try:
        for name, content in (files or {}).items():
            with open(os.path.join(tmp, name), 'w') as fh:
                fh.write(content)
        child_env = {k: v for k, v in os.environ.items() if k not in CLEARED_ENV}
        child_env['NO_PROXY'] = child_env['no_proxy'] = '127.0.0.1,localhost'
        child_env.update(env or {})
        proc = subprocess.run(
            [sys.executable, '-c', textwrap.dedent(snippet)],
            cwd=tmp, env=child_env, capture_output=True, text=True, timeout=300,
        )
        return proc.returncode, proc.stdout, proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_json(snippet, env=None, files=None):
    code, out, err = run_snippet(snippet, env, files)
    if code != 0:
        raise RuntimeError(f'check exited {code}:\n{err[-1500:]}')
    return json.loads(out.strip().splitlines()[-1])


OWNERSHIP_SNIPPET = r'''
import json, sqlite3
import main as m
from src import auth_db, crawl_db

def make_user(name):
    auth_db.create_user(name, name + "@example.invalid", "Passw0rd-long-enough")
    con = sqlite3.connect(auth_db.DB_FILE)
    uid = con.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]
    con.close()
    auth_db.verify_user(uid)
    return uid

def registered_client(user_id, name):
    client = m.app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = user_id; s["username"] = name; s["tier"] = "user"
    return client

def guest_client():
    client = m.app.test_client()
    client.post("/api/guest-login")
    client.get("/api/get_settings")  # first call gives the guest session its session_id
    return client

victim = make_user("victim")
attacker = make_user("attacker")
victim_crawl = crawl_db.create_crawl(victim, "sess-victim", "http://127.0.0.1:9/", "127.0.0.1", {})

guest = guest_client()
with guest.session_transaction() as s:
    guest_session_id = s["session_id"]
own_guest_crawl = crawl_db.create_crawl(None, guest_session_id, "http://127.0.0.1:9/", "127.0.0.1", {})

other_guest = guest_client()
owner = registered_client(victim, "victim")
other_user = registered_client(attacker, "attacker")
anon = m.app.test_client()

print(json.dumps({
    "anon_get_victim": anon.get(f"/api/crawls/{victim_crawl}").status_code,
    "owner_get_victim": owner.get(f"/api/crawls/{victim_crawl}").status_code,
    "guest_get_victim": guest.get(f"/api/crawls/{victim_crawl}").status_code,
    "guest_archive_victim": guest.post(f"/api/crawls/{victim_crawl}/archive").status_code,
    "guest_delete_victim": guest.delete(f"/api/crawls/{victim_crawl}/delete").status_code,
    "guest_load_victim": guest.post(f"/api/crawls/{victim_crawl}/load").status_code,
    "guest_resume_victim": guest.post(f"/api/crawls/{victim_crawl}/resume").get_json().get("message"),
    "guest_get_own": guest.get(f"/api/crawls/{own_guest_crawl}").status_code,
    "other_guest_get_own": other_guest.get(f"/api/crawls/{own_guest_crawl}").status_code,
    "registered_other_get_victim": other_user.get(f"/api/crawls/{victim_crawl}").status_code,
}))
'''

DEBUG_SNIPPET = r'''
import json
import main as m
guest = m.app.test_client()
guest.post("/api/guest-login")
admin = m.app.test_client()
with admin.session_transaction() as s:
    s["user_id"] = 1; s["username"] = "admin"; s["tier"] = "admin"
result = {}
for path in ("/debug/memory", "/api/debug/memory", "/api/debug/memory/profile"):
    result["guest " + path] = guest.get(path).status_code
    result["admin " + path] = admin.get(path).status_code
print(json.dumps(result))
'''

PROXY_SNIPPET = r'''
import json
import main as m
from src.auth_db import log_guest_crawl
plain = m.app.test_client()
plain.post("/api/guest-login")
for _ in range(3):
    log_guest_crawl("127.0.0.1")  # the real peer has used its 3 guest crawls
result = {}
result["spoofed X-Forwarded-For, TRUST_PROXY off"] = plain.get(
    "/api/user/info", headers={"X-Forwarded-For": "10.0.0.1"}).get_json()["user"]["crawls_remaining"]
m.TRUST_PROXY = True
result["spoofed X-Forwarded-For, TRUST_PROXY on"] = plain.get(
    "/api/user/info", headers={"X-Forwarded-For": "10.0.0.1"}).get_json()["user"]["crawls_remaining"]
print(json.dumps(result))
'''

DOTENV_SNIPPET = r'''
import json
import main  # main loads .env before it imports src.email_service
from src import email_service as es
print(json.dumps({"MAIN_APP_URL": es.MAIN_APP_URL, "SMTP_HOST": es.SMTP_HOST, "SMTP_PORT": es.SMTP_PORT}))
'''

BIND_DEFAULT_SNIPPET = r'''
import json
import main as m
print(json.dumps({"BIND_HOST": m.BIND_HOST}))
'''

BIND_LAN_SNIPPET = r'''
import json
import main as m
refused = False
try:
    m.main()
except SystemExit as exc:
    refused = "Refusing to start" in str(exc)
print(json.dumps({"local_mode_lan_refused": refused}))
'''

ROBOTS_SNIPPET = r'''
import json, http.server, socket, threading
from src.crawler import WebCrawler

MODE = {"value": "allow"}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            if MODE["value"] == "unavailable":
                self.send_response(503); self.end_headers(); self.wfile.write(b"maintenance"); return
            body = b"User-agent: *\nDisallow: /private\n" if MODE["value"] == "disallow" else b""
            self.send_response(200); self.end_headers(); self.wfile.write(body); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"page")
    def log_message(self, *args):
        pass

server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % server.server_address[1]
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    unreachable_base = "http://127.0.0.1:%d" % probe.getsockname()[1]

def allowed(site, path):
    crawler = WebCrawler()
    crawler.config["respect_robots"] = True
    crawler.config["crawl_external"] = True
    return crawler._should_crawl_url(site + path)

result = {}
MODE["value"] = "disallow"
result["Disallow rule blocks /private"] = allowed(base, "/private/page")
result["Disallow rule allows /public"] = allowed(base, "/public/page")
MODE["value"] = "unavailable"
result["robots.txt 503 blocks /page"] = allowed(base, "/page")
result["robots.txt unreachable blocks /page"] = allowed(unreachable_base, "/page")
server.shutdown()
print(json.dumps(result))
'''


def expect(label, actual, expected, failures):
    if actual == expected:
        print(f'  PASS {label}: {actual!r}')
    else:
        print(f'  FAIL {label}: got {actual!r}, expected {expected!r}')
        failures.append(label)


def check_guest_crawl_ownership(failures):
    got = run_json(OWNERSHIP_SNIPPET)
    expect('anonymous GET crawl', got['anon_get_victim'], 401, failures)
    expect('owner GET own crawl', got['owner_get_victim'], 200, failures)
    expect('guest GET a registered user crawl', got['guest_get_victim'], 403, failures)
    expect('guest archive a registered user crawl', got['guest_archive_victim'], 403, failures)
    expect('guest delete a registered user crawl', got['guest_delete_victim'], 403, failures)
    expect('guest load a registered user crawl', got['guest_load_victim'], 403, failures)
    expect('guest resume a registered user crawl', got['guest_resume_victim'],
           "Unauthorized - you don't own this crawl", failures)
    expect('guest GET own guest crawl', got['guest_get_own'], 200, failures)
    expect('other guest GET that guest crawl', got['other_guest_get_own'], 403, failures)
    expect('other registered user GET crawl', got['registered_other_get_victim'], 403, failures)


def check_debug_routes_admin_only(failures):
    got = run_json(DEBUG_SNIPPET)
    for path in ('/debug/memory', '/api/debug/memory', '/api/debug/memory/profile'):
        expect(f'guest {path}', got[f'guest {path}'], 403, failures)
        expect(f'admin {path}', got[f'admin {path}'], 200, failures)


def check_proxy_headers_not_trusted_by_default(failures):
    got = run_json(PROXY_SNIPPET)
    expect('spoofed X-Forwarded-For ignored by default', got['spoofed X-Forwarded-For, TRUST_PROXY off'], 0, failures)
    expect('spoofed X-Forwarded-For honoured with TRUST_PROXY', got['spoofed X-Forwarded-For, TRUST_PROXY on'], 3, failures)


def check_dotenv_loaded_before_email_settings(failures):
    env_file = 'MAIN_APP_URL=https://selfhost.example.test\nSMTP_HOST=smtp.example.test\n'
    got = run_json(DOTENV_SNIPPET, files={'.env': env_file})
    expect('.env MAIN_APP_URL reaches email_service', got['MAIN_APP_URL'], 'https://selfhost.example.test', failures)
    expect('.env SMTP_HOST reaches email_service', got['SMTP_HOST'], 'smtp.example.test', failures)
    got = run_json(DOTENV_SNIPPET, env={'SMTP_PORT': ''})
    expect('empty SMTP_PORT falls back to 587', got['SMTP_PORT'], 587, failures)


def check_bind_address(failures):
    expect('BIND_HOST defaults to loopback', run_json(BIND_DEFAULT_SNIPPET)['BIND_HOST'], '127.0.0.1', failures)
    got = run_json(BIND_LAN_SNIPPET, env={'LOCAL_MODE': 'true', 'BIND_HOST': '0.0.0.0'})
    expect('local mode refuses a LAN bind', got['local_mode_lan_refused'], True, failures)


def check_robots_unavailable_disallows(failures):
    got = run_json(ROBOTS_SNIPPET)
    expect('Disallow rule blocks /private', got['Disallow rule blocks /private'], False, failures)
    expect('Disallow rule allows /public', got['Disallow rule allows /public'], True, failures)
    expect('robots.txt 503 blocks /page', got['robots.txt 503 blocks /page'], False, failures)
    expect('robots.txt unreachable blocks /page', got['robots.txt unreachable blocks /page'], False, failures)


CHECKS = (
    ('guest crawl ownership (LC-01)', check_guest_crawl_ownership),
    ('debug routes admin only (LC-05)', check_debug_routes_admin_only),
    ('proxy headers ignored by default (LC-06)', check_proxy_headers_not_trusted_by_default),
    ('.env loaded before email settings (LC-07)', check_dotenv_loaded_before_email_settings),
    ('bind address and local-mode guard (LC-02)', check_bind_address),
    ('robots.txt 5xx and unreachable disallow (LC-10)', check_robots_unavailable_disallows),
)


def main():
    any_failed = False
    for title, check in CHECKS:
        print(title)
        failures = []
        try:
            check(failures)
        except Exception as exc:  # a crashed check is a failed check
            failures.append(title)
            print(f'  FAIL {exc}')
        if failures:
            any_failed = True
            print(f'FAIL {title}')
        else:
            print(f'PASS {title}')
    sys.exit(1 if any_failed else 0)


if __name__ == '__main__':
    main()
