/* visualization.md — extraction tree viewer, vanilla JS, no frameworks. */

'use strict';

// ── Type color palette ──────────────────────────────────────────────────────
const TYPE_COLORS = {
  table:     '#3b82f6',  // blue
  key_value: '#16a34a',  // green
  metadata:  '#ea580c',  // orange
};

// ── Module state ────────────────────────────────────────────────────────────
const state = {
  jsonData: null,
  nodes: [],
  idToNode: {},
  idToBlock: {},
};

let tooltip = null;
let currentHighlighted = [];

// ── Startup ─────────────────────────────────────────────────────────────────
async function main() {
  try {
    state.jsonData = await fetchData();
    renderContent(state.jsonData);
  } catch (err) {
    document.getElementById('page-body').innerHTML =
      `<p class="error">Failed to load data: ${escHtml(String(err))}</p>`;
  }
}

async function fetchData() {
  // Prefer embedded JSON (for saved offline HTML files).
  const embedded = document.getElementById('embedded-data');
  if (embedded && embedded.textContent.trim()) {
    return JSON.parse(embedded.textContent);
  }
  const resp = await fetch('/data.json');
  if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching /data.json`);
  return resp.json();
}

// ── Content rendering ────────────────────────────────────────────────────────
function renderContent(data) {
  const header = document.getElementById('page-header');
  const body   = document.getElementById('page-body');
  body.innerHTML = '';

  const records  = data.records || [];
  const nRecords = records.length;
  const docName  = data.doc_name || '(no doc_name)';
  const model    = data.model    || '(no model)';

  // Page header
  header.innerHTML = `
    <span class="doc-name">${escHtml(docName)}</span>
    <span class="model-label">model: ${escHtml(model)}</span>
    <span class="record-info">
      record <strong>${nRecords > 0 ? escHtml(records[0].record_id || '1') : '—'}</strong>
      of ${nRecords}
    </span>
    <button id="save-btn" onclick="saveAsHTML()">Save as HTML</button>
  `;

  if (nRecords === 0) {
    body.innerHTML = '<p class="error">No records in input JSON — nothing to render.</p>';
    return;
  }

  const firstRecord = records[0];
  const nodes = firstRecord.nodes || [];

  // Build lookup maps
  state.nodes = nodes;
  state.idToNode = {};
  for (const n of nodes) state.idToNode[n.id] = n;
  state.idToBlock = {};

  if (nodes.length === 0) {
    body.innerHTML = '<p class="empty-record">(record contains no nodes)</p>';
    return;
  }

  // Column container (blocks + SVG overlay)
  const colContainer   = document.createElement('div');
  colContainer.id      = 'col-container';
  const blocksDiv      = document.createElement('div');
  blocksDiv.id         = 'blocks-container';
  colContainer.appendChild(blocksDiv);
  body.appendChild(colContainer);

  // Render blocks in document order
  for (const node of nodes) {
    const blockEl = buildBlock(node, state.idToNode);
    blocksDiv.appendChild(blockEl);
    state.idToBlock[node.id] = blockEl;
  }

  // Draw edges after layout is stable
  requestAnimationFrame(() => {
    drawEdges(colContainer);
    // ResizeObserver: recompute edges on column resize
    const ro = new ResizeObserver(() => drawEdges(colContainer));
    ro.observe(colContainer);
  });
}

// ── Block construction ───────────────────────────────────────────────────────
function buildBlock(node, idToNode) {
  const color = TYPE_COLORS[node.type] || '#888';
  const div   = document.createElement('div');
  div.className    = 'block';
  div.dataset.nodeId = node.id;

  // Detect unresolved parent
  const pid = node.relationship && node.relationship.parent_id;
  const hasUnresolved = pid && !idToNode[pid];

  // Label
  const label = document.createElement('div');
  label.className = 'block-label';
  label.style.borderLeftColor = color;
  label.innerHTML = [
    `<span class="node-id" style="color:${color}">[${escHtml(node.id)}]</span>`,
    `<span class="node-type" style="color:${color}">${escHtml(node.type)}</span>`,
    `<span class="node-summary">· ${escHtml(autoSummary(node))}</span>`,
    hasUnresolved
      ? `<span class="parent-warning">⚠ unresolved parent: ${escHtml(String(pid))}</span>`
      : '',
  ].join('');

  // Body
  const bodyDiv = document.createElement('div');
  bodyDiv.className = 'block-body';

  let bodyHtml = '';
  if (node.type === 'table')     bodyHtml = renderTable(node.content);
  else if (node.type === 'key_value') bodyHtml = renderKeyValue(node.content);
  else if (node.type === 'metadata')  bodyHtml = renderMetadata(node.content);

  bodyDiv.innerHTML = bodyHtml || '<em class="empty-content">(empty)</em>';

  div.appendChild(label);
  div.appendChild(bodyDiv);
  return div;
}

function autoSummary(node) {
  const c = node.content;
  if (node.type === 'table') {
    const h = (c && c.headers) ? c.headers.length : 0;
    const r = (c && c.rows)    ? c.rows.length    : 0;
    return `Table — ${h} cols × ${r} rows`;
  }
  if (node.type === 'key_value') {
    const p = Array.isArray(c) ? c.length : 0;
    return `Key-value — ${p} pairs`;
  }
  if (node.type === 'metadata') {
    const items = Array.isArray(c) ? c.length : 0;
    if (items === 1) {
      const s = String(c[0] || '');
      return `Metadata — "${s.length > 40 ? s.slice(0, 40) + '…' : s}"`;
    }
    return `Metadata — ${items} items`;
  }
  return '';
}

// ── Per-type body renderers ──────────────────────────────────────────────────
function renderTable(content) {
  if (!content || !Array.isArray(content.headers) || !Array.isArray(content.rows)) {
    return '<em class="empty-content">(empty)</em>';
  }
  const headers = content.headers;
  const rows    = content.rows;
  if (headers.length === 0 && rows.length === 0) {
    return '<em class="empty-content">(empty)</em>';
  }

  // Collect any extra keys present in rows but absent from headers
  const headerSet = new Set(headers.map(String));
  const extraKeys = [];
  for (const row of rows) {
    for (const cell of row) {
      const k = String(cell.key ?? '');
      if (!headerSet.has(k) && !extraKeys.includes(k)) extraKeys.push(k);
    }
  }

  let html = '<div class="table-wrapper"><table class="node-table"><thead><tr>';
  for (const h of headers) html += `<th>${escHtml(String(h))}</th>`;
  for (const k of extraKeys) html += `<th class="extra-key">${escHtml(k)}</th>`;
  html += '</tr></thead><tbody>';

  for (const row of rows) {
    const kv = {};
    for (const cell of row) kv[String(cell.key ?? '')] = cell.value;
    html += '<tr>';
    for (const h of headers) {
      const hStr = String(h);
      if (hStr in kv) {
        html += `<td>${escHtml(String(kv[hStr] ?? ''))}</td>`;
      } else {
        html += `<td data-missing="true" class="missing-cell"></td>`;
      }
    }
    for (const k of extraKeys) {
      if (k in kv) {
        html += `<td class="extra-key">${escHtml(String(kv[k] ?? ''))}</td>`;
      } else {
        html += `<td data-missing="true" class="missing-cell extra-key"></td>`;
      }
    }
    html += '</tr>';
  }
  return html + '</tbody></table></div>';
}

function renderKeyValue(content) {
  if (!Array.isArray(content) || content.length === 0) {
    return '<em class="empty-content">(empty)</em>';
  }
  let html = '<table class="kv-table"><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>';
  for (const item of content) {
    html += `<tr>
      <td class="kv-key">${escHtml(String(item.key  ?? ''))}</td>
      <td class="kv-value">${escHtml(String(item.value ?? ''))}</td>
    </tr>`;
  }
  return html + '</tbody></table>';
}

function renderMetadata(content) {
  if (!Array.isArray(content) || content.length === 0) {
    return '<em class="empty-content">(empty)</em>';
  }
  if (content.length === 1) {
    return `<p class="metadata-single">${escHtml(String(content[0]))}</p>`;
  }
  let html = '<ul class="metadata-list">';
  for (const s of content) html += `<li>${escHtml(String(s))}</li>`;
  return html + '</ul>';
}

// ── Edge drawing ─────────────────────────────────────────────────────────────
function drawEdges(colContainer) {
  // Remove old SVG overlay
  const old = colContainer.querySelector('#edges-overlay');
  if (old) old.remove();

  const colRect = colContainer.getBoundingClientRect();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'edges-overlay';
  svg.setAttribute('width',  colRect.width);
  svg.setAttribute('height', colContainer.scrollHeight);
  svg.style.cssText = `position:absolute;top:0;left:0;pointer-events:none;overflow:visible;`;

  // Arrowhead markers (one per type)
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  for (const [type, color] of Object.entries(TYPE_COLORS)) {
    defs.appendChild(makeArrowMarker(`arrow-${type}`, color));
  }
  svg.appendChild(defs);

  for (const node of state.nodes) {
    const pid = node.relationship && node.relationship.parent_id;
    if (!pid) continue;
    if (!state.idToNode[pid]) continue;   // unresolved — skip

    const parentEl = state.idToBlock[pid];
    const childEl  = state.idToBlock[node.id];
    if (!parentEl || !childEl) continue;

    const pRect = parentEl.getBoundingClientRect();
    const cRect = childEl.getBoundingClientRect();
    const color = TYPE_COLORS[node.type] || '#888';
    const pathD = computeEdgePath(pRect, cRect, colRect);

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.dataset.parent = pid;
    g.dataset.child  = node.id;
    g.style.pointerEvents = 'all';

    // Invisible hit-area path (wide stroke)
    const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    hit.setAttribute('d', pathD);
    hit.setAttribute('fill', 'none');
    hit.setAttribute('stroke', 'transparent');
    hit.setAttribute('stroke-width', '12');

    // Visible path
    const vis = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    vis.setAttribute('d', pathD);
    vis.setAttribute('fill', 'none');
    vis.setAttribute('stroke', color);
    vis.setAttribute('stroke-width', '2');
    vis.setAttribute('opacity', '0.75');
    vis.setAttribute('marker-end', `url(#arrow-${node.type})`);

    g.appendChild(hit);
    g.appendChild(vis);

    const parentNode = state.idToNode[pid];
    const childNode  = node;

    g.addEventListener('mouseenter', (e) => {
      showTooltip(e, parentNode, childNode);
      highlightBlocks([parentEl, childEl], color);
    });
    g.addEventListener('mousemove', moveTooltip);
    g.addEventListener('mouseleave', () => {
      hideTooltip();
      clearHighlights();
    });

    svg.appendChild(g);
  }

  colContainer.insertBefore(svg, colContainer.firstChild);
}

function computeEdgePath(pRect, cRect, colRect, gutter = 48) {
  const ox = colRect.left;
  const oy = colRect.top;

  const x1 = pRect.left + pRect.width / 2 - ox;
  const y1 = pRect.bottom - oy;
  const x2 = cRect.left + cRect.width / 2 - ox;
  const y2 = cRect.top  - oy;

  if (y2 >= y1 - 4) {
    // Child is below parent — simple S-curve
    const mid = (y1 + y2) / 2;
    return `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`;
  }
  // Child above parent — route via right margin
  const xR = colRect.width - gutter;
  const mid = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1+gutter},${y1} ${xR},${y1} ${xR},${mid} S${xR},${y2} ${x2},${y2}`;
}

function makeArrowMarker(id, color) {
  const m = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
  m.setAttribute('id', id);
  m.setAttribute('markerWidth',  '8');
  m.setAttribute('markerHeight', '8');
  m.setAttribute('refX', '5');
  m.setAttribute('refY', '3');
  m.setAttribute('orient', 'auto');
  m.setAttribute('markerUnits', 'strokeWidth');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', 'M0,0 L6,3 L0,6 Z');
  p.setAttribute('fill', color);
  p.setAttribute('opacity', '0.75');
  m.appendChild(p);
  return m;
}

// ── Tooltip ──────────────────────────────────────────────────────────────────
function ensureTooltip() {
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.id = 'edge-tooltip';
    document.body.appendChild(tooltip);
  }
}

function showTooltip(e, parentNode, childNode) {
  ensureTooltip();
  const pLabel = `${parentNode.id} (${parentNode.type})`;
  const cLabel = `${childNode.id} (${childNode.type})`;
  const note   = (childNode.relationship && childNode.relationship.note) || '';
  const noteHtml = note
    ? escHtml(note)
    : '<em style="color:#9ca3af">(no note recorded)</em>';

  tooltip.innerHTML = `
    <div class="tooltip-header">${escHtml(pLabel)} → ${escHtml(cLabel)}</div>
    <hr class="tooltip-hr">
    <div class="tooltip-note">${noteHtml}</div>
  `;
  tooltip.style.display = 'block';
  moveTooltip(e);
}

function moveTooltip(e) {
  if (!tooltip || tooltip.style.display === 'none') return;
  const x = e.clientX + 14;
  const y = e.clientY -  8;
  // Keep inside viewport
  const tw = tooltip.offsetWidth;
  const th = tooltip.offsetHeight;
  tooltip.style.left = Math.min(x, window.innerWidth  - tw - 8) + 'px';
  tooltip.style.top  = Math.min(y, window.innerHeight - th - 8) + 'px';
}

function hideTooltip() {
  if (tooltip) tooltip.style.display = 'none';
}

// ── Block highlight ──────────────────────────────────────────────────────────
function highlightBlocks(blocks, color) {
  clearHighlights();
  currentHighlighted = blocks;
  for (const b of blocks) {
    b.style.outline      = `2px solid ${color}`;
    b.style.outlineOffset = '2px';
  }
}

function clearHighlights() {
  for (const b of currentHighlighted) {
    b.style.outline = '';
    b.style.outlineOffset = '';
  }
  currentHighlighted = [];
}

// ── Save as HTML ─────────────────────────────────────────────────────────────
function saveAsHTML() {
  // Remove stale embedded data, then embed fresh
  const existing = document.getElementById('embedded-data');
  if (existing) existing.remove();

  const script       = document.createElement('script');
  script.type        = 'application/json';
  script.id          = 'embedded-data';
  script.textContent = JSON.stringify(state.jsonData, null, 2);
  document.head.appendChild(script);

  const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
  const blob = new Blob([html], { type: 'text/html' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `${(state.jsonData && state.jsonData.doc_name) || 'visualization'}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Utilities ────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ── Boot ─────────────────────────────────────────────────────────────────────
main().catch(err => {
  document.getElementById('page-body').innerHTML =
    `<p class="error">Error: ${escHtml(String(err))}</p>`;
});
