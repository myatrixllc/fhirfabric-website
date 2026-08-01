#!/usr/bin/env python3
"""
Inject live API wiring into workflow-dashboard.html.

Adds a loadRealClaims() function that:
  1. Fetches a demo token from the API (or uses a hardcoded one)
  2. Calls POST /v1/claims/validate/x12 for all four demo EDI payloads
  3. Updates PERIOD_TOTALS.today with real results
  4. Re-renders KPIs and shows a per-claim result panel

Run from the fhirfabric-website directory:
    python3 ../fhirfabric/scripts/inject_dashboard.py
"""
import re
from pathlib import Path

DASHBOARD = Path("workflow-dashboard.html")
if not DASHBOARD.exists():
    raise SystemExit("run from the fhirfabric-website directory")

# Read the four demo EDI payloads from the engine repo
EDI_DIR = Path("../fhirfabric/demo/edi")
CLAIMS = [
    ("Office visit",     "run1_837p_office_visit"),
    ("HMO office visit", "run2_837p_hmo_visit"),
    ("Surgical",         "run3_837p_surgical"),
    ("PT clinic",        "run4_837p_pt_fraud"),
]

import json
edi_payloads = {}
for label, stem in CLAIMS:
    p = EDI_DIR / f"{stem}.edi"
    if not p.exists():
        raise SystemExit(f"EDI file not found: {p}")
    edi_payloads[label] = p.read_text()

# Build the JS injection block
claim_data_js = "const DEMO_EDI = " + json.dumps(
    {label: edi for label, edi in edi_payloads.items()},
    indent=2
) + ";\n"

INJECTION = '''
// ═══════════════════════════════════════════════════════════════════════════
// LIVE API INTEGRATION — auto-injected by inject_dashboard.py
// ═══════════════════════════════════════════════════════════════════════════

''' + claim_data_js + '''
const API_BASE = 'https://api.fhirfabric.com';
let _apiToken = null;
let _realClaims = [];   // store full API responses for drilldown

// Mint a demo token via the API (requires the private key on the server)
// For the dashboard we use a pre-minted token stored in sessionStorage,
// or fall back to prompting the user.
function getToken() {
  if (_apiToken) return _apiToken;
  const stored = sessionStorage.getItem('fhirfabric_token');
  if (stored) { _apiToken = stored; return _apiToken; }
  const t = prompt(
    'Paste your FHIRFabric demo token:\\n' +
    '(run: python scripts/mint_demo_token.py --partner DEMOPAYER-demo --kid demopayer-2026-a --ttl 14400)');
  if (t) { _apiToken = t.trim(); sessionStorage.setItem('fhirfabric_token', _apiToken); }
  return _apiToken;
}

async function submitClaim(label, edi, token) {
  const resp = await fetch(API_BASE + '/v1/claims/validate/x12', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + token,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ edi }),
  });
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return resp.json();
}

function dispositionType(d) {
  if (!d) return 'pend';
  const v = d.toLowerCase();
  if (v === 'approved' || v === 'approve') return 'pass';
  if (v === 'denied'   || v === 'deny')   return 'deny';
  return 'pend';
}

function buildClaimsPanel(results) {
  const labels = {pass:'APPROVE', deny:'DENY', pend:'PEND'};
  const colors = {pass:'#3B6D11', deny:'#A32D2D', pend:'#854F0B'};
  const bgs    = {pass:'#EAF3DE', deny:'#FCEBEB', pend:'#FAEEDA'};

  return `
    <div style="padding:20px 24px 0;border-top:1px solid #E2E6ED;margin-top:16px;">
      <div style="font-size:.75rem;font-weight:700;color:var(--text-3);letter-spacing:.08em;
                  text-transform:uppercase;margin-bottom:12px;">Live Results — ${results.length} Claims</div>
      ${results.map(r => {
        const t = dispositionType(r.response.final_disposition);
        const savings = parseFloat(r.response.total_estimated_savings || 0);
        const conf = Math.round((r.response.confidence_score || 0) * 100);
        const stages = (r.response.stages || []).length;
        return `
          <div style="background:${bgs[t]};border:1px solid ${colors[t]}33;border-radius:8px;
                      padding:10px 14px;margin-bottom:8px;display:flex;align-items:center;
                      justify-content:space-between;cursor:pointer;"
               onclick="showClaimDetail(${results.indexOf(r)})">
            <div>
              <div style="font-weight:600;color:var(--navy);font-size:.82rem;">${r.label}</div>
              <div style="font-size:.72rem;color:var(--text-3);margin-top:2px;">
                $${parseFloat(r.response.total_billed||0).toLocaleString()} billed
                ${savings > 0 ? '· <b style="color:#00838F">$' + savings.toLocaleString() + ' saved</b>' : ''}
                · ${r.response.total_findings||0} findings
                · ${stages} stages
                · ${conf}% confidence
              </div>
              ${r.response.short_circuit_at ?
                `<div style="font-size:.68rem;color:#854F0B;margin-top:2px;">
                  ⚡ stopped at: ${r.response.short_circuit_at}</div>` : ''}
            </div>
            <span style="background:${colors[t]};color:#fff;font-size:.7rem;font-weight:700;
                         padding:3px 10px;border-radius:20px;white-space:nowrap;">
              ${labels[t]}
            </span>
          </div>`;
      }).join('')}
    </div>`;
}

function showClaimDetail(idx) {
  const r = _realClaims[idx];
  if (!r) return;
  const panel = document.getElementById('live-results-detail');
  if (!panel) return;
  const stages = (r.response.stages || []).filter(s => s.stage && s.name);
  const rows = stages.map(s => {
    const disp = s.disposition || '—';
    const color = disp.includes('deny') ? '#A32D2D'
                : disp.includes('siu')  ? '#534AB7'
                : disp.includes('pend') ? '#854F0B'
                : '#3B6D11';
    return `<tr style="border-bottom:1px solid #E2E6ED;">
      <td style="padding:6px 8px;font-size:.75rem;color:var(--text-3);">${s.stage}</td>
      <td style="padding:6px 8px;font-size:.75rem;font-weight:500;">${s.name}</td>
      <td style="padding:6px 8px;font-size:.75rem;">${s.status||'—'}</td>
      <td style="padding:6px 8px;font-size:.75rem;color:${color};font-weight:600;">${disp}</td>
      <td style="padding:6px 8px;font-size:.75rem;text-align:right;">${s.confidence != null ? Math.round(s.confidence*100)+'%' : '—'}</td>
      <td style="padding:6px 8px;font-size:.75rem;text-align:right;">${s.risk != null ? s.risk : '—'}</td>
      <td style="padding:6px 8px;font-size:.75rem;text-align:right;">${s.findings||0}</td>
    </tr>`;
  }).join('');
  panel.innerHTML = `
    <div style="padding:16px 24px;border-top:2px solid var(--teal);">
      <div style="font-size:.82rem;font-weight:700;color:var(--navy);margin-bottom:4px;">${r.label}</div>
      <div style="font-size:.72rem;color:var(--text-3);margin-bottom:12px;">${r.response.disposition_summary||''}</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F0F2F5;">
          <th style="padding:6px 8px;font-size:.68rem;text-align:left;color:var(--text-3);">#</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:left;color:var(--text-3);">Stage</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:left;color:var(--text-3);">Status</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:left;color:var(--text-3);">Disposition</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:right;color:var(--text-3);">Conf</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:right;color:var(--text-3);">Risk</th>
          <th style="padding:6px 8px;font-size:.68rem;text-align:right;color:var(--text-3);">Findings</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  panel.scrollIntoView({behavior:'smooth', block:'nearest'});
}

async function loadRealClaims() {
  const token = getToken();
  if (!token) return;

  // Show loading state on KPIs
  ['s-total','s-pass','s-deny','s-pend','s-fwa','s-siu'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '…';
  });
  document.getElementById('s-sav').textContent = '$…';

  // Inject a results panel below the KPI row if not already there
  if (!document.getElementById('live-results-panel')) {
    const kpiRow = document.querySelector('.scorecard-row') ||
                   document.getElementById('s-total')?.closest('section, div.row, div');
    if (kpiRow && kpiRow.parentNode) {
      const panel = document.createElement('div');
      panel.id = 'live-results-panel';
      kpiRow.parentNode.insertBefore(panel, kpiRow.nextSibling);

      const detail = document.createElement('div');
      detail.id = 'live-results-detail';
      kpiRow.parentNode.insertBefore(detail, panel.nextSibling);
    }
  }

  // Submit all four claims concurrently
  const entries = Object.entries(DEMO_EDI);
  const results = await Promise.allSettled(
    entries.map(([label, edi]) =>
      submitClaim(label, edi, token).then(r => ({label, response: r}))
    )
  );

  _realClaims = [];
  let pass=0, deny=0, pend=0, fwa=0, siu=0, sav=0;

  for (const r of results) {
    if (r.status === 'rejected') continue;
    const v = r.value;
    _realClaims.push(v);

    const t = dispositionType(v.response.final_disposition);
    if (t === 'pass') pass++;
    else if (t === 'deny') deny++;
    else pend++;

    const q = v.response.pend_queue || '';
    if (q.includes('fraud') || q.includes('fwa')) fwa++;
    if (q.includes('siu')) siu++;

    sav += parseFloat(v.response.total_estimated_savings || 0);
  }

  const total = _realClaims.length;

  // Update PERIOD_TOTALS.today with real data
  PERIOD_TOTALS.today = {total, pass, deny, pend, fwa, siu, sav};

  // Re-render KPIs
  if (period === 'today') renderKPIs();
  else {
    // Force today period to show real data
    document.getElementById('s-total').textContent = total;
    document.getElementById('s-pass').textContent = pass;
    document.getElementById('s-deny').textContent = deny;
    document.getElementById('s-pend').textContent = pend;
    document.getElementById('s-fwa').textContent = fwa;
    document.getElementById('s-siu').textContent = siu;
    document.getElementById('s-sav').textContent =
      sav >= 1000 ? '$' + (sav/1000).toFixed(0) + 'K' : '$' + sav;
  }

  // Show per-claim results panel
  const panel = document.getElementById('live-results-panel');
  if (panel) panel.innerHTML = buildClaimsPanel(_realClaims);
}

// Auto-load on page open — token prompt appears once per session
document.addEventListener('DOMContentLoaded', function() {
  // Small delay so the page renders first
  setTimeout(loadRealClaims, 500);
});

// ═══════════════════════════════════════════════════════════════════════════
// END LIVE API INTEGRATION
// ═══════════════════════════════════════════════════════════════════════════
'''

# Inject before the closing </script> tag near the end
src = DASHBOARD.read_text()

# Find the last </script> before </body>
insert_marker = '</script>\n</body>'
if insert_marker not in src:
    insert_marker = '</script>\n</body>'
    # Try without newline
    if '</script>\n</body>' not in src:
        # Find any </script></body>
        m = re.search(r'</script>\s*</body>', src)
        if m:
            insert_marker = src[m.start():m.end()]
        else:
            raise SystemExit("could not find </script></body> — check the file structure")

new_src = src.replace(insert_marker,
                      INJECTION + '\n' + insert_marker, 1)
if new_src == src:
    raise SystemExit("injection failed — marker not found")

DASHBOARD.write_text(new_src)
print(f"injected {len(INJECTION)} chars into {DASHBOARD}")
print("Next: git add workflow-dashboard.html && git commit && git push")
