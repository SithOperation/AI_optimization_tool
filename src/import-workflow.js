/**
 * Large-file import workflow management.
 * Handles upload, analysis, mapping, preview, and progress tracking.
 */

export function createUploadFormData(file, chunk) {
  const formData = new FormData();
  formData.append('file', chunk, file.name);
  return formData;
}

export class ImportWorkflow {
  constructor(api, money, num) {
    this.api = api;
    this.money = money;
    this.num = num;
    this.importId = null;
    this.status = null;
    this.autoMapping = {};
    this.manualMapping = {};
    this.fileFormat = 'csv';
    this.duplicateHandling = 'skip';
    this.progressInterval = null;
  }

  // UI: Render the main import page
  renderPage() {
    return `
      <div class="import-workflow">
        ${this.renderUploadZone()}
        ${this.renderStatus()}
        <div class="import-panels" id="import-panels" style="display:none">
          ${this.renderAnalysisPanel()}
          ${this.renderMappingPanel()}
          ${this.renderPreviewPanel()}
          ${this.renderProgressPanel()}
          ${this.renderHistoryPanel()}
        </div>
      </div>
    `;
  }

  renderUploadZone() {
    return `
      <article class="panel import-upload">
        <div class="panel-head">
          <div>
            <p class="eyebrow">IMPORT TELEMETRY</p>
            <h2>Drop a CSV or JSON file here</h2>
          </div>
        </div>
        
        <div class="upload-zone" id="upload-zone" data-dragover="false">
          <div class="zone-content">
            <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            <p class="zone-title">Drop CSV or JSON file</p>
            <p class="zone-subtitle">Maximum 500 MB</p>
            <button class="primary" id="browse-file">Browse files</button>
            <input id="file-input" type="file" accept=".csv,.json,.jsonl" style="display:none">
          </div>
        </div>

        <div class="upload-info">
          <div>
            <strong>Supported formats:</strong><br>
            CSV (.csv) · JSON (.json, .jsonl)
          </div>
          <div>
            <strong>Maximum size:</strong><br>
            500 MB
          </div>
          <div>
            <strong>Privacy:</strong><br>
            Processed locally
          </div>
        </div>
      </article>
    `;
  }

  renderAnalysisPanel() {
    if (!this.status || this.status.status === 'UPLOADED') return '';
    
    return `
      <article class="panel import-panel" id="analysis-panel" style="display:none">
        <div class="panel-head">
          <div>
            <p class="eyebrow">FILE ANALYSIS</p>
            <h2>${this.escapeHtml(this.status.filename)}</h2>
          </div>
          <span class="tag">${this.status.format.toUpperCase()}</span>
        </div>

        <div class="analysis-grid">
          <div class="stat">
            <strong>${this.num.format(this.status.file_size / 1_000_000)}</strong>
            <small>MB</small>
          </div>
          <div class="stat">
            <strong>${this.num.format(this.status.total_rows)}</strong>
            <small>Rows</small>
          </div>
          <div class="stat">
            <strong>${this.status.detected_encoding}</strong>
            <small>Encoding</small>
          </div>
          <div class="stat">
            <strong>${this.status.detected_delimiter || ','}</strong>
            <small>Delimiter</small>
          </div>
        </div>

        <div id="sample-preview" class="sample-preview"></div>

        <div class="action-row">
          <button id="continue-to-mapping" class="primary">Continue to column mapping</button>
          <button id="start-over" class="secondary">Choose different file</button>
        </div>
      </article>
    `;
  }

  renderMappingPanel() {
    if (!this.status || this.status.status !== 'READY') return '';

    const sampleRow = this.status.sample_rows?.[0] || {};
    const headers = Object.keys(sampleRow);

    return `
      <article class="panel import-panel" id="mapping-panel" style="display:none">
        <div class="panel-head">
          <div>
            <p class="eyebrow">COLUMN MAPPING</p>
            <h2>Map CSV columns to telemetry fields</h2>
          </div>
        </div>

        <div class="mapping-table">
          <div class="mapping-row mapping-header">
            <span>CSV COLUMN</span>
            <span>TARGET FIELD</span>
            <span>SAMPLE VALUE</span>
          </div>
          ${headers.map((col, idx) => `
            <div class="mapping-row">
              <strong>${this.escapeHtml(col)}</strong>
              <select data-mapping-col="${col}" class="mapping-select">
                <option value="">-- Ignore --</option>
                <option value="timestamp" ${this.autoMapping[col] === 'timestamp' ? 'selected' : ''}>timestamp</option>
                <option value="application" ${this.autoMapping[col] === 'application' ? 'selected' : ''}>application</option>
                <option value="provider" ${this.autoMapping[col] === 'provider' ? 'selected' : ''}>provider</option>
                <option value="model" ${this.autoMapping[col] === 'model' ? 'selected' : ''}>model</option>
                <option value="input_tokens" ${this.autoMapping[col] === 'input_tokens' ? 'selected' : ''}>input_tokens</option>
                <option value="output_tokens" ${this.autoMapping[col] === 'output_tokens' ? 'selected' : ''}>output_tokens</option>
                <option value="cached_input_tokens" ${this.autoMapping[col] === 'cached_input_tokens' ? 'selected' : ''}>cached_input_tokens</option>
                <option value="total_tokens" ${this.autoMapping[col] === 'total_tokens' ? 'selected' : ''}>total_tokens</option>
                <option value="latency_ms" ${this.autoMapping[col] === 'latency_ms' ? 'selected' : ''}>latency_ms</option>
                <option value="success" ${this.autoMapping[col] === 'success' ? 'selected' : ''}>success</option>
                <option value="retry_count" ${this.autoMapping[col] === 'retry_count' ? 'selected' : ''}>retry_count</option>
                <option value="cache_hit" ${this.autoMapping[col] === 'cache_hit' ? 'selected' : ''}>cache_hit</option>
                <option value="estimated_total_cost" ${this.autoMapping[col] === 'estimated_total_cost' ? 'selected' : ''}>estimated_total_cost</option>
                <option value="department" ${this.autoMapping[col] === 'department' ? 'selected' : ''}>department</option>
                <option value="team" ${this.autoMapping[col] === 'team' ? 'selected' : ''}>team</option>
                <option value="workload" ${this.autoMapping[col] === 'workload' ? 'selected' : ''}>workload</option>
              </select>
              <code>${this.escapeHtml(String(sampleRow[col] || '').slice(0, 40))}</code>
            </div>
          `).join('')}
        </div>

        <div class="mapping-options">
          <label>
            <strong>Duplicate handling:</strong>
            <select id="duplicate-handling">
              <option value="skip" selected>Skip duplicates</option>
              <option value="replace">Replace duplicates</option>
              <option value="fail">Fail on duplicates</option>
            </select>
          </label>
        </div>

        <div class="action-row">
          <button id="preview-import" class="primary">Preview data</button>
          <button id="back-to-analysis" class="secondary">Back</button>
        </div>
      </article>
    `;
  }

  renderPreviewPanel() {
    if (!this.status || this.status.status !== 'READY') return '';

    return `
      <article class="panel import-panel" id="preview-panel" style="display:none">
        <div class="panel-head">
          <div>
            <p class="eyebrow">IMPORT PREVIEW</p>
            <h2>Review normalized rows before import</h2>
          </div>
        </div>

        <div class="preview-summary" id="preview-summary"></div>

        <div class="preview-rows" id="preview-rows"></div>

        <div class="action-row">
          <button id="start-import" class="primary">Start import</button>
          <button id="back-to-mapping" class="secondary">Back</button>
        </div>
      </article>
    `;
  }

  renderProgressPanel() {
    return `
      <article class="panel import-panel" id="progress-panel" style="display:none">
        <div class="panel-head">
          <div>
            <p class="eyebrow">IMPORT PROGRESS</p>
            <h2 id="progress-title">Importing...</h2>
          </div>
        </div>

        <div class="progress-container">
          <div class="progress-bar">
            <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
          </div>
          <div class="progress-text">
            <span id="progress-percent">0%</span>
            <span id="progress-fraction">0 / 0 rows</span>
          </div>
        </div>

        <div class="progress-stats">
          <div>
            <strong id="stat-valid">0</strong>
            <small>Valid rows</small>
          </div>
          <div>
            <strong id="stat-rejected">0</strong>
            <small>Rejected</small>
          </div>
          <div>
            <strong id="stat-rate">0</strong>
            <small>rows/sec</small>
          </div>
          <div>
            <strong id="stat-elapsed">0:00</strong>
            <small>Elapsed</small>
          </div>
        </div>

        <div id="progress-messages"></div>

        <button id="cancel-import" class="secondary">Cancel</button>
      </article>
    `;
  }

  renderHistoryPanel() {
    return `
      <article class="panel import-panel" id="history-panel" style="display:none">
        <div class="panel-head">
          <div>
            <p class="eyebrow">IMPORT HISTORY</p>
            <h2>Past imports</h2>
          </div>
        </div>

        <div id="history-list" class="history-list"></div>
      </article>
    `;
  }

  // Event binding
  bind() {
    const browseBtn = document.querySelector('#browse-file');
    const fileInput = document.querySelector('#file-input');
    const uploadZone = document.querySelector('#upload-zone');

    browseBtn?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', (e) => this.handleFileSelect(e.target.files[0]));

    // Drag and drop
    uploadZone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      uploadZone.setAttribute('data-dragover', 'true');
    });

    uploadZone?.addEventListener('dragleave', () => {
      uploadZone.setAttribute('data-dragover', 'false');
    });

    uploadZone?.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      uploadZone.setAttribute('data-dragover', 'false');
      const file = e.dataTransfer?.files?.[0];
      if (file) this.handleFileSelect(file);
    });

    document.querySelector('#continue-to-mapping')?.addEventListener('click', () => this.showMappingPanel());
    document.querySelector('#preview-import')?.addEventListener('click', () => this.previewData());
    document.querySelector('#start-import')?.addEventListener('click', () => this.startImport());
    document.querySelector('#cancel-import')?.addEventListener('click', () => this.cancelImport());
    document.querySelector('#start-over')?.addEventListener('click', () => this.reset());
    document.querySelector('#back-to-analysis')?.addEventListener('click', () => this.showAnalysisPanel());
    document.querySelector('#back-to-mapping')?.addEventListener('click', () => this.showMappingPanel());
  }

  async handleFileSelect(file) {
    if (!file) return;

    const validExts = ['.csv', '.json', '.jsonl'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!validExts.includes(ext)) {
      alert('Unsupported file type. Use CSV or JSON.');
      return;
    }

    if (file.size > 500_000_000) {
      alert('File exceeds 500 MB limit.');
      return;
    }

    // Determine format
    this.fileFormat = ext === '.csv' ? 'csv' : 'json';

    try {
      // Start import
      const start = await this.api('/import/start', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          file_size: file.size,
          format: this.fileFormat,
        }),
      });

      this.importId = start.import_id;

      // Upload file in chunks. The backend appends each multipart payload.
      const chunkSize = 5_000_000; // 5 MB chunks
      const chunks = Math.ceil(file.size / chunkSize);

      for (let i = 0; i < chunks; i++) {
        const start_idx = i * chunkSize;
        const end_idx = Math.min(start_idx + chunkSize, file.size);
        const chunk = file.slice(start_idx, end_idx);

        const formData = createUploadFormData(file, chunk);

        await this.api(`/import/${this.importId}/upload`, {
          method: 'POST',
          body: formData,
        });
      }

      // Analyze file
      await this.analyzeFile();
    } catch (error) {
      alert(`Upload failed: ${error.message}`);
      this.reset();
    }
  }

  async analyzeFile() {
    try {
      const result = await this.api(`/import/${this.importId}/analyze`, { method: 'POST' });
      this.status = result;
      this.autoMapping = result.auto_mapping || {};

      // Show analysis panel
      this.showAnalysisPanel();

      // Render sample preview
      if (result.sample_rows?.length) {
        const preview = document.querySelector('#sample-preview');
        if (preview) {
          preview.innerHTML = `
            <div class="sample-table">
              <div class="sample-row sample-header">
                ${Object.keys(result.sample_rows[0]).map(k => `<span>${this.escapeHtml(k)}</span>`).join('')}
              </div>
              ${result.sample_rows.slice(0, 5).map(row => `
                <div class="sample-row">
                  ${Object.values(row).map(v => `<span>${this.escapeHtml(String(v).slice(0, 20))}</span>`).join('')}
                </div>
              `).join('')}
            </div>
          `;
        }
      }
    } catch (error) {
      alert(`Analysis failed: ${error.message}`);
      this.reset();
    }
  }

  showAnalysisPanel() {
    document.querySelector('#upload-zone').style.display = 'none';
    document.querySelector('#analysis-panel').style.display = 'block';
    document.querySelector('#mapping-panel').style.display = 'none';
    document.querySelector('#preview-panel').style.display = 'none';
    document.querySelector('#progress-panel').style.display = 'none';
    document.querySelector('#history-panel').style.display = 'none';
  }

  showMappingPanel() {
    document.querySelector('#upload-zone').style.display = 'none';
    document.querySelector('#analysis-panel').style.display = 'none';
    document.querySelector('#mapping-panel').style.display = 'block';
    document.querySelector('#preview-panel').style.display = 'none';
    document.querySelector('#progress-panel').style.display = 'none';
    document.querySelector('#history-panel').style.display = 'none';

    // Collect manual mapping from selects
    document.querySelectorAll('[data-mapping-col]').forEach((sel) => {
      const col = sel.dataset.mappingCol;
      const field = sel.value;
      if (field) {
        this.manualMapping[col] = field;
      }
    });
  }

  async previewData() {
    // Collect current mapping
    document.querySelectorAll('[data-mapping-col]').forEach((sel) => {
      const col = sel.dataset.mappingCol;
      const field = sel.value;
      if (field) {
        this.manualMapping[col] = field;
      }
    });

    // Show preview panel
    document.querySelector('#upload-zone').style.display = 'none';
    document.querySelector('#analysis-panel').style.display = 'none';
    document.querySelector('#mapping-panel').style.display = 'none';
    document.querySelector('#preview-panel').style.display = 'block';
    document.querySelector('#progress-panel').style.display = 'none';
    document.querySelector('#history-panel').style.display = 'none';

    // TODO: Fetch preview from backend or generate locally from sample rows
    const preview = document.querySelector('#preview-summary');
    if (preview && this.status) {
      preview.innerHTML = `
        <div class="validation-summary">
          <div class="summary-stat">
            <strong>Total rows</strong>
            <span>${this.num.format(this.status.total_rows)}</span>
          </div>
          <div class="summary-stat">
            <strong>Valid</strong>
            <span>${this.status.validation_summary?.valid_rows || 0}</span>
          </div>
          <div class="summary-stat">
            <strong>Rejected</strong>
            <span>${this.status.validation_summary?.rejected_rows || 0}</span>
          </div>
        </div>
      `;
    }
  }

  async startImport() {
    this.duplicateHandling = document.querySelector('#duplicate-handling')?.value || 'skip';

    // Show progress panel
    document.querySelector('#upload-zone').style.display = 'none';
    document.querySelector('#analysis-panel').style.display = 'none';
    document.querySelector('#mapping-panel').style.display = 'none';
    document.querySelector('#preview-panel').style.display = 'none';
    document.querySelector('#progress-panel').style.display = 'block';
    document.querySelector('#history-panel').style.display = 'none';

    try {
      const result = await this.api(`/import/${this.importId}/commit`, {
        method: 'POST',
        body: JSON.stringify({
          import_id: this.importId,
          mapping: this.manualMapping,
          duplicate_handling: this.duplicateHandling,
        }),
      });

      // Show completion
      const title = document.querySelector('#progress-title');
      if (title) {
        title.textContent = 'Import complete!';
      }

      // TODO: Show results summary

      // Clear after delay
      setTimeout(() => this.showHistory(), 2000);
    } catch (error) {
      alert(`Import failed: ${error.message}`);
    }
  }

  async cancelImport() {
    if (!this.importId) return;
    try {
      await this.api(`/import/${this.importId}/cancel`, { method: 'DELETE' });
      this.reset();
    } catch (error) {
      alert(`Cancel failed: ${error.message}`);
    }
  }

  async showHistory() {
    try {
      const history = await this.api('/import/history', { method: 'GET' });

      document.querySelector('#upload-zone').style.display = 'none';
      document.querySelector('#analysis-panel').style.display = 'none';
      document.querySelector('#mapping-panel').style.display = 'none';
      document.querySelector('#preview-panel').style.display = 'none';
      document.querySelector('#progress-panel').style.display = 'none';
      document.querySelector('#history-panel').style.display = 'block';

      const list = document.querySelector('#history-list');
      if (list && history.imports?.length) {
        list.innerHTML = history.imports
          .map(
            (imp) => `
          <div class="history-item">
            <div class="history-info">
              <strong>${this.escapeHtml(imp.filename)}</strong>
              <small>${new Date(imp.created_at).toLocaleString()}</small>
            </div>
            <div class="history-stats">
              <span>${imp.inserted_rows} / ${imp.total_rows} rows</span>
              <span class="status ${imp.status.toLowerCase()}">${imp.status}</span>
            </div>
          </div>
        `
          )
          .join('');
      }
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  }

  reset() {
    this.importId = null;
    this.status = null;
    this.autoMapping = {};
    this.manualMapping = {};
    document.querySelector('#file-input').value = '';
    document.querySelector('#upload-zone').style.display = 'block';
    document.querySelector('#analysis-panel').style.display = 'none';
    document.querySelector('#mapping-panel').style.display = 'none';
    document.querySelector('#preview-panel').style.display = 'none';
    document.querySelector('#progress-panel').style.display = 'none';
    document.querySelector('#history-panel').style.display = 'none';
  }

  escapeHtml(str) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return String(str).replace(/[&<>"']/g, (char) => map[char]);
  }
}
