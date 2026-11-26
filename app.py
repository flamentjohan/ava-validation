"""AVA - Application de suivi de validation de propositions de projet."""
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (Flask, flash, g, redirect, render_template, request,
                   send_file, url_for)

from mailer import send_validation_email, send_final_confirmation


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / os.environ.get("AVA_DB_PATH", "ava.db")

UPS = ["A2", "DELVERT", "FAISSOLE", "FILET BLEU", "FOURNIL", "KERLYS",
       "MLC", "MSA", "MSB", "MSP", "SOLARYS"]
INTERNAL_AGRO_ROLES = ["Développeur", "Directeur commercial", "Adhérent"]
ITMAI_ROLES = ["Acheteur", "Responsable marketing", "CEQ"]
VALIDATOR_STATUSES = ["en_attente", "mail_envoye", "valide", "refuse"]
PROJECT_STATUSES = ["phase_interne", "phase_externe", "valide", "refuse"]

app = Flask(__name__)
app.secret_key = os.environ.get("AVA_SECRET_KEY", secrets.token_hex(32))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            creator_name TEXT NOT NULL,
            creator_email TEXT NOT NULL,
            up TEXT NOT NULL,
            description TEXT NOT NULL,
            launch_delay_months INTEGER NOT NULL,
            total_gain TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'phase_interne',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS validators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            grp TEXT NOT NULL,
            role TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'en_attente',
            sent_at TEXT,
            answered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS emails_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            mime TEXT NOT NULL,
            data BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    _ensure_column(db, "validators", "sent_at", "TEXT")
    db.commit()
    db.close()


def _ensure_column(db, table, column, decl):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


init_db()


def validator_status_label(status):
    return {"en_attente": "En attente d'envoi",
            "mail_envoye": "En attente de validation",
            "valide": "Validé",
            "refuse": "Refusé"}.get(status, status)


def project_status_label(status):
    return {"phase_interne": "Validation interne en cours",
            "phase_externe": "Validation ITMAI en cours",
            "valide": "Projet validé",
            "refuse": "Projet refusé"}.get(status, status)


def record_email(db, project_id, recipient, subject, body, error=None):
    db.execute(
        "INSERT INTO emails_log (project_id, recipient, subject, body,"
        " sent_at, delivered, error) VALUES (?,?,?,?,?,?,?)",
        (project_id, recipient, subject, body,
         datetime.now().isoformat(timespec="seconds"),
         0 if error else 1, error),
    )


def notify_group(db, project, group):
    validators = db.execute(
        "SELECT * FROM validators WHERE project_id=? AND grp=? AND"
        " email<>'' ORDER BY id", (project["id"], group)).fetchall()
    base_url = request.url_root.rstrip("/")
    now = datetime.now().isoformat(timespec="seconds")
    for v in validators:
        if v["status"] != "en_attente":
            continue
        link = f"{base_url}{url_for('validate', token=v['token'])}"
        body = render_template("email_validation.md", project=project,
                               validator=v, link=link)
        error = send_validation_email(v["email"], body, link)
        record_email(db, project["id"], v["email"],
                     "Vous avez un projet AVA à valider", body, error)
        if error:
            flash(f"Mail non délivré à {v['email']} : {error}", "warning")
        db.execute(
            "UPDATE validators SET status='mail_envoye', sent_at=? WHERE id=?",
            (now, v["id"]))


def parse_gain(value):
    if not value:
        return 0.0
    cleaned = re.sub(r"[^\d.,-]", "", str(value)).replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def participants(db, project_id, group):
    return [v for v in db.execute(
        "SELECT * FROM validators WHERE project_id=? AND grp=? ORDER BY id",
        (project_id, group)).fetchall() if v["email"]]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/test")
def test_page():
    return render_template("test.html", url=request.host_url.rstrip("/"))


@app.route("/nouveau-projet", methods=["GET", "POST"])
def new_project():
    if request.method == "POST":
        form = request.form
        errors = []
        if not form.get("name", "").strip():
            errors.append("Le nom du projet est obligatoire.")
        rows = []
        for group, roles in (("interne_agro", INTERNAL_AGRO_ROLES),
                             ("itmai", ITMAI_ROLES)):
            for role in roles:
                email = form.get(f"{group}__{role}__email", "").strip()
                first = form.get(f"{group}__{role}__first_name", "").strip()
                last = form.get(f"{group}__{role}__last_name", "").strip()
                if first or last or email:
                    rows.append((group, role, first, last, email))
        if not any(r[0] == "interne_agro" and r[4] for r in rows):
            errors.append("Indiquez au moins un valideur interne Agro "
                          "(avec son adresse mail).")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("new_project.html", form=request.form,
                                   ups=UPS, internal_roles=INTERNAL_AGRO_ROLES,
                                   itmai_roles=ITMAI_ROLES), 400

        with get_db() as db:
            cur = db.execute(
                "INSERT INTO projects (name, date, creator_name, creator_email,"
                " up, description, launch_delay_months, total_gain, status,"
                " created_at) VALUES (?,?,?,?,?,?,?,?, 'phase_interne', ?)",
                (form.get("name", "").strip(),
                 form.get("date", "").strip() or datetime.now().strftime("%Y-%m-%d"),
                 form.get("creator_name", "").strip(),
                 form.get("creator_email", "").strip(),
                 form.get("up", "").strip(),
                 form.get("description", "").strip(),
                 form.get("launch_delay_months", "0") or 0,
                 form.get("total_gain", "").strip(),
                 datetime.now().isoformat(timespec="seconds")))
            project_id = cur.lastrowid
            for group, role, first, last, email in rows:
                db.execute(
                    "INSERT INTO validators (project_id, grp, role, first_name,"
                    " last_name, email, token, status) VALUES (?,?,?,?,?,?,?,"
                    "'en_attente')",
                    (project_id, group, role, first, last, email,
                     secrets.token_urlsafe(24)))
            ids = [i for i in re.split(r"[^\d]+",
                                       form.get("image_ids", "")) if i]
            for i in ids:
                db.execute("UPDATE images SET project_id=? WHERE id=?",
                           (project_id, i))
            project = db.execute("SELECT * FROM projects WHERE id=?",
                                 (project_id,)).fetchone()
            notify_group(db, project, "interne_agro")
        flash("La fiche projet a été validée. Un mail de validation a été "
              "envoyé aux valideurs internes Agro.", "success")
        return redirect(url_for("dashboard"))

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("new_project.html", form={"date": today},
                           ups=UPS, internal_roles=INTERNAL_AGRO_ROLES,
                           itmai_roles=ITMAI_ROLES)


@app.route("/api/upload-image", methods=["POST"])
def upload_image():
    data = request.get_json(silent=True) or {}
    src = data.get("data", "")
    m = re.match(r"data:(image/[\w.+-]+);base64,(.+)", src, re.S)
    if not m:
        return {"error": "image invalide"}, 400
    import base64
    try:
        blob = base64.b64decode(m.group(2))
    except Exception:
        return {"error": "image illisible"}, 400
    if len(blob) > 8 * 1024 * 1024:
        return {"error": "image trop volumineuse (max 8 Mo)"}, 400
    db = get_db()
    with db:
        cur = db.execute(
            "INSERT INTO images (project_id, mime, data, created_at)"
            " VALUES (NULL, ?, ?, ?)",
            (m.group(1), blob,
             datetime.now().isoformat(timespec="seconds")))
    return {"id": cur.lastrowid}


@app.route("/images/<int:image_id>")
def image_file(image_id):
    db = get_db()
    img = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if img is None:
        return "", 404
    from io import BytesIO
    return send_file(BytesIO(img["data"]), mimetype=img["mime"])


@app.route("/valider/<token>", methods=["GET", "POST"])
def validate(token):
    db = get_db()
    v = db.execute("SELECT * FROM validators WHERE token=?",
                   (token,)).fetchone()
    if v is None:
        return render_template("validate.html",
                               error="Lien de validation invalide."), 404

    if request.method == "POST":
        choice = request.form.get("choice")
        if choice not in ("oui", "non"):
            flash("Veuillez choisir OUI ou NON.", "danger")
            return redirect(url_for("validate", token=token))
        new_status = "valide" if choice == "oui" else "refuse"
        with db:
            db.execute(
                "UPDATE validators SET status=?, answered_at=? WHERE id=?",
                (new_status, datetime.now().isoformat(timespec="seconds"),
                 v["id"]))
            project = db.execute("SELECT * FROM projects WHERE id=?",
                                 (v["project_id"],)).fetchone()
            if new_status == "refuse":
                db.execute("UPDATE projects SET status='refuse' WHERE id=?",
                           (project["id"],))
            else:
                pending = db.execute(
                    "SELECT COUNT(*) c FROM validators WHERE project_id=? AND"
                    " grp='interne_agro' AND email<>'' AND status<>'valide'",
                    (project["id"],)).fetchone()["c"]
                external = [x for x in db.execute(
                    "SELECT * FROM validators WHERE project_id=? AND grp='itmai'",
                    (project["id"],)).fetchall() if x["email"]]
                external_validated = sum(1 for x in external
                                         if x["status"] == "valide")
                if pending == 0 and project["status"] == "phase_interne":
                    if external and external_validated < len(external):
                        db.execute(
                            "UPDATE projects SET status='phase_externe'"
                            " WHERE id=?", (project["id"],))
                        notify_group(db, project, "itmai")
                        flash("Merci ! Les valideurs internes ont validé. "
                              "Les valideurs ITMAI viennent d'être notifiés.",
                              "success")
                    else:
                        finalize(db, project)
                elif (pending == 0 and project["status"] == "phase_externe"
                      and external
                      and external_validated == len(external)):
                    finalize(db, project)
                elif choice == "non":
                    flash("Votre refus a été enregistré.", "warning")
                else:
                    flash("Merci pour votre validation.", "success")
        return redirect(url_for("validate", token=token))

    project = db.execute(
        """SELECT p.name, p.date AS proj_date, p.creator_name, p.creator_email,
                  p.up, p.description, p.launch_delay_months, p.total_gain,
                  p.status
             FROM validators v JOIN projects p ON p.id = v.project_id
            WHERE v.token = ?""",
        (token,)).fetchone()
    if project is None:
        return render_template("validate.html",
                               error="Lien de validation invalide."), 404
    images = db.execute(
        "SELECT id FROM images WHERE project_id=? ORDER BY id",
        (v["project_id"],)).fetchall()
    return render_template("validate.html", project=project, validator=v,
                           images=images,
                           already=v["status"] in ("valide", "refuse"))


def finalize(db, project):
    db.execute("UPDATE projects SET status='valide' WHERE id=?",
               (project["id"],))
    link = f"{request.url_root.rstrip('/')}{url_for('dashboard')}"
    body = (f"Bonjour {project['creator_name']},\n\n"
            f"Le projet \"{project['name']}\" a été validé par l'ensemble des "
            "valideurs internes Agro et externes ITMAI.\n\n"
            f"Vous pouvez le consulter dans le tableau de pilotage : {link}\n\n"
            "-- Application AVA")
    error = send_final_confirmation(project["creator_email"], body)
    record_email(db, project["id"], project["creator_email"],
                 "Votre projet AVA est validé", body, error)


def _projects_with_validators(db, archived):
    projects = db.execute(
        "SELECT * FROM projects WHERE archived=? ORDER BY created_at DESC",
        (archived,)).fetchall()
    grouped = {}
    for v in db.execute("SELECT * FROM validators ORDER BY id").fetchall():
        if v["email"] == "" and v["first_name"] == "" and v["last_name"] == "":
            continue
        grouped.setdefault(v["project_id"], []).append(v)
    return projects, grouped


@app.route("/tableau-de-pilotage")
def dashboard():
    db = get_db()
    projects, grouped = _projects_with_validators(db, 0)
    return render_template("dashboard.html", projects=projects,
                           validators_by_project=grouped,
                           status_label=validator_status_label,
                           project_status_label=project_status_label)


@app.route("/archives")
def archives():
    db = get_db()
    projects, grouped = _projects_with_validators(db, 1)
    return render_template("archives.html", projects=projects,
                           validators_by_project=grouped,
                           status_label=validator_status_label,
                           project_status_label=project_status_label)


@app.route("/projet/<int:project_id>/modifier", methods=["GET", "POST"])
def edit_project(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id=?",
                         (project_id,)).fetchone()
    if project is None:
        flash("Projet introuvable.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        form = request.form
        with db:
            db.execute(
                """UPDATE projects SET name=?, date=?, up=?, creator_name=?,
                       creator_email=?, description=?, launch_delay_months=?,
                       total_gain=?, status=?, archived=?
                    WHERE id=?""",
                (form.get("name", "").strip(),
                 form.get("date", "").strip(),
                 form.get("up", "").strip(),
                 form.get("creator_name", "").strip(),
                 form.get("creator_email", "").strip(),
                 form.get("description", "").strip(),
                 form.get("launch_delay_months", "0") or 0,
                 form.get("total_gain", "").strip(),
                 form.get("status", "phase_interne"),
                 1 if form.get("archived") == "on" else 0,
                 project_id))
            for v in db.execute(
                    "SELECT * FROM validators WHERE project_id=?",
                    (project_id,)).fetchall():
                p = f"v{v['id']}"
                db.execute(
                    """UPDATE validators SET first_name=?, last_name=?,
                           email=?, status=?, sent_at=?, answered_at=?
                        WHERE id=?""",
                    (form.get(f"{p}__first_name", "").strip(),
                     form.get(f"{p}__last_name", "").strip(),
                     form.get(f"{p}__email", "").strip(),
                     form.get(f"{p}__status", v["status"]),
                     form.get(f"{p}__sent_at", "").strip() or None,
                     form.get(f"{p}__answered_at", "").strip() or None,
                     v["id"]))
        flash("Modifications enregistrées.", "success")
        return redirect(url_for("dashboard"))

    _, grouped = _projects_with_validators(db, 0)
    validators = [v for v in db.execute(
        "SELECT * FROM validators WHERE project_id=? ORDER BY id",
        (project_id,)).fetchall()
        if v["email"] or v["first_name"] or v["last_name"]]
    images = db.execute(
        "SELECT id FROM images WHERE project_id=? ORDER BY id",
        (project_id,)).fetchall()
    return render_template("edit_project.html", project=project, ups=UPS,
                           validators=validators,
                           internal_roles=INTERNAL_AGRO_ROLES,
                           itmai_roles=ITMAI_ROLES,
                           validator_statuses=VALIDATOR_STATUSES,
                           project_statuses=PROJECT_STATUSES,
                           status_label=validator_status_label,
                           images=images)


@app.post("/projet/<int:project_id>/edition-rapide")
def quick_edit(project_id):
    db = get_db()
    with db:
        for v in db.execute(
                "SELECT * FROM validators WHERE project_id=?",
                (project_id,)).fetchall():
            p = f"v{v['id']}"
            status = request.form.get(f"{p}__status")
            if status is None:
                continue
            name = request.form.get(f"{p}__name", "").strip()
            parts = name.split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:])
            answered = request.form.get(f"{p}__answered_at", "").strip()
            if status in ("en_attente", "mail_envoye") and not answered:
                answered = None
            db.execute(
                """UPDATE validators SET first_name=?, last_name=?, email=?,
                       status=?, answered_at=? WHERE id=?""",
                (first, last,
                 request.form.get(f"{p}__email", "").strip(),
                 status, answered, v["id"]))
        project = db.execute("SELECT * FROM projects WHERE id=?",
                             (project_id,)).fetchone()
        refused = db.execute(
            "SELECT COUNT(*) c FROM validators WHERE project_id=? AND "
            "status='refuse'", (project_id,)).fetchone()["c"]
        if refused:
            db.execute("UPDATE projects SET status='refuse' WHERE id=?",
                       (project_id,))
        elif project["status"] != "refuse":
            pending = db.execute(
                "SELECT COUNT(*) c FROM validators WHERE project_id=? AND "
                "grp='interne_agro' AND email<>'' AND status<>'valide'",
                (project_id,)).fetchone()["c"]
            external = [x for x in db.execute(
                "SELECT * FROM validators WHERE project_id=? AND grp='itmai'",
                (project_id,)).fetchall() if x["email"]]
            validated_ext = sum(1 for x in external if x["status"] == "valide")
            if pending == 0 and project["status"] == "phase_interne":
                if external and validated_ext < len(external):
                    db.execute("UPDATE projects SET status='phase_externe' "
                               "WHERE id=?", (project_id,))
                    notify_group(db, project, "itmai")
                    flash("Tous les valideurs internes ont validé : les "
                          "valideurs ITMAI viennent d'être notifiés.",
                          "success")
                else:
                    finalize(db, project)
            elif (pending == 0 and project["status"] == "phase_externe"
                  and external and validated_ext == len(external)):
                finalize(db, project)
    flash("Modifications enregistrées.", "success")
    return redirect(url_for("dashboard"))


@app.route("/rapport")
def rapport():
    mois = request.args.get("mois", type=int)
    if mois not in (12, 24):
        return render_template("rapport_selection.html")
    from rapport_pdf import build_pdf
    pdf = build_pdf(get_db(), mois)
    return send_file(pdf, mimetype="application/pdf",
                     download_name=f"dashboard_AVAA_{mois}mois.pdf",
                     as_attachment=True)


@app.route("/projet/<int:project_id>")
def project_detail(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id=?",
                         (project_id,)).fetchone()
    if project is None:
        flash("Projet introuvable.", "danger")
        return redirect(url_for("dashboard"))
    validators = db.execute(
        "SELECT * FROM validators WHERE project_id=? AND "
        "(email<>'' OR first_name<>'' OR last_name<>'') ORDER BY id",
        (project_id,)).fetchall()
    images = db.execute(
        "SELECT id FROM images WHERE project_id=? ORDER BY id",
        (project_id,)).fetchall()
    return render_template("project_detail.html", project=project,
                           validators=validators, images=images,
                           status_label=validator_status_label,
                           project_status_label=project_status_label)


@app.post("/projet/<int:project_id>/archiver")
def archive_project(project_id):
    with get_db() as db:
        db.execute("UPDATE projects SET archived=1 WHERE id=?", (project_id,))
    flash("Le projet a été archivé.", "success")
    return redirect(url_for("dashboard"))


@app.post("/projet/<int:project_id>/desarchiver")
def unarchive_project(project_id):
    with get_db() as db:
        db.execute("UPDATE projects SET archived=0 WHERE id=?", (project_id,))
    flash("Le projet a été désarchivé.", "success")
    return redirect(url_for("archives"))


@app.post("/projet/<int:project_id>/supprimer")
def delete_project(project_id):
    from_url = request.form.get("from", "dashboard")
    with get_db() as db:
        db.execute("DELETE FROM images WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM validators WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM emails_log WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    flash("Le projet a été supprimé définitivement.", "success")
    return redirect(url_for("archives" if from_url == "archives"
                            else "dashboard"))


@app.route("/projets/<int:project_id>/emails")
def project_emails(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id=?",
                         (project_id,)).fetchone()
    if project is None:
        flash("Projet introuvable.", "danger")
        return redirect(url_for("dashboard"))
    emails = db.execute(
        "SELECT * FROM emails_log WHERE project_id=? ORDER BY sent_at",
        (project_id,)).fetchall()
    return render_template("emails.html", project=project, emails=emails)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("AVA_PORT", "5000")),
            debug=os.environ.get("AVA_DEBUG") == "1")
