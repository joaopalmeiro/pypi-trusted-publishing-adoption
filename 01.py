import clickhouse_connect

if __name__ == "__main__":
    client = clickhouse_connect.get_client(
        host="sql-clickhouse.clickhouse.com", port="443", user="demo", password="", secure=True
    )

    top_100 = client.query_df("""
        SELECT
            project,
            sum(count) AS downloads
        FROM pypi.pypi_downloads
        GROUP BY project
        ORDER BY downloads DESC
        LIMIT 100
    """)

    print(top_100["project"].to_list())
