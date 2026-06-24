FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tooling for any C extension; cleaned up in the same RUN so it
# doesn't bloat the layer it was needed for. Mirrors swapped to a China
# mirror because deb.debian.org has been flaky and pip's default index is
# slow from here.
RUN sed -i 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g; s|http://security.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/*.sources 2>/dev/null || true \
 && apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

# Default pip to a fast Chinese mirror for the install steps below.
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# === Tier 1: heavy ML deps that rarely change (~5 GB) ============
# Split out so a sqlalchemy bump (in tier 2) doesn't force the registry
# to ship torch all over again.
COPY requirements-heavy.txt .
RUN pip install -r requirements-heavy.txt

# === Tier 2: app deps that change occasionally (~200 MB) ==========
COPY requirements-app.txt .
RUN pip install -r requirements-app.txt

# === Tier 3: source code (small, changes on every commit) =========
COPY . .

EXPOSE 8004 8005

# --proxy-headers makes Uvicorn parse X-Forwarded-{For,Proto,Host} so
# request.client.host reflects the real client IP, not the TCP peer (which
# behind K8s ingress / docker is a pod-network / bridge address). Without
# this flag, Uvicorn's default --forwarded-allow-ips=127.0.0.1 means it
# only trusts XFF from localhost — so ingress-nginx, sitting in another
# pod, has its header silently ignored.
# --forwarded-allow-ips="*" trusts XFF from any source. Safe here because
# the LoadBalancer (externalTrafficPolicy=Local) sends traffic only to
# ingress-nginx pods; web-api is not exposed directly to the internet, so
# no client can reach it without first traversing ingress (which appends
# the real $remote_addr to XFF). Revisit if web-api ever gains a public
# endpoint that bypasses ingress.
CMD ["uvicorn", "app.web_app:app", "--host", "0.0.0.0", "--port", "8004", "--proxy-headers", "--forwarded-allow-ips=*"]
