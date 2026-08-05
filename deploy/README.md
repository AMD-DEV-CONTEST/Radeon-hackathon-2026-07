# Hadoop Cluster Deployment — Quick Reproduction Guide

This directory contains everything needed to reproduce the 3-node Hadoop HA cluster in Docker.

## Cluster Topology

```
hadoop01 (10.20.0.11)  hadoop02 (10.20.0.12)  hadoop03 (10.20.0.13)
├── ZK (myid=1)         ├── ZK (myid=2)         ├── ZK (myid=3)
├── JournalNode         ├── JournalNode         ├── JournalNode
├── NameNode (nn1)      ├── NameNode (nn2)      ├── DataNode
├── ZKFC                ├── ZKFC                ├── NodeManager
├── DataNode            ├── DataNode            └── RegionServer
├── NodeManager         ├── NodeManager
├── ResourceManager(rm1)├── ResourceManager(rm2)
├── JobHistoryServer    ├── HiveMetaStore
├── HiveMetaStore       ├── HiveServer2
├── HiveServer2         └── HMaster (backup)
└── HMaster (active)     └── RegionServer
                         └── RegionServer

mysql (10.20.0.30)       prometheus (10.20.0.20)  grafana (10.20.0.22)
└── Hive Metastore DB    └── Metrics scrape       └── Dashboards (admin/admin)
```

## Components & Versions

| Component | Version | JDK |
|-----------|---------|-----|
| Hadoop (HDFS + YARN + MR) | 3.3.6 | JDK 8 (default) / JDK 21 (MR containers) |
| Hive (MetaStore + Server2) | 4.2.0 | JDK 21 |
| Tez | 0.10.2 | JDK 21 |
| HBase (Master + RegionServer) | 2.5.15 | JDK 8 |
| ZooKeeper | 3.8.4 | JDK 8 |
| MySQL | 8.0 | — (Hive Metastore DB) |
| Prometheus + Grafana | latest | — (monitoring) |

## HA Configuration

- **HDFS HA**: Active/Standby NameNodes (nn1=hadoop01, nn2=hadoop02) with ZKFC automatic failover + QJM (3 JournalNodes)
- **YARN RM HA**: Active/Standby ResourceManagers (rm1=hadoop01, rm2=hadoop02) with ZKRMStateStore automatic failover
- **HBase HA**: Active/Backup HMaster (hadoop01, hadoop02) with 3 RegionServers
- **Hive HA**: Dual HiveMetaStore + Dual HiveServer2

## Prerequisites

- Docker 20.10+ with Docker Compose v2
- 8GB+ free RAM (cluster uses ~6GB)
- Linux or WSL2 (Windows)

## Step 1: Download Tarballs

Download required packages to `deploy/image/tarballs/`. See [`tarballs/README.md`](image/tarballs/README.md) for download links.

```bash
cd deploy/image/tarballs
# Follow instructions in README.md to download all 7 files
```

## Step 2: Build & Start Cluster

```bash
cd deploy
bash up.sh
# This runs: docker compose build && docker compose up -d
# First build takes ~5-10 minutes
```

## Step 3: Initialize Cluster (First Time Only)

```bash
bash scripts/init-cluster.sh
# This formats HDFS, bootstraps standby NN, formats RM state-store, starts master daemons
```

## Step 4: Verify Cluster

```bash
# Check HDFS HA
docker exec hadoop01 hdfs haadmin -getAllServiceState

# Check YARN RM HA
docker exec hadoop01 yarn rmadmin -getAllServiceState

# Check HDFS health
docker exec hadoop01 hdfs dfsadmin -report

# Check YARN nodes
docker exec hadoop01 yarn node -list

# Run a MapReduce job
docker exec hadoop01 yarn jar /opt/hadoop/share/hadoop/mapreduce/hadoop-mapreduce-examples-3.3.6.jar pi 2 10
```

## Subsequent Starts (Non-First-Time)

If you already ran `init-cluster.sh` before and just stopped the cluster:

```bash
cd deploy
bash up.sh                      # Start containers (data volumes persist)
bash scripts/restart-daemons.sh # Restart master daemons
```

## Web UIs

| Service | URL | Credentials |
|---------|-----|-------------|
| HDFS NameNode (active) | http://localhost:9870 | — |
| HDFS NameNode (standby) | http://localhost:9871 | — |
| YARN ResourceManager (active) | http://localhost:8088 | — |
| YARN ResourceManager (standby) | http://localhost:8081 | — |
| JobHistoryServer | http://localhost:19888 | — |
| HBase Master | http://localhost:16010 | — |
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| SSH (hadoop01) | `ssh -p 2222 root@localhost` | Use `deploy/config/ssh/id_rsa` |

## Reset Cluster (Destroy All Data)

```bash
cd deploy
bash reset.sh
# This stops containers + deletes data volumes + removes image
# To start fresh: bash up.sh && bash scripts/init-cluster.sh
```

## Directory Structure

```
deploy/
├── docker-compose.yml          # Docker Compose orchestration (3 Hadoop + MySQL + monitoring)
├── up.sh                       # Build image + start containers
├── down.sh                     # Stop containers (keep data)
├── reset.sh                    # Stop + delete data + remove image
├── config/                     # All service configs (bind-mounted read-only)
│   ├── hadoop/                 # core-site, hdfs-site, yarn-site, mapred-site, log4j, workers
│   ├── hive/                   # hive-site, hive-env
│   ├── hbase/                  # hbase-site, hbase-env
│   ├── tez/                    # tez-site
│   ├── zookeeper/              # zoo.cfg
│   ├── prometheus/             # prometheus.yml (scrape configs)
│   ├── grafana/                # Grafana provisioning (datasources + 4 dashboards)
│   ├── jmx-exporter/           # JMX exporter agent jar + config
│   └── ssh/                    # SSH keys + configs (container inter-node trust)
├── image/                      # Docker image build context
│   ├── Dockerfile              # Single image, multi-role (NODE_ROLE env selects daemons)
│   ├── entrypoint.sh           # Sets ZK myid + links Tez jars + SSH setup + starts supervisord
│   ├── beeline.sh              # Hive beeline helper script
│   ├── hbase-wrapper.sh        # HBase startup wrapper
│   ├── tarballs/               # Download packages here (see tarballs/README.md)
│   └── supervisord/            # Per-node supervisord configs (which daemons to run)
│       ├── supervisord-hadoop01.conf
│       ├── supervisord-hadoop02.conf
│       └── supervisord-hadoop03.conf
├── scripts/
│   ├── init-cluster.sh         # First-time initialization (format + bootstrap + start)
│   └── restart-daemons.sh      # Non-first-time restart of master daemons
└── tests/
    └── hive_test.sql           # Hive end-to-end test (create/insert/select)
```

## Key Configuration Details

### Java 21 `--add-opens` (mapred-site.xml)

MapReduce containers run on Java 21, which requires `--add-opens` JVM options to allow reflective access. These are configured in `mapred-site.xml`:
- `yarn.app.mapreduce.am.command-opts` — ApplicationMaster container
- `mapreduce.map.java.opts` — Map tasks
- `mapreduce.reduce.java.opts` — Reduce tasks

### YARN RM HA (yarn-site.xml)

- `yarn.resourcemanager.ha.enabled=true`
- `yarn.resourcemanager.ha.rm-ids=rm1,rm2`
- `yarn.resourcemanager.recovery.enabled=true`
- `yarn.resourcemanager.store.class=ZKRMStateStore`
- Automatic failover via ZooKeeper leader election

### HDFS HA (hdfs-site.xml + core-site.xml)

- `dfs.ha.automatic-failover.enabled=true`
- `dfs.nameservices=mycluster`
- QJM: `qjournal://hadoop01:8485;hadoop02:8485;hadoop03:8485/mycluster`
- ZKFC on both NameNodes for automatic failover

### Hive Execution Engine

Configured as `tez` in `hive-site.xml`. If Tez engine encounters issues, fallback to local MR mode:
```sql
SET hive.execution.engine=mr;
SET mapreduce.framework.name=local;
```

## Known Issues

See `docs/TEST_REPORT.md` → "Known Issues" section.
