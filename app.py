"""AVA - Application de suivi de validation de propositions de projet."""
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)

from mailer import send_validation_email, send_final_confirmation


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / os.environ.get("AVA_DB_PATH", "ava.db")

INTERNAL_AGRO_ROLES = ["Développeur", "Directeur commercial", "Adhérent"]
ITMAI_ROLES = ["Acheteur", "Responsable marketing", "CEQ"]

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
        """
    )
    db.commit()
    db.close()


init_db()


def validator_status_label(status):
    return {"en_attente": "En attente d'envoi",
            "mail_envoye": "En attente de validation",
            "valide": "Validé",
            "refuse": "Refusé"}.get(status, status)


def record_email(db, project_id, recipient, subject, body, error=None):
    db.execute(
        "INSERT INTO emails_log (project_id, recipient, subject, body, sent_at,"
        " delivered, error) VALUES (?,?,?,?,?,?,?)",
        (project_id, recipient, subject, body,
         datetime.now().isoformat(timespec="seconds"),
         0 if error else 1, error),
    )


def notify_group(db, project, group):
    validators = db.execute(
        "SELECT * FROM validators WHERE project_id=? AND grp=? ORDER BY id",
        (project["id"], group)).fetchall()
    base_url = request.url_root.rstrip("/")
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
            flash(f"Impossible d'envoyer le mail à {v['email']} : {error}",
                  "warning")
        db.execute(
            "UPDATE validators SET status='mail_envoye' WHERE id=?",
            (v["id"],))


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
        if not form.get("creator_email", "").strip():
            errors.append("L'adresse mail du créateur est obligatoire.")
        validator_rows = []
        for group, roles in (("interne_agro", INTERNAL_AGRO_ROLES),
                             ("itmai", ITMAI_ROLES)):
            for role in roles:
                email = form.get(f"{group}__{role}__email", "").strip()
                if not email:
                    errors.append(
                        f"Adresse mail manquante pour {role} ({'Agro' if group == 'interne_agro' else 'ITMAI'}).")
                validator_rows.append((group, role,
                                       form.get(f"{group}__{role}__first_name", "").strip(),
                                       form.get(f"{group}__{role}__last_name", "").strip(),
                                       email))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("new_project.html", form=request.form,
                                   internal_roles=INTERNAL_AGRO_ROLES,
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
            for group, role, first, last, email in validator_rows:
                db.execute(
                    "INSERT INTO validators (project_id, grp, role, first_name,"
                    " last_name, email, token, status) VALUES (?,?,?,?,?,?,?,"
                    "'en_attente')",
                    (project_id, group, role, first, last, email,
                     secrets.token_urlsafe(24)))
            project = db.execute("SELECT * FROM projects WHERE id=?",
                                 (project_id,)).fetchone()
            notify_group(db, project, "interne_agro")
        flash("La fiche projet a été validée. Un mail de validation a été "
              "envoyé aux trois valideurs internes Agro.", "success")
        return redirect(url_for("dashboard"))

    return render_template("new_project.html", form={},
                           internal_roles=INTERNAL_AGRO_ROLES,
                           itmai_roles=ITMAI_ROLES)


@app.route("/valider/<token>", methods=["GET", "POST"])
def validate(token):
    db = get_db()
    v = db.execute(
        "SELECT v.*, p.* FROM validators v JOIN projects p ON p.id=v.project_id"
        " WHERE v.token=?", (token,)).fetchone()
    if v is None:
        return render_template("validate.html", error="Lien de validation "
                               "invalide."), 404

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
                    " grp='interne_agro' AND status<>'valide'",
                    (project["id"],)).fetchone()["c"]
                external_pending = db.execute(
                    "SELECT COUNT(*) c FROM validators WHERE project_id=? AND"
                    " grp='itmai' AND status NOT IN ('valide')",
                    (project["id"],)).fetchone()["c"]
                if pending == 0 and project["status"] == "phase_interne":
                    if external_pending > 0:
                        db.execute("UPDATE projects SET status='phase_externe'"
                                   " WHERE id=?", (project["id"],))
                        notify_group(db, project, "itmai")
                        flash("Merci ! Tous les valideurs internes Agro ont "
                              "validé. Les valideurs ITMAI viennent d'être "
                              "notifiés.", "success")
                    else:
                        finalize(db, project)
                elif pending == 0 and project["status"] == "phase_externe":
                    finalize(db, project)
                else:
                    if v["grp"] == "itmai":
                        remaining = db.execute(
                            "SELECT COUNT(*) c FROM validators WHERE "
                            "project_id=? AND grp='itmai' AND status<>'valide'",
                            (project["id"],)).fetchone()["c"]
                        flash("Merci pour votre validation." +
                              (f" Il reste {remaining} valideur(s) ITMAI."
                               if remaining else ""), "success")
                    else:
                        remaining = db.execute(
                            "SELECT COUNT(*) c FROM validators WHERE "
                            "project_id=? AND grp='interne_agro' AND "
                            "status<>'valide'",
                            (project["id"],)).fetchone()["c"]
                        flash("Merci pour votre validation." +
                              (f" Il reste {remaining} valideur(s) interne(s)"
                               " Agro." if remaining else ""), "success")
                    if choice == "non":
                        flash("Votre refus a été enregistré.", "warning")
        return redirect(url_for("validate", token=token))

    project = db.execute(
        """SELECT p.name, p.date AS proj_date, p.creator_name, p.creator_email,
                  p.up, p.description, p.launch_delay_months, p.total_gain,
                  p.status
             FROM validators v JOIN projects p ON p.id = v.project_id
            WHERE v.token = ?""",
        (token,)).fetchone()
    if project is None:
        return render_template("validate.html", error="Lien de validation "
                               "invalide."), 404
    return render_template("validate.html", project=project,
                           validator=v,
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


@app.route("/tableau-de-pilotage")
def dashboard():
    db = get_db()
    projects = db.execute(
        """SELECT p.*, GROUP_CONCAT(v.grp) AS grp_list
             FROM projects p LEFT JOIN validators v ON v.project_id = p.id
            WHERE p.archived = 0
            GROUP BY p.id ORDER BY p.created_at DESC""").fetchall()
    all_validators = db.execute(
        "SELECT * FROM validators ORDER BY id").fetchall()
    grouped = {}
    for v in all_validators:
        grouped.setdefault(v["project_id"], []).append(v)
    return render_template("dashboard.html", projects=projects,
                           validators_by_project=grouped,
                           status_label=validator_status_label)


@app.route("/archives")
def archives():
    db = get_db()
    projects = db.execute(
        "SELECT * FROM projects WHERE archived = 1 ORDER BY created_at DESC"
    ).fetchall()
    all_validators = db.execute(
        "SELECT * FROM validators ORDER BY id").fetchall()
    grouped = {}
    for v in all_validators:
        grouped.setdefault(v["project_id"], []).append(v)
    return render_template("archives.html", projects=projects,
                           validators_by_project=grouped,
                           status_label=validator_status_label)


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
