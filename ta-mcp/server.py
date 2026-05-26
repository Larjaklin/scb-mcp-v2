"""
Tillväxtanalys MCP Server — PxWebAPI v1
Ger AI-agenter tillgång till Tillväxtanalys statistikdatabas via fyra verktyg:
  - ta_list_tables        : Bläddra bland tabeller och kataloger
  - ta_get_table_metadata : Hämta variabler och tillåtna värden för en tabell
  - ta_query_table        : Kör valfri PxWeb-fråga mot en tabell
  - ta_konkurser_arsvis   : Färdigt verktyg: årsvis konkursstatistik per län
"""

import json
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

TA_BASE_URL = os.environ.get(
    "TA_BASE_URL",
    "https://statistik.tillvaxtanalys.se/PxWeb/api/v1/sv",
)

# Sökväg till konkursstatistik per län (verifiera med ta_list_tables vid behov)
KONKURS_LAN_PATH = (
    "Tillväxtanalys statistikdatabas/"
    "Tillväxtanalys statistikdatabas__Konkurser och offentliga ackord/"
    "konk_ar_lan_1996.px"
)

SWEDISH_COUNTIES: dict[str, str] = {
    "01": "Stockholms län",
    "03": "Uppsala län",
    "04": "Södermanlands län",
    "05": "Östergötlands län",
    "06": "Jönköpings län",
    "07": "Kronobergs län",
    "08": "Kalmar län",
    "09": "Gotlands län",
    "10": "Blekinge län",
    "12": "Skåne län",
    "13": "Hallands län",
    "14": "Västra Götalands län",
    "17": "Värmlands län",
    "18": "Örebro län",
    "19": "Västmanlands län",
    "20": "Dalarnas län",
    "21": "Gävleborgs län",
    "22": "Västernorrlands län",
    "23": "Jämtlands län",
    "24": "Västerbottens län",
    "25": "Norrbottens län",
}

# ---------------------------------------------------------------------------
# MCP-server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ta_mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)

# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------


async def _ta_get(path: str) -> list | dict:
    """GET mot Tillväxtanalys PxWebAPI v1."""
    url = f"{TA_BASE_URL}/{path}" if path else TA_BASE_URL
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            messages = {
                400: "Felaktig förfrågan (400): Kontrollera sökväg och variabelkoder.",
                403: "Förbjudet (403): Frågan returnerar för många dataceller. Lägg till filter.",
                404: "Hittades inte (404): Kontrollera tabellsökvägen.",
                429: "För många anrop (429): Vänta och försök igen.",
            }
            raise ValueError(messages.get(status, f"API-fel ({status}): {e.response.text[:300]}"))
        except httpx.TimeoutException:
            raise ValueError("Timeout: Tillväxtanalys API svarade inte inom 30 sekunder.")


async def _ta_post(path: str, body: dict) -> dict:
    """POST mot Tillväxtanalys PxWebAPI v1 (datahämtning)."""
    url = f"{TA_BASE_URL}/{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            messages = {
                400: "Felaktig förfrågan (400): Kontrollera frågesyntaxen och variabelkoderna.",
                403: "Förbjudet (403): Frågan returnerar för många dataceller. Lägg till filter.",
                404: "Hittades inte (404): Kontrollera tabellsökvägen.",
                429: "För många anrop (429): Vänta och försök igen.",
            }
            raise ValueError(messages.get(status, f"API-fel ({status}): {e.response.text[:300]}"))
        except httpx.TimeoutException:
            raise ValueError("Timeout: Tillväxtanalys API svarade inte inom 30 sekunder.")


def _format_catalog(data: list | dict, path: str) -> str:
    """Formaterar PxWebAPI v1 kataloglista till markdown."""
    if isinstance(data, dict):
        # Enstaka tabell returnerar metadata direkt
        return f"*Tabellen '{path}' returnerade metadata direkt — använd ta_get_table_metadata.*"

    lines = [f"## Tillväxtanalys katalog: {path or 'Rot'}\n"]
    folders = [item for item in data if item.get("type") == "l"]
    tables = [item for item in data if item.get("type") == "t"]

    if folders:
        lines.append(f"### Mappar ({len(folders)})")
        for f in folders:
            lines.append(f"- **{f.get('text', '?')}** — id: `{f.get('id', '?')}`")
        lines.append("")

    if tables:
        lines.append(f"### Tabeller ({len(tables)})")
        for t in tables:
            upd = t.get("updated", "")[:10]
            upd_str = f" — uppdaterad {upd}" if upd else ""
            lines.append(f"- **{t.get('text', '?')}** — id: `{t.get('id', '?')}`{upd_str}")
        lines.append("")

    if not folders and not tables:
        lines.append("*Inga tabeller eller mappar hittades på denna sökväg.*")

    return "\n".join(lines)


def _parse_px_json(data: dict) -> str:
    """Konverterar PxWebAPI v1 'json'-svar till markdown-tabell."""
    # Format: {"columns": [...], "data": [{"key": [...], "values": [...]}, ...]}
    columns = data.get("columns", [])
    rows = data.get("data", [])

    if not columns or not rows:
        # Försök JSON-stat-format som fallback
        if "id" in data and "value" in data:
            return _parse_json_stat(data)
        return f"Inga data returnerades.\n\nRåsvar:\n{json.dumps(data, ensure_ascii=False)[:2000]}"

    dim_cols = [c for c in columns if c.get("type") in ("d", "t")]
    val_cols = [c for c in columns if c.get("type") == "c"]
    headers = [c.get("text", c.get("code", "?")) for c in dim_cols + val_cols]

    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
    ]
    for row in rows:
        keys = row.get("key", [])
        values = row.get("values", [])
        cells = keys + values
        lines.append("| " + " | ".join(str(c) if c is not None else "." for c in cells) + " |")

    lines.append(f"\n*{len(rows)} rader*")
    return "\n".join(lines)


def _parse_json_stat(data: dict) -> str:
    """Konverterar JSON-stat-svar till markdown-tabell (fallback)."""
    import itertools

    dim_ids: list[str] = data.get("id", [])
    dimensions: dict = data.get("dimension", {})
    values: list = data.get("value", [])

    dim_codes: dict[str, list[str]] = {}
    dim_labels: dict[str, dict[str, str]] = {}
    for dim_id in dim_ids:
        dim = dimensions.get(dim_id, {})
        cat = dim.get("category", {})
        idx = cat.get("index", {})
        lbl = cat.get("label", {})
        dim_codes[dim_id] = sorted(idx.keys(), key=lambda k: idx[k])
        dim_labels[dim_id] = lbl

    headers = [dimensions.get(d, {}).get("label", d) for d in dim_ids] + ["Värde"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
    ]
    combos = list(itertools.product(*[dim_codes[d] for d in dim_ids]))
    for i, combo in enumerate(combos):
        if i >= len(values):
            break
        parts = [dim_labels[d].get(c, c) for d, c in zip(dim_ids, combo)]
        val_str = str(values[i]) if values[i] is not None else "."
        lines.append("| " + " | ".join(parts + [val_str]) + " |")

    lines.append(f"\n*{len(combos)} kombinationer*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verktyg 1 — Bläddra i katalog
# ---------------------------------------------------------------------------


class ListTablesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: Optional[str] = Field(
        default=None,
        description=(
            "Sökväg i katalogen. Lämna tomt för rotnivån. "
            "Exempel: 'Tillväxtanalys statistikdatabas' eller "
            "'Tillväxtanalys statistikdatabas/Tillväxtanalys statistikdatabas__Konkurser och offentliga ackord'"
        ),
    )


@mcp.tool(
    name="ta_list_tables",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ta_list_tables(params: ListTablesInput) -> str:
    """Bläddra bland tabeller och kataloger i Tillväxtanalys statistikdatabas.

    Navigera katalogstrukturen steg för steg: börja utan path för rotnivån,
    klicka sedan vidare med mapp-id:n för att hitta specifika tabeller.

    Args:
        params (ListTablesInput):
            - path (str, valfri): Sökväg i katalogen (tomt = rot)

    Returns:
        str: Markdown med mappar och tabeller på den valda nivån
    """
    try:
        path = params.path.strip("/") if params.path else ""
        data = await _ta_get(path)
        return _format_catalog(data, path)
    except ValueError as exc:
        return f"Fel vid katalogbläddring: {exc}"


# ---------------------------------------------------------------------------
# Verktyg 2 — Tabellmetadata
# ---------------------------------------------------------------------------


class GetTableMetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    table_path: str = Field(
        ...,
        description=(
            "Fullständig sökväg till tabellen (inklusive .px-fil), t.ex. "
            "'Tillväxtanalys statistikdatabas/"
            "Tillväxtanalys statistikdatabas__Konkurser och offentliga ackord/"
            "konk_ar_lan_1996.px'"
        ),
        min_length=1,
        max_length=500,
    )


@mcp.tool(
    name="ta_get_table_metadata",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ta_get_table_metadata(params: GetTableMetadataInput) -> str:
    """Hämta variabler och tillåtna värden för en Tillväxtanalys-tabell.

    Visar alla dimensioner med koder och möjliga värden.
    Obligatoriskt steg innan datahämtning med ta_query_table.

    Args:
        params (GetTableMetadataInput):
            - table_path (str): Fullständig sökväg till tabellen inkl. .px-fil

    Returns:
        str: Markdown med variabler, koder och möjliga värden
    """
    try:
        path = params.table_path.strip("/")
        data = await _ta_get(path)

        if not isinstance(data, dict) or "variables" not in data:
            raw = json.dumps(data, ensure_ascii=False)[:3000]
            return f"Oväntad datastruktur (ingen 'variables'-nyckel):\n{raw}"

        title = data.get("title", path.split("/")[-1])
        lines = [f"## Metadata: {title}\n"]

        for var in data.get("variables", []):
            code = var.get("code", "?")
            text = var.get("text", "?")
            values = var.get("values", [])
            value_texts = var.get("valueTexts", values)
            elimination = var.get("elimination", False)

            lines.append(f"### `{code}` — {text}")
            lines.append(f"- Valfri (kan utelämnas): {'Ja' if elimination else 'Nej'}")
            lines.append(f"- Antal värden: {len(values)}")

            pairs = list(zip(values, value_texts))[:30]
            if pairs:
                lines.append("- Koder:")
                for v, vt in pairs:
                    lines.append(f"  - `{v}` = {vt}")
                if len(values) > 30:
                    lines.append(f"  - *…och {len(values) - 30} till*")
            lines.append("")

        lines += [
            "---",
            "**Använd ta_query_table med dessa koder. Exempel:**",
            "```json",
            '{',
            '  "query": [',
            '    {"code": "Lan", "selection": {"filter": "item", "values": ["14"]}},',
            '    {"code": "Tid", "selection": {"filter": "range", "values": ["2015", "2024"]}}',
            '  ],',
            '  "response": {"format": "json"}',
            '}',
            "```",
            "",
            "**Filter-typer:** `item` (specifika värden), `all` (alla, values=[\"*\"]), "
            "`range` (intervall, values=[\"från\", \"till\"]), `top` (senaste N, values=[\"5\"])",
        ]
        return "\n".join(lines)
    except ValueError as exc:
        return f"Fel: {exc}"


# ---------------------------------------------------------------------------
# Verktyg 3 — Kör valfri PxWeb-fråga
# ---------------------------------------------------------------------------


class QueryTableInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    table_path: str = Field(
        ...,
        description="Fullständig sökväg till tabellen inkl. .px-fil",
        min_length=1,
        max_length=500,
    )
    query: str = Field(
        ...,
        description=(
            "PxWeb v1 JSON-fråga som sträng. Exempel: "
            '\'{"query": [{"code": "Lan", "selection": {"filter": "item", "values": ["14"]}}, '
            '{"code": "Tid", "selection": {"filter": "range", "values": ["2015", "2024"]}}], '
            '"response": {"format": "json"}}\''
        ),
    )
    output_format: Optional[str] = Field(
        default="readable",
        description="'readable' (markdown-tabell, default) eller 'json' (rådata)",
    )


@mcp.tool(
    name="ta_query_table",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ta_query_table(params: QueryTableInput) -> str:
    """Kör en valfri PxWeb-fråga mot en Tillväxtanalys-tabell.

    Kräver att variabelkoder är kända (kör ta_get_table_metadata först).
    Frågan skickas som POST med PxWebAPI v1 JSON-format.

    Args:
        params (QueryTableInput):
            - table_path (str): Fullständig sökväg till tabellen
            - query (str): PxWeb v1 JSON-fråga (se ta_get_table_metadata för koder)
            - output_format (str): 'readable' | 'json'

    Returns:
        str: Statistikdata i valt format
    """
    try:
        body = json.loads(params.query)
    except json.JSONDecodeError as exc:
        return f"Ogiltig JSON-fråga: {exc}\n\nKontrollera att JSON-syntaxen är korrekt."

    if "response" not in body:
        body["response"] = {"format": "json"}

    try:
        path = params.table_path.strip("/")
        data = await _ta_post(path, body)

        if params.output_format == "json":
            return json.dumps(data, ensure_ascii=False, indent=2)

        result = _parse_px_json(data)
        return f"## Resultat\n\n{result}"

    except ValueError as exc:
        return f"Fel vid datahämtning: {exc}"


# ---------------------------------------------------------------------------
# Verktyg 4 — Årsvis konkursstatistik per län (färdigkonfigurerat)
# ---------------------------------------------------------------------------


class KonkurserArsvisInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    lan_kod: str = Field(
        ...,
        description=(
            "Länskod, t.ex. '14' för Västra Götaland, '01' för Stockholm. "
            "Ange '*' för alla 21 län."
        ),
        min_length=1,
        max_length=2,
    )
    start_year: int = Field(
        default=2015,
        description="Startår (data finns från 1996)",
        ge=1996,
        le=2030,
    )
    end_year: int = Field(
        default=2024,
        description="Slutår",
        ge=1996,
        le=2030,
    )


@mcp.tool(
    name="ta_konkurser_arsvis",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ta_konkurser_arsvis(params: KonkurserArsvisInput) -> str:
    """Hämta årsvis konkursstatistik per län från Tillväxtanalys.

    Färdigkonfigurerat verktyg — ange bara länskod och tidsperiod.
    Data inkluderar antal konkurser och berörda anställda per år.
    Täcker perioden 1996 och framåt, uppdateras månadsvis.

    Länskoder:
      01=Stockholm, 03=Uppsala, 04=Södermanland, 05=Östergötland,
      06=Jönköping, 07=Kronoberg, 08=Kalmar, 09=Gotland, 10=Blekinge,
      12=Skåne, 13=Halland, 14=Västra Götaland, 17=Värmland, 18=Örebro,
      19=Västmanland, 20=Dalarna, 21=Gävleborg, 22=Västernorrland,
      23=Jämtland, 24=Västerbotten, 25=Norrbotten

    Args:
        params (KonkurserArsvisInput):
            - lan_kod (str): Länskod, t.ex. '14' för Västra Götaland
            - start_year (int): Startår, default 2015
            - end_year (int): Slutår, default 2024

    Returns:
        str: Markdown-tabell med konkursstatistik per år
    """
    if params.start_year > params.end_year:
        return "Fel: start_year måste vara ≤ end_year."

    if params.lan_kod == "*":
        lan_filter = "all"
        lan_values = ["*"]
        lan_desc = "alla svenska län"
    else:
        lan_filter = "item"
        lan_values = [params.lan_kod]
        lan_desc = SWEDISH_COUNTIES.get(params.lan_kod, f"Länskod {params.lan_kod}")

    body = {
        "query": [
            {
                "code": "Lan",
                "selection": {
                    "filter": lan_filter,
                    "values": lan_values,
                },
            },
            {
                "code": "Tid",
                "selection": {
                    "filter": "range",
                    "values": [str(params.start_year), str(params.end_year)],
                },
            },
        ],
        "response": {"format": "json"},
    }

    try:
        data = await _ta_post(KONKURS_LAN_PATH, body)
        table = _parse_px_json(data)
        header = (
            f"## Konkurser i {lan_desc} ({params.start_year}–{params.end_year})\n"
            f"*Källa: Tillväxtanalys statistikdatabas*\n"
        )
        return header + table

    except ValueError as exc:
        hint = ""
        if "404" in str(exc):
            hint = (
                "\n\n**Tips:** Tabellsökvägen kan vara fel. "
                "Kör `ta_list_tables` med path='Tillväxtanalys statistikdatabas' "
                "för att hitta rätt mappnamn, och sedan navigera till konkurs-tabellen."
            )
        return f"Fel: {exc}{hint}"


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

# ASGI-app exponeras på modulnivå för Render/uvicorn
app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
