# UKI Student Management API

A Flask REST API for a multi-tenant tuition center / student management SaaS platform. It supports institution onboarding, classroom management, attendance tracking, study session logging, SMS alert logs, and role-based billing.

**Base URL (local):** `http://localhost:5000`

---

## Features

- JWT authentication with role-based access control
- Multi-tenant institutions (super admin, institution admin, teacher, student, parent)
- Classroom and student management with CSV import
- Attendance marking with automatic late/absent detection and SMS alerts
- Study session tracking and analytics for students
- Billing records and SMS log history per institution
- PDF export of classroom attendance
- Background scheduler for absentee sweeps

---

## Tech Stack

| Layer        | Technology                          |
| ------------ | ----------------------------------- |
| Framework    | Flask 3.x                           |
| Database     | MySQL (via PyMySQL + SQLAlchemy)    |
| Auth         | Flask-JWT-Extended                  |
| Scheduler    | APScheduler                         |
| PDF          | ReportLab                           |
| Production   | Gunicorn                            |

---

## Prerequisites

- Python 3.10+
- MySQL 8.x running locally (or a remote MySQL instance)
- VS Code with **Thunder Client** extension, **or** **Postman** desktop/app

---

## Getting Started

### 1. Clone and install dependencies

```bash
cd api
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Copy the example env file and update your values:

```bash
cp .env.example .env
```

| Variable                         | Description                              | Default                    |
| -------------------------------- | ---------------------------------------- | -------------------------- |
| `DB_USER`                        | MySQL username                           | `root`                     |
| `DB_PASSWORD`                    | MySQL password                           | —                          |
| `DB_HOST`                        | MySQL host                               | `localhost`                |
| `DB_PORT`                        | MySQL port                               | `3306`                     |
| `DB_NAME`                        | Database name                            | `student_mgt_sys`         |
| `DATABASE_URL`                   | Complete SQLAlchemy database URL         | —                          |
| `MYSQL_URL`                      | Railway MySQL connection URL fallback    | —                          |
| `JWT_SECRET_KEY`                 | Secret for signing JWT tokens            | —                          |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | Token lifetime in minutes              | `1440`                     |
| `FLASK_DEBUG`                    | Enable Flask debug mode                  | `false`                    |
| `CORS_ORIGINS`                   | Comma-separated allowed origins          | `http://localhost:3000`    |
| `FRONTEND_URL`                   | One frontend origin to allow             | —                          |
| `CORS_ALLOW_VERCEL`              | Allow Vercel preview origins             | `true`                     |
| `PORT`                           | HTTP port; Railway supplies this         | `5000`                     |

The database is created automatically on first startup if it does not exist.

### 3. Run the API

```bash
python run.py
```

The server starts at `http://localhost:5000`.

Verify it is running:

```http
GET http://localhost:5000/api/health
```

Expected response:

```json
{ "status": "ok" }
```

## Deploying the API to Railway

Create a Railway service from this `student-management-system-api` directory.
Railway will use the `Procfile`, bind to its assigned `PORT`, and expose the
health check at `/api/health`.

If you add a Railway MySQL service, connect it to the API service. The API
accepts Railway's `MYSQL_URL` or `MYSQLHOST`/`MYSQLPORT`/`MYSQLDATABASE`/
`MYSQLUSER`/`MYSQLPASSWORD` variables. You can also set `DATABASE_URL`
explicitly; it takes precedence over `MYSQL_URL`.

Set these API service variables:

```env
JWT_SECRET_KEY=<long-random-secret>
SECRET_KEY=<different-long-random-secret>
FRONTEND_URL=https://your-vercel-app.vercel.app
CORS_ORIGINS=https://your-vercel-app.vercel.app
```

Keep `CORS_ALLOW_VERCEL=true` if Vercel preview deployments must access the
API. After deployment, copy the Railway public URL into the frontend's
Vercel variable:

```env
NEXT_PUBLIC_API_URL=https://your-api.up.railway.app
```

Verify the connection by opening
`https://your-api.up.railway.app/api/health` and checking for
`{ "status": "ok" }`.

## Seed demo data (optional)

Populate the database with a demo institution, users, classrooms, and sample records:

```bash
python seed.py
```

To clear and reseed:

```bash
python seed.py --force
```

---

## Authentication

Most endpoints require a JWT Bearer token.

### Login

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "admin@uki-demo.com",
  "password": "Demo@123"
}
```

**Response (200):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 2,
    "email": "admin@uki-demo.com",
    "role": "institution_admin",
    "full_name": "Institution Admin"
  }
}
```

### Using the token

Add the token to every protected request:

```http
Authorization: Bearer <access_token>
```

### Roles

| Role               | Description                                      |
| ------------------ | ------------------------------------------------ |
| `super_admin`      | Platform-wide access                             |
| `institution_admin`| Manages one institution                          |
| `teacher`          | Marks attendance, views assigned classrooms      |
| `student`          | Study logs, own attendance                       |
| `parent`           | Views children's attendance                      |

### Demo credentials

After running `python seed.py`:

| Role              | Email                      | Password        |
| ----------------- | -------------------------- | --------------- |
| Super Admin       | `superadmin@platform.com`  | `SuperAdmin@123`|
| Institution Admin | `admin@uki-demo.com`       | `Demo@123`      |
| Teacher 1         | `teacher1@uki-demo.com`    | `Demo@123`      |
| Teacher 2         | `teacher2@uki-demo.com`    | `Demo@123`      |
| Student 1         | `kavisan@test.com`         | `Demo@123`      |
| Student 2         | `abiraami@test.com`        | `Demo@123`      |
| Parent 1          | `selvam@test.com`          | `Demo@123`      |
| Parent 2          | `balan@test.com`           | `Demo@123`      |

---

## API Endpoints

### Health

| Method | Endpoint        | Auth | Roles |
| ------ | --------------- | ---- | ----- |
| GET    | `/api/health`   | No   | —     |

### Auth (`/api/auth`)

| Method | Endpoint                  | Auth | Roles                              |
| ------ | ------------------------- | ---- | ---------------------------------- |
| POST   | `/login`                  | No   | —                                  |
| POST   | `/register-institution`   | No   | —                                  |
| POST   | `/register`               | Yes  | `super_admin`, `institution_admin` |

**Register institution (public):**

```json
{
  "name": "My Tuition Center",
  "subdomain": "my-center",
  "admin_name": "John Doe",
  "admin_email": "john@center.com",
  "admin_password": "SecurePass1",
  "admin_phone": "+94770000000"
}
```

**Register user (authenticated):**

```json
{
  "role": "teacher",
  "email": "newteacher@center.com",
  "password": "Demo@123",
  "full_name": "New Teacher",
  "phone_number": "+94770000099"
}
```

### Institutions (`/api/institutions`)

| Method | Endpoint                        | Auth | Roles                              |
| ------ | ------------------------------- | ---- | ---------------------------------- |
| POST   | `/`                             | Yes  | `super_admin`                      |
| GET    | `/`                             | Yes  | `super_admin`                      |
| PATCH  | `/:institution_id/status`       | Yes  | `super_admin`                      |
| GET    | `/:institution_id/billing`      | Yes  | `super_admin`, `institution_admin` |

**Create institution (tuition center):**

Creates the institution row and automatically creates a default **institution admin** user linked to that `institution_id`. A temporary password is generated and returned once so Super Admin can share login details with the center owner.

Request body:

```json
{
  "name": "Bright Minds Tuition",
  "subdomain": "bright-minds",
  "admin_name": "Center Owner",
  "admin_email": "owner@brightminds.com",
  "admin_phone": "+94770000001"
}
```

`admin_name`, `admin_email`, and `admin_phone` are optional. If `admin_email` is omitted, the API generates one like `admin.bright-minds@studentmgt.app`.

Example `201` response:

```json
{
  "institution": {
    "id": 12,
    "name": "Bright Minds Tuition",
    "subdomain": "bright-minds",
    "status": "Active",
    "created_at": "2026-07-23T12:00:00"
  },
  "admin": {
    "id": 45,
    "institution_id": 12,
    "email": "owner@brightminds.com",
    "role": "institution_admin",
    "full_name": "Center Owner",
    "phone_number": "+94770000001",
    "is_active": true
  },
  "admin_credentials": {
    "email": "owner@brightminds.com",
    "password": "GeneratedOnce!",
    "full_name": "Center Owner",
    "role": "institution_admin",
    "institution_id": 12
  }
}
```

**Update status:**

```json
{ "status": "Active" }
```

Valid values: `Active`, `Suspended`

### Classrooms (`/api/classrooms`)

| Method | Endpoint | Auth | Roles                                              |
| ------ | -------- | ---- | -------------------------------------------------- |
| GET    | `/`      | Yes  | `super_admin`, `institution_admin`, `teacher`      |
| POST   | `/`      | Yes  | `institution_admin`                                |

**Create classroom:**

```json
{
  "name": "Mathematics Grade 10",
  "schedule_start_time": "09:00",
  "teacher_id": 3
}
```

### Students (`/api/students`)

| Method | Endpoint          | Auth | Roles                                    |
| ------ | ----------------- | ---- | ---------------------------------------- |
| GET    | `/`               | Yes  | `institution_admin`, `teacher`, `super_admin` |
| POST   | `/import`         | Yes  | `institution_admin`                      |
| GET    | `/my-children`    | Yes  | `parent`                                 |
| GET    | `/teachers`       | Yes  | `institution_admin`, `super_admin`       |
| GET    | `/import/template`| Yes  | `institution_admin`                      |

**Import students:** send a CSV file as `multipart/form-data` with field name `file`, or send raw CSV in the request body.

### Attendance (`/api/attendance`)

| Method | Endpoint                              | Auth | Roles                                                        |
| ------ | ------------------------------------- | ---- | ------------------------------------------------------------ |
| POST   | `/mark`                               | Yes  | `teacher`                                                    |
| POST   | `/scan`                               | Yes  | `teacher`                                                    |
| GET    | `/today`                              | Yes  | `teacher`, `institution_admin`, `super_admin`                |
| GET    | `/classroom/:classroom_id`            | Yes  | `teacher`, `institution_admin`, `super_admin`                |
| GET    | `/student/:student_id`                | Yes  | `student`, `parent`, `teacher`, `institution_admin`, `super_admin` |
| GET    | `/report`                             | Yes  | `teacher`, `institution_admin`, `super_admin`                |
| GET    | `/report/export/csv`                  | Yes  | `teacher`, `institution_admin`                               |
| GET    | `/report/export/pdf`                  | Yes  | `teacher`, `institution_admin`                               |
| GET    | `/classroom/:classroom_id/export/pdf` | Yes  | `teacher`, `institution_admin`                               |

**Student history query params:** optional `classroom_id`, `start_date`, `end_date`. Response includes `summary` with total classes, present, absent, and percentage.

**Report / export query params:** required `classroom_id`, `start_date`, `end_date` (YYYY-MM-DD). Summary columns: Student Name, ID, Total Present, Total Absent, Percentage.

**Mark attendance:**

```json
{
  "student_id": 1,
  "classroom_id": 1,
  "status": "Present"
}
```

`status` is optional. If omitted, the API calculates `Present`, `Late`, or `Absent` from the classroom schedule.

**QR timetable behavior:** a QR scan marks the student's active timetable class. If the next
timetable class starts exactly when the active class ends, it is treated as a continuous class
and is marked by the same scan. A later class with any real break remains separate and can be
marked by scanning again during its 10-minute pre-start window or while it is in progress.

### Study Logs (`/api/study-logs`)

| Method | Endpoint     | Auth | Roles                          |
| ------ | ------------ | ---- | ------------------------------ |
| POST   | `/toggle`    | Yes  | `student`                      |
| GET    | `/analytics` | Yes  | `student`, `institution_admin` |
| GET    | `/active`    | Yes  | `student`                      |

**Analytics query param:** `?days=30` (default: 30)

### SMS Logs (`/api/sms-logs`)

| Method | Endpoint | Auth | Roles                          |
| ------ | -------- | ---- | ------------------------------ |
| GET    | `/`      | Yes  | `institution_admin`, `super_admin` |

---

## Error Responses

Errors are returned as JSON:

```json
{
  "errors": ["Invalid credentials"]
}
```

| Status | Meaning                    |
| ------ | -------------------------- |
| 400    | Validation error           |
| 401    | Invalid or missing token   |
| 403    | Insufficient permissions   |
| 404    | Resource not found         |
| 500    | Server error               |

---

## Thunder Client Workflow (VS Code)

Use Thunder Client when you want to test the API directly inside VS Code.

### Step 1 — Install Thunder Client

1. Open VS Code.
2. Go to **Extensions** (`Ctrl+Shift+X`).
3. Search for **Thunder Client** and install it.
4. Open the Thunder Client panel from the sidebar (lightning bolt icon).

### Step 2 — Create an environment

1. In Thunder Client, open **Env** (environments tab).
2. Click **New Environment** and name it `Local Dev`.
3. Add these variables:

| Variable       | Value                        |
| -------------- | ---------------------------- |
| `baseUrl`      | `http://localhost:5000`      |
| `accessToken`  | *(leave empty for now)*      |

4. Set `Local Dev` as the active environment.

### Step 3 — Create a collection

1. Open the **Collections** tab.
2. Click **New Collection** and name it `UKI Skill Swap API`.
3. Add folders to mirror the API modules:
   - `Auth`
   - `Institutions`
   - `Classrooms`
   - `Students`
   - `Attendance`
   - `Study Logs`
   - `SMS Logs`

### Step 4 — Health check request

1. Inside the collection, create a request:
   - **Name:** `Health Check`
   - **Method:** `GET`
   - **URL:** `{{baseUrl}}/api/health`
2. Send the request. You should receive `{ "status": "ok" }`.

### Step 5 — Login and save the token

1. Create a request under `Auth`:
   - **Name:** `Login`
   - **Method:** `POST`
   - **URL:** `{{baseUrl}}/api/auth/login`
   - **Body → JSON:**

```json
{
  "email": "admin@uki-demo.com",
  "password": "Demo@123"
}
```

2. Send the request.
3. Copy `access_token` from the response.
4. Go to **Env → Local Dev** and paste the token into `accessToken`.
5. Save the environment.

> **Tip:** For a faster workflow, use Thunder Client's **Tests** tab on the Login request to auto-save the token:
>
> ```js
> const json = tc.response.json();
> tc.setVar("accessToken", json.access_token);
> ```

### Step 6 — Set collection-level auth

1. Open your collection settings (gear icon on the collection).
2. Under **Auth**, choose **Bearer Token**.
3. Set the token value to `{{accessToken}}`.
4. All requests in the collection will inherit this header automatically.

### Step 7 — Test protected endpoints

Add and run these sample requests (all inherit Bearer auth from the collection):

| Name                    | Method | URL                                              |
| ----------------------- | ------ | ------------------------------------------------ |
| List Classrooms         | GET    | `{{baseUrl}}/api/classrooms`                     |
| List Students           | GET    | `{{baseUrl}}/api/students`                       |
| Classroom Attendance    | GET    | `{{baseUrl}}/api/attendance/classroom/1`         |
| Mark Attendance         | POST   | `{{baseUrl}}/api/attendance/mark`                |
| Study Analytics         | GET    | `{{baseUrl}}/api/study-logs/analytics?days=7`    |
| SMS Logs                | GET    | `{{baseUrl}}/api/sms-logs`                       |

**Mark Attendance body (login as `teacher1@uki-demo.com` first):**

```json
{
  "student_id": 1,
  "classroom_id": 1
}
```

### Step 8 — Switch roles

To test different role permissions:

1. Change the login email (e.g. `teacher1@uki-demo.com`, `kavisan@test.com`).
2. Re-run **Login** to refresh `accessToken`.
3. Re-run protected requests and confirm allowed/denied responses.

### Recommended Thunder Client request order

```
1. Health Check
2. Login (Institution Admin)
3. List Classrooms
4. List Students
5. Login (Teacher)
6. Mark Attendance
7. Get Classroom Attendance
8. Login (Student)
9. Toggle Study Session
10. Get Study Analytics
```

---

## Postman Workflow

Use Postman when you need shareable collections, team environments, or automated test scripts.

### Step 1 — Install Postman

1. Download from [postman.com/downloads](https://www.postman.com/downloads/).
2. Sign in or create a free account (optional but useful for syncing).

### Step 2 — Create an environment

1. Click the **Environments** icon in the left sidebar.
2. Click **+** to create a new environment named `UKI Local`.
3. Add variables:

| Variable       | Type    | Initial Value              | Current Value              |
| -------------- | ------- | -------------------------- | -------------------------- |
| `baseUrl`      | default | `http://localhost:5000`    | `http://localhost:5000`    |
| `accessToken`  | secret  | *(empty)*                  | *(empty)*                  |

4. Save and select `UKI Local` from the environment dropdown (top-right).

### Step 3 — Create a collection

1. Click **Collections → +** to create `UKI Skill Swap API`.
2. Add folders: `Auth`, `Institutions`, `Classrooms`, `Students`, `Attendance`, `Study Logs`, `SMS Logs`.

### Step 4 — Health check

1. Inside the collection, add a request:
   - **Name:** `Health Check`
   - **Method:** `GET`
   - **URL:** `{{baseUrl}}/api/health`
2. Click **Send**. Expect `200` with `{ "status": "ok" }`.

### Step 5 — Login with auto-token script

1. Under `Auth`, create a request:
   - **Name:** `Login`
   - **Method:** `POST`
   - **URL:** `{{baseUrl}}/api/auth/login`
   - **Body → raw → JSON:**

```json
{
  "email": "admin@uki-demo.com",
  "password": "Demo@123"
}
```

2. Open the **Tests** tab and add:

```javascript
if (pm.response.code === 200) {
    const json = pm.response.json();
    pm.environment.set("accessToken", json.access_token);
    pm.test("Login successful", () => {
        pm.expect(json.access_token).to.be.a("string");
    });
}
```

3. Send the request. The `accessToken` environment variable is set automatically.

### Step 6 — Collection-level Bearer auth

1. Click the collection name → **Authorization** tab.
2. Set **Type** to **Bearer Token**.
3. Set **Token** to `{{accessToken}}`.
4. Set individual requests to **Inherit auth from parent** (default).

### Step 7 — Add and run protected requests

Create these requests under the appropriate folders:

| Folder      | Name                 | Method | URL                                              |
| ----------- | -------------------- | ------ | ------------------------------------------------ |
| Classrooms  | List Classrooms      | GET    | `{{baseUrl}}/api/classrooms`                     |
| Students    | List Students        | GET    | `{{baseUrl}}/api/students`                       |
| Attendance  | Mark Attendance      | POST   | `{{baseUrl}}/api/attendance/mark`                |
| Attendance  | Classroom Attendance | GET    | `{{baseUrl}}/api/attendance/classroom/1`         |
| Study Logs  | Toggle Session       | POST   | `{{baseUrl}}/api/study-logs/toggle`              |
| Study Logs  | Analytics            | GET    | `{{baseUrl}}/api/study-logs/analytics?days=30`   |
| SMS Logs    | List SMS Logs        | GET    | `{{baseUrl}}/api/sms-logs`                       |

### Step 8 — Use Collection Runner

1. Click the collection → **Run**.
2. Select requests in this order:
   - Health Check
   - Login
   - List Classrooms
   - List Students
3. Click **Run UKI Skill Swap API**.
4. Review pass/fail results in the runner summary.

### Step 9 — Export and share (optional)

1. Right-click the collection → **Export**.
2. Choose **Collection v2.1** format.
3. Share the `.json` file with teammates.
4. Export the environment the same way (**Environments → … → Export**).

> Import on another machine: **Import → drag the JSON files → select the environment**.

### Step 10 — Test role-based access

1. Duplicate the **Login** request for each role (Teacher, Student, Parent).
2. Change the email in each duplicate's body.
3. Run Login before each role-specific request group to refresh `accessToken`.
4. Confirm `403` responses when a role lacks permission (e.g. a student calling `POST /api/attendance/mark`).

---

## Project Structure

```
api/
├── app/
│   ├── controllers/     # Business logic
│   ├── models/          # SQLAlchemy models
│   ├── routes/          # Flask blueprints (URL routes)
│   ├── seeders/         # Demo data seeder
│   ├── utils/           # PDF, CSV, SMS, alert helpers
│   ├── config.py        # App configuration
│   ├── extensions.py    # DB and JWT instances
│   └── middleware.py    # Role guards and tenant filtering
├── run.py               # Development entry point
├── seed.py              # CLI seeder script
├── requirements.txt
├── .env.example
└── Procfile             # Production (Gunicorn)
```

---

## Production

```bash
gunicorn "app:create_app()" --bind 0.0.0.0:5000
```

Or use the included `Procfile` with a platform like Heroku or Railway.

---

## License

Private — UKI Skill Swap final project.
