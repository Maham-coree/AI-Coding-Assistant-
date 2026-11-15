## AI Coding Assistant
**A web-based coding assistant that helps users generate, understand, debug, optimize, and convert code through a simple interface.**

## Table of Contents
- Overview
- Features
- AI Modes
- Technology Stack
- Project Structure
- Getting Started
- Environment Variables
- Database Setup
- Running Tests
- Deployment
- Security


Overview
AI Coding Assistant is designed to make common programming tasks easier. Users can work with code in one place, save useful results, organize conversations, and reuse prompt templates.

The application provides five coding modes and a workspace for managing coding tasks and saved content.

## Features
- User authentication: Register, log in, and log out securely.
- Password protection: Passwords are stored as hashes rather than plain text.
- Five coding modes: Generate, Explain, Debug, Optimize, and Convert.
- Conversation management: Create and access coding conversations.
- Saved snippets: Save and manage useful code snippets.
- Prompt templates: Create, search, save, and reuse prompt templates.
- User preferences: Store supported interface and account preferences.
- Analytics dashboard: View activity information recorded by the application.
- Responsive interface: Use the application on desktop and smaller screens.
- Password recovery: Request a time-limited, single-use reset link without revealing whether an account exists.

## AI Modes
Mode	Purpose
Generate	Create code from a task description.
Explain	Understand what a code snippet does.
Debug	Review code and help identify possible errors.
Optimize	Suggest ways to improve code readability or efficiency.
Convert	Convert code from one programming language or format to another.


## Technology Stack
- Backend: Python, Flask
- Frontend: HTML, CSS, JavaScript
- AI service: Google Gemini API
- Database: PostgreSQL for hosted deployment; SQLite may be used for local development where configured
- ORM: SQLAlchemy
- Database migrations: Flask-Migrate and Alembic
- Authentication and security: Flask session management and Werkzeug password hashing
- Application server: Gunicorn
- Deployment: Render via Gunicorn; Vercel requires additional function configuration

## Project Structure
The project is organized into backend application code, frontend templates and static assets, database migrations, and tests. Exact filenames and folders may vary as the project develops.
AI-Coding-Assistant/
├── app.py
├── .env.example
├── templates/
├── static/
├── migrations/
├── tests/
├── requirements.txt
└── README.md

## Getting Started
1. Clone the repository
git clone https://github.com/Maham-coree/AI-Coding-Assistant-.git
cd AI-Coding-Assistant-
2. Create a virtual environment
Windows:
python -m venv venv
venv\Scripts\activate
macOS / Linux:
python3 -m venv venv
source venv/bin/activate
3. Install dependencies
pip install -r requirements.txt
4. Configure environment variables
Create a .env file in the project root and add the required values. See the Environment Variables section below.
5. Run the application
Use the Flask command configured for the project:
flask --app app run
Then open the local address shown in the terminal.

## Environment Variables
Configure the following environment variables in your local .env file and in your deployment platform:
| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Sets the application environment, such as `development` or `production`. |
| `SECRET_KEY` | Protects Flask sessions. Use a long, random value. |
| `DATABASE_URL` | Connection URL for the configured database. Use PostgreSQL in production; local development can use SQLite. |
| `GEMINI_API_KEY` | API key used to connect to Gemini. |
| `REDIS_URL` | Optional shared rate-limit storage for multi-worker deployments; the application can run without Redis. |
| `SMTP_HOST` | SMTP server for password-reset email. |
| `SMTP_PORT` | SMTP port; defaults to `587` (STARTTLS). Port `465` uses implicit TLS. |
| `SMTP_USERNAME` | SMTP authentication username. |
| `SMTP_PASSWORD` | SMTP authentication password. |
| `MAIL_DEFAULT_SENDER` | Sender address for reset email. |
| `PUBLIC_BASE_URL` | Public application origin used to construct reset links; production must use HTTPS. |

The SMTP settings are optional for running the application, but `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_DEFAULT_SENDER`, and `PUBLIC_BASE_URL` must be valid to deliver reset links. `SMTP_PORT` defaults to 587 (STARTTLS); port 465 uses implicit TLS. Production `PUBLIC_BASE_URL` must be the public HTTPS origin. Without complete SMTP settings, the application does not create or send a reset token. On delivery failure it invalidates the token, logs only the exception class, and keeps the response generic; it does not claim that mail was sent. Reset tokens are stored as hashes, expire after 30 minutes, and are single-use.
Do not publish your .env file, database credentials, secret key, or API key. Make sure .env is excluded from Git.

## Rate Limiting
The existing registration, login, forgot-password, and reset-password limits are enforced by Flask-Limiter. Set `REDIS_URL` to a provider-supplied Redis URL to share counters across application instances; use the provider's TLS URL (`rediss://`) when required. Redis stores rate-limit counters only, not account data, passwords, reset tokens, conversations, prompts, or snippets.

Without `REDIS_URL`, local development uses in-process memory. If configured Redis is unreachable, the limiter logs a warning and falls back to in-process memory so the application remains available and continues enforcing the same limits on that instance. This fallback is not shared across instances and is less reliable in serverless deployments until Redis recovers. Redis connectivity has not been verified in this environment.

## Database Setup
The application uses SQLAlchemy and Flask-Migrate/Alembic. Local development defaults to SQLite; production requires the configured PostgreSQL `DATABASE_URL` and will not fall back to SQLite.

After confirming that `DATABASE_URL` targets the intended database, apply migrations as a controlled deployment step:
```sh
flask --app app db upgrade
```
Do not run migrations automatically during application import.

## Running Tests
Run the automated suite with:
```sh
python -m unittest discover -s tests -v
```
The tests set a unique temporary SQLite `DATABASE_URL` before importing the Flask app and abort if the initialized SQLAlchemy engine does not use that isolated file. They never use the deployment database.

Production smoke checks against the configured PostgreSQL database and Gemini service passed: the app used PostgreSQL, all model tables and columns matched, Alembic was at revision `74b3af18c2de`, a live request through `/chat` returned a response, and registration/login, conversation/prompt/snippet round-trips, account isolation, and password reset with mocked email delivery succeeded. Smoke-test database writes were rolled back. Actual SMTP delivery and a live Redis connection have not been tested because those services are not configured.

## Deployment
### Render
Create a Render Web Service with:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Configure `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL` (hosted PostgreSQL), and `GEMINI_API_KEY` in the Render environment. Add the SMTP variables above to enable password-reset email.

### Vercel
`api/index.py` exports the existing Flask application, and `vercel.json` routes requests to that Python Function. The app selects `/tmp/instance` on Vercel and requires PostgreSQL for persistent data; it will not fall back to SQLite in production.

To deploy:
1. Import this repository into Vercel with the repository root as the project root.
2. Set `APP_ENV=production`, `SECRET_KEY` (random, at least 32 characters), `DATABASE_URL` (hosted PostgreSQL), and `GEMINI_API_KEY` in Vercel Project Settings → Environment Variables.
3. If using shared rate limiting, set `REDIS_URL` to the URL provided by your Redis service. Without it, the application uses process-local rate limits.
4. To enable password reset email, also set `SMTP_HOST`, `SMTP_PORT` (587 STARTTLS or 465 implicit TLS), `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_DEFAULT_SENDER`, and `PUBLIC_BASE_URL` to the deployed HTTPS origin.
5. Deploy from Vercel and inspect build/runtime logs. Do not put credentials in the repository or rely on a local `.env` file.
6. Smoke-test health, authentication, reset email delivery, AI modes, and database-backed features on the deployed URL. Creating these files does not establish that a deployment succeeded.

Do not run database migrations during import. Only run a migration as a separate, controlled operation after verifying that the configured `DATABASE_URL` points to the intended database.

## Security
- Passwords should be stored using secure password hashing.
- Keep secret keys, API keys, and database credentials out of source control.
- Use environment variables for deployment configuration.
- Use HTTPS for the deployed application.
- Keep dependencies updated and review application logs when diagnosing errors.


## Author

**Maham Waseem**


Passionate about AI, Python, and software development.

GitHub: <https://github.com/Maham-coree>

LinkedIn: <https://www.linkedin.com/in/maham-waseem-89735134a>

Project: AI Coding Assistant
Repository: GitHub – AI Coding Assistant
