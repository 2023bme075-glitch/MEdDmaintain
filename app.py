import os, csv, io, secrets
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-before-deployment")
db_url = os.environ.get("DATABASE_URL", "sqlite:///medmaintain.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to submit or manage maintenance records."

STATUSES = ["Operational", "In Maintenance", "Out of Service", "Standby", "Decommissioned"]
SERVICE_TYPES = ["Preventive Maintenance", "Corrective Maintenance", "Calibration", "Inspection", "Repair", "Software Update", "Installation", "Other"]

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="technician", nullable=False)
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
    def as_dict(self):
        return {"id":self.id,"serial_number":self.serial_number,"model_number":self.model_number,
                "manufacturer":self.manufacturer,"current_location":self.current_location,
                "past_locations":self.past_locations,"service_date":self.service_date,
                "service_type":self.service_type,"status":self.status,"issues":self.issues,
                "submitted_at":self.submitted_at.isoformat()+"Z","submitted_by":self.submitted_by,"source":self.source}

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin": abort(403)
        return fn(*args, **kwargs)
    return wrapped

def get_payload():
    return request.get_json(silent=True) if request.is_json else request.form

def validate(payload):
    p = payload or {}
    serial = (p.get("serial_number") or "").strip()
    model = (p.get("model_number") or "").strip()
    status = (p.get("status") or "Operational").strip()
    service_type = (p.get("service_type") or "N/A").strip()
    service_date = (p.get("service_date") or "").strip() or "N/A"
    if not serial or not model: return None, "Serial number and model number are required."
    if status not in STATUSES: return None, "Choose a valid equipment status."
    if service_type != "N/A" and service_type not in SERVICE_TYPES: return None, "Choose a valid service type."
    if service_date != "N/A":
        try: date.fromisoformat(service_date)
        except ValueError: return None, "Service date must be YYYY-MM-DD."
    return dict(serial_number=serial, model_number=model,
        manufacturer=(p.get("manufacturer") or "").strip() or "N/A",
        current_location=(p.get("current_location") or "").strip() or "N/A",
        past_locations=(p.get("past_locations") or "").strip() or "N/A",
        service_date=service_date, service_type=service_type,
        status=status, issues=(p.get("issues") or "").strip() or "N/A"), None

@app.get("/")
def index():
    q=(request.args.get("q") or "").strip()
    query=Equipment.query
    if q:
        like=f"%{q}%"
        query=query.filter(db.or_(Equipment.serial_number.ilike(like), Equipment.model_number.ilike(like),
                                  Equipment.manufacturer.ilike(like), Equipment.current_location.ilike(like)))
    records=query.order_by(Equipment.submitted_at.desc()).limit(150).all()
    stats={"total":Equipment.query.count(),
           "operational":Equipment.query.filter_by(status="Operational").count(),
           "maintenance":Equipment.query.filter_by(status="In Maintenance").count(),
           "out":Equipment.query.filter_by(status="Out of Service").count()}
    return render_template("index.html", records=records, stats=stats, q=q)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        username=(request.form.get("username") or "").strip()
        password=request.form.get("password") or ""
        if len(username)<3 or len(password)<10:
            flash("Use a username of at least 3 characters and a password of at least 10 characters.","error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already registered.","error")
        else:
            user=User(username=username,role="technician"); user.set_password(password)
            db.session.add(user); db.session.commit()
            login_user(user); flash("Account created. You can now submit maintenance entries.","success")
            return redirect(url_for("index"))
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        user=User.query.filter_by(username=(request.form.get("username") or "").strip()).first()
        if user and user.check_password(request.form.get("password") or ""):
            login_user(user); return redirect(request.args.get("next") or url_for("index"))
        flash("Incorrect username or password.","error")
    return render_template("auth.html", mode="login")

@app.get("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("index"))

@app.route("/submit", methods=["GET","POST"])
@login_required
def submit():
    if request.method=="POST":
        values,error=validate(get_payload())
        if error: flash(error,"error")
        else:
            record=Equipment(**values,submitted_by=current_user.username,source="website")
            db.session.add(record); db.session.commit()
            flash(f"Maintenance entry saved (record #{record.id}).","success")
            return redirect(url_for("record_detail",record_id=record.id))
    return render_template("submit.html", statuses=STATUSES, service_types=SERVICE_TYPES)

@app.get("/record/<int:record_id>")
def record_detail(record_id):
    record=db.get_or_404(Equipment,record_id)
    return render_template("detail.html",record=record)

@app.route("/record/<int:record_id>/delete",methods=["POST"])
@admin_required
def delete_record(record_id):
    record=db.get_or_404(Equipment,record_id)
    db.session.delete(record); db.session.commit()
    flash("Record deleted.","success")
    return redirect(url_for("index"))

@app.get("/api/equipment")
def api_list():
    # Public read access; notebook sync is optionally protected by a dedicated API key.
    supplied=request.headers.get("X-API-Key")
    required=os.environ.get("NOTEBOOK_API_KEY")
    if required and supplied != required:
        return jsonify({"ok":False,"error":"Valid X-API-Key required for notebook synchronization."}),401
    since_id=request.args.get("since_id",default=0,type=int)
    records=Equipment.query.filter(Equipment.id>since_id).order_by(Equipment.id.asc()).all()
    return jsonify({"ok":True,"count":len(records),"records":[r.as_dict() for r in records]})

@app.get("/api/equipment/<int:record_id>")
def api_one(record_id):
    record=db.get_or_404(Equipment,record_id)
    return jsonify({"ok":True,"record":record.as_dict()})

@app.get("/export.csv")
@login_required
def export_csv():
    output=io.StringIO()
    fields=["id","serial_number","model_number","manufacturer","current_location","past_locations","service_date","service_type","status","issues","submitted_at","submitted_by","source"]
    writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
    for r in Equipment.query.order_by(Equipment.id.desc()).all(): writer.writerow(r.as_dict())
    return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=medical_equipment_register.csv"})

@app.get("/admin")
@admin_required
def admin():
    users=User.query.order_by(User.created_at.desc()).all()
    return render_template("admin.html",users=users)

@app.post("/admin/users/<int:user_id>/role")
@admin_required
def change_role(user_id):
    user=db.get_or_404(User,user_id)
    if user.id==current_user.id:
        flash("You cannot change your own role here.","error")
    else:
        role=request.form.get("role")
        if role in ["admin","technician"]:
            user.role=role; db.session.commit(); flash("User role updated.","success")
    return redirect(url_for("admin"))

@app.get("/health")
def health(): return jsonify({"ok":True,"service":"MedMaintain"})

with app.app_context():
    db.create_all()
    # First admin is created only when both environment variables are supplied.
    admin_name=os.environ.get("ADMIN_USERNAME")
    admin_password=os.environ.get("ADMIN_PASSWORD")
    if admin_name and admin_password and not User.query.filter_by(username=admin_name).first():
        admin_user=User(username=admin_name,role="admin")
        admin_user.set_password(admin_password); db.session.add(admin_user); db.session.commit()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
