# Run on separate shell
docker exec -it $(docker ps -qf name=msinventory) bash -lc "
  python manage.py createsuperuser --noinput --username admin --email admin@gmail.com || true
"

# load products (mount or copy CSV into the container or run locally pointing to host path)
docker cp /absolute/path/to/product-template.csv $(docker ps -qf name=msinventory):/app/
docker exec -it $(docker ps -qf name=msinventory) bash -lc "python manage.py import_products static/resources/product-template.csv"

# create a dump compatible with PostgreSQL 12 (on host)
pg_dump -h 127.0.0.1 -p 5432 -U dima -Fc -f dima_pg12.dump dima
# password: dima
