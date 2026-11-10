# Datasets Podiumkunst.net

Deze repository bevat python scripts om verschillende dataset-beschrijvingen te maken, valideren en publiceren in het [NDE datasetregister](https://datasetregister.netwerkdigitaalerfgoed.nl/).
Geïnspireerd door de code van [Hay Kranen](https://github.com/hay) in [deze repository van het NADD](https://github.com/naddnetwork/datasetregister).  

## Gebruik

Installeer [`uv`](https://docs.astral.sh/uv/) en doe eenmalig een `uv sync` in de root van dit project.

| Commando | Wat het doet |
| --- | --- |
| `uv run datasets.py build` | Maakt en valideert de beschrijvingen van alle organisaties |
| `uv run datasets.py build som pknet` | Doet hetzelfde voor alleen deze organisaties |
| `uv run datasets.py validate bestand.jsonld` | Valideert bestaande bestanden (JSON-LD of Turtle), zonder iets te schrijven |
| `uv run datasets.py validate --online bestand.ttl` of `... --online <url>` | Valideert met de validator van het NDE-datasetregister zelf. Die controleert ook of URL's bereikbaar zijn. Let op: dit stuurt het bestand naar het register (zonder het te registreren) |
| `uv run datasets.py register` | Registreert de gepubliceerde datacatalogus van elke organisatie, als die nog niet geregistreerd is. Vraagt eerst om bevestiging |
| `uv run datasets.py register --update` | Registreert ook catalogi die al geregistreerd zijn opnieuw, zodat het register ze meteen opnieuw ophaalt |
| `uv run datasets.py refresh-profile` | Downloadt het NDE-profiel dat het register zelf gebruikt |

De gemaakte beschrijvingen komen in `output/<organisatie>/` te staan.

### Een organisatie of dataset toevoegen

Elke organisatie heeft een eigen map met een `organisations/<organisatie>/datasets.toml`. 
Zie `organisations/som/datasets.toml` als voorbeeld. Wat daarin staat wordt gebruikt bij de generatie van de RDF-bestanden.
Het bestaat uit:

- `[organisation]` met de gegevens van de organisatie, die als maker en uitgever worden gebruikt, en `[organisation.contact_point]` met het contactpunt.
- `[catalog]` met de `id`, naam en beschrijving van de datacatalogus. De datasets verwijzen hier automatisch naar. Zonder deze sectie wordt er geen datacatalogus gemaakt.
- `[defaults]` met waarden die voor alle datasets van de organisatie gelden. Een dataset kan deze overschrijven.
- `[[datasets]]` per dataset, met daaronder `[[datasets.distributions]]` per distributie.

Teksten schrijf je per taal als `name.nl = "..."` en `name.en = "..."`. Is een tekst in beide talen gelijk, dan schrijf je die één keer als `name = "..."` en krijgt hij zowel de taal nl als en. Dit geldt voor namen, beschrijvingen, trefwoorden, genres en de url van de organisatie. 
Distributies nemen `license`, `in_language` en de datums over van hun dataset, tenzij ze een eigen waarde hebben. 
Zonder `date_modified` wordt de datum van vandaag gebruikt.

### Validatie

De beschrijvingen worden lokaal gevalideerd tegen de SHACL-shapes van het NDE-datasetregister, opgeslagen in `profile/nde-dataset-register.ttl`. De exit code is 1 als er violations zijn. Warnings en infos worden alleen getoond.

Deze validatie controleert niet of URL's bereikbaar zijn. Dat doet het register zelf in een aparte stap. Gebruik `validate --online` om ook dat te controleren.

### Registreren

Het register haalt een datacatalogus op van de URL in `[catalog] id`, niet uit `output/`. Publiceer de catalogus dus eerst, en registreer daarna. De datasets in de catalogus worden daarmee ook geregistreerd. Bij opnieuw registreren blijft de oorspronkelijke registratiedatum staan, en verdwijnen datasets die niet meer in de catalogus staan. Een catalogus die niet geldig is, wordt geweigerd, en de bestaande registratie blijft dan ongewijzigd.
