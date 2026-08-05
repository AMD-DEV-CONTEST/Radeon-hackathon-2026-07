# Hadoop Cluster Functional Test Report

**Test Date:** 2026-07-19  
**Cluster:** aiops-ha (3 nodes: hadoop01, hadoop02, hadoop03)  
**Network:** Docker Bridge 10.20.0.0/24 (hadoop01=10.20.0.11, hadoop02=10.20.0.12, hadoop03=10.20.0.13)  


---

## Executive Summary

| Component | Version | Tests | Passed | Failed | Status |
|-----------|---------|-------|--------|--------|--------|
| HDFS | 3.3.6 | 25 | 25 | 0 | ✅ All Passed |
| YARN | 3.3.6 | 5 | 5 | 0 | ✅ All Passed |
| Hive | 4.2.0 | 27 | 25 | 2 | ⚠️ Tez Engine Issue |
| HBase | 2.5.15 | 25 | 25 | 0 | ✅ All Passed |
| ZooKeeper | 3.8.4 | 6 | 6 | 0 | ✅ All Passed |
| JobHistoryServer | 3.3.6 | 3 | 3 | 0 | ✅ All Passed |
| HDFS HA Failover | 3.3.6 | 6 | 6 | 0 | ✅ All Passed |
| YARN RM HA Failover | 3.3.6 | 6 | 6 | 0 | ✅ All Passed |
| **Total** | - | **103** | **101** | **2** | **98.1% Passed** |

---

## 1. HDFS (Hadoop Distributed File System)

**Version:** Hadoop 3.3.6  
**HA Configuration:** Active/Standby (hadoop02=active, hadoop01=standby)  
**DataNodes:** 3 nodes online  
**Total Capacity:** 2.95 TB | Used: 591 MB (0.02%) | Available: 2.69 TB

### 1.1 File Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 1 | `hdfs dfs -mkdir -p` | Create nested directories | ✅ PASS | `/user/test/hdfs_check` created |
| 2 | `hdfs dfs -ls` | List directory contents | ✅ PASS | 5 root directory items shown |
| 3 | `hdfs dfs -put` | Upload local file to HDFS | ✅ PASS | 59 bytes, replication=2 |
| 4 | `hdfs dfs -cat` | Read file content | ✅ PASS | 3 lines match original file |
| 5 | `hdfs dfs -get` | Download HDFS file to local | ✅ PASS | Local file 59 bytes, content identical |
| 6 | `hdfs dfs -copyFromLocal` | Copy local file to HDFS | ✅ PASS | 10 bytes uploaded correctly |
| 7 | `hdfs dfs -copyToLocal` | Copy HDFS file to local | ✅ PASS | Content "copy test" identical |
| 8 | `hdfs dfs -appendToFile` | Append data to file | ✅ PASS | File expanded from 1 to 2 lines |
| 9 | `hdfs dfs -tail` | View file end | ✅ PASS | Output full file content |
| 10 | `hdfs dfs -text` | Read file as text | ✅ PASS | Output identical to cat |
| 11 | `hdfs dfs -touchz` | Create empty file | ✅ PASS | 0-byte file created |
| 12 | `hdfs dfs -cp` | Copy within HDFS | ✅ PASS | File count increased from 2 to 3 |
| 13 | `hdfs dfs -mv` | Rename/move file | ✅ PASS | `copy_test.txt` → `renamed_test.txt` |
| 14 | `hdfs dfs -rm` | Delete file | ✅ PASS | Output "Deleted", verified by ls |
| 15 | `hdfs dfs -rm -r` | Recursive directory delete | ✅ PASS | Output "Deleted", directory empty |

### 1.2 Metadata & Statistics

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 16 | `hdfs dfs -stat` | File metadata | ✅ PASS | Name/size/blocksize/replication/time correct |
| 17 | `hdfs dfs -count -q -h` | Directory quota stats | ✅ PASS | 1 dir, 1 file, 23 bytes |
| 18 | `hdfs dfs -du -h` | Directory size stats | ✅ PASS | Per-file size and replication total |
| 19 | `hdfs dfs -df -h` | Filesystem capacity | ✅ PASS | 2.9T total / 591.4M used / 2.7T available |
| 20 | `hdfs dfs -chmod` | Modify permissions | ✅ PASS | `rw-r--r--` → `rwx------` |
| 21 | `hdfs dfs -setrep` | Modify replication factor | ✅ PASS | Replication 2 → 3 |

### 1.3 System Administration

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 22 | `hdfs fsck -files -blocks -locations` | Block health check | ✅ PASS | **HEALTHY**, replication 2/2, cross-node |
| 23 | `hdfs dfsadmin -report` | Cluster report | ✅ PASS | 3 DataNodes online, 2.95TB capacity |
| 24 | `hdfs dfsadmin -safemode get` | Safe mode status | ✅ PASS | Both NN: **Safe mode is OFF** |
| 25 | `hdfs haadmin -getAllServiceState` | HA NameNode status | ✅ PASS | hadoop02=active, hadoop01=standby |

---

## 2. YARN (Yet Another Resource Negotiator)

**Version:** Hadoop 3.3.6  
**ResourceManager HA:** rm1=hadoop01 (active), rm2=hadoop02 (standby)  
**ResourceManager Web UI:** hadoop01:8088, hadoop02:8088  
**NodeManagers:** 3 nodes (hadoop01, hadoop02, hadoop03)  
**JobHistoryServer:** Running on hadoop01 (port 19888)  
**Recovery:** Enabled (ZKRMStateStore with ZooKeeper quorum)

### 2.1 Test Results

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | YARN node status | ✅ PASS | 3 nodes RUNNING, 0 containers |
| 2 | Pi estimation job | ✅ PASS | Pi ≈ 3.8, 24 seconds, 2 maps |
| 3 | WordCount job | ✅ PASS | 8 words counted correctly |
| 4 | `_SUCCESS` marker | ✅ PASS | Job completion marker present |
| 5 | JobHistory REST API | ✅ PASS | 6 historical jobs, all SUCCEEDED |

---

## 3. Hive

**Version:** Apache Hive 4.2.0  
**HiveServer2:** Running on hadoop01 (port 10000)  
**MetaStore:** Running on hadoop01 (port 9083)  
**Execution Engine:** tez (configured) / mr (fallback)  
**Java:** OpenJDK 21

### 3.1 Test Results

#### Process & Connection

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | HiveServer2 process | ✅ PASS | `-Dproc_hiveserver2`, 536MB |
| 2 | MetaStore process | ✅ PASS | `-Dproc_metastore` |
| 3 | Beeline connection | ✅ PASS | Connected to Hive 4.2.0 via JDBC |

#### Database Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 4 | `CREATE DATABASE` | Create database | ✅ PASS | `testdb` created |
| 5 | `SHOW DATABASES` | List databases | ✅ PASS | aiopstest, default, testdb |
| 6 | `DESCRIBE DATABASE` | Database info | ✅ PASS | Location: `hdfs://mycluster/user/hive/warehouse/testdb.db` |

#### Table Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 7 | `CREATE TABLE ... STORED AS ORC` | Create ORC table | ✅ PASS | `users` table created |
| 8 | `CREATE TABLE ... STORED AS TEXTFILE` | Create TEXT table | ✅ PASS | `users_text` table created |
| 9 | `DESCRIBE` | Table structure | ✅ PASS | id INT, name STRING, city STRING |
| 10 | `DESCRIBE FORMATTED` | Detailed metadata | ✅ PASS | SerDe=OrcSerde, numFiles=1, numRows=5 |
| 11 | `INSERT INTO ... VALUES` | Insert data | ✅ PASS | 5 rows written (local MR mode) |
| 12 | `SELECT *` | Full table scan | ✅ PASS | 5 rows complete and correct |
| 13 | `SELECT * WHERE` | Conditional query | ✅ PASS | WHERE city='Beijing' returns 1 row |
| 14 | `LOAD DATA INPATH` | Import CSV from HDFS | ✅ PASS | 5 CSV rows imported to users_text |
| 15 | `SHOW TABLES` | List tables | ✅ PASS | All tables displayed correctly |
| 16 | `DROP TABLE` | Drop table | ✅ PASS | orders table dropped |
| 17 | `DROP VIEW` | Drop view | ✅ PASS | beijing_users view dropped |

#### Complex Queries

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 18 | `SELECT COUNT(*)` | Aggregate count | ✅ PASS | Returns 5, local MR job completed |
| 19 | `GROUP BY + ORDER BY` | Group and sort | ✅ PASS | 5 cities × 1 record each, 2 MR jobs |
| 20 | `UNION ALL + ORDER BY` | Union query | ✅ PASS | 10 rows merged and sorted |
| 21 | `JOIN ... ON` | Equi-join | ✅ PASS | users JOIN orders returns 5 rows |

#### Partitioned Tables

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 22 | `CREATE TABLE ... PARTITIONED BY` | Create partitioned table | ✅ PASS | users_part partitioned by city |
| 23 | `INSERT INTO ... PARTITION` | Insert by partition | ✅ PASS | Beijing 2 rows, Shanghai 2 rows |
| 24 | `SHOW PARTITIONS` | List partitions | ✅ PASS | city=Beijing, city=Shanghai |
| 25 | `SELECT * WHERE partition` | Partition pruning | ✅ PASS | WHERE city='Beijing' scans 1 partition |

#### Views

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 26 | `CREATE VIEW AS SELECT` | Create view | ✅ PASS | beijing_users view created |
| 27 | `SELECT * FROM VIEW` | Query view | ✅ PASS | Returns 1 row (Alice) |

---

## 4. HBase

**Version:** HBase 2.5.15  
**Java:** OpenJDK 8  
**HMaster:** hadoop01 (active), hadoop02 (backup)  
**HRegionServers:** 3 nodes (hadoop01, hadoop02, hadoop03)  
**ZooKeeper Quorum:** hadoop01, hadoop02, hadoop03

### 4.1 Test Results

#### Process & Status

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | HMaster process | ✅ PASS | `-Dproc_master`, Java 8, 256MB |
| 2 | Backup HMaster | ✅ PASS | hadoop02 backup master |
| 3 | HRegionServer | ✅ PASS | 3 nodes: hadoop01, hadoop02, hadoop03 |
| 4 | ZooKeeper quorum | ✅ PASS | 3 QuorumPeerMain processes |
| 5 | `status` command | ✅ PASS | 1 active master, 1 backup, 3 servers, 0 dead, avg load 1.3333 |

#### Namespace Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 6 | `list_namespace` | List namespaces | ✅ PASS | default, hbase |
| 7 | `create_namespace` | Create namespace | ✅ PASS | testns created |
| 8 | `drop_namespace` | Drop namespace | ✅ PASS | testns dropped |

#### Table Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 9 | `create` | Create table (3 column families) | ✅ PASS | testns:users, families: cf/user_info/log_info |
| 10 | `list` | List tables | ✅ PASS | All tables shown |
| 11 | `describe` | Table structure | ✅ PASS | 3 column families, full config |
| 12 | `alter` | Modify column family VERSIONS | ✅ PASS | cf family VERSIONS 1→3 |
| 13 | `disable` | Disable table | ✅ PASS | Took 4.3 seconds |
| 14 | `enable` | Enable table | ✅ PASS | Took 0.7 seconds |
| 15 | `is_disabled` | Check disabled state | ✅ PASS | Returns false |
| 16 | `drop` | Drop table | ✅ PASS | Requires disable first |

#### Data Operations

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 17 | `put` | Write data | ✅ PASS | 15 PUTs all successful |
| 18 | `get` | Read single row | ✅ PASS | user1 returns age/city/name |
| 19 | `scan` | Full table scan | ✅ PASS | All rows and columns correct |
| 20 | `count` | Row count | ✅ PASS | 3→2→4 correct changes |
| 21 | `delete` | Delete cell | ✅ PASS | user1's cf:age deleted |
| 22 | `deleteall` | Delete entire row | ✅ PASS | user3 row deleted |

#### Filter Queries

| # | Command | Test | Result | Evidence |
|---|---------|------|--------|----------|
| 23 | `PrefixFilter` | Row key prefix filter | ✅ PASS | Query user1 returns 1 row |
| 24 | `SingleColumnValueFilter` | Column value filter | ✅ PASS | age=28 returns 2 rows |
| 25 | `LIMIT` | Limit returned rows | ✅ PASS | Limited to 2 rows correct |

---

## 5. ZooKeeper

**Version:** 3.8.4  
**Java:** OpenJDK 8  
**Cluster:** 3 nodes (hadoop01, hadoop02, hadoop03)  
**Port:** 2181

### 5.1 Test Results

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | Cluster connection | ✅ PASS | zkCli connected, session established |
| 2 | Root node listing | ✅ PASS | 5 znodes: hadoop-ha, hbase, rmstore, yarn-leader-election, zookeeper |
| 3 | `create` znode | ✅ PASS | `/test_zk` created |
| 4 | `get` znode | ✅ PASS | Returns "hello_zk" |
| 5 | `delete` znode | ✅ PASS | `/test_zk` deleted |
| 6 | 3-node quorum | ✅ PASS | QuorumPeerMain on all 3 nodes |

---

## 6. JobHistoryServer

**Version:** Hadoop 3.3.6  
**Port:** 19888 (bound to hadoop01)  

### 6.1 Test Results

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | REST API `/ws/v1/history/info` | ✅ PASS | Returns Hadoop 3.3.6 build info |
| 2 | Job list query | ✅ PASS | 6 historical jobs, all SUCCEEDED |
| 3 | Job detail query | ✅ PASS | word count: Map 2.8s, Reduce 0.6s, 0 failures |

### 6.2 Historical Jobs Recorded

| Job ID | Name | State | Maps | Reduces |
|--------|------|-------|------|---------|
| job_1784427763474_0001 | QuasiMonteCarlo | SUCCEEDED | 2 | 1 |
| job_1784429933024_0006 | insert into demo | SUCCEEDED | 1 | 1 |
| job_1784429933024_0007 | select * from demo order by id | SUCCEEDED | 1 | 1 |
| job_1784429933024_0008 | select count(*) as cnt from demo | SUCCEEDED | 1 | 1 |
| job_1784465596252_0006 | QuasiMonteCarlo | SUCCEEDED | 2 | 1 |
| job_1784465596252_0007 | word count | SUCCEEDED | 1 | 1 |

---

## 7. HDFS HA Failover

**Configuration:** Active/Standby with ZKFC automatic failover  
**Nameservice:** mycluster (nn1=hadoop01, nn2=hadoop02)  
**JournalNodes:** 3 nodes (QJM)

### 7.1 Test Results

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | Initial HA state | ✅ PASS | hadoop02=active, hadoop01=standby |
| 2 | Manual failover nn2→nn1 | ✅ PASS | "Failover to NameNode at hadoop01 successful" |
| 3 | Post-failover state | ✅ PASS | hadoop01=active, hadoop02=standby |
| 4 | HDFS read/write after failover | ✅ PASS | put/cat/rm all successful |
| 5 | Failback nn1→nn2 | ✅ PASS | Restored original state |
| 6 | ZKFC auto-failover enabled | ✅ PASS | `dfs.ha.automatic-failover.enabled=true` |

---

## 8. YARN RM HA Failover

**Configuration:** Active/Standby with ZooKeeper-based automatic failover  
**ResourceManagers:** rm1=hadoop01, rm2=hadoop02  
**State Store:** ZKRMStateStore (ZooKeeper quorum: hadoop01, hadoop02, hadoop03)  
**Recovery:** Enabled

### 8.1 Test Results

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | Initial RM HA state | ✅ PASS | rm1 (hadoop01)=active, rm2 (hadoop02)=standby |
| 2 | Both RM processes running | ✅ PASS | ResourceManager on hadoop01 and hadoop02 |
| 3 | Auto-failover on RM failure | ✅ PASS | Killed active RM on hadoop01 → hadoop02 became active within 20s |
| 4 | RM process auto-restart | ✅ PASS | Killed RM restarted by supervisor as standby |
| 5 | Job submission after failover | ✅ PASS | Pi estimation job succeeded on new active RM (32s) |
| 6 | Failback to original state | ✅ PASS | Killed hadoop02 RM → hadoop01 restored as active |

---

## 9. Known Issues

### 9.1 Tez Engine Version Incompatibility

- **Severity:** Critical (affects distributed queries)
- **Symptom:** `java.lang.NoSuchMethodError: 'java.lang.String org.apache.tez.client.TezClient.getAmHost()'`
- **Root Cause:** Tez 0.10.2 is incompatible with Hive 4.2.0; Hive 4.2.0 requires Tez 0.10.3+
- **Workaround:** Use local MR mode:
  ```sql
  SET hive.execution.engine=mr;
  SET mapreduce.framework.name=local;
  ```
- **Resolution:** Upgrade Tez to 0.10.3+

### 9.2 MapJoin Local Task Failure

- **Severity:** Medium
- **Symptom:** `MapredLocalTask` returns error code 1
- **Workaround:** `SET hive.auto.convert.join=false;`
- **Note:** Resolving the Tez engine issue (9.1) will also resolve this

---

## 10. Conclusion

The Hadoop cluster is **98.1% functional** with 101 out of 103 tests passing. All core components (HDFS, YARN, HBase, ZooKeeper, JobHistoryServer, HDFS HA, YARN RM HA) are fully operational. The only remaining issue is Hive's Tez engine incompatibility, which has a working workaround (local MR mode). The cluster is ready for development and testing use.
