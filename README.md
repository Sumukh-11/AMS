# Stride

Stride is a local Windows desktop athlete workspace. `run.bat` opens the packaged native app when it exists, or launches the development version in a browser.

## Run

Python 3.11 or newer is recommended.

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Or double-click `run.bat`. Streamlit prints the local address, usually `http://localhost:8501`.

## Build the Windows desktop app

The native window uses the Microsoft Edge WebView2 Runtime. Install the Evergreen Runtime on the target Windows PC if it is not already present. On a development PC, install the build tools and create the package:

```powershell
python -m pip install -r requirements-desktop.txt
build_desktop.bat
```

The build produces `dist/Stride/Stride.exe` and `dist/Stride-Windows.zip`. Keep the full `Stride` folder together when moving the app; the executable uses the bundled files beside it. Double-click `Stride.exe` to launch the native window. Frozen-app data is stored in `%LOCALAPPDATA%\Stride\data`.

Use **Explore the demo workspace** to try the sample, or create an athlete account. To add a coach or other support member, create an invite from the athlete's **Team** workspace. The support member registers with that code and gets a separate login.

Each signed-in user can edit their own name, email, sport, team, and training city in **Profile**. The **Admin sign-in** tab stays disabled until an administrator is explicitly configured; there is no default admin password. Set both values before starting Stride:

```powershell
$env:STRIDE_ADMIN_EMAIL = "admin@example.com"
$env:STRIDE_ADMIN_PASSWORD = "use-a-unique-password-at-least-12-characters"
python -m streamlit run app.py
```

They can also be stored in `.streamlit/secrets.toml` (ignored by Git). Admins get an account/system overview, not athlete sessions, health-adjacent metrics, media, or private companion chats. Admin accounts cannot be created through public registration.

## Included workflows

- Athlete dashboard with training trends, goals, team notes, and current weather from Open-Meteo when a training city is set.
- Manual session logs and CSV imports from wearable exports. Importing is file-based; OAuth/device-cloud connections are not configured.
- Goals with persisted progress points, support-team invites, and a shared dated notebook.
- Game progression with session XP, levels, rest-friendly streaks, milestone badges, and a weekly quest. Points are tied to saved activity and goal progress.
- Nearby official events from Athletics Canada or the World Athletics country calendar, filtered by sport, city, and radius. Direct registration links are used when published; otherwise the official event listing is linked. World Athletics covers supported athletics disciplines across countries in its calendar.
- Photo capture and video/image uploads. Shared uploads appear in the support team's review queue. Video is stored for human review; this prototype does not perform video motion analysis or benchmark against professional athletes.
- Athlete-only companion chat for sport and general conversation, with multi-turn history, a friendlier listening style, and streaming OpenAI/Claude connectors. It uses recent athlete-entered context when relevant. With no API key, it uses a clearly labeled offline conversational guide instead of claiming to be an AI model.

> NOTHING HAPPENS OVERNIGHT NOTHING TAKES THE WHOLE LIFE - SUMUKH

To enable live chat, either paste a provider key into **AI connection settings** in the app (kept in memory for that session only), or set one or both provider keys in PowerShell before starting Streamlit:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:ANTHROPIC_API_KEY = "your-api-key"
python -m streamlit run app.py
```

When both are configured, choose OpenAI or Claude in the companion. Defaults are `gpt-4o-mini` and `claude-sonnet-4-20250514`; optionally set `OPENAI_MODEL` or `ANTHROPIC_MODEL` to another model available to your account. Alternatively, create `.streamlit/secrets.toml` with one or both keys. That file is ignored by Git. Chat messages and recent training context are sent to the selected provider and may incur charges; the offline guide makes no external AI request. No provider key is configured by default.

## Data and scope

Accounts, session logs, goals, notes, chat, and uploaded media are stored locally in `data/`. Demo content is fictional and labeled. Automatic live sources include current weather and official Athletics Canada/World Athletics event calendars; training data must be logged or imported by the athlete. Global event coverage is limited to competitions listed by World Athletics, and those listings do not always include organizer registration links. This is a product prototype, not a production identity or health-record system: it has no hosted authentication, encrypted database, audit/compliance controls, direct wearable integrations, or clinical validation. Do not use it for emergency, diagnostic, or treatment decisions.

The recommended VS Code Python, environment, and Pylance extensions are listed in `.vscode/extensions.json`; they are already installed in the current workspace.