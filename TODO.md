# Todo

- [x] Add registration of a dataset in the NDE Dataset Register to the script
      (`uv run datasets.py register`, with `--update` to re-register).
- [ ] First real registration with `register --update`, after publishing the current catalogs.
      Not yet done: on 2026-11-10 `https://data.muziekschatten.nl/sparql` (the contentUrl of all
      distributions) was unreachable, and the register's validator counts that as a violation.
      Check with `uv run datasets.py validate --online <catalog url>` first.
- [ ] Serve data.podiumkunst.net from the QLever triplestore (the one set up with Skosmos in
      another project) instead of uploading files manually:
  - [ ] Add `uv run datasets.py upload`, which loads each `output/<org>/datacatalog.ttl` into its
        own named graph, named after the catalog URI
        (e.g. `https://data.podiumkunst.net/datacatalog/pknet`).
  - [ ] Replace that graph completely on every upload, never append to it. Distributions and
        contact points are blank nodes, so loading a file twice would duplicate them.
  - [ ] Check how QLever accepts updates (SPARQL Update, Graph Store Protocol or rebuilding the
        index) and how its access token is handled, so the token stays out of this repository.
  - [ ] Let the site build `/dataset/<slug>` and `/datacatalog/<org>` from queries on the store.
        Use an explicit `CONSTRUCT` that includes the distribution, contact point and organisation,
        unless QLever's `DESCRIBE` is confirmed to include blank nodes.
  - [ ] Once the site reads from the store, stop writing the separate dataset files (or make them
        optional), since the catalogs then hold everything.
- [ ] Decide whether to restructure `datasets.py` into classes, like the NADD script:
      a `DatasetWriter` per organisation and a `ProfileValidator` that holds the NDE profile.
