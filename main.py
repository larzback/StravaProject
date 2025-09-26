import os, time, datetime, math, requests
from collections import defaultdict
from flask import Flask, request, redirect, session, url_for

# ----------------- App & Config -----------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev")

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = os.environ["STRAVA_REDIRECT_URI"]

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


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
    """Récupère toutes les activités entre deux dates (UTC) en paginant."""
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
    return f"""<!doctype html><html lang="fr"><head>
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
.wrap{{max-width:1024px;margin:0 auto}}
.card{{
  background:linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
  border:1px solid var(--line); border-radius:20px; padding:22px 20px;
  box-shadow:0 10px 40px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.04);
  backdrop-filter: blur(6px);
}}
.title{{font-size:30px;font-weight:800;margin:0 0 8px}}
.subtitle{{color:var(--muted);margin:0 0 18px;line-height:1.55}}
.row{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 6px}}
.pill{{font-size:12px;color:#e2e8f0;background:#0f172a;border:1px solid var(--line);padding:8px 12px;border-radius:999px}}
.btn{{
  appearance:none;border:0;border-radius:12px;padding:14px 18px;font-weight:800;font-size:15px;
  background:linear-gradient(180deg, var(--btn), var(--btnH)); color:white; cursor:pointer;
  box-shadow:0 8px 24px rgba(249,115,22,.35); transition:transform .05s ease, box-shadow .2s ease;
}}
.btn:hover{{box-shadow:0 10px 32px rgba(249,115,22,.5)}} .btn:active{{transform:translateY(1px)}}
.links{{display:flex;gap:14px;margin-top:10px;flex-wrap:wrap}}
.a{{color:#93c5fd;text-decoration:none;font-weight:600}} .a:hover{{text-decoration:underline}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}}
.k{{font-size:26px;font-weight:800}} .l{{color:var(--muted);font-size:13px}}
table{{width:100%; border-collapse:collapse; margin-top:8px}}
th,td{{padding:8px 6px; border-bottom:1px solid var(--line); text-align:left; font-size:14px}}
.badge{{display:inline-block;background:#0b1220;border:1px solid var(--line);padding:4px 8px;border-radius:8px;font-size:12px}}
.note{{color:#86efac;font-weight:600;margin-top:8px}}
.small{{font-size:12px;color:var(--muted)}}
</style></head><body><div class="wrap">"""


def html_foot():
    return "</div></body></html>"


# ----------------- Routes -----------------
@app.route("/")
def home():
    connected = "access_token" in session

    if not connected:
        return html_head("Projet Strava – Lara") + """
        <div class="card">
          <h1 class="title">Bienvenue sur le premier projet de Lara 🚀</h1>
          <p class="subtitle">Connecte ton compte Strava pour afficher un mini‑dashboard (activités, <b>Stats 2025</b>, tops).</p>
          <div class="row">
            <span class="pill">Flask</span><span class="pill">Strava API</span><span class="pill">OAuth2</span>
          </div>
          <form action="/connect" method="get" style="margin-top:16px">
            <button class="btn" type="submit">🚴 Se connecter avec Strava</button>
          </form>
          <div class="note">✓ Auth en session locale, rien n'est stocké côté serveur</div>
        </div>
        """ + html_foot()

    # connecté : menu visible, sans bouton de connexion
    return html_head("Strava – Lara (connectée)") + """
    <div class="card">
      <h1 class="title">Hello Lara ✨</h1>
      <p class="subtitle">Tu es connectée. Accède au profil, aux activités et à la page <b>Stats 2025</b>.</p>
      <div class="links">
        <a class="a" href="/me">Profil</a>
        <a class="a" href="/activities">Dernières activités</a>
        <a class="a" href="/stats-2025">📊 Stats 2025</a>
        <a class="a" href="/logout">Se déconnecter</a>
      </div>
      <div class="row" style="margin-top:14px">
        <span class="pill">Connectée ✅</span><span class="pill">Dashboard</span><span class="pill">2025</span>
      </div>
    </div>
    """ + html_foot()


@app.route("/connect")
def connect():
    # Étend les scopes pour tout récupérer (activités privées comprises)
    scope = "read,activity:read,activity:read_all"

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope
    }

    # Construction de l'URL d'auth Strava
    query_string = "&".join(f"{k}={requests.utils.quote(v)}"
                            for k, v in params.items())
    auth_url = f"{STRAVA_AUTH_URL}?{query_string}"

    # DEBUG — impression console
    print("🔍 DEBUG — Strava Auth")
    print("Client ID :", CLIENT_ID)
    print("Redirect URI :", REDIRECT_URI)
    print("URL générée :", auth_url)

    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erreur : aucun code reçu de Strava.", 400
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    }
    r = requests.post(STRAVA_TOKEN_URL, data=data, timeout=20)
    if r.status_code != 200:
        return f"Erreur token Strava : {r.text}", 400
    tok = r.json()
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
        return f"Erreur API /athlete: {r.text}", 400
    a = r.json()
    return html_head("Profil Strava") + f"""
    <div class="card">
      <h1 class="title">Profil Strava</h1>
      <p class="subtitle small">ID: {a.get('id')} — {a.get('firstname','')} {a.get('lastname','')}</p>
      <pre class="small" style="white-space:pre-wrap">{a}</pre>
      <div class="links"><a class="a" href="/">← Retour</a></div>
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
        return f"Erreur API /athlete/activities: {r.text}", 400
    acts = r.json()

    items = ""
    for a in acts:
        link = strava_activity_link(a.get("id"))
        dist = km(a.get("distance", 0))
        elev = int(a.get("total_elevation_gain", 0) or 0)
        mt = fmt_hms(a.get("moving_time", 0))
        name = a.get("name", "(sans titre)")
        sport = a.get("sport_type") or a.get("type") or "Other"
        items += f"<tr><td><a class='a' href='{link}' target='_blank'>{name}</a></td><td class='badge'>{sport}</td><td>{dist} km</td><td>{elev} m</td><td>{mt}</td></tr>"

    return html_head("Dernières activités") + f"""
    <div class="card">
      <h1 class="title">Dernières activités</h1>
      <table>
        <thead><tr><th>Nom</th><th>Sport</th><th>Distance</th><th>D+</th><th>Temps</th></tr></thead>
        <tbody>{items or "<tr><td colspan='5'>Aucune activité.</td></tr>"}</tbody>
      </table>
      <div class="links"><a class="a" href="/">← Retour</a></div>
    </div>
    """ + html_foot()


@app.route("/stats-2025")
def stats_2025():
    if "access_token" not in session:
        return redirect(url_for("home"))
    token = session["access_token"]

    # Fenêtre 2025 (UTC)
    start = datetime.datetime(2025, 1, 1)
    end = datetime.datetime(2026, 1, 1)

    acts = get_activities_between(token, start, end)

    # Agrégations globales
    total_dist = sum((a.get("distance") or 0) for a in acts)
    total_elev = sum((a.get("total_elevation_gain") or 0) for a in acts)
    total_time = sum((a.get("moving_time") or 0) for a in acts)
    n = len(acts)

    # Par type
    by_type = defaultdict(lambda: {
        "dist": 0.0,
        "elev": 0.0,
        "time": 0,
        "count": 0
    })
    active_days = set()
    longest = None
    biggest_elev = None
    fastest_avg = None  # meilleure moyenne (>=5km)

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

    # Tops (distance / D+ / vitesse moyenne >= 5 km)
    top_by_distance = sorted(acts,
                             key=lambda x: x.get("distance") or 0,
                             reverse=True)[:5]
    top_by_elev = sorted(acts,
                         key=lambda x: x.get("total_elevation_gain") or 0,
                         reverse=True)[:5]

    # vitesse moyenne en km/h (>= 5 km)
    def avg_kmh(a):
        d = a.get("distance") or 0
        mt = a.get("moving_time") or 0
        if d < 5000 or mt <= 0:
            return 0.0
        return (d / mt) * 3.6

    top_by_speed = sorted(acts, key=lambda x: avg_kmh(x), reverse=True)[:5]

    # Tableaux HTML
    def rows_by_type():
        out = ""
        for t, agg in sorted(by_type.items(), key=lambda kv: -kv[1]["dist"]):
            out += f"<tr><td class='badge'>{t}</td><td>{agg['count']}</td><td>{km(agg['dist'])} km</td><td>{int(agg['elev'])} m</td><td>{fmt_hms(agg['time'])}</td></tr>"
        return out or "<tr><td colspan='5'>Aucune activité 2025.</td></tr>"

    def rows_top(acts_list, metric):
        out = ""
        for a in acts_list:
            name = a.get("name", "(sans titre)")
            link = strava_activity_link(a.get("id"))
            if metric == "distance":
                val = f"{km(a.get('distance',0))} km"
            elif metric == "elev":
                val = f"{int(a.get('total_elevation_gain',0) or 0)} m"
            else:  # speed
                v = round(avg_kmh(a), 2)
                val = f"{v} km/h"
            out += f"<tr><td><a class='a' target='_blank' href='{link}'>{name}</a></td><td>{val}</td></tr>"
        return out or "<tr><td colspan='2'>Aucune donnée.</td></tr>"

    # Records
    long_html = "-" if not longest else f"<a class='a' target='_blank' href='{strava_activity_link(longest.get('id'))}'>{longest.get('name','(sans titre)')}</a> — {km(longest.get('distance',0))} km"
    climb_html = "-" if not biggest_elev else f"<a class='a' target='_blank' href='{strava_activity_link(biggest_elev.get('id'))}'>{biggest_elev.get('name','(sans titre)')}</a> — {int(biggest_elev.get('total_elevation_gain',0))} m D+"
    fast_html = "-"
    if fastest_avg:
        v_kmh = round(fastest_avg["v"] * 3.6, 2)
        act = fastest_avg["act"]
        fast_html = f"<a class='a' target='_blank' href='{strava_activity_link(act.get('id'))}'>{act.get('name','(sans titre)')}</a> — {v_kmh} km/h (≥5 km)"

    # Render
    html = html_head("Stats 2025 – Lara") + f"""
    <div class="card">
      <h1 class="title">📊 Stats 2025</h1>
      <p class="subtitle">Période : 01.01.2025 → 31.12.2025</p>

      <div class="grid">
        <div class="card"><div class="k">{km(total_dist)} km</div><div class="l">Distance totale</div></div>
        <div class="card"><div class="k">{int(total_elev)} m</div><div class="l">Dénivelé positif</div></div>
        <div class="card"><div class="k">{fmt_hms(total_time)}</div><div class="l">Temps de déplacement</div></div>
        <div class="card"><div class="k">{n}</div><div class="l">Nombre d'activités</div></div>
        <div class="card"><div class="k">{days_active}</div><div class="l">Jours actifs</div></div>
        <div class="card"><div class="k">{round(avg_km_per_day,2)}</div><div class="l">Km moyen / jour actif</div></div>
      </div>

      <div class="grid">
        <div class="card"><div class="k" style="font-size:18px">Plus longue sortie</div><div class="l">{long_html}</div></div>
        <div class="card"><div class="k" style="font-size:18px">Plus gros D+</div><div class="l">{climb_html}</div></div>
        <div class="card"><div class="k" style="font-size:18px">Meilleure vitesse moyenne</div><div class="l">{fast_html}</div></div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top distance (5)</div>
          <table><tbody>{rows_top(top_by_distance, "distance")}</tbody></table>
        </div>
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top D+ (5)</div>
          <table><tbody>{rows_top(top_by_elev, "elev")}</tbody></table>
        </div>
        <div class="card">
          <div class="k" style="font-size:18px;margin-bottom:6px">Top vitesse moy. (5)</div>
          <table><tbody>{rows_top(top_by_speed, "speed")}</tbody></table>
        </div>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="k" style="font-size:18px;margin-bottom:8px">Par sport</div>
        <table>
          <thead><tr><th>Sport</th><th>#</th><th>Distance</th><th>D+</th><th>Temps</th></tr></thead>
          <tbody>{rows_by_type()}</tbody>
        </table>
      </div>

      <div class="links" style="margin-top:10px"><a class="a" href="/">← Retour</a></div>
    </div>
    """
    return html + html_foot()


# ----------------- Run -----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    #deploiement
