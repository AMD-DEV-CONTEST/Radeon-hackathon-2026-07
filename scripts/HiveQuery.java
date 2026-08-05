import java.sql.*;

public class HiveQuery {
    public static void main(String[] args) throws Exception {
        String url = "jdbc:hive2://localhost:10000";
        String user = "root";
        String sql = args.length > 0 ? args[0] : "SELECT 1";
        Connection conn = DriverManager.getConnection(url, user, "");
        Statement stmt = conn.createStatement();
        if (sql.toLowerCase().startsWith("select")) {
            ResultSet rs = stmt.executeQuery(sql);
            int cols = rs.getMetaData().getColumnCount();
            while (rs.next()) {
                for (int i = 1; i <= cols; i++) System.out.print(rs.getString(i) + "\t");
                System.out.println();
            }
            rs.close();
        } else {
            stmt.execute(sql);
            System.out.println("OK");
        }
        stmt.close();
        conn.close();
    }
}
