-- Hive 端到端测试 (Hive on Tez: insert 会起 Tez DAG 跑通 YARN->HDFS)
show databases;
create database if not exists aiopstest;
use aiopstest;
create table if not exists demo (id int, name string) stored as textfile;
insert into demo values (1, 'hello-hive'), (2, 'tez-engine'), (3, 'ha-cluster');
select * from demo order by id;
select count(*) as cnt from demo;
show databases;
