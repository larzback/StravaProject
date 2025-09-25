import os, requests
from flask import Flask, request, redirect, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev")

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = os.environ["STRAVA_REDIRECT_URI"]

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

@app.route("/")
def home():
    if "access_token" in session:
        return '''
            <h1>Connectée à Strava ✅</h1>
            <p><a href="/me">Voir mes infos</a></p>
            <p><a href="/activities">Voir mes activités</a></p>
            <p><a href="/logout">Se déconnecter</a></p>
        '''
    return '''
        <h1>Bienvenue !</h1>
        <a href="/connect">Se connecter avec Strava</a>
    '''

@app.route("/connect")
def connect():
    scope = "read,activity:read"
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope
    }
    # Utilisation de requests pour construire l'URL avec les paramètres encodés
    r = requests.Request('GET', STRAVA_AUTH_URL, params=params)
    prepared = r.prepare()
    
    # Debug : affichons les informations pour vérifier
    print(f"CLIENT_ID: {CLIENT_ID}")
    print(f"REDIRECT_URI: {REDIRECT_URI}")
    print(f"URL générée: {prepared.url}")
    
    return redirect(prepared.url or STRAVA_AUTH_URL)

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
    r = requests.post(STRAVA_TOKEN_URL, data=data, timeout=15)
    if r.status_code != 200:
        return f"Erreur lors de la récupération du token : {r.text}", 400

    tok = r.json()
    session["access_token"] = tok["access_token"]
    session["athlete"] = tok.get("athlete", {})
    return redirect(url_for("home"))

@app.route("/me")
def me():
    if "access_token" not in session:
        return redirect(url_for("home"))
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    r = requests.get(f"{STRAVA_API_BASE}/athlete", headers=headers, timeout=15)
    if r.status_code != 200:
        return f"Erreur API /athlete: {r.text}", 400
    a = r.json()
    return f"<h2>Profil Strava</h2><pre>{a}</pre><p><a href='/'>Retour</a></p>"

@app.route("/activities")
def activities():
    if "access_token" not in session:
        return redirect(url_for("home"))
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    r = requests.get(f"{STRAVA_API_BASE}/athlete/activities?per_page=5", headers=headers, timeout=15)
    if r.status_code != 200:
        return f"Erreur API /athlete/activities: {r.text}", 400
    acts = r.json()
    html = "<h2>Mes 5 dernières activités</h2><ul>"
    for act in acts:
        km = round(act.get("distance", 0)/1000, 2)
        html += f"<li>{act.get('name')} — {km} km — D+ {act.get('total_elevation_gain', 0)} m</li>"
    html += "</ul><p><a href='/'>Retour</a></p>"
    return html

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)