import asyncio
import httpx2
import clickhouse_connect
import time


async def fetch_package(client: httpx2.AsyncClient, project: str):
    response = await client.get(
        f"/simple/{project}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json"},
    )
    response.raise_for_status()
    data = response.json()

    latest_version = data["versions"][-1]


async def fetch_all(projects: list[str]):
    async with httpx2.AsyncClient(
        base_url="https://pypi.org",
        headers={
            "User-Agent": "pypi-trusted-publishing-adoption (https://github.com/joaopalmeiro/pypi-trusted-publishing-adoption)",
        }
    ) as client:
        tasks = [fetch_package(client, project) for project in projects]

        start = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        print(f"Elapsed: {time.perf_counter() - start:.2f}s")

        return results


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

    projects = top_100["project"].to_list()

    results = asyncio.run(fetch_all(projects))
