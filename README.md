Pre-reqs: Docker, Docker Compose.

* How to run: docker-compose up --build
* Login: admin / (set password via createsuperuser prompt or dj superuser creation).
* Swagger: http://127.0.0.1:8000/api/schema/swagger-ui/
* Admin: http://127.0.0.1:8000/admin/
* Web UI: http://127.0.0.1:5173

Dump restore: pg_restore -h 127.0.0.1 -U dima -d dima dima_pg12.dump
