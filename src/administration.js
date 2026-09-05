const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function administrationPanel(data) {
  const deployment = data.enterprise;
  const config = deployment.configuration;
  return `<section class="panel administration-panel"><h2>Enterprise / Administration</h2>
    <p>Active mode: <strong>${escapeHtml(deployment.active_mode)}</strong> · Database: ${escapeHtml(deployment.database)}</p>
    <details><summary>Enterprise deployment configuration</summary><p class="help">${escapeHtml(deployment.notice)}</p>
    <form id="enterprise-form" class="enterprise-form">
      <label>Planned operating mode<select name="operating_mode">${['local','enterprise'].map(value => `<option ${config.operating_mode===value?'selected':''}>${value}</option>`).join('')}</select></label>
      <label>Organization name<input name="organization_name" maxlength="120" value="${escapeHtml(config.organization_name)}"></label>
      <label>Enterprise API URL<input name="api_url" type="url" placeholder="https://api.example.org" value="${escapeHtml(config.api_url)}"></label>
      <label>Identity protocol<select name="identity_protocol">${['none','oidc'].map(value => `<option ${config.identity_protocol===value?'selected':''}>${value}</option>`).join('')}</select></label>
      <label>Identity issuer URL<input name="issuer_url" type="url" value="${escapeHtml(config.issuer_url)}"></label>
      <label>Public client ID<input name="client_id" value="${escapeHtml(config.client_id)}"></label>
      <label>Audience<input name="audience" value="${escapeHtml(config.audience)}"></label>
      <label>Planned database<select name="database_mode">${['sqlite','postgresql'].map(value => `<option ${config.database_mode===value?'selected':''}>${value}</option>`).join('')}</select></label>
      <button type="submit">Save deployment configuration</button>
    </form></details>
    ${data.diagnostics.credential_store === 'Windows Credential Manager' ? `<details><summary>Secure provider credentials</summary>
    <p class="help">Save a credential in Windows Credential Manager for this Windows account. Use the same reference as the provider setting. Saved credentials are never displayed.</p>
    <form id="credential-form" class="enterprise-form"><label>Credential reference<input name="reference" required pattern="[A-Z][A-Z0-9_]{0,99}" placeholder="OPENAI_API_KEY" autocomplete="off"></label>
    <label>New credential<input name="secret" type="password" required maxlength="2560" autocomplete="new-password"></label><button type="submit">Save or replace credential</button><button type="button" id="delete-credential">Delete stored credential</button></form></details>` : ''}
    <h2>Data Management</h2><p class="help">Backups are saved in the application data directory under backups. They include persistent application data and credential references, but no provider secrets. Protect backups as sensitive telemetry.</p>
    <button id="backup-data">Backup Application Data</button>
    <label>Available backup<select id="restore-backup"><option value="">Select a backup</option>${data.backups.backups.map(item => `<option value="${escapeHtml(item.backup_id)}">${escapeHtml(new Date(item.created_at).toLocaleString())} · ${escapeHtml(item.backup_id.slice(0,8))}</option>`).join('')}</select></label>
    <button id="restore-data">Restore Application Data</button>
    <p class="help">Restore validates integrity first, creates a recovery backup, and preserves audit history. Complete or cancel imports before restoring.</p>
    <details><summary>Diagnostics for IT support</summary><pre id="diagnostics-content">${escapeHtml(JSON.stringify(data.diagnostics,null,2))}</pre><button id="copy-diagnostics">Copy diagnostics</button><button id="export-diagnostics">Export diagnostics JSON</button></details>
    <p id="administration-status" role="status"></p>
  </section>`;
}

export function bindAdministration(api, reload) {
  const status = document.querySelector('#administration-status');
  const action = (selector, handler) => document.querySelector(selector)?.addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try { await handler(); } catch(error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.querySelector('#enterprise-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    for (const key of ['api_url','issuer_url','client_id','audience']) payload[key] ||= null;
    try {
      await api('/administration/configuration', {method:'PUT',body:JSON.stringify(payload)});
      status.textContent = 'Deployment configuration saved. The active connection remains local.';
    } catch(error) { status.textContent = error.message; }
  });
  document.querySelector('#credential-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api('/administration/credentials', {method:'PUT',body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      status.textContent = 'Credential saved securely. The value cannot be displayed.';
    } catch(error) { status.textContent = error.message; }
    finally { form.elements.secret.value = ''; }
  });
  action('#delete-credential', async () => {
    const reference = document.querySelector('#credential-form').elements.reference.value;
    if (!reference || !confirm(`Delete the stored credential for ${reference}?`)) return;
    const result = await api('/administration/credentials/'+encodeURIComponent(reference), {method:'DELETE'});
    document.querySelector('#credential-form').elements.secret.value = '';
    status.textContent = result.notice;
  });
  action('#backup-data', async () => {
    status.textContent = 'Creating backup…';
    const result = await api('/administration/backups', {method:'POST'});
    alert(`Backup saved: ${result.backup_id}.aiopt-backup`);
    await reload();
  });
  action('#restore-data', async () => {
    const id = document.querySelector('#restore-backup').value;
    if (!id) throw new Error('Select a backup first.');
    status.textContent = 'Validating backup…';
    await api(`/administration/backups/${encodeURIComponent(id)}/validate`, {method:'POST'});
    if (!confirm('Backup validated. Replace current application data with this backup? A recovery backup will be created; audit history is preserved.')) { status.textContent = 'Restore cancelled.'; return; }
    status.textContent = 'Restoring application data…';
    await api(`/administration/backups/${encodeURIComponent(id)}/restore`, {method:'POST',body:JSON.stringify({confirmed:true})});
    await reload();
  });
  action('#copy-diagnostics', async () => {
    await navigator.clipboard.writeText(document.querySelector('#diagnostics-content').textContent);
    status.textContent = 'Diagnostics copied.';
  });
  action('#export-diagnostics', async () => {
    const url = URL.createObjectURL(new Blob([document.querySelector('#diagnostics-content').textContent], {type:'application/json'}));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'aiopt-diagnostics.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}
