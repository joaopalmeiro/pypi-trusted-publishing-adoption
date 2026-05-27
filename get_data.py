import asyncio
import base64
import json
import time
from itertools import chain
from typing import Any, TypedDict

import clickhouse_connect
import httpx2
import pandas as pd
from packaging.utils import InvalidSdistFilename, parse_sdist_filename, parse_wheel_filename


class ProjectFile(TypedDict):
    project: str
    version: str
    file: str


class ProjectProvenance(ProjectFile):
    has_provenance: bool
    publisher: str | None


def get_file_version(filename: str) -> str | None:
    try:
        if filename.endswith(".whl"):
            _, ver, _, _ = parse_wheel_filename(filename)
            return str(ver)

        _, ver = parse_sdist_filename(filename)
        return str(ver)
    except InvalidSdistFilename:
        return None


def get_publish_attestation(raw_data: Any) -> tuple[bool, str | None]:
    for bundle in raw_data["attestation_bundles"]:
        for attestation in bundle["attestations"]:
            statement = json.loads(base64.b64decode(attestation["envelope"]["statement"]))

            if statement["predicateType"] == "https://docs.pypi.org/attestations/publish/v1":
                publisher = bundle["publisher"]["kind"]
                return True, publisher

    return False, None


async def fetch_package(client: httpx2.AsyncClient, project: str) -> list[ProjectFile]:
    response = await client.get(
        f"/simple/{project}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json"},
    )
    response.raise_for_status()
    raw_data = response.json()

    latest_version = raw_data["versions"][-1]

    data: list[ProjectFile] = [
        {"project": project, "version": latest_version, "file": f["filename"]}
        for f in raw_data["files"]
        if get_file_version(f["filename"]) == latest_version
    ]

    return data


async def fetch_provenance(client: httpx2.AsyncClient, project_file: ProjectFile) -> ProjectProvenance:
    response = await client.get(
        f"/integrity/{project_file['project']}/{project_file['version']}/{project_file['file']}/provenance",
        headers={"Accept": "application/vnd.pypi.integrity.v1+json"},
    )

    if response.status_code == httpx2.codes.NOT_FOUND:
        return {
            **project_file,
            "has_provenance": False,
            "publisher": None,
        }

    response.raise_for_status()
    raw_data = response.json()

    has_provenance, publisher = get_publish_attestation(raw_data)

    return {
        **project_file,
        "has_provenance": has_provenance,
        "publisher": publisher,
    }


async def fetch_files(client: httpx2.AsyncClient, projects: list[str]) -> list[ProjectFile]:
    semaphore = asyncio.Semaphore(10)

    async def fetch_with_semaphore(project: str) -> list[ProjectFile]:
        async with semaphore:
            return await fetch_package(client, project)

    tasks = [fetch_with_semaphore(project) for project in projects]

    start = time.perf_counter()
    results = await asyncio.gather(*tasks, return_exceptions=False)
    print(f"Elapsed: {time.perf_counter() - start:.2f}s")

    return list(chain.from_iterable(results))


async def fetch_provenances(client: httpx2.AsyncClient, project_files: list[ProjectFile]) -> list[ProjectProvenance]:
    semaphore = asyncio.Semaphore(10)

    async def fetch_with_semaphore(project_file: ProjectFile) -> ProjectProvenance:
        async with semaphore:
            return await fetch_provenance(client, project_file)

    tasks = [fetch_with_semaphore(project_file) for project_file in project_files]

    start = time.perf_counter()
    results = await asyncio.gather(*tasks, return_exceptions=False)
    print(f"Elapsed: {time.perf_counter() - start:.2f}s")

    return results


async def fetch_all(projects: list[str]) -> list[ProjectProvenance]:
    async with httpx2.AsyncClient(
        base_url="https://pypi.org",
        headers={
            "User-Agent": "pypi-trusted-publishing-adoption (https://github.com/joaopalmeiro/pypi-trusted-publishing-adoption)",
        },
    ) as client:
        project_files = await fetch_files(client, projects)
        return await fetch_provenances(client, project_files)


if __name__ == "__main__":
    client = clickhouse_connect.get_client(
        host="sql-clickhouse.clickhouse.com", port="443", user="demo", password="", secure=True
    )

    top_500 = client.query_df("""
        SELECT
            project,
            sum(count) AS downloads
        FROM pypi.pypi_downloads
        GROUP BY project
        ORDER BY downloads DESC
        LIMIT 500
    """)

    projects = top_500["project"].to_list()

    results = asyncio.run(fetch_all(projects))

    results_df = pd.DataFrame(results)
    results_df.to_csv("results.csv", index=False)
