FROM postgres:16-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv gettext-base curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/patroni \
 && /opt/patroni/bin/pip install --no-cache-dir "patroni[etcd3]==3.3.2" psycopg2-binary

ENV PATH=/opt/patroni/bin:$PATH

RUN mkdir -p /pgdata && chown postgres:postgres /pgdata && chmod 700 /pgdata

COPY patroni.yml.tpl /etc/patroni.yml.tpl
COPY entrypoint.sh /entrypoint.sh
COPY post_bootstrap.sh /scripts/post_bootstrap.sh
RUN chmod +x /entrypoint.sh /scripts/post_bootstrap.sh

EXPOSE 5432 8008
ENTRYPOINT ["/entrypoint.sh"]
