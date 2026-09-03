FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE.txt ./
COPY netbox_pve_sync ./netbox_pve_sync

RUN pip install --no-cache-dir .

CMD ["nbpxsync"]
