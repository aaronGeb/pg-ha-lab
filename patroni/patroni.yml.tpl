scope: ${CLUSTER_SCOPE}
name: ${NODE_NAME}

restapi:
  listen: 0.0.0.0:8008
  connect_address: ${NODE_NAME}:8008

etcd3:
  host: etcd:2379

log:
  level: INFO

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    # Ledger durability: a commit is acknowledged only after one standby has it,
    # and Patroni only promotes a node that is (or was) the synchronous standby.
    synchronous_mode: true
    synchronous_mode_strict: false
    synchronous_node_count: 1
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
        wal_level: logical
        hot_standby: "on"
        hot_standby_feedback: "on"
        max_wal_senders: 10
        max_replication_slots: 10
        max_slot_wal_keep_size: 2048MB
        wal_log_hints: "on"
        password_encryption: scram-sha-256
        unix_socket_directories: /var/run/postgresql
    # Logical slot that survives failover: Patroni recreates / advances it on replicas.
    slots:
      cdc_slot:
        type: logical
        database: ledger
        plugin: pgoutput
  initdb:
    - encoding: UTF8
    - data-checksums
  pg_hba:
    - local all postgres peer
    - host replication replicator 0.0.0.0/0 scram-sha-256
    - host all all 0.0.0.0/0 scram-sha-256
  post_bootstrap: /scripts/post_bootstrap.sh

postgresql:
  listen: 0.0.0.0:5432
  connect_address: ${NODE_NAME}:5432
  data_dir: /pgdata/data
  bin_dir: /usr/lib/postgresql/16/bin
  use_unix_socket: true
  pgpass: /tmp/pgpass
  authentication:
    superuser:
      username: postgres
      password: ${POSTGRES_PASSWORD}
    replication:
      username: replicator
      password: ${REPLICATOR_PASSWORD}
  parameters:
    unix_socket_directories: /var/run/postgresql

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false
  nosync: false

basebackup:
  checkpoint: fast
