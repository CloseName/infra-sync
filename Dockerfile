FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE.txt ./
COPY netbox_sync ./netbox_sync

RUN pip install --no-cache-dir .

CMD ["netbox-sync"]
