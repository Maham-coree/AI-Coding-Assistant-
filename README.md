AI Coding Assistant
A web-based AI Coding Assistant built with Python, Flask, HTML, CSS, and JavaScript. It provides a focused workspace for common coding tasks, conversation management, and personal productivity.
Features
AI Coding Modes
- Generate: Create code from a written requirement.
- Explain: Understand code and programming concepts.
- Debug: Review code and help identify errors.
- Optimize: Suggest improvements to code readability and efficiency.
- Convert: Convert code between supported programming languages.
Personal Workspace
- User registration, login, and logout
- Protected pages and user-specific data
- Conversation history and message management
- Create, edit, search, and reuse saved prompt templates
- Save, edit, search, and manage code snippets
- Analytics dashboard based on recorded application activity
- User settings and theme preferences
Security and Data Management
- Password hashing
- Session-based authentication
- Authorization checks for protected features
- User data separation
- Database models and migrations
- Environment-based configuration for sensitive values
Technology Stack
- Backend: Python, Flask
- Frontend: HTML, CSS, JavaScript
- AI service: Google Gemini API
- Database: SQLAlchemy with PostgreSQL for hosted deployment
- Migrations: Flask-Migrate / Alembic
- Deployment: Vercel
Project Structure
AI-Coding-Assistant/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── vercel.json
├── api/
│   └── index.py
├── migrations/
├── static/
│   ├── script.js
│   └── style.css
├── templates/
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── settings.html
│   ├── analytics.html
│   ├── prompts.html
│   └── snippets.html
└── tests/
The exact files and folders may vary as the project develops. Keep this section aligned with the actual repository structure.

Run Locally
1. Clone the repository
git clone https://github.com/Maham-coree/AI-Coding-Assistant-.git
cd AI-Coding-Assistant-
2. Create and activate a virtual environment
Windows (PowerShell):
python -m venv venv
.\venv\Scripts\Activate.ps1
3. Install dependencies
pip install -r requirements.txt
4. Configure environment variables
Create a .env file in the project root and add the required values:
APP_ENV=development
SECRET_KEY=your-long-random-secret-key
DATABASE_URL=your-database-connection-string
GEMINI_API_KEY=your-gemini-api-key
Use the variable names required by the current application configuration. Do not commit .env or real credentials to GitHub.
5. Apply database migrations
flask --app app db upgrade
6. Start the application
python app.py
Open http://127.0.0.1:5000 in your browser.
Deployment on Vercel
This project uses Flask, so it must be configured for Vercel's Python Functions runtime. A normal Flask development server command is not used as the Vercel start command.
Deployment preparation
1. Push the project to the GitHub repository.
2. Make sure the repository contains the Vercel Python entry point and Vercel configuration required by the project.
3. Import the GitHub repository into Vercel.
4. Configure the project settings according to the repository's Vercel configuration.
5. Add the required environment variables in the Vercel project settings.
6. Deploy and review the deployment logs.
Environment variables
Configure the following values in Vercel → Project → Settings → Environment Variables:
Variable	Purpose
APP_ENV	Set to production
SECRET_KEY	A strong, randomly generated secret used by the application
DATABASE_URL	Connection string for the hosted PostgreSQL database
GEMINI_API_KEY	API key used by the Gemini integration


Add any other variables only if the application actually requires them. Never place real secret values in this README or commit them to GitHub.
Database and serverless considerations
- Use a hosted PostgreSQL database for production data.
- Do not rely on a local SQLite file or Vercel's temporary filesystem for persistent user data.
- Vercel's `VERCEL=1` environment variable enables production checks, so set both `SECRET_KEY` and a PostgreSQL `DATABASE_URL`; SQLite remains available for local development.
- The application creates its instance directory only when using SQLite locally. Authentication sessions use signed cookies, and the application does not write uploads or user data to the function filesystem.
- Vercel Functions are serverless and may start or stop between requests. Store conversations, users, prompts, snippets, and settings in the configured database.
- Database connection handling should be suitable for serverless execution.
- Run database migrations as a controlled deployment step; do not assume that a local database automatically exists in Vercel.
- Verify that session and cookie settings work correctly over HTTPS and across serverless requests.
Vercel deployment requires the correct Python Function entry point and configuration for this Flask application. Confirm these files and the current Vercel Python runtime requirements before deploying. Do not assume that a Render Procfile or Gunicorn start command is sufficient for Vercel.

Testing
Run the automated tests locally:
python -m pytest -q
Also test the main user flows in a browser:
- Register, log in, and log out
- Open each of the five AI modes
- Create and revisit conversations
- Create, edit, search, and reuse prompt templates
- Create, edit, and search snippets
- Review analytics and settings
- Confirm that one user's private data is not visible to another user
Before production use, verify the Gemini API integration and hosted PostgreSQL connection using the deployment environment variables.
Current Scope and Notes
- Email verification and password recovery may not be included in the current version.
- Gemini API and hosted PostgreSQL behavior must be verified in the deployed environment.
- Optional services should only be configured if the application actually uses them.
- Update this section as features are completed and tested.
Security Reminders
- Keep .env out of GitHub.
- Never publish API keys, database passwords, or the Flask secret key.
- Use a strong, unique SECRET_KEY in production.
- Use HTTPS and secure cookie settings in production.
- Keep dependencies updated and review authentication, authorization, and user-data isolation before public release.
License
No license has been specified for this project. Unless a license is added, the default copyright rules apply.

## Author

**Maham Waseem**

Passionate about AI, Python, and software development.

GitHub: <https://github.com/Maham-coree>

LinkedIn: <https://www.linkedin.com/in/maham-waseem-89735134a>
