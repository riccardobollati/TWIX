# Visualization

This document specifies the **fourth stage** of the pipeline: rendering the extracted JSON tree in a browser, served from a local HTTP server, so a human can inspect what was extracted at a glance. It consumes the output of stage 1 (`agent_data_extraction.md`) or stage 2 (`code_gen.md`) — both produce JSON in the same schema — and shows the **first record only**, with parent/child relationships drawn as edges that reveal their `note` text on hover.

The visualization is read-only. It is a debugging and demo tool, not an editor.

---

## 1. Pipeline Overview

```
results/<doc_name>__<model>.json
            │
            ▼
   ┌───────────────────────┐
   │ Local HTTP server     │
   │ (serves index.html +  │
   │  the JSON file)       │
   └────────────┬──────────┘
                │
                ▼
   Browser renders, in order:
     [block 1]
        │ edge — hover for note
        ▼
     [block 2]
        │
        ▼
     [block 3]
   …only nodes that belong to the FIRST RECORD are shown.
```

---

## 2. Input

A single JSON file produced by stage 1 or stage 2, conforming to `agent_data_extraction.md` §4:

```json
{
  "doc_name": "...",
  "model":    "...",
  "sampled_pages": 5,
  "records": [
    {
      "record_id": "r1",
      "nodes": [
        { "id": "...", "type": "table" | "key_value" | "metadata",
          "content": ..., "relationship": { "parent_id": "..."|null, "note": "..." } }
      ]
    },
    { "record_id": "r2", "nodes": [ ... ] }
  ]
}
```

The visualizer never modifies this file. If both `<doc>__<model>.json` (gold) and `<doc>__<model>.code_output.json` (code) exist, the user picks one at launch time (CLI flag, see §8); the chosen file is what the page renders.

---

## 3. "First Record" — Definition and Selection

The schema is records-first (`agent_data_extraction.md` §4.1): the JSON has a top-level `records` list, and each record carries its own `nodes` list. Selecting "the first record" is therefore trivial:

```
selected_record = json["records"][0]
selected_nodes  = selected_record["nodes"]
N               = len(json["records"])
```

The page renders `selected_record` only. All other records are not in the DOM — they are not styled as faded, simply absent. The page header shows `"record 1 of N"` so the user knows other records exist (§4).

Edge cases:

- If `json["records"]` is empty, abort with a clear error message in the page: `"No records in input JSON — nothing to render."`
- If `selected_record["nodes"]` is empty, render the page header but show `"(record contains no nodes)"` in italic gray in the body area.
- If a node's `parent_id` references an `id` that does not exist in this record's `nodes`, treat that node as if its parent were `null` and log a warning to the JS console so the malformed link is debuggable. (Per the spec, `parent_id` must be record-local; a violation is a data-quality issue worth surfacing.)

Within the selected record, blocks are rendered in **the order they appear in `selected_record["nodes"]`** — not in tree-traversal order. This preserves the document-order intent the spec calls for ("show in order of the extracted nodes"). Tree shape is conveyed by the edges drawn on top (§7), not by reordering or indenting blocks.

---

## 4. Page Layout

The page is a single column of blocks, each block separated by vertical whitespace. Edges are drawn as SVG arrows on an overlay layer that sits behind the blocks (so they don't intercept clicks on block content but can still receive hover events on the arrow path).

```
┌──────────────────────────────────────────────────────────┐
│  <doc_name>      model: <model>     record 1 of N        │  ← page header
├──────────────────────────────────────────────────────────┤
│                                                          │
│   [Block label: n1 · metadata]                           │
│   ┌────────────────────────────────────────────┐         │
│   │  metadata content rendered as a list        │         │
│   └────────────────────────────────────────────┘         │
│            │                                              │
│            │  ◄── SVG arrow; hover shows note            │
│            ▼                                              │
│   [Block label: n2 · key_value]                          │
│   ┌────────────────────────────────────────────┐         │
│   │  Key             Value                      │         │
│   │  ─────────────   ────────────────────       │         │
│   │  Case Number     2021-014                   │         │
│   │  …                                          │         │
│   └────────────────────────────────────────────┘         │
│            │                                              │
│            ▼                                              │
│   [Block label: n3 · table]                              │
│   ┌────────────────────────────────────────────┐         │
│   │   Allegation │ Disposition │ Discipline    │         │
│   │   ─────────  │ ─────────── │ ────────────  │         │
│   │   …          │ …           │ …             │         │
│   └────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────┘
```

Page header (always visible at the top): `doc_name`, `model`, the selected record's `record_id`, and the text `"record 1 of N"` where N is `len(json["records"])`, so the user knows other records exist but only the first is shown.

---

## 5. Block Rendering — Per Type

Each block is a `<div class="block" data-node-id="<id>">` with two parts: a label header (§6) and a body. The body is determined by `node.type`.

### 5.1 `type = table`

Render as an HTML `<table>`:

- Header row from `content.headers`, in order. Use `<th>`.
- One body row per entry in `content.rows`. For each row, lay cells out **in `headers` order** by looking up each header in the row's `[{key, value}]` list. If a row is missing a key that exists in `headers`, render the cell as empty (and add a `data-missing="true"` attribute so it can be styled differently — e.g. a pale gray hatch).
- If a row contains a `key` that is **not** in `headers`, render an extra column at the end and tag the `<th>` and `<td>` with `class="extra-key"` so the irregularity is visible.

Styling: zebra striping on rows, sticky header within the block (not within the page), `font-variant-numeric: tabular-nums` so numeric columns align.

### 5.2 `type = key_value`

Render as a two-column table or a `<dl>`. Recommended: a two-column `<table>`:

- Left column header: `Key`, right column header: `Value`.
- One row per `{key, value}` entry, **in the order they appear in `content`**.
- Long values wrap; do not truncate.

### 5.3 `type = metadata`

Render as an unordered list (`<ul>`) — one `<li>` per string in `content`, in order. If `content` has exactly one item, render a single `<p>` instead so it doesn't look like a degenerate list.

### 5.4 Empty content

If a block's `content` is structurally empty (e.g. a `table` with zero rows, an empty `key_value` list, an empty `metadata` list), render the body area with the placeholder text `(empty)` in italic gray. Do not omit the block — its presence is meaningful.

---

## 6. Block Labels

Every block has a label header above its body. The label is a small horizontal strip showing:

```
  [<id>]   <type>   ·   <auto-summary>
```

Where:

- `<id>` is the node's `id` from the JSON, in a monospace badge.
- `<type>` is `table` / `key_value` / `metadata`, color-coded (one accent color per type — pick three distinct colors and use them consistently across labels and edges for that node's outgoing arrows).
- `<auto-summary>` is a short, machine-generated description so the block is recognizable without reading the body:
  - `table`: `"Table — <header_count> cols × <row_count> rows"`, e.g. `"Table — 3 cols × 5 rows"`.
  - `key_value`: `"Key-value — <pair_count> pairs"`.
  - `metadata`: `"Metadata — <item_count> items"`. If `item_count == 1`, show the single string truncated to 40 chars.

The label is always visible; it is **not** based on the `note` field (which describes the block's *relationship* to its parent, not the block itself).

---

## 7. Edges and Hover Tooltips

For every node `c` in the rendered subset whose `relationship.parent_id` points to a node `p` that is **also in the rendered subset**, draw a single edge from `p`'s block to `c`'s block.

### 7.1 Geometry

- Edges live on a single `<svg>` overlay positioned absolutely over the blocks column, sized to the column's bounding box.
- Each edge is an SVG `<path>` (a vertical or curved line with an arrowhead `<marker>` at the child end).
- Routing: anchor the start of the arrow at the **bottom-center** of the parent block and the end at the **top-center** of the child block. If the parent and child are not adjacent in the rendered order, route the path around intervening blocks with a small horizontal offset so the arrow doesn't pass through them. A simple heuristic: bend the path to the right by `gutter_px` (e.g. 32px) and run it down the right margin of the column.
- Recompute geometry on window resize and on scroll-induced reflow (use `ResizeObserver` on the column container).

### 7.2 Hover behavior

- The `<path>` has `pointer-events: stroke` and a generous `stroke-width` (e.g. 2px visible, 12px invisible "hit area" via a transparent duplicate path) so it's easy to hover.
- On `mouseenter`, show a tooltip near the cursor containing **exactly** the child node's `relationship.note` text. If the `note` is empty, show the placeholder `(no note recorded)` in italic gray.
- The tooltip also shows the parent and child labels for context, on a separate small line above the note:
  ```
  n1 (metadata) → n2 (key_value)
  ───────────────────────────────
  case-level metadata for the report named in n1
  ```
- The tooltip follows the cursor (or anchors near the edge midpoint — pick one and be consistent). Hide on `mouseleave`.
- Hovering the edge also temporarily highlights both endpoint blocks (e.g. a 2px outline in the edge's color) so the relationship is unambiguous even when the page is scrolled.

### 7.3 No cross-record edges

By spec, `parent_id` is record-local. If the selected record contains a node whose `parent_id` doesn't resolve inside that record's `nodes` list (i.e. malformed data), do **not** draw an edge. Add a small badge to the child block's label: `"⚠ unresolved parent: <id>"` so the situation is visible without breaking the layout.

---

## 8. Local Server

The page is served by a small local HTTP server. Two requirements:

1. The server can be started with a single command and takes the JSON path as an argument.
2. The browser can fetch the JSON from the same origin (no CORS), and reloads on JSON changes are a simple browser refresh — no build step.

Recommended implementation: a stdlib-only Python launcher.

```
python src/visualization/serve.py results/<doc_name>__<model>.json [--port 8765]
```

Behavior:

- Reads the JSON file once at startup, validates it against the stage-1 schema (`agent_data_extraction.md` §7), and aborts with a clear error if invalid.
- Computes the first-record subset per §3.
- Serves a single static directory containing `index.html`, `app.js`, `styles.css`, and exposes the JSON at `/data.json`.
- Prints `Visualization ready at http://localhost:<port>/` and exits on Ctrl-C.
- Defaults: port `8765`, bind to `127.0.0.1` only (do not expose on `0.0.0.0`; this is a local-only debugging tool).

Optional: a `--watch` flag that rereads the JSON on file change and bumps an ETag so the page can poll and reload. Out of scope for v1; mention it for future work.

The frontend is plain HTML + vanilla JS + a tiny amount of CSS. **No frameworks.** This keeps the visualizer a single-step debug tool with zero install footprint beyond Python's standard library.

---

## 9. Outputs

Visualization is a viewer, not a producer. It does not write to `results/`. The only thing the user gets back is the running webpage.

If the user wants to share a snapshot, the index page should expose a **"Save as HTML"** button that downloads the current DOM (with the SVG overlay inlined and the JSON embedded as a `<script type="application/json">` tag) so a single-file copy can be opened offline. This is purely a convenience; the canonical artifact remains the JSON in `results/`.

---

## 10. Suggested Project Layout

Building on the layouts from the previous three docs:

```
twix2.0/
├── docs/
│   ├── agent_data_extraction.md
│   ├── code_gen.md
│   ├── eval.md
│   └── visualization.md           # this file
├── results/
└── src/
    ├── data_extraction/           # stage 1
    ├── code_gen/                  # stage 2
    ├── eval/                      # stage 3
    └── visualization/             # stage 4
        ├── serve.py               # tiny stdlib HTTP server, takes JSON path
        ├── first_record.py        # §3 subset selection
        └── static/
            ├── index.html
            ├── app.js             # fetch /data.json, render blocks + edges
            └── styles.css
```

---

## 11. Validation Checklist

Before considering the visualization done:

1. `serve.py results/<doc>__<model>.json` starts without error and the page loads at `http://localhost:8765/`.
2. The page header shows the correct `doc_name`, `model`, `record_id` of the first record, and `record 1 of N` where N matches `len(json["records"])`.
3. Exactly the nodes inside `json["records"][0]` appear in the DOM. No nodes from any other record are present.
4. Blocks render in **`records[0].nodes`-array order**, not in tree-traversal order.
5. Tables show every header in `content.headers`; every rendered row has the same number of cells as headers (with empty cells for missing keys flagged via `data-missing`).
6. Key-value blocks show one row per entry, in input order.
7. Metadata blocks show one list item per string, in input order.
8. Every block has a label conforming to §6, with the auto-summary correctly reflecting the content.
9. For every parent/child pair where both endpoints are in the rendered subset, exactly one edge connects them.
10. Hovering an edge shows a tooltip containing the child node's `relationship.note` (or the `(no note recorded)` placeholder), plus the parent → child label line.
11. Edges re-route correctly on window resize.
12. The page is read-only — clicking, double-clicking, or right-clicking blocks does not mutate the JSON file on disk.
13. Server binds to `127.0.0.1` only, never `0.0.0.0`.
