'use strict';

let token = '';
let env = null;
let discovery = null;
let nodeReport = null;
let pendingAction = null;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), 3500);
}

async function api(path, options = {}) {
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {...options, headers});
  let payload = {};
  try { payload = await response.json(); } catch { /* response has no JSON body */ }
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function setPage(page) {
  $$('.nav').forEach(button => button.classList.toggle('active', button.dataset.page === page));
  $$('.page').forEach(panel => panel.classList.toggle('active', panel.dataset.pagePanel === page));
  const titles = {
    overview: 'RDMA environment',
    nodes: 'Managed-node diagnostics',
    network: 'SR-IOV & VFs',
    workloads: 'RDMA workloads',
    jobs: 'Activity',
    security: 'Security & access',
  };
  $('#page-title').textContent = titles[page] || 'OKE RDMA';
  if (page === 'jobs') refreshJobs();
}

function metric(label, value, note = '') {
  return `<article class="metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(String(value))}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ''}</article>`;
}

function ubuntuLabel(value) {
  if (value === 'ubuntu-noble') return 'Ubuntu 24.04 Noble';
  if (value === 'ubuntu-jammy') return 'Ubuntu 22.04 Jammy';
  return value || 'Unknown';
}

function renderPlatform(platform) {
  $('#platform-card').innerHTML = `
    <h3>Managed-node bootstrap</h3>
    <dl class="summary">
      <dt>OKE version</dt><dd>${escapeHtml(platform.kubernetes_version || '—')}</dd>
      <dt>Derived minor</dt><dd>${escapeHtml(platform.kubernetes_minor || '—')}</dd>
      <dt>Ubuntu</dt><dd>${escapeHtml(ubuntuLabel(platform.ubuntu_release))}</dd>
      <dt>OKE node package</dt><dd><code>${escapeHtml(platform.oke_node_package || '—')}</code></dd>
    </dl>
    <details><summary>Derived repository</summary><code class="wrap-code">${escapeHtml(platform.oke_repo_url || '—')}</code></details>
    <p class="doc-links"><a href="https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengCompatibilitymatrix_topic.htm" target="_blank" rel="noreferrer">Oracle Ubuntu node package compatibility ↗</a></p>`;
}

function setFormValues(data) {
  const rdma = data.rdma || {};
  $('#rdma-mtu').value = Number(rdma.mtu || 0) || '';
  $('#rdma-vfs').value = Number(rdma.vfs_per_node || 2);
  $('#rdma-resource').value = rdma.resource_name || String(rdma.resource || '').replace(/^nvidia\.com\//, '') || 'oci_rdma_vf';
  $('#rdma-pool').value = rdma.ip_pool || '10.239.251.0/24';
  $('#rdma-image').value = rdma.tools_image || '';
  populatePfSelect(rdma.pf || '');

  const locks = data.configuration_status || {};
  for (const id of ['rdma-pf', 'rdma-mtu', 'rdma-vfs', 'rdma-resource']) {
    $(`#${id}`).disabled = Boolean(locks.hardware_fields_locked);
  }
  $('#rdma-pool').disabled = Boolean(locks.network_fields_locked);
  const notes = [];
  if (locks.hardware_fields_locked) notes.push('VF policy exists: PF/MTU/VF/resource settings are locked.');
  if (locks.network_fields_locked) notes.push('VF network exists: IP pool is locked.');
  $('#config-lock-note').textContent = notes.join(' ');
}

function populatePfSelect(current = '') {
  const select = $('#rdma-pf');
  const candidates = discovery?.common_candidates || [];
  const eligible = candidates.filter(candidate => candidate.eligible);
  const options = [];
  if (current && !eligible.some(candidate => candidate.name === current)) {
    options.push(`<option value="${escapeHtml(current)}" selected>${escapeHtml(current)} · saved setting, currently not eligible</option>`);
  }
  for (const candidate of eligible) {
    const selected = candidate.name === current ? 'selected' : '';
    options.push(`<option value="${escapeHtml(candidate.name)}" ${selected}>${escapeHtml(candidate.name)} · MTU ${escapeHtml(candidate.mtu)} · ${escapeHtml(candidate.drivers.join(', '))}</option>`);
  }
  select.innerHTML = options.length ? options.join('') : '<option value="">No healthy common PF discovered</option>';
  if (!current && discovery?.recommended?.name) {
    select.value = discovery.recommended.name;
    $('#rdma-mtu').value = discovery.recommended.mtu;
  }
}

function renderDiscovery(data) {
  discovery = data;
  const candidates = data.common_candidates || [];
  const nodes = data.nodes || [];
  const recommended = data.recommended;
  const blockers = (data.blockers || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  const candidateHtml = candidates.length ? `
    <div class="candidate-list">
      ${candidates.map(candidate => {
        const classes = ['candidate'];
        if (recommended?.name === candidate.name) classes.push('recommended');
        if (!candidate.eligible) classes.push('blocked');
        const details = candidate.eligible
          ? `Eligible OCI RDMA PF · MTU ${candidate.mtu} · min ${candidate.min_total_vfs} total VFs`
          : `Not eligible · MTU ${candidate.mtu ?? candidate.mtus.join('/')} · ${candidate.blockers.join(' ')}`;
        return `<button type="button" class="${classes.join(' ')}" data-pf="${escapeHtml(candidate.name)}" ${candidate.eligible ? '' : 'disabled'}>
          <strong>${escapeHtml(candidate.name)}</strong>
          <span>${escapeHtml(details)}</span>
        </button>`;
      }).join('')}
    </div>` : '<p class="error">No PF name is reported as SR-IOV-capable on every selected RDMA node.</p>';

  const nodeRows = nodes.map(node => {
    const interfaces = (node.interfaces || []).map(iface => `${iface.name} (${iface.driver || 'driver ?'}, MTU ${iface.mtu}, totalVFs ${iface.total_vfs}, admin ${iface.link_admin_state || 'unknown'})`).join(', ') || 'No SR-IOV-capable interface reported';
    return `<tr><td>${escapeHtml(node.name)}</td><td>${escapeHtml(node.sync_status)}</td><td>${escapeHtml(interfaces)}</td></tr>`;
  }).join('');

  $('#discovery').innerHTML = `
    <div class="discovery-summary"><strong>${escapeHtml(data.nodes_reporting_state)}/${escapeHtml(data.nodes_expected)}</strong> RDMA workers reporting SR-IOV node state</div>
    ${blockers ? `<div class="callout danger-callout"><strong>Resolve before configuring VFs</strong><ul>${blockers}</ul></div>` : ''}
    ${candidateHtml}
    <details><summary>Per-node inventory</summary>
      <div class="table-wrap"><table><thead><tr><th>Node</th><th>SR-IOV sync</th><th>Interfaces</th></tr></thead><tbody>${nodeRows}</tbody></table></div>
    </details>
    <p class="muted">${escapeHtml(data.note || '')}</p>`;

  populatePfSelect(env?.rdma?.pf || recommended?.name || '');
  $$('.candidate:not(:disabled)').forEach(button => button.addEventListener('click', () => {
    const candidate = candidates.find(item => item.name === button.dataset.pf);
    if (!candidate) return;
    $('#rdma-pf').value = candidate.name;
    $('#rdma-mtu').value = candidate.mtu;
    toast(`Selected healthy PF ${candidate.name}`);
  }));
}

function renderEnvironment(data) {
  env = data;
  $('#env-name').textContent = data.environment_name;
  $('#mode-pill').textContent = data.mode === 'demo' ? 'Demo — no cloud changes' : 'Live private operator';
  renderPlatform(data.platform || {});

  const ready = data.nodes.filter(node => node.ready).length;
  const expectedVfs = Number(data.rdma.vfs_per_node || 1);
  const vfNodes = data.nodes.filter(node => Number(node.vf_allocatable || 0) >= expectedVfs).length;
  const vfReady = Boolean(data.vf_reconciliation?.ready);
  const pf = data.rdma.configured ? data.rdma.pf : 'Not selected';
  const mtuNote = data.rdma.configured ? `MTU ${data.rdma.mtu}` : 'Discover and configure after node health is green';
  const networkOperator = (data.addons || []).find(addon => String(addon.name).toLowerCase() === 'nvidianetworkoperator'.toLowerCase() || String(addon.name).toLowerCase().includes('nvidia'));

  $('#metrics').innerHTML = [
    metric('RDMA workers', data.node_count, `${ready} Ready`),
    metric('Network Operator', networkOperator?.state || 'Unknown', networkOperator?.version || 'Version unavailable'),
    metric('Live RDMA PF', pf, mtuNote),
    metric('VF reconciliation', vfReady ? 'Ready' : 'Not ready', `${vfNodes}/${data.node_count} nodes at expected capacity`),
  ].join('');

  setFormValues(data);

  const configured = Boolean(data.rdma.configured);
  const policyExists = Boolean(data.configuration_status?.policy_exists);
  const vfSummary = configured ? `
    <dl class="summary">
      <dt>Physical function</dt><dd>${escapeHtml(data.rdma.pf)}</dd>
      <dt>MTU</dt><dd>${escapeHtml(data.rdma.mtu)}</dd>
      <dt>VFs per node</dt><dd>${escapeHtml(data.rdma.vfs_per_node)}</dd>
      <dt>Resource</dt><dd>${escapeHtml(data.rdma.resource)}</dd>
    </dl>` : '<div class="callout">Query the managed nodes, discover a healthy common PF, then save RDMA settings.</div>';

  $('#vf-card').innerHTML = `
    <h3>3. VF policy</h3>
    <p>Creates an RDMA-capable <code>SriovNetworkNodePolicy</code> only on nodes labelled <code>oci-rdma=true</code>.</p>
    ${vfSummary}
    <div class="callout">Applying this policy can drain or reconfigure RDMA nodes. Live node state is rechecked immediately before Apply.</div>
    <button class="danger" id="configure-vfs" ${configured && !policyExists ? '' : 'disabled'}>${policyExists ? 'VF policy already exists' : configured ? 'Approve VF configuration' : 'Save healthy RDMA settings first'}</button>`;
  $('#configure-vfs').addEventListener('click', () => confirmAction('configure_vfs', 'Approve VF configuration', 'This can drain or reconfigure RDMA nodes. Type the exact environment name to continue.'));

  const vfStatus = vfReady
    ? '<span class="state SUCCEEDED">VF reconciliation ready</span>'
    : '<span class="state RUNNING">Waiting for VF reconciliation</span>';
  const vfDetail = (data.vf_reconciliation?.nodes || []).map(node => typeof node === 'string' ? escapeHtml(node) :
    `${escapeHtml(node.name)}: ${escapeHtml(node.sync_status)} · ${escapeHtml(node.vf_allocatable)}/${escapeHtml(node.expected_vfs)} VFs`
  ).join('<br>');
  const networkExists = Boolean(data.configuration_status?.network_exists);
  $('#net-card').innerHTML = `
    <h3>4. VF network</h3>
    <p>Creates the workload namespace, NVIDIA IPAM pool and <code>SriovNetwork</code> only after every selected RDMA node has reconciled successfully.</p>
    <p>${vfStatus}</p>
    ${vfDetail ? `<p class="node-readiness">${vfDetail}</p>` : ''}
    <dl class="summary"><dt>Pool</dt><dd>${escapeHtml(data.rdma.ip_pool)}</dd><dt>Network</dt><dd>${escapeHtml(data.environment_name)}-rdma-vf</dd></dl>
    <div class="callout">The backend requires <code>syncStatus=Succeeded</code> and at least ${escapeHtml(expectedVfs)} allocatable ${escapeHtml(data.rdma.resource)} VF(s) on every RDMA node.</div>
    <button class="danger" id="configure-network" ${vfReady && !networkExists ? '' : 'disabled'}>${networkExists ? 'VF network already exists' : vfReady ? 'Approve VF network' : 'Waiting for VFs'}</button>`;
  $('#configure-network').addEventListener('click', () => confirmAction('configure_network', 'Approve VF network', 'This writes cluster networking resources. Type the exact environment name to continue.'));

  const validationButton = $('#run-validation');
  const canValidate = vfReady && networkExists && Boolean(data.rdma.tools_image_configured);
  validationButton.disabled = !canValidate;
  validationButton.title = canValidate ? '' : 'Complete VF/network configuration and configure an immutable RDMA tools image first.';
  $('#validation-image-state').textContent = data.rdma.tools_image_configured
    ? `Validation image: ${data.rdma.tools_image}`
    : 'Configure an immutable RDMA tools image in SR-IOV & VFs.';
}

function renderPreflight(data) {
  const host = $('#preflight');
  host.innerHTML = data.checks.map(check => {
    const detail = typeof check.detail === 'string' ? check.detail : JSON.stringify(check.detail, null, 2);
    return `<div class="check"><span class="dot ${escapeHtml(check.status)}"></span><div><strong>${escapeHtml(check.name)}</strong><small><pre>${escapeHtml(detail)}</pre></small></div></div>`;
  }).join('');
  if (data.blocking) toast(`${data.blocking} blocking preflight issue(s)`); else toast('Preflight has no blocking checks');
}

function pluginBadge(plugin) {
  const status = String(plugin.status || 'UNKNOWN').toUpperCase();
  const css = status === 'RUNNING' ? 'SUCCEEDED' : status === 'STOPPED' ? 'FAILED' : 'RUNNING';
  return `<span class="state ${css}">${escapeHtml(status)}</span>`;
}

function renderNodeDiagnostics(data) {
  nodeReport = data;
  $('#download-node-report').disabled = false;
  const summary = data.summary || {};
  const recommended = summary.recommended_pf;
  const overallClass = data.overall === 'pass' ? 'SUCCEEDED' : data.overall === 'block' ? 'FAILED' : 'RUNNING';
  const cards = (data.nodes || []).map(node => {
    const issueHtml = (node.issues || []).length
      ? `<ul class="issue-list">${node.issues.map(issue => `<li class="${escapeHtml(issue.severity)}">${escapeHtml(issue.message)}</li>`).join('')}</ul>`
      : '<p class="good-text">No blocking node issue detected by the API-level checks.</p>';
    const plugins = (node.plugins || []).map(plugin => `<tr><td>${escapeHtml(plugin.name)}</td><td>${pluginBadge(plugin)}</td><td>${escapeHtml(plugin.message || '')}</td></tr>`).join('');
    const interfaces = (node.interfaces || []).map(iface => `<tr><td><code>${escapeHtml(iface.name)}</code></td><td>${escapeHtml(iface.driver)}</td><td>${escapeHtml(iface.mtu)}</td><td>${escapeHtml(iface.num_vfs)}/${escapeHtml(iface.total_vfs)}</td><td>${escapeHtml(iface.link_admin_state || 'unknown')}</td></tr>`).join('');
    return `<article class="card node-card">
      <div class="card-head"><div><h3>${escapeHtml(node.name)}</h3><p class="muted">${escapeHtml(node.internal_ip || 'No InternalIP')} · ${escapeHtml(node.instance?.shape || 'Shape unavailable')}</p></div><span class="state ${node.status === 'pass' ? 'SUCCEEDED' : node.status === 'block' ? 'FAILED' : 'RUNNING'}">${escapeHtml(node.status)}</span></div>
      <dl class="summary compact">
        <dt>Kubernetes</dt><dd>${node.ready ? 'Ready' : 'Not Ready'}</dd>
        <dt>OCI instance</dt><dd>${escapeHtml(node.instance?.lifecycle_state || 'Unavailable')}</dd>
        <dt>SR-IOV sync</dt><dd>${escapeHtml(node.sriov_sync_status)}</dd>
        <dt>VF allocatable</dt><dd>${escapeHtml(node.vf_allocatable)}</dd>
        <dt>OS / kernel</dt><dd>${escapeHtml(node.os_image || '—')} · ${escapeHtml(node.kernel_version || '—')}</dd>
      </dl>
      ${issueHtml}
      <details><summary>Oracle Cloud Agent RDMA plugins</summary><div class="table-wrap"><table><thead><tr><th>Plugin</th><th>Status</th><th>Message</th></tr></thead><tbody>${plugins}</tbody></table></div></details>
      <details><summary>SR-IOV interfaces</summary><div class="table-wrap"><table><thead><tr><th>PF</th><th>Driver</th><th>MTU</th><th>VFs</th><th>Admin state</th></tr></thead><tbody>${interfaces || '<tr><td colspan="5">No interfaces reported</td></tr>'}</tbody></table></div></details>
      <details><summary>Break-glass host inspection command</summary><p>This command is displayed for an administrator; the web service never executes it.</p><code class="wrap-code">${escapeHtml(node.break_glass_command)}</code></details>
    </article>`;
  }).join('');

  $('#node-diagnostics').innerHTML = `
    <div class="node-summary">
      <span class="state ${overallClass}">${escapeHtml(data.overall)}</span>
      <strong>${escapeHtml(summary.ready || 0)}/${escapeHtml(summary.total || 0)}</strong> Kubernetes Ready ·
      <strong>${escapeHtml(summary.plugin_healthy || 0)}/${escapeHtml(summary.total || 0)}</strong> RDMA plugins healthy ·
      <strong>${escapeHtml(recommended?.name || 'No healthy common PF')}</strong>${recommended ? ` at MTU ${escapeHtml(recommended.mtu)}` : ''}
    </div>
    ${(summary.discovery_blockers || []).length ? `<div class="callout danger-callout"><strong>VF configuration blocked</strong><ul>${summary.discovery_blockers.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>` : ''}
    <div class="node-grid">${cards}</div>
    <p class="muted">${escapeHtml(data.note || '')}</p>`;
}

async function refreshEnvironment() {
  renderEnvironment(await api('/api/v1/environment'));
}

async function refreshPreflight() {
  $('#preflight').textContent = 'Running checks…';
  try { renderPreflight(await api('/api/v1/preflight')); }
  catch (error) { $('#preflight').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

async function refreshNodeDiagnostics() {
  $('#node-diagnostics').textContent = 'Querying Kubernetes nodes, SR-IOV state and OCI Instance Agent plugins…';
  $('#download-node-report').disabled = true;
  try {
    renderNodeDiagnostics(await api('/api/v1/nodes'));
    toast('Managed-node diagnostics refreshed');
  } catch (error) {
    $('#node-diagnostics').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

function downloadNodeReport() {
  if (!nodeReport) return;
  const blob = new Blob([JSON.stringify(nodeReport, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${env?.environment_name || 'oke-rdma'}-node-diagnostics.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function discoverHardware() {
  $('#discovery').textContent = 'Reading live SR-IOV node state…';
  try {
    renderDiscovery(await api('/api/v1/rdma/discovery'));
    toast(discovery.recommended ? 'Healthy RDMA PF discovered' : 'Discovery completed with blockers');
  } catch (error) {
    $('#discovery').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

async function saveRdmaConfig(event) {
  event.preventDefault();
  const payload = {
    rdma_pf_name: $('#rdma-pf').value.trim(),
    rdma_mtu: Number($('#rdma-mtu').value),
    rdma_vfs_per_node: Number($('#rdma-vfs').value),
    rdma_resource_name: $('#rdma-resource').value.trim(),
    rdma_ip_pool_cidr: $('#rdma-pool').value.trim(),
    rdma_tools_image: $('#rdma-image').value.trim(),
  };
  try {
    await api('/api/v1/rdma/config', {method: 'PUT', body: JSON.stringify(payload)});
    toast('Healthy RDMA settings saved');
    await refreshEnvironment();
  } catch (error) { toast(error.message); }
}

function stateClass(state) { return `state ${escapeHtml(state)}`; }

function renderJob(job) {
  const result = job.result ? `<pre>${escapeHtml(JSON.stringify(job.result, null, 2))}</pre>` : '';
  const error = job.error ? `<p class="error">${escapeHtml(job.error)}</p>` : '';
  const events = (job.events || []).map(event => `<small>${escapeHtml(event.level)} · ${escapeHtml(event.message)}</small>`).join('<br>');
  return `<article class="job"><div class="job-head"><div><strong>${escapeHtml(job.action)}</strong><br><small>${escapeHtml(job.id)}</small></div><span class="${stateClass(job.state)}">${escapeHtml(job.state)}</span></div>${error}${result}${events ? `<details><summary>Activity</summary>${events}</details>` : ''}</article>`;
}

async function refreshJobs() {
  if (!token) return;
  try {
    const data = await api('/api/v1/jobs');
    $('#jobs-list').innerHTML = data.items.length ? data.items.map(renderJob).join('') : '<div class="empty">No operations yet.</div>';
  } catch (error) { $('#jobs-list').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

async function queue(action, confirmation = '') {
  const job = await api('/api/v1/jobs', {method: 'POST', body: JSON.stringify({action, confirmation})});
  toast(`${action} queued`);
  setPage('jobs');
  await pollJob(job.id);
}

async function pollJob(id) {
  for (let index = 0; index < 180; index += 1) {
    const job = await api(`/api/v1/jobs/${encodeURIComponent(id)}`);
    await refreshJobs();
    if (['SUCCEEDED', 'FAILED'].includes(job.state)) {
      toast(job.state === 'SUCCEEDED' ? 'Operation completed' : 'Operation failed');
      refreshEnvironment().catch(() => {});
      return job;
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  toast('Operation is still running; see Activity');
  return null;
}

function confirmAction(action, title, copy) {
  pendingAction = action;
  $('#confirm-title').textContent = title;
  $('#confirm-copy').textContent = copy;
  $('#confirm-input').value = '';
  $('#confirm-dialog').showModal();
}

$('#confirm-form').addEventListener('submit', async event => {
  if (event.submitter?.value === 'cancel') { pendingAction = null; return; }
  event.preventDefault();
  const confirmation = $('#confirm-input').value;
  const action = pendingAction;
  $('#confirm-dialog').close();
  pendingAction = null;
  if (!action) return;
  try { await queue(action, confirmation); } catch (error) { toast(error.message); }
});

async function login() {
  const candidate = $('#token').value.trim();
  $('#login-error').textContent = '';
  if (!candidate) { $('#login-error').textContent = 'Enter the workspace token.'; return; }
  token = candidate;
  try {
    await api('/api/v1/session', {method: 'POST'});
    $('#login').hidden = true;
    $('#app').hidden = false;
    $('#token').value = '';
    await refreshEnvironment();
    await refreshJobs();
  } catch (error) {
    token = '';
    $('#login-error').textContent = error.message;
  }
}

$('#login-button').addEventListener('click', login);
$('#token').addEventListener('keydown', event => { if (event.key === 'Enter') login(); });
$('#refresh').addEventListener('click', async () => { try { await refreshEnvironment(); toast('Environment refreshed'); } catch (error) { toast(error.message); } });
$('#run-preflight').addEventListener('click', refreshPreflight);
$('#refresh-nodes').addEventListener('click', refreshNodeDiagnostics);
$('#download-node-report').addEventListener('click', downloadNodeReport);
$('#discover-hardware').addEventListener('click', discoverHardware);
$('#rdma-config-form').addEventListener('submit', saveRdmaConfig);
$('#rdma-pf').addEventListener('change', () => {
  const candidate = (discovery?.common_candidates || []).find(item => item.name === $('#rdma-pf').value);
  if (candidate?.eligible && candidate?.mtu) $('#rdma-mtu').value = candidate.mtu;
});
$('#run-validation').addEventListener('click', () => queue('rdma_validation').catch(error => toast(error.message)));
$$('.nav').forEach(button => button.addEventListener('click', () => setPage(button.dataset.page)));
