import os, csv, io, secrets
from pathlib import Path
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, abort, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect, text
from PIL import Image, UnidentifiedImageError

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-before-deployment")
db_url = os.environ.get("DATABASE_URL", "sqlite:///medmaintain.db")
if db_url.startswith("postgres://"): db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
PROFILE_IMAGE_DIR = Path(app.instance_path) / "profile_images"
PROFILE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."

STATUSES = ["Operational", "In Maintenance", "Out of Service", "Standby", "Decommissioned"]
SERVICE_TYPES = ["Preventive Maintenance", "Corrective Maintenance", "Calibration", "Inspection", "Repair", "Software Update", "Installation", "Other"]
PRIVILEGED_ROLES = ("owner", "supervisor", "admin")

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="technician", nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    auth_token = db.Column(db.String(64), default=lambda: secrets.token_urlsafe(32), nullable=False)
    display_name = db.Column(db.String(80), nullable=True)
    profile_image = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(120), nullable=False, index=True)
    model_number = db.Column(db.String(160), nullable=False)
    manufacturer = db.Column(db.String(160), default="N/A")
    current_location = db.Column(db.String(200), default="N/A")
    past_locations = db.Column(db.Text, default="N/A")
    service_date = db.Column(db.String(20), default="N/A")
    service_type = db.Column(db.String(80), default="N/A")
    status = db.Column(db.String(40), default="Operational")
    issues = db.Column(db.Text, default="N/A")
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    submitted_by = db.Column(db.String(80), default="system")
    source = db.Column(db.String(30), default="website")
    review_status = db.Column(db.String(20), default="pending", nullable=False)
    reviewed_by = db.Column(db.String(80))
    reviewed_at = db.Column(db.DateTime)
    def as_dict(self):
        return {"id":self.id,"serial_number":self.serial_number,"model_number":self.model_number,
          "manufacturer":self.manufacturer,"current_location":self.current_location,"past_locations":self.past_locations,
          "service_date":self.service_date,"service_type":self.service_type,"status":self.status,"issues":self.issues,
          "submitted_at":self.submitted_at.isoformat()+"Z","submitted_by":self.submitted_by,"source":self.source,
          "review_status":self.review_status}

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(40), nullable=False)
    target_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    if user is None:
        return None
    # Require the browser session to carry this account's current database token.
    saved_token = session.get("auth_token")
    if not saved_token or not secrets.compare_digest(saved_token, user.auth_token or ""):
        return None
    return user

def supervisor_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in PRIVILEGED_ROLES: abort(403)
        return fn(*args, **kwargs)
    return wrapped

def owner_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "owner": abort(403)
        return fn(*args, **kwargs)
    return wrapped

def get_payload(): return request.get_json(silent=True) if request.is_json else request.form

def allowed_domains():
    return {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}

def email_allowed(email):
    email = (email or "").strip().lower()
    if "@" not in email: return False
    domain = email.rsplit("@",1)[1]
    return bool(allowed_domains()) and domain in allowed_domains()

def audit(actor, action, target_type, target_id=None, details=None):
    db.session.add(AuditLog(actor=actor, action=action, target_type=target_type, target_id=target_id, details=details))

def validate(payload):
    p=payload or {}
    serial=(p.get("serial_number") or "").strip(); model=(p.get("model_number") or "").strip()
    status=(p.get("status") or "Operational").strip(); service_type=(p.get("service_type") or "N/A").strip()
    service_date=(p.get("service_date") or "").strip() or "N/A"
    if not serial or not model: return None,"Serial number and model number are required."
    if status not in STATUSES: return None,"Choose a valid equipment status."
    if service_type!="N/A" and service_type not in SERVICE_TYPES: return None,"Choose a valid service type."
    if service_date!="N/A":
        try: date.fromisoformat(service_date)
        except ValueError: return None,"Service date must be YYYY-MM-DD."
    return dict(serial_number=serial,model_number=model,manufacturer=(p.get("manufacturer") or "").strip() or "N/A",
      current_location=(p.get("current_location") or "").strip() or "N/A",past_locations=(p.get("past_locations") or "").strip() or "N/A",
      service_date=service_date,service_type=service_type,status=status,issues=(p.get("issues") or "").strip() or "N/A"),None

@app.get("/")
def index():
    if not current_user.is_authenticated: return render_template("index.html",records=[],stats=None,q="")
    q=(request.args.get("q") or "").strip()
    query=Equipment.query
    if current_user.role not in PRIVILEGED_ROLES: query=query.filter_by(review_status="approved")
    if q:
        like=f"%{q}%"
        query=query.filter(db.or_(Equipment.serial_number.ilike(like),Equipment.model_number.ilike(like),Equipment.manufacturer.ilike(like),Equipment.current_location.ilike(like)))
    records=query.order_by(Equipment.submitted_at.desc()).limit(150).all()
    stats={"total":query.count(),"operational":query.filter_by(status="Operational").count(),
      "maintenance":query.filter_by(status="In Maintenance").count(),"out":query.filter_by(status="Out of Service").count()}
    pending=Equipment.query.filter_by(review_status="pending").count() if current_user.role in PRIVILEGED_ROLES else 0
    return render_template("index.html",records=records,stats=stats,q=q,pending_count=pending)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        username=(request.form.get("username") or "").strip()
        email=(request.form.get("email") or "").strip().lower()
        password=request.form.get("password") or ""
        if len(username)<3 or len(password)<12: flash("Use a username of at least 3 characters and a password of at least 12 characters.","error")
        elif not email_allowed(email): flash("Registration is limited to approved organization email domains. Contact the system supervisor if your domain should be added.","error")
        elif User.query.filter(db.or_(User.username==username,User.email==email)).first(): flash("That username or email is already registered.","error")
        else:
            user=User(username=username,email=email,role="technician",is_approved=False); user.set_password(password)
            db.session.add(user); audit(username,"account_registered","user",details=email); db.session.commit()
            flash("Registration received. Your account is pending supervisor approval.","success")
            return redirect(url_for("login"))
    return render_template("auth.html",mode="register")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        user=User.query.filter_by(username=(request.form.get("username") or "").strip()).first()
        if user and user.check_password(request.form.get("password") or ""):
            if not user.is_approved and user.role not in PRIVILEGED_ROLES:
                flash("Your account is awaiting supervisor approval.","error")
                return redirect(url_for("login"))
            login_user(user); session["auth_token"] = user.auth_token
            return redirect(request.args.get("next") or url_for("index"))
        flash("Incorrect username or password.","error")
    return render_template("auth.html",mode="login")

@app.route("/owner-setup",methods=["GET","POST"])
def owner_setup():
    if User.query.filter_by(role="owner").first():
        abort(404)
    setup_token=os.environ.get("OWNER_SETUP_TOKEN","")
    owner_email=(os.environ.get("OWNER_EMAIL","") or "").strip().lower()
    if not setup_token or len(setup_token)<32 or not owner_email:
        abort(404)
    if request.method=="POST":
        supplied=request.form.get("setup_token","")
        username=(request.form.get("username") or "medmaintain_owner").strip()
        email=(request.form.get("email") or "").strip().lower()
        password=request.form.get("password") or ""
        if not secrets.compare_digest(supplied,setup_token): flash("Invalid setup authorization.","error")
        elif not secrets.compare_digest(email,owner_email): flash("The email does not match the designated owner email.","error")
        elif len(username)<3 or len(password)<14: flash("Use a username of at least 3 characters and a password of at least 14 characters.","error")
        elif User.query.filter(db.or_(User.username==username,User.email==email)).first(): flash("That username or email is already in use.","error")
        else:
            user=User(username=username,email=email,role="owner",is_approved=True); user.set_password(password)
            db.session.add(user); audit(username,"initial_owner_created","user",details=email); db.session.commit()
            login_user(user); session["auth_token"] = user.auth_token
            flash("Owner account created. Remove OWNER_SETUP_TOKEN from your private hosting configuration now.","success")
            return redirect(url_for("supervisor_portal"))
    return render_template("owner_setup.html")

@app.get("/logout")
@login_required
def logout(): logout_user(); return redirect(url_for("index"))

def profile_csrf_token():
    token = session.get("profile_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["profile_csrf_token"] = token
    return token

@app.context_processor
def inject_profile_helpers():
    return {"profile_csrf_token": profile_csrf_token}

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("profile_csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            abort(400, description="Your profile form expired. Refresh the page and try again.")
        action = request.form.get("action", "details")
        if action == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not current_user.check_password(current_password):
                flash("Your current password is incorrect.", "error")
            elif len(new_password) < 12:
                flash("Your new password must contain at least 12 characters.", "error")
            elif new_password != confirm_password:
                flash("The new passwords do not match.", "error")
            elif current_user.check_password(new_password):
                flash("Choose a password different from your current password.", "error")
            else:
                current_user.set_password(new_password)
                current_user.auth_token = secrets.token_urlsafe(32)
                audit(current_user.username, "password_changed", "user", current_user.id)
                db.session.commit()
                session["auth_token"] = current_user.auth_token
                session["profile_csrf_token"] = secrets.token_urlsafe(32)
                flash("Your password has been changed successfully.", "success")
                return redirect(url_for("profile"))
        elif action == "details":
            display_name = (request.form.get("display_name") or "").strip()
            if len(display_name) > 80:
                flash("Display name must be 80 characters or fewer.", "error")
            else:
                new_image = None
                upload = request.files.get("profile_image")
                remove_image = request.form.get("remove_image") == "yes"
                if upload and upload.filename:
                    if len(upload.read()) > app.config["MAX_CONTENT_LENGTH"]:
                        flash("The image must be 2 MB or smaller.", "error")
                        return redirect(url_for("profile"))
                    upload.stream.seek(0)
                    try:
                        image = Image.open(upload.stream)
                        if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                            raise ValueError("Unsupported image")
                        image.verify()
                        upload.stream.seek(0)
                        image = Image.open(upload.stream)
                        image.thumbnail((512, 512))
                        if image.mode not in ("RGB", "RGBA"):
                            image = image.convert("RGB")
                        new_image = secrets.token_hex(16) + ".webp"
                        image.save(PROFILE_IMAGE_DIR / new_image, "WEBP", quality=82, method=6)
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
                        flash("Upload a valid, non-animated JPG, PNG or WebP image.", "error")
                        return redirect(url_for("profile"))
                old_image = current_user.profile_image
                current_user.display_name = display_name or None
                if new_image:
                    current_user.profile_image = new_image
                elif remove_image:
                    current_user.profile_image = None
                audit(current_user.username, "profile_updated", "user", current_user.id)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    if new_image:
                        (PROFILE_IMAGE_DIR / new_image).unlink(missing_ok=True)
                    raise
                if old_image and current_user.profile_image != old_image:
                    (PROFILE_IMAGE_DIR / old_image).unlink(missing_ok=True)
                flash("Your profile has been updated.", "success")
                return redirect(url_for("profile"))
        else:
            abort(400)
    return render_template("profile.html")

@app.get("/profile/image/<filename>")
@login_required
def profile_image(filename):
    if not current_user.profile_image or not secrets.compare_digest(filename, current_user.profile_image):
        abort(404)
    return send_from_directory(PROFILE_IMAGE_DIR, current_user.profile_image, mimetype="image/webp", max_age=3600)


@app.route("/submit",methods=["GET","POST"])
@login_required
def submit():
    if request.method=="POST":
        values,error=validate(get_payload())
        if error: flash(error,"error")
        else:
            record=Equipment(**values,submitted_by=current_user.username,source="website",review_status="pending")
            db.session.add(record); db.session.flush()
            audit(current_user.username,"record_submitted","equipment",record.id)
            db.session.commit()
            flash(f"Entry submitted for supervisor review (record #{record.id}).","success")
            return redirect(url_for("record_detail",record_id=record.id))
    return render_template("submit.html",statuses=STATUSES,service_types=SERVICE_TYPES)

@app.get("/record/<int:record_id>")
@login_required
def record_detail(record_id):
    record=db.get_or_404(Equipment,record_id)
    if record.review_status!="approved" and current_user.role not in PRIVILEGED_ROLES and record.submitted_by!=current_user.username: abort(403)
    return render_template("detail.html",record=record)

@app.post("/record/<int:record_id>/review")
@supervisor_required
def review_record(record_id):
    record=db.get_or_404(Equipment,record_id)
    action=request.form.get("action")
    if action not in ("approve","return"): abort(400)
    record.review_status="approved" if action=="approve" else "returned"
    record.reviewed_by=current_user.username; record.reviewed_at=datetime.utcnow()
    audit(current_user.username,"record_"+action,"equipment",record.id,request.form.get("note","")[:1000])
    db.session.commit(); flash(f"Record #{record.id} {('approved' if action=='approve' else 'returned for correction')}.","success")
    return redirect(url_for("supervisor_portal"))

@app.get("/supervisor")
@supervisor_required
def supervisor_portal():
    pending_records=Equipment.query.filter_by(review_status="pending").order_by(Equipment.submitted_at.asc()).all()
    pending_users=User.query.filter_by(is_approved=False).order_by(User.created_at.asc()).all()
    logs=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()
    return render_template("supervisor.html",pending_records=pending_records,pending_users=pending_users,logs=logs)

@app.post("/supervisor/users/<int:user_id>/approve")
@supervisor_required
def approve_user(user_id):
    user=db.get_or_404(User,user_id)
    if user.role!="technician": abort(400)
    user.is_approved=True; audit(current_user.username,"account_approved","user",user.id); db.session.commit()
    flash(f"Account {user.username} approved.","success"); return redirect(url_for("supervisor_portal"))

@app.post("/supervisor/users/<int:user_id>/role")
@owner_required
def owner_change_role(user_id):
    user=db.get_or_404(User,user_id)
    role=request.form.get("role")
    if user.role=="owner" or role not in ("technician","supervisor"): abort(400)
    user.role=role; audit(current_user.username,"role_changed","user",user.id,role); db.session.commit()
    flash("User role updated.","success"); return redirect(url_for("supervisor_portal"))

@app.get("/admin")
@supervisor_required
def admin():
    users=User.query.order_by(User.created_at.desc()).all()
    return render_template("admin.html",users=users)

@app.post("/admin/users/<int:user_id>/role")
@owner_required
def change_role(user_id):
    user=db.get_or_404(User,user_id); role=request.form.get("role")
    if user.role=="owner" or role not in ("technician","supervisor"): abort(400)
    user.role=role; audit(current_user.username,"role_changed","user",user.id,role); db.session.commit()
    flash("User role updated.","success"); return redirect(url_for("admin"))

@app.post("/record/<int:record_id>/delete")
@supervisor_required
def delete_record(record_id):
    record=db.get_or_404(Equipment,record_id)
    audit(current_user.username,"record_deleted","equipment",record.id,record.serial_number)
    db.session.delete(record); db.session.commit()
    flash("Record deleted.","success")
    return redirect(url_for("index"))

@app.post("/admin/users/<int:user_id>/delete")
@owner_required
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    # Protect the active owner session and every owner account from deletion.
    if user.id == current_user.id or user.role == "owner":
        abort(400)
    username = user.username
    email = user.email or ""
    role = user.role
    audit(current_user.username, "user_deleted", "user", user.id,
          f"username={username}; email={email}; role={role}")
    db.session.delete(user)
    db.session.commit()
    flash(f"User account {username} was deleted.", "success")
    return redirect(url_for("admin"))


@app.post("/owner/transfer/<int:user_id>")
@owner_required
def transfer_owner(user_id):
    successor=db.get_or_404(User,user_id)
    if successor.role!="supervisor" or not successor.is_approved:
        abort(400)
    old_owner=current_user
    old_owner.role="supervisor"
    successor.role="owner"
    audit(old_owner.username,"owner_role_transferred","user",successor.id,successor.username)
    db.session.commit()
    flash("Owner role transferred. Your account now has supervisor access.","success")
    return redirect(url_for("supervisor_portal"))

@app.get("/export.csv")
@login_required
def export_csv():
    query=Equipment.query
    if current_user.role not in PRIVILEGED_ROLES: query=query.filter_by(review_status="approved")
    output=io.StringIO(); fields=["id","serial_number","model_number","manufacturer","current_location","past_locations","service_date","service_type","status","issues","submitted_at","submitted_by","source","review_status"]
    writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
    for r in query.order_by(Equipment.id.desc()).all():
        row=r.as_dict(); writer.writerow({k:row.get(k,"") for k in fields})
    return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=medical_equipment_register.csv"})

def api_authorized():
    required=os.environ.get("NOTEBOOK_API_KEY",""); supplied=request.headers.get("X-API-Key","")
    return bool(required) and secrets.compare_digest(supplied,required)

@app.route("/api/equipment",methods=["GET","POST"])
def api_equipment():
    if not os.environ.get("NOTEBOOK_API_KEY"): return jsonify({"ok":False,"error":"Notebook API access is not configured."}),503
    if not api_authorized(): return jsonify({"ok":False,"error":"Valid X-API-Key required."}),401
    if request.method=="POST":
        values,error=validate(request.get_json(silent=True))
        if error: return jsonify({"ok":False,"error":error}),400
        record=Equipment(**values,submitted_by="notebook",source="notebook",review_status="pending")
        db.session.add(record); db.session.flush(); audit("notebook","record_submitted","equipment",record.id); db.session.commit()
        return jsonify({"ok":True,"record":record.as_dict(),"message":"Entry queued for supervisor review."}),201
    since_id=request.args.get("since_id",default=0,type=int)
    query=Equipment.query.filter(Equipment.id>since_id,Equipment.review_status=="approved")
    records=query.order_by(Equipment.id.asc()).all()
    return jsonify({"ok":True,"count":len(records),"records":[r.as_dict() for r in records]})

@app.get("/api/equipment/<int:record_id>")
def api_one(record_id):
    if not os.environ.get("NOTEBOOK_API_KEY"): return jsonify({"ok":False,"error":"Notebook API access is not configured."}),503
    if not api_authorized(): return jsonify({"ok":False,"error":"Valid X-API-Key required."}),401
    record=db.get_or_404(Equipment,record_id)
    if record.review_status!="approved": return jsonify({"ok":False,"error":"Record is not approved."}),403
    return jsonify({"ok":True,"record":record.as_dict()})

@app.get("/health")
def health(): return jsonify({"ok":True,"service":"MedMaintain"})

def migrate_existing_database():
    # Additive migration for existing SQLite/PostgreSQL installations; existing records remain visible.
    inspector=inspect(db.engine)
    tables=inspector.get_table_names()
    if "user" in tables:
        cols={c["name"] for c in inspector.get_columns("user")}
        dialect=db.engine.dialect.name
        additions={"email":"VARCHAR(254)","is_approved":"BOOLEAN NOT NULL DEFAULT TRUE","auth_token":"VARCHAR(64)","display_name":"VARCHAR(80)","profile_image":"VARCHAR(80)"}
        for name,definition in additions.items():
            if name not in cols: db.session.execute(text(f"ALTER TABLE \"user\" ADD COLUMN {name} {definition}"))
        # Existing accounts receive tokens; old sessions must sign in again.
        for existing_user in User.query.filter(User.auth_token.is_(None)).all():
            existing_user.auth_token = secrets.token_urlsafe(32)
    if "equipment" in tables:
        cols={c["name"] for c in inspector.get_columns("equipment")}
        additions={"review_status":"VARCHAR(20) NOT NULL DEFAULT 'approved'","reviewed_by":"VARCHAR(80)","reviewed_at":"TIMESTAMP"}
        for name,definition in additions.items():
            if name not in cols: db.session.execute(text(f"ALTER TABLE equipment ADD COLUMN {name} {definition}"))
    db.session.commit()

with app.app_context():
    db.create_all()
    migrate_existing_database()
    # Legacy administrator accounts retain supervisory access after this update.
    admin_name=os.environ.get("ADMIN_USERNAME"); admin_password=os.environ.get("ADMIN_PASSWORD")
    if admin_name and admin_password and not User.query.filter_by(username=admin_name).first():
        admin_user=User(username=admin_name,role="admin",is_approved=True); admin_user.set_password(admin_password)
        db.session.add(admin_user); db.session.commit()

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
