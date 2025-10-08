import os, time, datetime, math, requests
import json, base64
from collections import defaultdict
from flask import Flask, request, redirect, session, url_for, jsonify
# --- Added for Strava webhook patch ---
import sqlite3
import csv
import time
from urllib.parse import urlencode
# --- Google Drive integration imports ---
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except Exception as _drive_import_err:
    # Libs might not be installed yet on Render. We'll handle at runtime.
    pass

# ----------------- App & Config -----------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev")

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = os.environ["STRAVA_REDIRECT_URI"]

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
BASE_URL = os.environ.get("BASE_URL", "https://strava-project-lara.onrender.com").rstrip("/")


# ----------------- Helpers -----------------
def unix(dt):  # datetime -> epoch seconds
    return int(time.mktime(dt.timetuple()))


def fmt_hms(seconds):
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m:02d}"


def km(meters):
    return round((meters or 0) / 1000.0, 2)


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def get_activities_between(token,
                           start_dt,
                           end_dt,
                           per_page=200,
                           max_pages=12):
    """Fetch all activities between two dates (UTC) with pagination."""
    headers = {"Authorization": f"Bearer {token}"}
    after = unix(start_dt)
    before = unix(end_dt)
    all_acts = []
    page = 1
    while page <= max_pages:
        url = (
            f"{STRAVA_API_BASE}/athlete/activities?"
            f"after={after}&before={before}&per_page={per_page}&page={page}")
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        all_acts.extend(batch)
        page += 1
    return all_acts


def strava_activity_link(act_id):
    return f"https://www.strava.com/activities/{act_id}"


# ----------------- UI Fragments -----------------
def html_head(title="Strava – Lara"):
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
:root {{ --bg1:#0f172a; --bg2:#1e293b; --text:#e5e7eb; --muted:#94a3b8; --btn:#f97316; --btnH:#ea580c; --line:rgba(148,163,184,.18); }}
*{{box-sizing:border-box}} html,body{{height:100%}}
body{{
  margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,"Helvetica Neue",Arial;
  color:var(--text);
  background:radial-gradient(90vw 90vh at 80% -10%, #1f2937 0, transparent 60%),
             radial-gradient(70vw 70vh at -10% 110%, #1f2937 0, transparent 60%),
             linear-gradient(160deg, var(--bg1), var(--bg2));
  padding:24px;
}}
.wrap {{
  max-width: 1024px;
  margin: 0 auto;
  text-align: center; /* center layout */
}}
.row{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 6px;justify-content:center}}
.links{{display:flex;gap:14px;margin-top:10px;flex-wrap:wrap;justify-content:center}}
.card{{
  background:linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
  border:1px solid var(--line); border-radius:20px; padding:22px 20px;
  box-shadow:0 10px 40px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.04);
  backdrop-filter: blur(6px);
  text-align:left; /* keep text readable inside cards */
}}
.title{{font-size:30px;font-weight:800;margin:0 0 8px;text-align:center}}
.subtitle{{color:var(--muted);margin:0 0 18px;line-height:1.55;text-align:center}}
.pill{{font-size:12px;color:#e2e8f0;background:#0f172a;border:1px solid var(--line);padding:8px 12px;border-radius:999px}}
.btn{{
  appearance:none;border:0;border-radius:12px;padding:14px 18px;font-weight:800;font-size:15px;
  background:linear-gradient(180deg, var(--btn), var(--btnH)); color:white; cursor:pointer;
  box-shadow:0 8px 24px rgba(249,115,22,.35); transition:transform .05s ease, box-shadow .2s ease;
}}
.btn:hover{{box-shadow:0 10px 32px rgba(249,115,22,.5)}} .btn:active{{transform:translateY(1px)}}
.a{{color:#93c5fd;text-decoration:none;font-weight:600}} .a:hover{{text-decoration:underline}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}}
.k{{font-size:26px;font-weight:800}} .l{{color:var(--muted);font-size:13px}}
table{{width:100%; border-collapse:collapse; margin-top:8px}}
th,td{{padding:8px 6px; border-bottom:1px solid var(--line); text-align:left; font-size:14px}}
.badge{{display:inline-block;background:#0b1220;border:1px solid var(--line);padding:4px 8px;border-radius:8px;font-size:12px}}
.note{{color:#86efac;font-weight:600;margin-top:8px}}
.small{{font-size:12px;color:var(--muted)}}
@keyframes spin {{
  0% {{ transform: rotate(0deg); }}
  100% {{ transform: rotate(360deg); }}
}}

</style></head><body><div class="wrap">"""


def html_foot():
    return """
      <div style="margin-top:30px;text-align:center;font-size:12px;color:#94a3b8">
        Powered by <a class="a" href="https://www.strava.com" target="_blank">Strava</a> •
        <a class="a" href="/privacy">Privacy Policy</a>
      </div>
    </div></body></html>
    """

# ----------------- Routes -----------------
@app.route("/")
def home():
    connected = "access_token" in session

    if not connected:
        return html_head("Strava Project – Lara") + """
        <div class="card">
          <h1 class="title">Welcome to Lara’s first project 🚀</h1>
          <p class="subtitle">Connect your Strava account to see a quick dashboard (activities, <b>2025 Stats</b>, top lists).</p>
          <div class="row">
            <span class="pill">Flask</span><span class="pill">Strava API</span><span class="pill">OAuth2</span>
          </div>

          <div style="display:flex; justify-content:center; margin-top:32px">
            <form action="/connect" method="get">
              <button class="btn" type="submit">🚴 Connect with Strava</button>
            </form>
          </div>

<div class="note">✓ Auth lives only in your session; nothing is stored server‑side.</div>
<div class="links" style="margin-top:10px">
  <a class="a" href="/privacy">Privacy Policy</a>
</div>
        """ + html_foot()

    # connected: show menu (no connect button)
    return html_head("Strava – Lara (connected)") + """
    <div class="card">
      <h1 class="title">Hello Lara ✨</h1>
      <p class="subtitle">You’re connected. Access your profile, recent activities and <b>2025 Stats</b>.</p>
<div class="links">
  <a class="a" href="/me">Profile</a>
  <a class="a" href="/activities">Recent activities</a>
  <a class="a" href="/stats-2025">📊 2025 Stats</a>
  <a class="a" href="/privacy">Privacy Policy</a>  <!-- ✅ ici -->
  <a class="a" href="/logout">Log out</a>
</div>
      <div class="row" style="margin-top:14px">
        <span class="pill">Connected ✅</span><span class="pill">Dashboard</span><span class="pill">2025</span>
      </div>
    </div>
    """ + html_foot()

@app.route("/privacy")
def privacy():
    return html_head("Privacy Policy") + f"""
    <div class="card">
      <h1 class="title">🔒 Privacy Policy</h1>
      <p class="subtitle">This personal app uses the Strava and Google Drive APIs to automate training analysis and file storage.</p>

      <ul class="small">
        <li>📥 <b>Data retrieved (Strava):</b> athlete profile, activity list, performance metrics (distance, time, elevation gain, power/HR/cadence when available), and detailed per-second <i>streams</i> via webhook. Laps are only read if you manually upload a <code>.fit</code> file.</li>

        <li>💾 <b>Server-side storage:</b>
          <ul>
            <li>SQLite database <code>{DB_PATH}</code> — minimal tables:
              <ul>
                <li><code>users</code>: Strava tokens (access/refresh + expiry) per athlete.</li>
                <li><code>meta</code>: Google OAuth credentials (refresh token) for Drive uploads.</li>
              </ul>
            </li>
            <li>Local files stored under <code>{DATA_DIR}</code> (CSV / .fit) and/or uploaded to your personal Google Drive.</li>
          </ul>
        </li>

        <li>🔐 <b>Security:</b> all API keys and secrets are injected via environment variables. Browser sessions are signed using <code>APP_SECRET_KEY</code>.</li>

        <li>📤 <b>Data sharing:</b> no data is ever sold or shared with third parties. Files may be uploaded to your own Google Drive only if you explicitly authorize access (scope <code>drive.file</code>, limited to files created by this app).</li>

        <li>⏳ <b>Retention:</b> tokens remain stored while automation is active. You can revoke access anytime from your Strava or Google account (“Third-party access”). Local files remain under <code>{DATA_DIR}</code> until manually deleted; Drive files remain in your selected folder.</li>

        <li>❌ <b>Data deletion:</b> you can request deletion of all stored data (tokens and local files) by emailing <a class="a" href="mailto:ldmc.meyer@gmail.com">ldmc.meyer@gmail.com</a>. You can also log out to clear your browser session immediately.</li>

        <li>🧾 <b>Scopes used:</b> Strava <code>read</code>, <code>activity:read</code>, <code>activity:read_all</code>; Google Drive <code>drive.file</code>.</li>
      </ul>

      <div class="links"><a class="a" href="/">← Back</a></div>
    </div>
    """ + html_foot()

@app.route("/connect")
def connect():
    # Scopes (include private activities)
    scope = "read,activity:read,activity:read_all"

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope
    }

    # Build auth URL
    query_string = "&".join(f"{k}={requests.utils.quote(v)}"
                            for k, v in params.items())
    auth_url = f"{STRAVA_AUTH_URL}?{query_string}"

    # DEBUG — printed to server logs (Render) / console (Replit)
    print("🔍 DEBUG — Strava Auth")
    print("Client ID:", CLIENT_ID)
    print("Redirect URI:", REDIRECT_URI)
    print("Generated URL:", auth_url)

    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: no authorization code returned by Strava.", 400
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    }
    r = requests.post(STRAVA_TOKEN_URL, data=data, timeout=20)
    if r.status_code != 200:
        return f"Error while exchanging token: {r.text}", 400
    tok = r.json()
    try:
        save_user_token(tok.get("athlete", {}), tok)
    except Exception as _e:
        print("save_user_token warning:", _e)

    session["access_token"] = tok["access_token"]
    session["athlete"] = tok.get("athlete", {})
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/me")
def me():
    if "access_token" not in session:
        return redirect(url_for("home"))
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    r = requests.get(f"{STRAVA_API_BASE}/athlete", headers=headers, timeout=20)
    if r.status_code != 200:
        return f"Error calling /athlete: {r.text}", 400
    a = r.json()
    return html_head("Strava Profile") + f"""
    <div class="card">
      <h1 class="title">Strava Profile</h1>
      <p class="subtitle small">ID: {a.get('id')} — {a.get('firstname','')} {a.get('lastname','')}</p>
      <pre class="small" style="white-space:pre-wrap">{a}</pre>
      <div class="links"><a class="a" href="/">← Back</a></div>
    </div>
    """ + html_foot()


@app.route("/activities")
def activities():
    if "access_token" not in session:
        return redirect(url_for("home"))
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    r = requests.get(f"{STRAVA_API_BASE}/athlete/activities?per_page=10",
                     headers=headers,
                     timeout=25)
    if r.status_code != 200:
        return f"Error calling /athlete/activities: {r.text}", 400
    acts = r.json()

    items = ""
    for a in acts:
        link = strava_activity_link(a.get("id"))
        dist = km(a.get("distance", 0))
        elev = int(a.get("total_elevation_gain", 0) or 0)
        mt = fmt_hms(a.get("moving_time", 0))
        name = a.get("name", "(untitled)")
        sport = a.get("sport_type") or a.get("type") or "Other"
        items += f"<tr><td><a class='a' href='{link}' target='_blank'>{name}</a></td><td class='badge'>{sport}</td><td>{dist} km</td><td>{elev} m</td><td>{mt}</td></tr>"

    return html_head("Recent activities") + f"""
    <div class="card">
      <h1 class="title">Recent activities</h1>
      <table>
        <thead><tr><th>Name</th><th>Sport</th><th>Distance</th><th>Elev. gain</th><th>Moving time</th></tr></thead>
        <tbody>{items or "<tr><td colspan='5'>No activities.</td></tr>"}</tbody>
      </table>
      <div class="links"><a class="a" href="/">← Back</a></div>
    </div>
    """ + html_foot()



@app.route("/stats-2025/data")
def stats_2025_data():
    if "access_token" not in session:
        return redirect(url_for("home"))
    token = session["access_token"]

    # 2025 window (UTC)
    start = datetime.datetime(2025, 1, 1)
    end = datetime.datetime(2026, 1, 1)

    acts = get_activities_between(token, start, end)

    # Aggregates
    total_dist = sum((a.get("distance") or 0) for a in acts)
    total_elev = sum((a.get("total_elevation_gain") or 0) for a in acts)
    total_time = sum((a.get("moving_time") or 0) for a in acts)
    n = len(acts)

    # By sport
    by_type = defaultdict(lambda: {
        "dist": 0.0,
        "elev": 0.0,
        "time": 0,
        "count": 0
    })
    active_days = set()
    longest = None
    biggest_elev = None
    fastest_avg = None  # best avg speed (>= 5 km)

    for a in acts:
        t = (a.get("sport_type") or a.get("type") or "Other")
        d = a.get("distance") or 0
        e = a.get("total_elevation_gain") or 0
        mt = a.get("moving_time") or 0

        by_type[t]["dist"] += d
        by_type[t]["elev"] += e
        by_type[t]["time"] += mt
        by_type[t]["count"] += 1

        if not longest or d > longest.get("distance", 0):
            longest = a
        if not biggest_elev or e > biggest_elev.get("total_elevation_gain", 0):
            biggest_elev = a
        if d >= 5000 and mt > 0:
            v = d / mt  # m/s
            if not fastest_avg or v > fastest_avg["v"]:
                fastest_avg = {"v": v, "act": a}

        start_local = a.get("start_date_local") or a.get("start_date")
        if start_local:
            active_days.add(start_local[:10])  # YYYY-MM-DD

    days_active = len(active_days)
    avg_km_per_day = km(total_dist) / max(1, days_active)

    # Tops (distance / elev / avg speed >= 5 km)
    top_by_distance = sorted(acts,
                             key=lambda x: x.get("distance") or 0,
                             reverse=True)[:5]
    top_by_elev = sorted(acts,
                         key=lambda x: x.get("total_elevation_gain") or 0,
                         reverse=True)[:5]

    def avg_kmh(a):
        d = a.get("distance") or 0
        mt = a.get("moving_time") or 0
        if d < 5000 or mt <= 0:
            return 0.0
        return (d / mt) * 3.6

    top_by_speed = sorted(acts, key=lambda x: avg_kmh(x), reverse=True)[:5]

    # Tables
    def rows_by_type():
        out = ""
        for t, agg in sorted(by_type.items(), key=lambda kv: -kv[1]["dist"]):
            out += f"<tr><td class='badge'>{t}</td><td>{agg['count']}</td><td>{km(agg['dist'])} km</td><td>{int(agg['elev'])} m</td><td>{fmt_hms(agg['time'])}</td></tr>"
        return out or "<tr><td colspan='5'>No 2025 activity.</td></tr>"

    def rows_top(acts_list, metric):
        out = ""
        for a in acts_list:
            name = a.get("name", "(untitled)")
            link = strava_activity_link(a.get("id"))
            if metric == "distance":
                val = f"{km(a.get('distance',0))} km"
            elif metric == "elev":
                val = f"{int(a.get('total_elevation_gain',0) or 0)} m"
            else:  # speed
                v = round(avg_kmh(a), 2)
                val = f"{v} km/h"
            out += f"<tr><td><a class='a' target='_blank' href='{link}'>{name}</a></td><td>{val}</td></tr>"
        return out or "<tr><td colspan='2'>No data.</td></tr>"

    # Records
    long_html = "-" if not longest else f"<a class='a' target='_blank' href='{strava_activity_link(longest.get('id'))}'>{longest.get('name','(untitled)')}</a> — {km(longest.get('distance',0))} km"
    climb_html = "-" if not biggest_elev else f"<a class='a' target='_blank' href='{strava_activity_link(biggest_elev.get('id'))}'>{biggest_elev.get('name','(untitled)')}</a> — {int(biggest_elev.get('total_elevation_gain',0))} m gain"
    fast_html = "-"
    if fastest_avg:
        v_kmh = round(fastest_avg["v"] * 3.6, 2)
        act = fastest_avg["act"]
        fast_html = f"<a class='a' target='_blank' href='{strava_activity_link(act.get('id'))}'>{act.get('name','(untitled)')}</a> — {v_kmh} km/h (≥5 km)"

    # Render
    # Render (return ONLY the inner content for injection)
    body_html = f"""
    <div class="card">
      <h1 class="title">📊 2025 Stats</h1>
      <p class="subtitle">Period: 01.01.2025 → 31.12.2025</p>

      <div class="grid">
        <div class="card"><div class="k">{km(total_dist)} km</div><div class="l">Total distance</div></div>
        <div class="card"><div class="k">{int(total_elev)} m</div><div class="l">Elevation gain</div></div>
        <div class="card"><div class="k">{fmt_hms(total_time)}</div><div class="l">Moving time</div></div>
        <div class="card"><div class="k">{n}</div><div class="l">Activities</div></div>
        <div class="card"><div class="k">{days_active}</div><div class="l">Active days</div></div>
        <div class="card"><div class="k">{round(avg_km_per_day, 2)}</div><div class="l">Avg km / active day</div></div>
      </div>

      <div class="grid">
        <div class="card"><div class="k" style="font-size:18px">Longest activity</div><div class="l">{long_html}</div></div>
        <div class="card"><div class="k" style="font-size:18px">Biggest elevation gain</div><div class="l">{climb_html}</div></div>
        <div class="card"><div class="k" style="font-size:18px">Best average speed</div><div class="l">{fast_html}</div></div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top distance (5)</div>
          <table><tbody>{rows_top(top_by_distance, "distance")}</tbody></table>
        </div>
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top elevation gain (5)</div>
          <table><tbody>{rows_top(top_by_elev, "elev")}</tbody></table>
        </div>
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top average speed (5)</div>
          <table><tbody>{rows_top(top_by_speed, "speed")}</tbody></table>
        </div>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="k" style="font-size:18px;margin-bottom:8px">By sport</div>
        <table>
          <thead><tr><th>Sport</th><th>#</th><th>Distance</th><th>Elev. gain</th><th>Time</th></tr></thead>
          <tbody>{rows_by_type()}</tbody>
        </table>
      </div>

      <div class="links" style="margin-top:10px"><a class="a" href="/">← Back</a></div>
    </div>
    """

    return body_html

@app.route("/stats-2025")
def stats_2025_shell():
    if "access_token" not in session:
        return redirect(url_for("home"))

    return html_head("2025 Stats – Lara") + """
<div id="loading-message" style="
  position: fixed; top: 0; left: 0; width: 100%%;
  background: #fff3cd; color: #856404;
  padding: 10px; text-align: center; z-index: 9999;
  border-bottom: 1px solid #ffeeba;
">
  ⏳ Processing stats… this may take a few seconds. Please don’t refresh.
</div>

<div id="content" style="margin-top: 52px;">Preparing…</div>

<script>
  fetch('/stats-2025/data', { credentials: 'same-origin' })
    .then(response => {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    })
    .then(html => {
      document.getElementById('content').innerHTML = html;
      document.getElementById('loading-message').style.display = 'none';
    })
    .catch(error => {
      document.getElementById('content').innerHTML = 'Error loading stats.';
      console.error(error);
    });
</script>
""" + html_foot()

# OAuth user flow (Drive)
try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials as UserCredentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except Exception as _e:
    Flow = UserCredentials = build = MediaFileUpload = None

GOOGLE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
OAUTH_REDIRECT_URI = f"{BASE_URL}/oauth2callback"

def get_drive_service_user():
    """Build a Drive client using the stored user refresh token (if present)."""
    if not (UserCredentials and build):
        return None
    token_json = meta_get("google_user_token_json")
    if not token_json:
        return None
    try:
        data = json.loads(token_json)
        creds = UserCredentials.from_authorized_user_info(data, GOOGLE_OAUTH_SCOPES)
        if not creds.valid and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            meta_set("google_user_token_json", creds.to_json())
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print("get_drive_service_user error:", e)
        return None

@app.route("/google_auth")
def google_auth():
    if not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and Flow):
        return "OAuth not configured", 400
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [OAUTH_REDIRECT_URI],
            }
        },
        scopes=GOOGLE_OAUTH_SCOPES,
    )
    flow.redirect_uri = OAUTH_REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    meta_set("google_oauth_state", state)
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    if not Flow:
        return "OAuth not configured", 400
    state = meta_get("google_oauth_state")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [OAUTH_REDIRECT_URI],
            }
        },
        scopes=GOOGLE_OAUTH_SCOPES,
        state=state,
    )
    flow.redirect_uri = OAUTH_REDIRECT_URI
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        return f"OAuth error: {e}", 400
    creds = flow.credentials
    # Sauvegarde complète (inclut refresh_token)
    meta_set("google_user_token_json", creds.to_json())
    return "Google Drive connected ✅ You can close this tab."




# ----------------- Run (optional for local dev) -----------------
if __name__ == "__main__":
    # For local runs (e.g., Replit). On Render, gunicorn (Procfile) is used instead.
    app.run(host="0.0.0.0", port=5000)
    # deployment

# --- Added env for webhook patch ---
STRAVA_VERIFY_TOKEN = os.environ.get("STRAVA_VERIFY_TOKEN", "dev-verify-token")
DB_PATH = os.environ.get("DB_PATH", "strava.db")
DATA_DIR = os.environ.get("DATA_DIR", "data")
if not os.path.isdir(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# === SQLite helpers for multi-user tokens ===
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                athlete_id INTEGER PRIMARY KEY,
                firstname TEXT,
                lastname TEXT,
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER
            );
            """
        )
        conn.commit()

# Initialize DB table if not exists
try:
    init_db()
except Exception as e:
    print("DB init warning:", e)

def save_user_token(athlete_dict, token_dict):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users (athlete_id, firstname, lastname, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                firstname=excluded.firstname,
                lastname=excluded.lastname,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at
            """,
            (
                athlete_dict.get("id"),
                athlete_dict.get("firstname"),
                athlete_dict.get("lastname"),
                token_dict.get("access_token"),
                token_dict.get("refresh_token"),
                token_dict.get("expires_at"),
            ),
        )
        conn.commit()

#meta table
def ensure_meta_table():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY,
            v TEXT
        );""")
        conn.commit()
try:
    ensure_meta_table()
except Exception as _e:
    print("meta table warn:", _e)

def meta_get(key, default=None):
    with get_db() as conn:
        cur = conn.execute("SELECT v FROM meta WHERE k=?", (key,))
        row = cur.fetchone()
    return row["v"] if row else default

def meta_set(key, value):
    with get_db() as conn:
        conn.execute("""INSERT INTO meta(k, v) VALUES(?,?)
                        ON CONFLICT(k) DO UPDATE SET v=excluded.v""", (key, value))
        conn.commit()

#other
def get_user(athlete_id: int):
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM users WHERE athlete_id=?", (athlete_id,))
        return cur.fetchone()

def refresh_if_needed(row):
    """Return a valid access_token for this athlete row, refreshing if needed."""
    if not row:
        return None
    now = int(time.time())
    exp = int(row["expires_at"]) if row["expires_at"] else 0
    if exp - 120 > now:
        return row["access_token"]
    # refresh
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": row["refresh_token"],
    }
    r = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    save_user_token({"id": row["athlete_id"]}, data)
    return data["access_token"]

# === Helpers: base URL and Strava streams ===
def get_base_url():
    if BASE_URL:
        return BASE_URL.rstrip("/")
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    return f"{scheme}://{request.host}"

def fetch_streams(access_token, activity_id, types=None):
    if types is None:
        types = [
            "time", "distance", "altitude", "velocity_smooth",
            "watts", "heartrate", "cadence", "grade_smooth", "temp"
        ]
    url = f"{STRAVA_API_BASE}/activities/{activity_id}/streams"
    params = {"keys": ",".join(types), "key_by_type": "true"}
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def save_streams_csv(athlete_id, activity_id, streams_json):
    # Align streams by index
    keys = [k for k, v in streams_json.items() if isinstance(v, dict) and "data" in v]
    if not keys:
        raise RuntimeError("No stream data returned — check activity privacy/scopes.")

    max_len = max(len(streams_json[k]["data"]) for k in keys)
    rows = []
    for i in range(max_len):
        row = {"idx": i}
        for k in keys:
            data = streams_json[k]["data"]
            row[k] = data[i] if i < len(data) else ""
        rows.append(row)

    # Save locally
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, f"{athlete_id}_{activity_id}.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # Upload to Google Drive if configured (still inside the function!)
    try:
        if 'upload_to_drive' in globals() and callable(upload_to_drive) and DRIVE_FOLDER_ID:
            fname = os.path.basename(out_path)
            drive_info = upload_to_drive(out_path, fname, "text/csv", DRIVE_FOLDER_ID)
            if isinstance(drive_info, dict):
                print(f"📤 Uploaded to Drive: {drive_info.get('webViewLink') or drive_info.get('id')}")
    except Exception as _e:
        print("Drive upload skipped/error:", _e)

    return out_path




# === Strava Webhook endpoints ===
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == STRAVA_VERIFY_TOKEN:
            return jsonify({"hub.challenge": challenge})
        return jsonify({"error": "Verification failed"}), 403

    try:
        event = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    if not event or event.get("object_type") != "activity":
        return jsonify({"ok": True})

    aspect = event.get("aspect_type")
    owner_id = event.get("owner_id")
    activity_id = event.get("object_id")

    if aspect == "create" and owner_id and activity_id:
        row = get_user(owner_id)
        token = refresh_if_needed(row)
        if token:
            try:
                streams = fetch_streams(token, activity_id)
                out_path = save_streams_csv(owner_id, activity_id, streams)
                print(f"✅ Saved streams → {out_path}")
            except Exception as e:
                print("⚠️ fetch/save error:", e)
        else:
            print("⚠️ No token stored for owner_id:", owner_id)
    return jsonify({"ok": True})

@app.route("/admin/create_subscription")
def create_subscription():
    base = get_base_url()
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "callback_url": f"{base}/webhook",
        "verify_token": STRAVA_VERIFY_TOKEN,
    }
    r = requests.post(f"{STRAVA_API_BASE}/push_subscriptions", data=payload, timeout=20)
    try:
        return r.json()
    except Exception:
        return {"status": r.status_code, "text": r.text[:2000]}

# --- Google Drive ENV ---
# If you *don't* have a Persistent Disk, enable Drive uploads:
# Set GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON or base64) and DRIVE_FOLDER_ID
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")  # target folder ID


# === Google Drive helpers ===
_drive_service_cache = None

def _parse_sa_json(sa_str):
    if not sa_str:
        return None
    sa_str = sa_str.strip()
    if sa_str.startswith("{"):
        return json.loads(sa_str)
    # assume base64-encoded
    try:
        decoded = base64.b64decode(sa_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None

def get_drive_service():
    global _drive_service_cache
    if _drive_service_cache is not None:
        return _drive_service_cache
    try:
        sa_info = _parse_sa_json(GOOGLE_SERVICE_ACCOUNT_JSON)
        if not sa_info:
            return None
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        _drive_service_cache = service
        return service
    except Exception as e:
        print("Drive init error:", e)
        return None

def upload_to_drive(local_path, filename, mimetype="text/csv", folder_id=None):
    """
    Try user OAuth first (Drive perso), fallback to Service Account if available.
    """
    # 1) User OAuth
    svc = get_drive_service_user()
    if svc:
        meta = {"name": filename}
        if folder_id:
            meta["parents"] = [folder_id]
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)
        try:
            file = svc.files().create(
                body=meta,
                media_body=media,
                fields="id, webViewLink, webContentLink, parents",
            ).execute()
            return file
        except Exception as e:
            print("Drive user upload error:", e)

    # 2) Fallback Service Account si tu gardes ce mode
    try:
        from google.oauth2 import service_account
        sa_ok = True
    except Exception:
        sa_ok = False

    if sa_ok and 'get_drive_service' in globals():
        svc_sa = get_drive_service()
        if svc_sa:
            meta = {"name": filename}
            if folder_id:
                meta["parents"] = [folder_id]
            media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)
            try:
                file = svc_sa.files().create(
                    body=meta,
                    media_body=media,
                    fields="id, webViewLink, webContentLink, parents",
                    # supportsAllDrives=True,  # active si Drive partagé
                ).execute()
                return file
            except Exception as e:
                print("Drive SA upload error:", e)

    return None

@app.route("/status")
def status():
    drive = bool(get_drive_service_user() or get_drive_service())
    user_oauth = bool(get_drive_service_user())
    sa_enabled = bool(get_drive_service())
    return {
        "ok": True,
        "drive_enabled": drive,
        "drive_user_oauth": user_oauth,
        "drive_service_account": sa_enabled,
        "drive_folder_id_set": bool(DRIVE_FOLDER_ID),
        "data_dir": DATA_DIR,
        "db_path": DB_PATH,
    }


# --- Optional FIT upload & summary (works with or without Drive) ---
from flask import request, jsonify

# Try to import fitparse for FIT decoding (optional)
try:
    from fitparse import FitFile
except Exception:
    FitFile = None

def parse_fit_summary(local_path):
    """
    Minimal FIT summary:
    - total time, total distance (if present)
    - laps count + basic lap times
    Returns dict. If fitparse not installed, returns {'parsed': False, 'reason': ...}
    """
    if FitFile is None:
        return {"parsed": False, "reason": "fitparse not installed"}

    try:
        fitfile = FitFile(local_path)
        fitfile.parse()

        total_timer = None
        total_dist = None
        laps = []
        # Attempt to read session + laps messages
        for msg in fitfile.get_messages():
            name = msg.name
            fields = {f.name: f.value for f in msg}
            if name == "session":
                total_timer = fields.get("total_timer_time")
                total_dist = fields.get("total_distance")
            elif name == "lap":
                laps.append({
                    "lap_time": fields.get("total_timer_time"),
                    "lap_dist": fields.get("total_distance"),
                    "avg_hr": fields.get("avg_heart_rate"),
                    "max_hr": fields.get("max_heart_rate"),
                    "avg_power": fields.get("avg_power"),
                    "max_power": fields.get("max_power"),
                })
        return {
            "parsed": True,
            "total_timer_s": total_timer,
            "total_distance_m": total_dist,
            "laps_count": len(laps),
            "laps": laps[:20],
        }
    except Exception as e:
        return {"parsed": False, "reason": str(e)}

@app.route("/upload_fit", methods=["GET", "POST"])
def upload_fit():
    if request.method == "GET":
        # Simple HTML form for manual upload
        return (
            "<h3>Upload FIT</h3>"
            "<form method='POST' enctype='multipart/form-data'>"
            "<input type='file' name='file' accept='.fit' required />"
            "<button type='submit'>Send</button>"
            "</form>"
        )

    # POST: receive file
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".fit"):
        return jsonify({"ok": False, "error": "Please provide a .fit file in 'file' field"}), 400

    # Save locally (temporary ok even without Persistent Disk)
    fname = f.filename
    local_path = os.path.join(DATA_DIR, fname)
    try:
        f.save(local_path)
    except Exception as e:
        # fallback to /tmp if DATA_DIR not writable
        local_path = os.path.join("/tmp", fname)
        f.save(local_path)

    # Upload to Google Drive if configured
    drive_file = None
    try:
        if 'upload_to_drive' in globals() and callable(upload_to_drive) and DRIVE_FOLDER_ID:
            drive_file = upload_to_drive(local_path, fname, "application/octet-stream", DRIVE_FOLDER_ID)
    except Exception as _e:
        print("Drive upload error:", _e)

    # Optional: quick parse summary
    summary = parse_fit_summary(local_path)

    return jsonify({
        "ok": True,
        "saved_local": local_path,
        "drive_file": drive_file if isinstance(drive_file, dict) else None,
        "fit_summary": summary,
        "hint": "If you want deeper analysis, I can run an interval detection on this file."
    })
