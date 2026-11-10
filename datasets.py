"""
Creates dataset descriptions and a data catalog per organisation from
organisations/<org>/datasets.toml, writes them to output/<org>/ as .jsonld and
.ttl, and validates them against the NDE profile.

    uv run datasets.py build                    # all organisations
    uv run datasets.py build som pknet          # only these organisations
    uv run datasets.py validate a.jsonld        # only validate existing files
    uv run datasets.py validate --online URL    # use the register's own validator
    uv run datasets.py register                 # register the published catalogs
    uv run datasets.py register --update        # also re-register registered ones
    uv run datasets.py refresh-profile          # download the latest profile

The exit code is 1 if any description has a SHACL violation, or a registration
fails. Warnings and infos are printed but do not fail the run.
"""
import argparse
import json
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pyshacl
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SH
from rdflib.util import guess_format

ROOT = Path(__file__).parent
ORGANISATIONS_DIR = ROOT / "organisations"
OUTPUT_DIR = ROOT / "output"
PROFILE_PATH = ROOT / "profile" / "nde-dataset-register.ttl"
API_URL = "https://datasetregister.netwerkdigitaalerfgoed.nl/api"
PROFILE_URL = API_URL + "/shacl"  # The shapes the live register validates with.

API_ERRORS = {
    403: "The URL's domain is not on the register's allow list",
    404: "The register cannot resolve the URL (is it published?)",
    406: "The register found no dataset at the URL, or could not fetch it",
}

SCHEMA = "https://schema.org/"
CONTEXT = {"@vocab": SCHEMA}
LANGUAGES = ("nl", "en")

# Distributions take these values from their dataset unless they set their own.
INHERITED_BY_DISTRIBUTION = (
    "license", "in_language", "date_created", "date_published", "date_modified",
)


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _one_or_many(values: list):
    return values[0] if len(values) == 1 else values


def plain(value):
    return _one_or_many(_as_list(value))


def lang_text(value):
    """A table keyed by language (name.nl = "..."), or a string or list that
    is the same in all LANGUAGES and gets each of their tags."""
    if not isinstance(value, dict):
        value = {lang: value for lang in LANGUAGES}
    return _one_or_many([
        {"@language": lang, "@value": val}
        for lang, vals in value.items()
        for val in _as_list(vals)
    ])


def iri(value):
    return _one_or_many([{"@id": item} for item in _as_list(value)])


def schema_date(value):
    # Unquoted TOML dates arrive as date objects.
    iso = value.isoformat() if hasattr(value, "isoformat") else value
    return {"@value": iso, "@type": "Date"}


def _map_fields(source: dict, fields: list[tuple]) -> dict:
    """Omits absent fields, so that missing ones are reported by the profile."""
    return {
        prop: convert(source[key])
        for key, prop, convert in fields
        if key in source
    }


ORGANISATION_FIELDS = [
    ("name", "name", lang_text),
    ("url", "url", lang_text),
    ("same_as", "sameAs", iri),
    ("identifier", "identifier", plain),
]

CONTACT_POINT_FIELDS = [
    ("name", "name", lang_text),
    ("email", "email", plain),
]

CATALOG_FIELDS = [
    ("name", "name", lang_text),
    ("description", "description", lang_text),
]

DISTRIBUTION_FIELDS = [
    ("name", "name", lang_text),
    ("description", "description", lang_text),
    ("content_url", "contentUrl", iri),
    ("encoding_format", "encodingFormat", plain),
    ("date_created", "dateCreated", schema_date),
    ("date_modified", "dateModified", schema_date),
    ("date_published", "datePublished", schema_date),
    ("in_language", "inLanguage", plain),
    ("usage_info", "usageInfo", iri),
    ("license", "license", iri),
    ("main_entity_of_page", "mainEntityOfPage", iri),
]

DATASET_FIELDS = [
    ("identifier", "identifier", plain),
    ("name", "name", lang_text),
    ("description", "description", lang_text),
    ("date_created", "dateCreated", schema_date),
    ("date_modified", "dateModified", schema_date),
    ("date_published", "datePublished", schema_date),
    ("in_language", "inLanguage", plain),
    ("version", "version", plain),
    ("data_catalog", "includedInDataCatalog", iri),
    ("keywords", "keywords", lang_text),
    ("genre", "genre", lang_text),
    ("about", "about", iri),
    ("license", "license", iri),
    ("spatial_coverage", "spatialCoverage", iri),
    ("temporal_coverage", "temporalCoverage", plain),
    ("url", "url", iri),
    ("main_entity_of_page", "mainEntityOfPage", iri),
]


def build_organisation(organisation: dict) -> dict:
    node = {"@type": "Organization", "@id": organisation["id"]}
    node |= _map_fields(organisation, ORGANISATION_FIELDS)
    if "contact_point" in organisation:
        node["contactPoint"] = {
            "@type": "ContactPoint",
            **_map_fields(organisation["contact_point"], CONTACT_POINT_FIELDS),
        }
    return node


def build_distribution(distribution: dict, dataset: dict) -> dict:
    inherited = {k: dataset[k] for k in INHERITED_BY_DISTRIBUTION if k in dataset}
    return {
        "@type": "DataDownload",
        **_map_fields(inherited | distribution, DISTRIBUTION_FIELDS),
    }


def build_description(organisation: dict, dataset: dict, catalog_id: str | None) -> dict:
    fields = {
        "identifier": dataset["id"],
        "date_modified": date.today(),
        "data_catalog": catalog_id,
    }
    fields = {k: v for k, v in fields.items() if v is not None} | dataset

    return {
        "@context": CONTEXT,
        "@type": "Dataset",
        "@id": dataset["id"],
        **_map_fields(fields, DATASET_FIELDS),
        # One full node plus a reference, so the contact point stays a single
        # blank node in the resulting graph.
        "creator": {"@id": organisation["id"]},
        "publisher": build_organisation(organisation),
        "distribution": [
            build_distribution(d, fields) for d in dataset.get("distributions", [])
        ],
    }


def write_turtle(jsonld_path: Path):
    graph = Graph().parse(jsonld_path, format="json-ld")
    graph.bind("schema", SCHEMA)
    graph.serialize(destination=jsonld_path.with_suffix(".ttl"), format="turtle")


def build_catalog(organisation: dict, catalog: dict, descriptions: list[dict]) -> dict:
    return {
        "@context": CONTEXT,
        "@type": "DataCatalog",
        "@id": catalog["id"],
        **_map_fields(catalog, CATALOG_FIELDS),
        "publisher": build_organisation(organisation),
        # The organisation is embedded once above; datasets only refer to it,
        # so its contact point stays a single blank node.
        "dataset": [
            {k: v for k, v in description.items() if k != "@context"}
            | {"publisher": {"@id": organisation["id"]}}
            for description in descriptions
        ],
    }


def write_jsonld(path: Path, data: dict) -> Path:
    """Writes the JSON-LD and a Turtle version next to it."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    write_turtle(path)
    return path


def write_organisation(config_path: Path) -> list[Path]:
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    organisation = config["organisation"]
    catalog = config.get("catalog")
    catalog_id = catalog["id"] if catalog else None
    output_dir = OUTPUT_DIR / config_path.parent.name
    output_dir.mkdir(parents=True, exist_ok=True)

    written, descriptions = [], []
    for dataset in config.get("datasets", []):
        dataset = config.get("defaults", {}) | dataset
        description = build_description(organisation, dataset, catalog_id)
        descriptions.append(description)
        written.append(write_jsonld(output_dir / f"{dataset['slug']}.jsonld", description))

    if catalog:
        written.append(write_jsonld(
            output_dir / "datacatalog.jsonld",
            build_catalog(organisation, catalog, descriptions),
        ))

    return written


def load_profile() -> Graph:
    profile = Graph().parse(PROFILE_PATH, format="turtle")
    # The register checks these two components in a separate HTTP probe. They
    # have no SHACL implementation, and pyshacl refuses to load them.
    for component in list(profile.subjects(RDF.type, SH.ConstraintComponent)):
        for parameter in list(profile.objects(component, SH.parameter)):
            profile.remove((parameter, None, None))
        profile.remove((component, None, None))
    return profile


def _english_message(report: Graph, result) -> str:
    messages = list(report.objects(result, SH.resultMessage))
    english = [m for m in messages if getattr(m, "language", None) == "en"]
    return str((english or messages or ["(no message)"])[0])


def validate(path: Path, profile: Graph) -> int:
    """Prints the validation results and returns the number of violations."""
    print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)

    graph = Graph().parse(path, format=guess_format(str(path)) or "json-ld")
    if (None, RDF.type, URIRef(SCHEMA + "Dataset")) not in graph:
        # Without a schema:Dataset no shape applies and everything would pass.
        # The profile only targets https://schema.org/, not http://schema.org/.
        print(f"  Violation  no {SCHEMA}Dataset found in this file"
              " (http://schema.org/ is not supported)")
        return 1

    _, report, _ = pyshacl.validate(
        graph, shacl_graph=profile, inference="none", advanced=True
    )
    return print_report(report)


def print_report(report: Graph) -> int:
    """Prints the results of a SHACL report and returns the number of violations."""
    counts = {"Violation": 0, "Warning": 0, "Info": 0}
    for result in report.subjects(RDF.type, SH.ValidationResult):
        severity = str(report.value(result, SH.resultSeverity)).rpartition("#")[2]
        counts[severity] = counts.get(severity, 0) + 1
        path_term = report.value(result, SH.resultPath)
        where = str(path_term).removeprefix(SCHEMA) if path_term else "(node)"
        print(f"  {severity:<9}  {where}: {_english_message(report, result)}")

    print("  " + ", ".join(f"{n} {name.lower()}(s)" for name, n in counts.items()))
    return counts["Violation"]


def api_request(method: str, url: str, *, params: dict | None = None,
                body: bytes | None = None, content_type: str | None = None):
    """Returns the status code and body, also for error responses."""
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "text/turtle", "User-Agent": "podiumkunst-datasets-script"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def print_api_response(status: int, body: bytes) -> int:
    """Prints the register's response and returns the number of problems."""
    if status in (200, 202, 400):
        violations = print_report(Graph().parse(data=body, format="turtle"))
        return max(violations, int(status == 400))

    print(f"  {API_ERRORS.get(status, f'Unexpected response {status} from the register')}")
    detail = body.decode("utf-8", errors="replace").strip()
    if detail:
        print(f"  {detail[:500]}")
    return 1


def _id_body(url: str) -> bytes:
    return json.dumps({"@id": url}).encode()


def validate_online(target: str) -> int:
    """Validates a published URL or a local file with the register's validator."""
    print(target)
    if target.startswith(("http://", "https://")):
        # Validates what the register fetches from the URL, as it does on registration.
        status, body = api_request("PUT", API_URL + "/datasets/validate",
                                   body=_id_body(target), content_type="application/ld+json")
    else:
        is_turtle = guess_format(target) == "turtle"
        status, body = api_request(
            "POST", API_URL + "/datasets/validate", body=Path(target).read_bytes(),
            content_type="text/turtle" if is_turtle else "application/ld+json",
        )
    return print_api_response(status, body)


def register(config_path: Path, update: bool, yes: bool) -> bool:
    """Registers the organisation's published catalog. Returns False on failure."""
    with open(config_path, "rb") as f:
        catalog = tomllib.load(f).get("catalog")
    if not catalog:
        print(f"Skipping {config_path.parent.name}: no [catalog] to register")
        return True

    url = catalog["id"]
    print(url)
    status, body = api_request("GET", API_URL + "/datasets", params={"url": url})
    if status not in (200, 404):
        return print_api_response(status, body) == 0

    registered = status == 200
    if registered and not update:
        print("  Already registered. The register fetches it again periodically;"
              " use --update to have it fetched now.")
        return True

    # The register fetches the catalog from its URL, not from output/.
    action = "Re-register" if registered else "Register"
    question = f"  {action} the version that is published at this URL now? [y/N] "
    if not yes and input(question).strip().lower() != "y":
        print("  Skipped")
        return True

    status, body = api_request("POST", API_URL + "/datasets",
                               body=_id_body(url), content_type="application/ld+json")
    if status == 202:
        print("  Accepted: the register is fetching the datasets now")
    return print_api_response(status, body) == 0


def refresh_profile():
    status, content = api_request("GET", PROFILE_URL)
    if status != 200:
        sys.exit(f"Could not download the profile: {status} from {PROFILE_URL}")
    Graph().parse(data=content, format="turtle")  # Refuse to store a broken file.
    PROFILE_PATH.write_bytes(content)
    print(f"Updated {PROFILE_PATH.relative_to(ROOT)}")


def organisation_configs(names: list[str]) -> list[Path]:
    if names:
        configs = [ORGANISATIONS_DIR / name / "datasets.toml" for name in names]
        missing = [str(path.relative_to(ROOT)) for path in configs if not path.exists()]
        if missing:
            sys.exit(f"Not found: {', '.join(missing)}")
        return configs

    configs = []
    for directory in sorted(p for p in ORGANISATIONS_DIR.iterdir() if p.is_dir()):
        config = directory / "datasets.toml"
        if config.exists():
            configs.append(config)
        else:
            print(f"Skipping {directory.name}: no datasets.toml")
    return configs


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="create and validate the descriptions")
    build.add_argument("organisations", nargs="*", help="default: all organisations")

    validate_files = commands.add_parser(
        "validate", help="validate existing JSON-LD or Turtle files, without writing")
    validate_files.add_argument("files", nargs="+", metavar="FILE",
                                help="a file, or with --online also a published URL")
    validate_files.add_argument(
        "--online", action="store_true",
        help="validate with the register's own validator; this sends the files to it")

    register_catalogs = commands.add_parser(
        "register", help="register the published catalogs in the NDE Dataset Register")
    register_catalogs.add_argument("organisations", nargs="*",
                                   help="default: all organisations")
    register_catalogs.add_argument(
        "--update", action="store_true",
        help="also re-register catalogs that are already registered")
    register_catalogs.add_argument("--yes", action="store_true",
                                   help="do not ask for confirmation")

    commands.add_parser("refresh-profile", help="download the latest NDE profile")
    args = parser.parse_args()

    if args.command == "refresh-profile":
        refresh_profile()
        return

    if args.command == "register":
        results = [register(config, args.update, args.yes)
                   for config in organisation_configs(args.organisations)]
        sys.exit(0 if all(results) else 1)

    if args.command == "validate" and args.online:
        problems = sum(validate_online(target) for target in args.files)
        print(f"\nValidated {len(args.files)} description(s) online, {problems} problem(s)")
        sys.exit(1 if problems else 0)

    if args.command == "validate":
        urls = [f for f in args.files if f.startswith(("http://", "https://"))]
        if urls:
            sys.exit(f"URLs can only be validated with --online: {', '.join(urls)}")
        paths = [Path(f).resolve() for f in args.files]
    else:
        paths = [
            path
            for config in organisation_configs(args.organisations)
            for path in write_organisation(config)
        ]

    profile = load_profile()
    violations = sum(validate(path, profile) for path in paths)
    print(f"\nValidated {len(paths)} description(s), {violations} violation(s)")
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
