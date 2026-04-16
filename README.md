# SCB MCP Server v2

Ansluter AI-agenter (t.ex. n8n) till SCB:s Statistikdatabas via PxWebApi v2.

## Verktyg

| Verktyg | Beskrivning |
|---------|-------------|
| `scb_search_tables` | Sök bland alla SCB-tabeller |
| `scb_get_table_info` | Grundinfo om en specifik tabell |
| `scb_get_metadata` | Variabler och koder för en tabell |
| `scb_get_data` | Hämta statistikdata med filter |
| `scb_list_vg_regions` | Alla 49 VG-kommuner med koder |

---

## Driftsättning på Render.com

### Steg 1 — Skapa GitHub-repo

1. Gå till [github.com/new](https://github.com/new)
2. Namn: `scb-mcp-v2`
3. Klicka **Create repository**
4. Ladda upp dessa tre filer via **"uploading an existing file"**:
   - `server.py`
   - `requirements.txt`
   - `render.yaml`

### Steg 2 — Deploya på Render.com

1. Gå till [render.com](https://render.com) → **New** → **Web Service**
2. Koppla ditt GitHub-repo `scb-mcp-v2`
3. Render hittar `render.yaml` automatiskt — klicka **Create Web Service**
4. Vänta ~2 minuter tills deploy är klar
5. Din URL visas högst upp, t.ex.:
   ```
   https://scb-mcp-v2.onrender.com
   ```

### Steg 3 — Koppla in i n8n

1. Öppna ditt AI Agent-flöde i n8n
2. Klicka på **MCP Client**-noden (eller lägg till en ny)
3. Ange SSE-URL:
   ```
   https://scb-mcp-v2.onrender.com/sse
   ```
4. Spara och aktivera flödet

> **Obs:** Render.com free tier "sover" efter 15 minuters inaktivitet.
> Första anropet kan ta ~30 sekunder att vakna. Uppgradera till Starter ($7/mån) för alltid-på.

---

## Användningsexempel i chatten

### Sök tabeller
```
Sök efter befolkningsdata → scb_search_tables(query="befolkning")
```

### Hämta data för VG-kommuner
```
1. scb_search_tables(query="folkmängd")
2. scb_get_metadata(table_id="<ID från steg 1>")
3. scb_get_data(
     table_id="<ID>",
     variable_filters="Region=1480,1490,1488;Tid=top(5)"
   )
```

### VG-kommuners koder
```
scb_list_vg_regions()
scb_list_vg_regions(filter="borås")
```

---

## API-gränser (SCB)

- Max **150 000 dataceller** per anrop
- Max **30 anrop per 10 sekunder** (per IP)
- v1 stängs: **årsskiftet 2026/2027**
