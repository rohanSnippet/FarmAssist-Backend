# Farm-Assist Application: Django Backend

### To run the backend:

1. Clone the repository.
2. Create a virtual environment using *venv*:
```bash
python -m venv venv

```


3. Activate the virtual environment:
```bash
./venv/Scripts/activate

```

After activating the virtual enviornment, navigate to backend:
```bash
cd backend

```


*(Note: For macOS/Linux, use `source venv/bin/activate`)*


4. Install the dependencies:
```bash
pip install -r requirements.txt

```



---

### Run database services using Docker

1. Make sure **Docker Desktop** and **Docker Compose** are installed & Docker Engine is running.
2. From the project root, run:
```bash
docker-compose up -d

```


3. This will pull and start the following containers:
* **PostgreSQL** (port 5432)
* **Adminer** (port 8080)
* To access PostgreSQL GUI: Access **http://localhost:8080**
* Check configuration details in `docker-compose.yml`


4. To stop the containers:
```bash
docker-compose down

```



---

### Apply database migrations (first time only)

1. Ensure the PostgreSQL container is running:
```bash
docker-compose up -d

```


2. Create migration files (if not already committed):
```bash
python manage.py makemigrations

```


3. Apply migrations to the database:
```bash
python manage.py migrate

```



---

### Run Celery (Background Tasks)

To process background tasks, you need to run Celery in a separate terminal.

1. Open a **new terminal** window.
2. Navigate to your project root and activate the virtual environment:
```bash
./venv/Scripts/activate

```


3. Start the Celery worker (replace `<project_name>` with the name of the folder (FarmAssist-Backend) containing your `celery.py` and `settings.py` files):
```bash
celery -A <project_name> worker -l info --pool=solo

```


> **Windows Note:** If you run into issues executing Celery on Windows, append the `--pool=solo` flag:
> `celery -A <project_name> worker --loglevel=info --pool=solo`



---

### Finally, run the Django project

Back in your **original terminal** (with the virtual environment activated), start the Django development server:

```bash
python manage.py runserver

```
