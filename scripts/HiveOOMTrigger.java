import java.sql.*;
import java.util.concurrent.*;
import java.util.ArrayList;
import java.util.List;

/**
 * HiveOOMTrigger — Launches concurrent heavy queries to exhaust HS2 heap.
 *
 * Strategy: Cartesian product with large LIMIT forces HS2 to buffer
 * massive intermediate results. Combined with concurrent sessions
 * and large query plan caching, this exhausts 512MB heap.
 *
 * Also: each thread creates a temp view and runs complex queries,
 * forcing HS2 to hold multiple query plans + session metadata in memory.
 *
 * No heap change, no restart — pure query-driven OOM.
 *
 * Usage: HiveOOMTrigger <numThreads>
 */
public class HiveOOMTrigger {

    static final String URL = "jdbc:hive2://localhost:10000";
    static final String USER = "root";

    public static void main(String[] args) throws Exception {
        int numThreads = args.length > 0 ? Integer.parseInt(args[0]) : 10;

        // Multiple heavy SQL strategies to pressure HS2 heap:
        // 1. Complex subquery with UNION ALL (duplicates data in memory)
        // 2. Multiple SET commands increase session state
        // 3. Large result set with fetch conversion disabled
        // Each thread runs a different query to maximize memory diversity
        String[] queries = {
            // Query 0: UNION ALL doubles the result set in HS2 memory
            "USE aiopstest; " +
            "SET hive.execution.engine=mr; " +
            "SET mapreduce.framework.name=local; " +
            "SET hive.exec.mode.local.auto=true; " +
            "SET hive.exec.mode.local.auto.inputbytes.max=10000000000; " +
            "SET hive.fetch.task.conversion=none; " +
            "SELECT * FROM (SELECT * FROM bigdata_ext UNION ALL SELECT * FROM bigdata_ext) t",

            // Query 1: Self-join with local MR (hash table in HS2 JVM)
            "USE aiopstest; " +
            "SET hive.execution.engine=mr; " +
            "SET mapreduce.framework.name=local; " +
            "SET hive.exec.mode.local.auto=true; " +
            "SET hive.exec.mode.local.auto.inputbytes.max=10000000000; " +
            "SET hive.fetch.task.conversion=none; " +
            "SELECT t1.id, t1.name, t1.payload, t2.name, t2.payload " +
            "FROM bigdata_ext t1 JOIN bigdata_ext t2 ON t1.id = t2.id",

            // Query 2: ORDER BY forces full sort in memory
            "USE aiopstest; " +
            "SET hive.execution.engine=mr; " +
            "SET mapreduce.framework.name=local; " +
            "SET hive.exec.mode.local.auto=true; " +
            "SET hive.exec.mode.local.auto.inputbytes.max=10000000000; " +
            "SET hive.fetch.task.conversion=none; " +
            "SELECT * FROM bigdata_ext ORDER BY payload DESC, name DESC, id DESC",

            // Query 3: GROUP BY with large cardinality forces hash aggregation
            "USE aiopstest; " +
            "SET hive.execution.engine=mr; " +
            "SET mapreduce.framework.name=local; " +
            "SET hive.exec.mode.local.auto=true; " +
            "SET hive.exec.mode.local.auto.inputbytes.max=10000000000; " +
            "SET hive.fetch.task.conversion=none; " +
            "SELECT id, name, payload, COUNT(*) FROM bigdata_ext GROUP BY id, name, payload",

            // Query 4: Cross join generates massive intermediate data
            "USE aiopstest; " +
            "SET hive.execution.engine=mr; " +
            "SET mapreduce.framework.name=local; " +
            "SET hive.exec.mode.local.auto=true; " +
            "SET hive.exec.mode.local.auto.inputbytes.max=10000000000; " +
            "SET hive.fetch.task.conversion=none; " +
            "SELECT t1.* FROM bigdata_ext t1 CROSS JOIN bigdata_ext t2 LIMIT 50000000",
        };

        System.out.println("Starting " + numThreads + " concurrent heavy query threads...");
        System.out.println("Strategy: Multiple query types → diverse memory pressure on 512MB HS2 heap");
        System.out.println("Query types: UNION ALL, self-join, ORDER BY, GROUP BY, cross join");

        ExecutorService executor = Executors.newFixedThreadPool(numThreads);
        List<Future<String>> futures = new ArrayList<>();

        for (int i = 0; i < numThreads; i++) {
            final int idx = i;
            final String sql = queries[i % queries.length];
            futures.add(executor.submit(() -> {
                try {
                    long start = System.currentTimeMillis();
                    Connection conn = DriverManager.getConnection(URL, USER, "");
                    Statement stmt = conn.createStatement();

                    String[] stmts = sql.split(";");
                    for (String s : stmts) {
                        s = s.trim();
                        if (s.isEmpty()) continue;
                        System.out.println("[Thread " + idx + "] Executing: " +
                            s.substring(0, Math.min(80, s.length())));
                        boolean hasResult = stmt.execute(s);
                        if (hasResult) {
                            ResultSet rs = stmt.getResultSet();
                            int rows = 0;
                            while (rs.next()) {
                                rows++;
                                if (rows % 500000 == 0) {
                                    System.out.println("[Thread " + idx + "] Fetched " + rows + " rows...");
                                }
                            }
                            rs.close();
                            System.out.println("[Thread " + idx + "] Query completed: " + rows +
                                " rows in " + (System.currentTimeMillis() - start) + "ms");
                        } else {
                            System.out.println("[Thread " + idx + "] DDL/SET OK");
                        }
                    }
                    stmt.close();
                    conn.close();
                    return "Thread " + idx + " done";
                } catch (Exception e) {
                    System.err.println("[Thread " + idx + "] ERROR: " + e.getMessage());
                    return "Thread " + idx + " failed: " + e.getMessage();
                }
            }));
        }

        executor.shutdown();
        boolean done = executor.awaitTermination(5, TimeUnit.MINUTES);

        System.out.println("\n=== Results ===");
        for (Future<String> f : futures) {
            try {
                System.out.println(f.get(1, TimeUnit.SECONDS));
            } catch (Exception e) {
                System.out.println("Future error: " + e.getMessage());
            }
        }
        System.out.println("All threads finished: " + done);
    }
}
