<h1>This is a Django backend for the Farm-Assist Application.</h1>

<h3>To run the backend :</h3>

<ol>
  <li>Clone the repository.</li>

  <li>Create a virtual environment using <em>venv</em><br>
  
      > python -m venv venv
  </li>

  <li>Activate the virtual environment.<br>

      > ./venv/Scripts/activate
  </li>

  <li>Install the dependencies.<br>
  
      > pip install -r requirements.txt
  </li>
</ol>

<h3>Run database services using Docker (recommended)</h3>

<ol>
  <li>Make sure <strong>Docker dekstop</strong> and <strong>Docker Compose</strong> are installed & Docker Engine is running.</li>

  <li>From the project root, run:<br>

      > docker-compose up -d
  </li>

  <li>This will pull and start the following containers:
    <ul>
      <li><strong>PostgreSQL</strong> (port 5432)</li>
      <li><strong>Adminer</strong> (port 8080)</li>
       <li>To access postgresql GUI : Access **http://localhost:8080** </li>
      <li> Check configuration details in docker-compose.yml </li>
    </ul>
  </li>
  <br>
  <li>To stop the containers:<br>

      > docker-compose down
  </li>

</ol>

 <h3>Apply database migrations (first time only)</h3>

<ol>
  <li>Ensure the PostgreSQL container is running:<br>
    
      > docker-compose up -d
  </li>

  <li>Create migration files (if not already committed):<br>
    
      > python manage.py makemigrations
  </li>

  <li>Apply migrations to the database:<br>
    
      > python manage.py migrate
  </li>
</ol>


<h3>Finally, run the Django project.</h3>

```shell
> python manage.py runserver
