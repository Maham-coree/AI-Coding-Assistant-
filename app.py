import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import bleach
import markdown
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from email_validator import EmailNotValidError, validate_email
from google import genai
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf.csrf import CSRFProtect

load_dotenv()

is_vercel = os.getenv("VERCEL", "").strip().lower() in {"1", "true"}
app = Flask(
    __name__,
    instance_path=os.path.abspath("/tmp/instance") if is_vercel else None,
)
app_env = os.getenv("APP_ENV", "development").strip().lower()
is_production = (
    app_env == "production"
    or os.getenv("RENDER", "").lower() == "true"
    or is_vercel
)
secret_key = (os.getenv("SECRET_KEY") or "").strip() or None
configured_database_url = (os.getenv("DATABASE_URL") or "").strip() or None
if is_production and (
    not secret_key
    or len(secret_key) < 32
    or secret_key.lower().startswith("replace_with_")
):
    raise RuntimeError("Set SECRET_KEY to a randomly generated value of at least 32 characters in production.")
if is_production and not configured_database_url:
    raise RuntimeError("DATABASE_URL must point to persistent production storage.")
if is_production and configured_database_url.startswith("sqlite:"):
    raise RuntimeError("Configure persistent PostgreSQL storage instead of SQLite in production.")

database_url = configured_database_url or "sqlite:///assistant.db"
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config.update(
    SECRET_KEY=secret_key or os.urandom(32),
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_production,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    WTF_CSRF_HEADERS=["X-CSRFToken"],
    RATELIMIT_STORAGE_URI=os.getenv("REDIS_URL", "memory://"),
)
if database_url.startswith("sqlite:"):
    os.makedirs(app.instance_path, exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])
login_manager = LoginManager(app)
login_manager.session_protection = "strong"
if is_production:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

MODE_SYSTEM_PROMPTS = {
    "generate": "You are an expert software engineer and coding mentor. Generate high-quality code, explain it clearly, and tailor the answer to the user's exact request.",
    "explain": "You are a patient coding teacher. Explain the code or concept step by step in simple English, highlight key logic, and keep the explanation approachable for developers at different skill levels.",
    "debug": "You are a careful debugging assistant. Find likely errors, explain their root causes, and suggest a corrected version without claiming it was executed. Be precise and practical.",
    "optimize": "You are a code quality reviewer. Identify inefficiencies, improve readability, and propose cleaner, faster, and more maintainable solutions while explaining the changes.",
    "convert": "You are a language conversion specialist. Convert the original logic accurately between languages, explain important differences, and flag any limitations when structure or libraries differ.",
}

LANGUAGE_ALIASES = {
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "java": "java",
    "c#": "csharp",
    "csharp": "csharp",
    "cpp": "cpp",
    "c++": "cpp",
    "sql": "sql",
    "html": "html",
    "css": "css",
}
PROMPT_CATEGORIES = (
    "Code Generation",
    "Debugging",
    "Code Explanation",
    "Code Optimization",
    "Code Review",
    "Documentation",
    "SQL Assistance",
)
SAFE_MARKDOWN_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
    "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
    "thead", "tr", "ul",
}
SAFE_MARKDOWN_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "th": ["align"],
    "td": ["align"],
}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    theme = db.Column(db.String(10), nullable=False, default="light")
    explanation_preference = db.Column(db.String(20), nullable=False, default="step_by_step")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    conversations = db.relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")
    prompt_templates = db.relationship("PromptTemplate", back_populates="owner", cascade="all, delete-orphan")
    snippets = db.relationship("SavedSnippet", back_populates="owner", cascade="all, delete-orphan")


class Conversation(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = db.Column(db.String(100))
    title = db.Column(db.String(120), nullable=False, default="New conversation")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner = db.relationship("User", back_populates="conversations")
    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at, Message.id",
    )
    __table_args__ = (
        db.UniqueConstraint("owner_id", "source_id", name="uq_conversation_owner_source"),
        db.Index("ix_conversation_owner_updated", "owner_id", "updated_at"),
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(36), db.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    code = db.Column(db.Text, nullable=False, default="")
    mode = db.Column(db.String(20), nullable=False, default="generate")
    language = db.Column(db.String(30), nullable=False, default="python")
    generated_code = db.Column(db.Boolean, nullable=False, default=False)
    analytics_eligible = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    conversation = db.relationship("Conversation", back_populates="messages")


class PromptTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=False, default="")
    prompt = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="generate")
    language = db.Column(db.String(30), nullable=False, default="python")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner = db.relationship("User", back_populates="prompt_templates")
    __table_args__ = (
        db.UniqueConstraint("owner_id", "title", name="uq_prompt_template_owner_title"),
        db.Index("ix_prompt_template_owner_category", "owner_id", "category"),
    )


class SavedSnippet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False)
    code = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(30), nullable=False, default="python")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner = db.relationship("User", back_populates="snippets")


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("login"))


def api_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"status": "error", "error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def normalize_language(raw_language):
    value = (raw_language or "python").strip().lower()
    return LANGUAGE_ALIASES.get(value, "python")


def validate_password(password):
    if len(password) < 12:
        return "Use at least 12 characters for your password."
    if not re.search(r"[a-z]", password) or not re.search(r"[A-Z]", password) or not re.search(r"\d", password):
        return "Include an uppercase letter, a lowercase letter, and a number."
    return None


def normalize_email(email):
    try:
        return validate_email(email.casefold(), check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def sanitize_html(text):
    return bleach.clean(
        text or "",
        tags=SAFE_MARKDOWN_TAGS,
        attributes=SAFE_MARKDOWN_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception as exc:
        app.logger.error("Gemini client initialization failed (%s)", type(exc).__name__)
        return None


def build_prompt(mode, language, user_input, code_input, explanation_preference="step_by_step"):
    selected_mode = MODE_SYSTEM_PROMPTS.get(mode, MODE_SYSTEM_PROMPTS["generate"])
    prompt_sections = [
        selected_mode,
        f"You are working with the target language: {language}.",
        "Use Markdown formatting with headings, bullet points, and code blocks where helpful.",
        "Do not claim you have executed the code or tested it unless that was actually done.",
    ]
    if mode == "explain" and explanation_preference == "concise":
        prompt_sections.append("Keep the explanation concise while covering the key logic.")
    if user_input:
        prompt_sections.append(f"User request:\n{user_input}")
    if code_input:
        prompt_sections.append(f"Existing code:\n```{language}\n{code_input}\n```")
    return "\n\n".join(prompt_sections)


def render_markdown(text):
    if text is None:
        return ""
    sanitized = str(text).strip()
    if not sanitized:
        return ""
    rendered = markdown.markdown(
        sanitized,
        extensions=["fenced_code", "tables", "codehilite", "sane_lists"],
    )
    return sanitize_html(rendered)


def extract_response_text(response):
    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, list) and candidates:
        content = getattr(candidates[0], "content", None)
        if content is not None:
            parts = getattr(content, "parts", None) or []
            collected_parts = [part.text for part in parts if getattr(part, "text", None)]
            if collected_parts:
                return "\n".join(collected_parts)
    text = getattr(response, "text", "")
    return text if text else str(response)


def seed_prompt_templates(user):
    starters = [
        ("Code Generation Starter", "Code Generation", "Generate production-minded code for my requirements. Include validation, edge cases, and a short explanation.", "generate", "python"),
        ("Debugging Starter", "Debugging", "Find the root cause of this issue, explain it, and propose a minimal fix with relevant edge cases.", "debug", "python"),
        ("Code Explanation Starter", "Code Explanation", "Explain the supplied code step by step, including important data flow and assumptions.", "explain", "python"),
        ("Code Optimization Starter", "Code Optimization", "Review the supplied code for measurable performance and maintainability improvements. Explain trade-offs.", "optimize", "python"),
        ("Code Review Starter", "Code Review", "Review the supplied code for correctness, edge cases, and maintainability. Prioritize actionable findings.", "optimize", "python"),
        ("Documentation Starter", "Documentation", "Write concise developer documentation for the supplied code, including purpose, parameters, return values, and an example.", "explain", "python"),
        ("SQL Assistance Starter", "SQL Assistance", "Help write or review this SQL query. Explain joins, filters, and likely performance considerations.", "generate", "sql"),
    ]
    for title, category, prompt, mode, language in starters:
        db.session.add(PromptTemplate(
            owner=user,
            title=title,
            category=category,
            prompt=prompt,
            description="Starter template — edit it to fit your workflow.",
            mode=mode,
            language=language,
        ))


def serialize_message(message):
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "code": message.code,
        "mode": message.mode,
        "language": message.language,
        "created_at": message.created_at.isoformat(),
    }


def serialize_conversation(conversation, include_messages=True):
    result = {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if include_messages:
        result["messages"] = [serialize_message(message) for message in conversation.messages]
    return result


@app.route("/")
@login_required
def home():
    fill_template_id = request.args.get("template", type=int)
    return render_template(
        "index.html",
        fill_template_id=fill_template_id,
        modes=MODE_SYSTEM_PROMPTS,
        languages=sorted(set(LANGUAGE_ALIASES.values())),
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "provider_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    })


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = normalize_email((request.form.get("email") or "").strip())
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        if not 2 <= len(name) <= 80:
            flash("Enter a name between 2 and 80 characters.", "error")
        elif not email:
            flash("Enter a valid email address.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        elif (password_error := validate_password(password)):
            flash(password_error, "error")
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        else:
            user = User(name=name, email=email, password_hash=generate_password_hash(password, method="scrypt"))
            db.session.add(user)
            try:
                db.session.flush()
                seed_prompt_templates(user)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("An account with that email already exists.", "error")
            else:
                session.clear()
                login_user(user, fresh=True)
                return redirect(url_for("home"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        email = normalize_email((request.form.get("email") or "").strip())
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
        else:
            session.clear()
            login_user(user, fresh=True)
            return redirect(url_for("home"))
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("login"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        theme = request.form.get("theme", "light")
        explanation = request.form.get("explanation_preference", "step_by_step")
        password = request.form.get("new_password") or ""
        if not 2 <= len(name) <= 80:
            flash("Enter a name between 2 and 80 characters.", "error")
        elif not email:
            flash("Enter a valid email address.", "error")
        elif User.query.filter(User.email == email, User.id != current_user.id).first():
            flash("That email address is already associated with another account.", "error")
        elif theme not in {"light", "dark"} or explanation not in {"step_by_step", "concise"}:
            flash("Choose a valid preference.", "error")
        elif password and (
            not check_password_hash(current_user.password_hash, request.form.get("current_password") or "")
            or validate_password(password)
            or password != (request.form.get("confirm_password") or "")
        ):
            flash("Check your current password and ensure the new password meets the requirements.", "error")
        else:
            current_user.name = name
            current_user.email = email
            current_user.theme = theme
            current_user.explanation_preference = explanation
            if password:
                current_user.password_hash = generate_password_hash(password, method="scrypt")
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("That email address is already associated with another account.", "error")
            else:
                flash("Settings saved.", "success")
                return redirect(url_for("settings"))
    return render_template("settings.html")


@app.post("/api/preferences")
@api_login_required
def update_preferences():
    data = request.get_json(silent=True) or {}
    theme = data.get("theme")
    if theme not in {"light", "dark"}:
        return jsonify({"status": "error", "error": "Invalid theme."}), 400
    current_user.theme = theme
    db.session.commit()
    return jsonify({"status": "ok", "theme": theme})


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    mode = (request.form.get("mode", "generate") or "generate").strip().lower()
    if mode not in MODE_SYSTEM_PROMPTS:
        mode = "generate"
    language = normalize_language(request.form.get("language", "python"))
    user_input = (request.form.get("user_input", "") or "").strip()
    code_input = (request.form.get("code_input", "") or "").strip()
    conversation_id = (request.form.get("conversation_id") or "").strip()

    if not user_input and not code_input:
        payload = {"status": "error", "error": "Please enter a prompt or paste code before submitting."}
        if request.accept_mimetypes.accept_json:
            return jsonify(payload), 400
        flash(payload["error"], "error")
        return redirect(url_for("home"))
    if len(user_input) > 20000 or len(code_input) > 50000:
        payload = {"status": "error", "error": "Keep prompts under 20,000 characters and code under 50,000 characters."}
        if request.accept_mimetypes.accept_json:
            return jsonify(payload), 413
        flash(payload["error"], "error")
        return redirect(url_for("home"))

    client = get_gemini_client()
    if client is None:
        payload = {
            "status": "error",
            "error": "Gemini API key is missing or unavailable. Configure GEMINI_API_KEY before using the AI assistant.",
        }
        if request.accept_mimetypes.accept_json:
            return jsonify(payload), 401
        flash(payload["error"], "error")
        return redirect(url_for("home"))

    if conversation_id:
        conversation = Conversation.query.filter_by(id=conversation_id, owner_id=current_user.id).first()
        if conversation is None:
            return jsonify({"status": "error", "error": "Conversation not found."}), 404
    else:
        conversation = Conversation(owner=current_user, title="New conversation")
        db.session.add(conversation)
        db.session.flush()
    if conversation.title == "New conversation":
        title_source = user_input or code_input
        conversation.title = (title_source[:117] + "...") if len(title_source) > 120 else title_source
    conversation.updated_at = datetime.now(timezone.utc)
    prompt_message = Message(
        conversation=conversation,
        owner_id=current_user.id,
        role="user",
        content=user_input or "Review the provided code.",
        code=code_input,
        mode=mode,
        language=language,
    )
    db.session.add(prompt_message)
    db.session.commit()

    prompt = build_prompt(
        mode,
        language,
        user_input,
        code_input,
        current_user.explanation_preference,
    )
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw_text = extract_response_text(response)
        ai_response = render_markdown(raw_text)
        if not ai_response:
            ai_response = "<p>AI did not return any content for this request. Please try again with a clearer prompt.</p>"
        db.session.add(Message(
            conversation=conversation,
            owner_id=current_user.id,
            role="assistant",
            content=ai_response,
            mode=mode,
            language=language,
            generated_code=bool(re.search(r"<pre(?:\s|>)", ai_response)),
        ))
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        payload = {
            "status": "ok",
            "ai_response": ai_response,
            "mode": mode,
            "language": language,
            "conversation": serialize_conversation(conversation),
        }
    except Exception as exc:
        db.session.rollback()
        app.logger.error("Gemini request failed (%s)", type(exc).__name__)
        message = "Gemini is temporarily unavailable. Please try again shortly."
        payload = {"status": "error", "error": message, "conversation_id": conversation.id}
        if request.accept_mimetypes.accept_json:
            return jsonify(payload), 502
        flash(message, "error")
        return redirect(url_for("home"))

    if request.accept_mimetypes.accept_json:
        return jsonify(payload)
    return redirect(url_for("home"))


@app.route("/api/conversations", methods=["GET", "POST"])
@api_login_required
def conversations_api():
    if request.method == "GET":
        items = Conversation.query.filter_by(owner_id=current_user.id).order_by(Conversation.updated_at.desc()).all()
        return jsonify({"conversations": [serialize_conversation(item) for item in items]})
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New conversation").strip()[:120] or "New conversation"
    conversation = Conversation(owner_id=current_user.id, title=title)
    db.session.add(conversation)
    db.session.commit()
    return jsonify({"conversation": serialize_conversation(conversation)}), 201


@app.route("/api/conversations/import", methods=["POST"])
@api_login_required
def import_conversations():
    data = request.get_json(silent=True) or {}
    chats = data.get("chats")
    if not isinstance(chats, list) or len(chats) > 50:
        return jsonify({"status": "error", "error": "Import up to 50 conversations at a time."}), 400
    imported = []
    for chat_data in chats:
        if not isinstance(chat_data, dict):
            continue
        source_id = str(chat_data.get("id") or "")[:100]
        if source_id and Conversation.query.filter_by(owner_id=current_user.id, source_id=source_id).first():
            continue
        title = str(chat_data.get("title") or "Imported conversation").strip()[:120] or "Imported conversation"
        conversation = Conversation(owner_id=current_user.id, source_id=source_id or None, title=title)
        db.session.add(conversation)
        messages = chat_data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        for item in messages[:200]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "")[:50000]
            if item["role"] == "assistant":
                content = sanitize_html(content)
            else:
                content = content[:20000]
            db.session.add(Message(
                conversation=conversation,
                owner_id=current_user.id,
                role=item["role"],
                content=content,
                code=str(item.get("code") or "")[:50000],
                mode=item.get("mode") if item.get("mode") in MODE_SYSTEM_PROMPTS else "generate",
                language=normalize_language(item.get("language")),
                analytics_eligible=False,
            ))
        imported.append(conversation)
    db.session.commit()
    return jsonify({"status": "ok", "imported": len(imported)})


@app.route("/api/conversations/<conversation_id>", methods=["GET", "PATCH", "DELETE"])
@api_login_required
def conversation_api(conversation_id):
    conversation = Conversation.query.filter_by(id=conversation_id, owner_id=current_user.id).first()
    if conversation is None:
        return jsonify({"status": "error", "error": "Conversation not found."}), 404
    if request.method == "GET":
        return jsonify({"conversation": serialize_conversation(conversation)})
    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not 1 <= len(title) <= 120:
            return jsonify({"status": "error", "error": "Conversation title must be 1–120 characters."}), 400
        conversation.title = title
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"conversation": serialize_conversation(conversation)})
    db.session.delete(conversation)
    db.session.commit()
    return jsonify({"status": "ok"})


@app.delete("/api/conversations/<conversation_id>/messages")
@api_login_required
def clear_conversation_messages(conversation_id):
    conversation = Conversation.query.filter_by(id=conversation_id, owner_id=current_user.id).first()
    if conversation is None:
        return jsonify({"status": "error", "error": "Conversation not found."}), 404
    Message.query.filter_by(conversation_id=conversation.id, owner_id=current_user.id).delete()
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"conversation": serialize_conversation(conversation)})


@app.route("/api/prompt-templates/<int:template_id>")
@api_login_required
def prompt_template_api(template_id):
    template = PromptTemplate.query.filter_by(id=template_id, owner_id=current_user.id).first()
    if template is None:
        return jsonify({"status": "error", "error": "Template not found."}), 404
    return jsonify({
        "id": template.id,
        "title": template.title,
        "prompt": template.prompt,
        "mode": template.mode,
        "language": template.language,
    })


@app.route("/prompts", methods=["GET", "POST"])
@login_required
def prompts():
    if request.method == "POST":
        template, error = validate_prompt_form(request.form)
        if error:
            flash(error, "error")
        elif PromptTemplate.query.filter_by(owner_id=current_user.id, title=template["title"]).first():
            flash("You already have a template with that title.", "error")
        else:
            db.session.add(PromptTemplate(owner_id=current_user.id, **template))
            db.session.commit()
            flash("Prompt template created.", "success")
            return redirect(url_for("prompts"))
    search = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    query = PromptTemplate.query.filter_by(owner_id=current_user.id)
    if search:
        pattern = f"%{search[:100]}%"
        query = query.filter(or_(
            PromptTemplate.title.ilike(pattern),
            PromptTemplate.description.ilike(pattern),
            PromptTemplate.prompt.ilike(pattern),
        ))
    if category in PROMPT_CATEGORIES:
        query = query.filter_by(category=category)
    templates = query.order_by(PromptTemplate.updated_at.desc()).all()
    return render_template(
        "prompts.html",
        templates=templates,
        categories=PROMPT_CATEGORIES,
        modes=MODE_SYSTEM_PROMPTS,
        languages=sorted(set(LANGUAGE_ALIASES.values())),
        search=search,
        selected_category=category,
    )


def validate_prompt_form(form):
    title = (form.get("title") or "").strip()
    description = (form.get("description") or "").strip()
    prompt = (form.get("prompt") or "").strip()
    category = form.get("category")
    mode = form.get("mode")
    language = normalize_language(form.get("language"))
    if not 1 <= len(title) <= 100:
        return None, "Template title must be 1–100 characters."
    if len(description) > 300 or not prompt or len(prompt) > 20000:
        return None, "Add a prompt (up to 20,000 characters) and keep the description under 300 characters."
    if category not in PROMPT_CATEGORIES or mode not in MODE_SYSTEM_PROMPTS:
        return None, "Choose a valid template category and AI mode."
    return {
        "title": title,
        "description": description,
        "prompt": prompt,
        "category": category,
        "mode": mode,
        "language": language,
    }, None


@app.route("/prompts/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def edit_prompt(template_id):
    template = PromptTemplate.query.filter_by(id=template_id, owner_id=current_user.id).first_or_404()
    if request.method == "POST":
        values, error = validate_prompt_form(request.form)
        duplicate = PromptTemplate.query.filter(
            PromptTemplate.owner_id == current_user.id,
            PromptTemplate.title == (request.form.get("title") or "").strip(),
            PromptTemplate.id != template.id,
        ).first()
        if error:
            flash(error, "error")
        elif duplicate:
            flash("You already have a template with that title.", "error")
        else:
            for key, value in values.items():
                setattr(template, key, value)
            db.session.commit()
            flash("Prompt template updated.", "success")
            return redirect(url_for("prompts"))
    return render_template(
        "edit_prompt.html",
        template=template,
        categories=PROMPT_CATEGORIES,
        modes=MODE_SYSTEM_PROMPTS,
        languages=sorted(set(LANGUAGE_ALIASES.values())),
    )


@app.post("/prompts/<int:template_id>/delete")
@login_required
def delete_prompt(template_id):
    template = PromptTemplate.query.filter_by(id=template_id, owner_id=current_user.id).first_or_404()
    db.session.delete(template)
    db.session.commit()
    flash("Prompt template deleted.", "success")
    return redirect(url_for("prompts"))


@app.route("/snippets")
@login_required
def snippets():
    items = SavedSnippet.query.filter_by(owner_id=current_user.id).order_by(SavedSnippet.updated_at.desc()).all()
    return render_template("snippets.html", snippets=items)


@app.route("/api/snippets", methods=["GET", "POST"])
@api_login_required
def snippets_api():
    if request.method == "GET":
        items = SavedSnippet.query.filter_by(owner_id=current_user.id).order_by(SavedSnippet.updated_at.desc()).all()
        return jsonify({"snippets": [{
            "id": item.id,
            "title": item.title,
            "code": item.code,
            "language": item.language,
        } for item in items]})
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "").strip()
    code = str(data.get("code") or "").strip()
    language = normalize_language(data.get("language"))
    if not 1 <= len(title) <= 100 or not code or len(code) > 50000:
        return jsonify({"status": "error", "error": "Enter a title and code (up to 50,000 characters)."}), 400
    item = SavedSnippet(owner_id=current_user.id, title=title, code=code, language=language)
    db.session.add(item)
    db.session.commit()
    return jsonify({"status": "ok", "id": item.id}), 201


@app.route("/snippets/<int:snippet_id>/edit", methods=["GET", "POST"])
@login_required
def edit_snippet(snippet_id):
    snippet = SavedSnippet.query.filter_by(id=snippet_id, owner_id=current_user.id).first_or_404()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        code = (request.form.get("code") or "").strip()
        if not 1 <= len(title) <= 100 or not code or len(code) > 50000:
            flash("Enter a title and code (up to 50,000 characters).", "error")
        else:
            snippet.title = title
            snippet.code = code
            snippet.language = normalize_language(request.form.get("language"))
            db.session.commit()
            flash("Snippet updated.", "success")
            return redirect(url_for("snippets"))
    return render_template("edit_snippet.html", snippet=snippet, languages=sorted(set(LANGUAGE_ALIASES.values())))


@app.post("/snippets/<int:snippet_id>/delete")
@login_required
def delete_snippet(snippet_id):
    snippet = SavedSnippet.query.filter_by(id=snippet_id, owner_id=current_user.id).first_or_404()
    db.session.delete(snippet)
    db.session.commit()
    flash("Snippet deleted.", "success")
    return redirect(url_for("snippets"))


@app.route("/analytics")
@login_required
def analytics():
    user_filter = (
        Message.query.filter_by(owner_id=current_user.id, role="user", analytics_eligible=True)
    )
    total_requests = user_filter.count()
    conversations_count = Conversation.query.filter_by(owner_id=current_user.id).count()
    generated_code_responses = Message.query.filter_by(
        owner_id=current_user.id,
        role="assistant",
        analytics_eligible=True,
        generated_code=True,
    ).count()
    mode_rows = (
        db.session.query(Message.mode, func.count(Message.id))
        .filter_by(owner_id=current_user.id, role="user", analytics_eligible=True)
        .group_by(Message.mode)
        .all()
    )
    language_rows = (
        db.session.query(Message.language, func.count(Message.id))
        .filter_by(owner_id=current_user.id, role="user", analytics_eligible=True)
        .group_by(Message.language)
        .all()
    )
    since = datetime.now(timezone.utc) - timedelta(days=6)
    activity_rows = (
        db.session.query(func.date(Message.created_at), func.count(Message.id))
        .filter(
            Message.owner_id == current_user.id,
            Message.role == "user",
            Message.analytics_eligible.is_(True),
            Message.created_at >= since,
        )
        .group_by(func.date(Message.created_at))
        .all()
    )
    activity = {str(day): count for day, count in activity_rows}
    activity_days = []
    for offset in range(6, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).date()
        activity_days.append({"label": day.strftime("%a"), "count": activity.get(day.isoformat(), 0)})
    return render_template(
        "analytics.html",
        conversations_count=conversations_count,
        total_requests=total_requests,
        generated_code_responses=generated_code_responses,
        mode_data=sorted(mode_rows, key=lambda row: row[1], reverse=True),
        language_data=sorted(language_rows, key=lambda row: row[1], reverse=True),
        activity_days=activity_days,
        recent_activity_count=sum(item["count"] for item in activity_days),
        max_activity=max((item["count"] for item in activity_days), default=0),
        max_modes=max((count for _, count in mode_rows), default=0),
        max_languages=max((count for _, count in language_rows), default=0),
    )


@app.errorhandler(413)
def request_too_large(_error):
    del _error
    if request.path.startswith("/api/") or request.accept_mimetypes.accept_json:
        return jsonify({"status": "error", "error": "Request is too large."}), 413
    flash("Request is too large.", "error")
    return redirect(url_for("home"))


@app.errorhandler(SQLAlchemyError)
def database_error(_error):
    del _error
    db.session.rollback()
    app.logger.error("Database operation failed")
    if request.path.startswith("/api/") or request.accept_mimetypes.accept_json:
        return jsonify({"status": "error", "error": "The data operation could not be completed. Please try again."}), 503
    flash("The data operation could not be completed. Please try again.", "error")
    return redirect(url_for("home" if current_user.is_authenticated else "login"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
# Copilot file editing test
