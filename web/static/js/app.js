/**
 * Gnome Bot RoK - Dashboard Controller
 * Full interactive client for Live, Inventory, Config, History, and Upgrade tabs.
 */

let currentLogCount = 0;
let isPollingLogs = true;
let botConfig = {};
let engineState = { bot_enabled: false, is_running: false, status: 'standby' };
let accountsList = [];

// ==========================================
// TOAST NOTIFICATIONS
// ==========================================
function showToast(msg, type = 'info') {
  let toast = document.getElementById('arcaneToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'arcaneToast';
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      padding: 12px 20px;
      border-radius: 10px;
      font-size: 0.85rem;
      font-weight: 600;
      z-index: 99999;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
      transition: all 0.3s ease;
      backdrop-filter: blur(12px);
      font-family: 'Plus Jakarta Sans', sans-serif;
    `;
    document.body.appendChild(toast);
  }

  if (type === 'success') {
    toast.style.background = 'rgba(16, 185, 129, 0.95)';
    toast.style.color = '#fff';
    toast.style.border = '1px solid rgba(16, 185, 129, 0.4)';
    toast.innerHTML = `<span>✓</span> <span>${msg}</span>`;
  } else if (type === 'error') {
    toast.style.background = 'rgba(239, 68, 68, 0.95)';
    toast.style.color = '#fff';
    toast.style.border = '1px solid rgba(239, 68, 68, 0.4)';
    toast.innerHTML = `<span>⚠</span> <span>${msg}</span>`;
  } else {
    toast.style.background = 'rgba(139, 92, 246, 0.95)';
    toast.style.color = '#fff';
    toast.style.border = '1px solid rgba(139, 92, 246, 0.4)';
    toast.innerHTML = `<span>ℹ</span> <span>${msg}</span>`;
  }

  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
  }, 3500);
}

// ==========================================
// TAB NAVIGATION
// ==========================================
function initTabNavigation() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      const targetTab = tab.getAttribute('data-tab');
      document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
      });

      const activeContent = document.getElementById(`tab-${targetTab}`);
      if (activeContent) {
        activeContent.classList.add('active');
      }
    });
  });
}

// ==========================================
// CONFIG SIDEBAR NAVIGATION
// ==========================================
function initConfigSidebar() {
  const cfgLinks = document.querySelectorAll('.cfg-nav-link');
  cfgLinks.forEach(link => {
    link.addEventListener('click', () => {
      cfgLinks.forEach(l => l.classList.remove('active'));
      link.classList.add('active');

      const targetCfg = link.getAttribute('data-cfg');
      document.querySelectorAll('.cfg-panel-box').forEach(panel => {
        panel.style.display = 'none';
      });

      const activePanel = document.getElementById(`panel-${targetCfg}`);
      if (activePanel) {
        activePanel.style.display = 'block';
      }
    });
  });
}

// ==========================================
// MARCH COUNTERS (- 1 +)
// ==========================================
window.adjustMarch = function(resource, delta) {
  const counterElem = document.getElementById(`cnt${capitalize(resource)}March`);
  if (!counterElem) return;

  let current = parseInt(counterElem.textContent || '0', 10);
  let next = current + delta;
  if (next < 0) next = 0;
  if (next > 7) next = 7;

  const food = resource === 'food' ? next : parseInt(document.getElementById('cntFoodMarch')?.textContent || '0', 10);
  const wood = resource === 'wood' ? next : parseInt(document.getElementById('cntWoodMarch')?.textContent || '0', 10);
  const stone = resource === 'stone' ? next : parseInt(document.getElementById('cntStoneMarch')?.textContent || '0', 10);
  const gold = resource === 'gold' ? next : parseInt(document.getElementById('cntGoldMarch')?.textContent || '0', 10);

  if (food + wood + stone + gold > 7 && delta > 0) {
    showToast('Maximum total marches is 7 across all resources', 'error');
    return;
  }

  counterElem.textContent = next;
};

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ==========================================
// SYNC ENGINE STATE & TOP HEADER
// ==========================================
async function fetchEngineState() {
  try {
    const res = await fetch('/api/state');
    if (!res.ok) return;
    const data = await res.json();
    engineState = data;

    const headerUser = document.getElementById('headerBotUser');
    if (headerUser && data.bot_user) headerUser.textContent = data.bot_user;

    const headerId = document.getElementById('headerBotId');
    if (headerId && data.bot_id) headerId.textContent = data.bot_id;

    const statusText = document.getElementById('statusText');
    const badgeRunning = document.getElementById('badgeRunning');
    const dotPulse = document.getElementById('dotPulse');
    const btnBotIcon = document.getElementById('btnBotIcon');
    const btnBotText = document.getElementById('btnBotText');
    const btnToggleBot = document.getElementById('btnToggleBot');

    // Authoritative check: is the bot actively running?
    const isRunning = Boolean(data.bot_enabled && (data.is_running || data.status === 'running' || data.status === 'gathering'));

    if (statusText) statusText.textContent = isRunning ? 'Running' : 'Standby';
    if (dotPulse) {
      dotPulse.style.background = isRunning ? '#10b981' : '#f59e0b';
      dotPulse.style.boxShadow = isRunning ? '0 0 8px #10b981' : '0 0 8px #f59e0b';
    }
    if (badgeRunning) {
      badgeRunning.style.color = isRunning ? '#34d399' : '#fbbf24';
      badgeRunning.style.background = isRunning ? 'rgba(16, 185, 129, 0.12)' : 'rgba(245, 158, 11, 0.12)';
      badgeRunning.style.borderColor = isRunning ? 'rgba(16, 185, 129, 0.25)' : 'rgba(245, 158, 11, 0.25)';
    }

    if (btnBotIcon && btnBotText && btnToggleBot) {
      if (isRunning) {
        btnBotIcon.textContent = '⏹';
        btnBotText.textContent = 'Stop bot';
        btnToggleBot.className = 'btn-top-action btn-stop';
      } else {
        btnBotIcon.textContent = '▶';
        btnBotText.textContent = 'Start bot';
        btnToggleBot.className = 'btn-top-action';
      }
    }

    const headerNextRun = document.getElementById('headerNextRun');
    if (headerNextRun) {
      headerNextRun.textContent = data.next_loop_run ? `Next run ${data.next_loop_run}` : 'Next run in 54m';
    }

    const slotsUsed = document.getElementById('slotsUsed');
    const slotsTotal = document.getElementById('slotsTotal');
    if (slotsUsed && data.character_slots_used) slotsUsed.textContent = data.character_slots_used;
    if (slotsTotal && data.character_slots_total) slotsTotal.textContent = data.character_slots_total;

    const licenseTime = document.getElementById('licenseTimeLeft');
    if (licenseTime && data.license_time_left) licenseTime.textContent = data.license_time_left;

    const licenseFill = document.getElementById('licenseBarFill');
    if (licenseFill && data.license_percent) licenseFill.style.width = `${data.license_percent}%`;

    const licenseExpires = document.getElementById('licenseExpires');
    if (licenseExpires && data.license_expires) licenseExpires.textContent = `Expires ${data.license_expires}`;

    const licensePlan = document.getElementById('licensePlan');
    if (licensePlan && data.license_plan) licensePlan.textContent = data.license_plan;

    const lastSync = document.getElementById('lastSyncLabel');
    if (lastSync && data.last_sync) lastSync.textContent = `Synced: ${data.last_sync.split(' ')[1] || ''}`;

    // Update active account email in gathering panels if available
    if (data.account_email) {
      const acc1 = document.getElementById('cfgActiveAccountName1');
      const acc2 = document.getElementById('cfgActiveAccountName2');
      if (acc1) acc1.textContent = data.account_email;
      if (acc2) acc2.textContent = data.account_email;
    }

    // Render live marches dashboard cards
    renderMarches(data.marches || [], data.active_queues || 0, data.total_troops || 0);

  } catch (err) {
    console.error('Failed to fetch engine state:', err);
  }
}

// ==========================================
// ACTIVE GATHERING MARCHES RENDERER
// ==========================================
function renderMarches(marches = [], activeQueues = 0, totalTroops = 0) {
  const container = document.getElementById('marchesLiveGrid');
  if (!container) return;

  const countBadge = document.getElementById('txtActiveMarchesCount');
  if (countBadge) {
    countBadge.textContent = `${activeQueues} / 5 Active Marches`;
  }

  const troopsLabel = document.getElementById('lblCityTroopsAvail');
  if (troopsLabel) {
    troopsLabel.textContent = `Available Army: ${Number(totalTroops || 0).toLocaleString()} soldiers`;
  }

  let html = '';
  const totalSlots = 5;

  for (let i = 0; i < totalSlots; i++) {
    const march = marches[i];
    if (march) {
      const type = (march.type || 'food').toLowerCase();
      let icon = '🌾';
      let typeBg = 'rgba(245, 158, 11, 0.15)';
      let typeColor = '#fbbf24';
      if (type.includes('wood')) { icon = '🪵'; typeBg = 'rgba(16, 185, 129, 0.15)'; typeColor = '#34d399'; }
      else if (type.includes('stone')) { icon = '🪨'; typeBg = 'rgba(96, 165, 250, 0.15)'; typeColor = '#60a5fa'; }
      else if (type.includes('gold')) { icon = '🪙'; typeBg = 'rgba(234, 179, 8, 0.15)'; typeColor = '#facc15'; }
      else if (type.includes('gem')) { icon = '💎'; typeBg = 'rgba(236, 72, 153, 0.15)'; typeColor = '#f472b6'; }

      const cmdName = march.cmd_name || march.commander || `Commander #${march.cmd_id || (i + 1)}`;
      const targetName = march.target || 'Resource Tile';
      const troopsCnt = march.troops ? `${Number(march.troops).toLocaleString()} soldiers` : 'Troops dispatched';
      const loadStr = march.load ? `Load: ${Number(march.load).toLocaleString()}` : '';

      html += `
        <div style="background:#13131c; border:1px solid rgba(139, 92, 246, 0.25); border-radius:12px; padding:14px 16px; display:flex; flex-direction:column; gap:10px; box-shadow:0 4px 15px rgba(0,0,0,0.3);">
          <div style="display:flex; align-items:center; justify-content:space-between;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-weight:700; font-size:0.85rem; color:#fff;">March #${i + 1}</span>
              <span style="background:${typeBg}; color:${typeColor}; font-size:0.7rem; font-weight:700; padding:1px 6px; border-radius:4px;">${icon} ${type.toUpperCase()}</span>
            </div>
            <span style="display:inline-flex; align-items:center; gap:5px; font-size:0.72rem; color:#34d399; font-weight:700; background:rgba(16,185,129,0.12); padding:2px 8px; border-radius:999px;">
              <span class="dot-pulse" style="width:5px; height:5px; background:#10b981; box-shadow:0 0 6px #10b981;"></span> Gathering
            </span>
          </div>

          <div style="font-size:0.88rem; font-weight:600; color:#f8fafc; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            ${targetName}
          </div>

          <div style="display:flex; align-items:center; gap:8px; font-size:0.8rem; color:#a78bfa;">
            <span>🎖️</span> <span>${cmdName}</span>
          </div>

          <div style="display:flex; align-items:center; justify-content:space-between; font-size:0.75rem; color:var(--text-dim); border-top:1px solid rgba(255,255,255,0.05); padding-top:8px; margin-top:2px;">
            <span style="font-family:var(--font-mono); color:#cbd5e1;">${troopsCnt}</span>
            <span style="font-family:var(--font-mono);">${loadStr}</span>
          </div>
        </div>
      `;
    } else {
      html += `
        <div onclick="dispatchGatheringFromUI()" style="background:rgba(255,255,255,0.015); border:1px dashed rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; min-height:120px; cursor:pointer; transition:all 0.2s;" onmouseover="this.style.borderColor='rgba(139,92,246,0.4)'; this.style.background='rgba(139,92,246,0.04)';" onmouseout="this.style.borderColor='rgba(255,255,255,0.1)'; this.style.background='rgba(255,255,255,0.015)';">
          <div style="font-size:1.1rem; color:var(--text-dim);">➕</div>
          <div style="font-size:0.82rem; font-weight:600; color:var(--text-muted);">March Queue #${i + 1} Available</div>
          <div style="font-size:0.72rem; color:var(--text-dim);">Click to Deploy Gather March</div>
        </div>
      `;
    }
  }

  container.innerHTML = html;
}

window.goToGatheringConfig = function() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(t => t.classList.remove('active'));
  const cfgTabBtn = document.querySelector('.nav-tab[data-tab="config"]');
  if (cfgTabBtn) cfgTabBtn.classList.add('active');

  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const cfgContent = document.getElementById('tab-config');
  if (cfgContent) cfgContent.classList.add('active');

  const cfgLinks = document.querySelectorAll('.cfg-nav-link');
  cfgLinks.forEach(l => l.classList.remove('active'));
  const gatherLink = document.querySelector('.cfg-nav-link[data-cfg="gathering"]');
  if (gatherLink) gatherLink.classList.add('active');

  document.querySelectorAll('.cfg-panel-box').forEach(p => p.style.display = 'none');
  const gatherPanel = document.getElementById('panel-gathering');
  if (gatherPanel) {
    gatherPanel.style.display = 'block';
    gatherPanel.scrollIntoView({ behavior: 'smooth' });
  }
};

window.dispatchGatheringFromUI = async function() {
  const food = parseInt(document.getElementById('cntFoodMarch')?.textContent || '1', 10);
  const wood = parseInt(document.getElementById('cntWoodMarch')?.textContent || '1', 10);
  const stone = parseInt(document.getElementById('cntStoneMarch')?.textContent || '1', 10);
  const gold = parseInt(document.getElementById('cntGoldMarch')?.textContent || '0', 10);
  const maxNodeLevel = document.getElementById('cfgMaxNodeLevel')?.value || 'Level 6 and below';
  const onlyFinishable = document.getElementById('cfgOnlyFinishable')?.checked ?? true;
  const skipPartially = document.getElementById('cfgSkipPartially')?.checked ?? true;

  if (food + wood + stone + gold <= 0) {
    showToast('Please allocate at least 1 march counter before dispatching!', 'error');
    return;
  }

  showToast(`Deploying gathering marches (${maxNodeLevel})...`, 'info');

  try {
    const res = await fetch('/api/dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        food_marches: food,
        wood_marches: wood,
        stone_marches: stone,
        gold_marches: gold,
        max_node_level: maxNodeLevel,
        only_finishable: onlyFinishable,
        skip_partially_gathered: skipPartially
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast(data.message || 'Gathering marches successfully dispatched!', 'success');
      // Switch back to Live tab so Rey can view real-time execution
      const liveTabBtn = document.querySelector('.nav-tab[data-tab="live"]');
      if (liveTabBtn) liveTabBtn.click();
      fetchEngineState();
    } else {
      showToast(data.error || 'Failed to dispatch gathering', 'error');
    }
  } catch (err) {
    showToast('Error connecting to server for dispatch', 'error');
  }
};

// ==========================================
// TERMINAL LOGS POLLING
// ==========================================
async function fetchLogs() {
  if (!isPollingLogs) return;
  try {
    const res = await fetch(`/api/logs?since=${currentLogCount}`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.logs && data.logs.length > 0) {
      const term = document.getElementById('terminalLog');
      if (term) {
        data.logs.forEach(item => {
          const line = document.createElement('div');
          line.className = 'log-line';

          const timeSpan = document.createElement('span');
          timeSpan.className = 'log-time';
          timeSpan.textContent = item.time || '';

          const tagSpan = document.createElement('span');
          tagSpan.className = 'log-tag';
          tagSpan.textContent = item.tag || '[BOT]';

          const msgSpan = document.createElement('span');
          msgSpan.className = `log-msg ${item.type || 'info'}`;
          msgSpan.textContent = item.message || '';

          line.appendChild(timeSpan);
          line.appendChild(tagSpan);
          line.appendChild(msgSpan);
          term.appendChild(line);
        });

        term.scrollTop = term.scrollHeight;
      }
      currentLogCount = data.total;
      const countLabel = document.getElementById('linesCount');
      if (countLabel) countLabel.textContent = `${Math.min(currentLogCount, 100)} lines`;
    }
  } catch (err) {
    console.error('Error fetching logs:', err);
  }
}

// ==========================================
// ACCOUNTS & ACTIONS DROPDOWN (TAB 1)
// ==========================================
async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    if (!res.ok) return;
    accountsList = await res.json();
    renderAccounts(accountsList);
  } catch (err) {
    console.error('Failed to load accounts:', err);
  }
}

function renderAccounts(accounts) {
  const container = document.getElementById('accountCardsContainer');
  if (!container) return;

  container.innerHTML = '';

  accounts.forEach((acc, accIdx) => {
    const card = document.createElement('div');
    card.className = 'account-group-card';

    // Account Card Header matching Rey's media_1788815124021.png
    const header = document.createElement('div');
    header.className = 'account-card-header';
    header.innerHTML = `
      <div class="account-email-info">
        <span class="chevron-toggle" style="cursor:pointer; color:var(--text-dim);" onclick="toggleAccountCollapse(${accIdx})">▼</span>
        <span class="account-email">${acc.email}</span>
        <span class="account-last-run">${acc.last_run || 'active'}</span>
      </div>
      <div class="account-header-actions">
        <button class="btn-action-sm" onclick="showAccountSummaries('${acc.email}')">Summaries</button>
        <div class="account-actions-dropdown-wrap">
          <button class="btn-action-sm" onclick="toggleAccountDropdown(event, 'accDropdown_${accIdx}')">Actions ▾</button>
          <div class="account-dropdown-menu" id="accDropdown_${accIdx}">
            <button class="dropdown-item" onclick="triggerAccountAction('run_now', '${acc.email}')">
              <span>▶</span> Run now
            </button>
            <button class="dropdown-item" onclick="triggerAccountAction('recall', '${acc.email}')">
              <span>↩</span> Recall troops
            </button>
            <button class="dropdown-item" onclick="triggerAccountAction('shield', '${acc.email}')">
              <span>🛡</span> Shield
            </button>
            <button class="dropdown-item" onclick="triggerAccountAction('refresh', '${acc.email}')">
              <span>🔄</span> Refresh account
            </button>
            <button class="dropdown-item text-danger" onclick="triggerAccountAction('remove', '${acc.email}')">
              <span>✕</span> Remove account
            </button>
          </div>
        </div>
      </div>
    `;
    card.appendChild(header);

    // Governors Table
    const tableWrap = document.createElement('div');
    tableWrap.id = `accTableWrap_${accIdx}`;
    tableWrap.style.overflowX = 'auto';

    let rowsHtml = '';
    (acc.governors || []).forEach((gov, govIdx) => {
      rowsHtml += `
        <tr>
          <td>
            <input type="checkbox" ${gov.enabled ? 'checked' : ''} onchange="toggleGovStatus(${accIdx}, ${govIdx}, this.checked)">
          </td>
          <td style="color: var(--text-dim); font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;">${gov.id}</td>
          <td><span class="tag-kd">${gov.kingdom}</span></td>
          <td style="font-weight: 600; color: #fff;">${gov.name}</td>
          <td><span class="tag-ch">${gov.city_hall}</span></td>
          <td style="color: var(--text-dim);">${gov.last_run}</td>
          <td style="color: #a78bfa;">${gov.next_run}</td>
          <td><span class="tag-summary" style="cursor:pointer;" onclick="showAccountSummaries('${acc.email}')">Summaries</span></td>
          <td>
            <div class="account-actions-dropdown-wrap">
              <button class="btn-action-sm" onclick="toggleAccountDropdown(event, 'govDropdown_${accIdx}_${govIdx}')">Actions ▾</button>
              <div class="account-dropdown-menu" id="govDropdown_${accIdx}_${govIdx}">
                <button class="dropdown-item" onclick="triggerAccountAction('run_now', '${acc.email}', '${gov.id}')">
                  <span>▶</span> Run now
                </button>
                <button class="dropdown-item" onclick="triggerAccountAction('recall', '${acc.email}', '${gov.id}')">
                  <span>↩</span> Recall
                </button>
                <button class="dropdown-item" onclick="triggerAccountAction('refresh', '${acc.email}', '${gov.id}')">
                  <span>ℹ</span> Inspect stats
                </button>
              </div>
            </div>
          </td>
        </tr>
      `;
    });

    tableWrap.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 38px;">ON</th>
            <th>GOVERNOR ID</th>
            <th>KINGDOM</th>
            <th>NAME</th>
            <th>CITY HALL</th>
            <th>LAST RUN</th>
            <th>NEXT RUN</th>
            <th></th>
            <th>ACTIONS</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    `;

    card.appendChild(tableWrap);
    container.appendChild(card);
  });
}

// Dropdown Toggling & Action Execution
window.toggleAccountDropdown = function(event, dropdownId) {
  event.stopPropagation();
  // Close any other open dropdowns
  document.querySelectorAll('.account-dropdown-menu').forEach(menu => {
    if (menu.id !== dropdownId) menu.classList.remove('show');
  });

  const dd = document.getElementById(dropdownId);
  if (dd) {
    dd.classList.toggle('show');
  }
};

// Global click to close dropdowns
window.addEventListener('click', () => {
  document.querySelectorAll('.account-dropdown-menu').forEach(menu => {
    menu.classList.remove('show');
  });
});

window.triggerAccountAction = async function(action, email, govId = null) {
  document.querySelectorAll('.account-dropdown-menu').forEach(menu => menu.classList.remove('show'));

  if (action === 'remove') {
    if (!confirm(`Are you sure you want to remove account ${email}?`)) return;
  }

  showToast(`Executing ${action.replace('_', ' ')} on ${email}...`, 'info');

  try {
    const res = await fetch('/api/account_action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action, email: email, gov_id: govId })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      if (action === 'remove') {
        loadAccounts();
      } else if (action === 'run_now' || action === 'recall') {
        fetchEngineState();
      }
    } else {
      showToast(data.error || 'Action failed', 'error');
    }
  } catch (err) {
    showToast('Failed to execute action', 'error');
  }
};

window.showAccountSummaries = function(email) {
  showToast(`Displaying production & gathering report for ${email}`, 'info');
};

window.toggleAccountCollapse = function(accIdx) {
  const wrap = document.getElementById(`accTableWrap_${accIdx}`);
  if (wrap) {
    wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
  }
};

window.toggleGovStatus = async function(accIdx, govIdx, isEnabled) {
  if (accountsList[accIdx] && accountsList[accIdx].governors[govIdx]) {
    accountsList[accIdx].governors[govIdx].enabled = isEnabled;
    try {
      await fetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(accountsList)
      });
      showToast(`Governor ${accountsList[accIdx].governors[govIdx].name} ${isEnabled ? 'enabled' : 'disabled'}`);
    } catch (err) {
      showToast('Failed to update governor state', 'error');
    }
  }
};

function initLiveSearch() {
  const searchInput = document.getElementById('liveSearchInput');
  if (!searchInput) return;

  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    if (!query) {
      renderAccounts(accountsList);
      return;
    }

    const filtered = accountsList.map(acc => {
      const matchEmail = acc.email.toLowerCase().includes(query);
      const matchGovs = (acc.governors || []).filter(g => 
        g.name.toLowerCase().includes(query) ||
        g.id.toString().includes(query) ||
        g.kingdom.toString().includes(query)
      );

      if (matchEmail || matchGovs.length > 0) {
        return {
          ...acc,
          governors: matchGovs.length > 0 ? matchGovs : acc.governors
        };
      }
      return null;
    }).filter(Boolean);

    renderAccounts(filtered);
  });
}

// ==========================================
// INVENTORY BREAKDOWN (TAB 2)
// ==========================================
async function loadInventory() {
  try {
    const res = await fetch('/api/inventory');
    if (!res.ok) return;
    const inv = await res.json();

    if (inv.gathered) {
      if (inv.gathered.food) document.getElementById('invFoodAmt').textContent = inv.gathered.food.amount;
      if (inv.gathered.wood) document.getElementById('invWoodAmt').textContent = inv.gathered.wood.amount;
      if (inv.gathered.stone) document.getElementById('invStoneAmt').textContent = inv.gathered.stone.amount;
      if (inv.gathered.gold) document.getElementById('invGoldAmt').textContent = inv.gathered.gold.amount;
    }

    if (inv.in_cities) {
      const cFood = document.getElementById('cityFood');
      const cWood = document.getElementById('cityWood');
      const cStone = document.getElementById('cityStone');
      const cGold = document.getElementById('cityGold');

      if (cFood) cFood.textContent = inv.in_cities.food;
      if (cWood) cWood.textContent = inv.in_cities.wood;
      if (cStone) cStone.textContent = inv.in_cities.stone;
      if (cGold) cGold.textContent = inv.in_cities.gold;
    }

    if (inv.characters) {
      const tbody = document.getElementById('charBreakdownBody');
      if (tbody) {
        tbody.innerHTML = '';
        inv.characters.forEach(char => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td style="color: var(--text-dim); font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;">${char.id}</td>
            <td style="font-weight: 600; color: #fff;">${char.name}</td>
            <td><span class="tag-kd">${char.kingdom}</span></td>
            <td><span class="tag-ch">${char.city_hall}</span></td>
            <td style="color: #60a5fa; font-weight: 500;">${char.power}</td>
            <td>${char.food}</td>
            <td>${char.wood}</td>
            <td>${char.stone}</td>
            <td>${char.gold}</td>
            <td style="font-weight: 700; color: #34d399;">${char.total}</td>
          `;
          tbody.appendChild(tr);
        });
      }
    }
  } catch (err) {
    console.error('Failed to load inventory:', err);
  }
}

function initTimePills() {
  const pills = document.querySelectorAll('.time-pill');
  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      showToast(`Showing stats for ${pill.textContent}`);
    });
  });
}

// ==========================================
// CONFIG LOAD & SAVE (TAB 3)
// ==========================================
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    botConfig = await res.json();

    const g = botConfig.gathering || {};
    const cntFood = document.getElementById('cntFoodMarch');
    const cntWood = document.getElementById('cntWoodMarch');
    const cntStone = document.getElementById('cntStoneMarch');
    const cntGold = document.getElementById('cntGoldMarch');
    if (cntFood && g.food_marches !== undefined) cntFood.textContent = g.food_marches;
    if (cntWood && g.wood_marches !== undefined) cntWood.textContent = g.wood_marches;
    if (cntStone && g.stone_marches !== undefined) cntStone.textContent = g.stone_marches;
    if (cntGold && g.gold_marches !== undefined) cntGold.textContent = g.gold_marches;

    const maxNode = document.getElementById('cfgMaxNodeLevel');
    if (maxNode && g.max_node_level) maxNode.value = g.max_node_level;

    const onlyFin = document.getElementById('cfgOnlyFinishable');
    if (onlyFin && g.only_finishable !== undefined) onlyFin.checked = g.only_finishable;

    const skipPart = document.getElementById('cfgSkipPartially');
    if (skipPart && g.skip_partially_gathered !== undefined) skipPart.checked = g.skip_partially_gathered;

    const c = botConfig.city || {};
    const colCity = document.getElementById('cfgCollectCity');
    if (colCity && c.collect_resources !== undefined) colCity.checked = c.collect_resources;

    const bSmith = document.getElementById('cfgBlacksmith');
    if (bSmith && c.produce_blacksmith !== undefined) bSmith.checked = c.produce_blacksmith;

    const tInf = document.getElementById('cfgTrainInfantry');
    if (tInf && c.train_infantry) tInf.value = c.train_infantry;

    const tCav = document.getElementById('cfgTrainCavalry');
    if (tCav && c.train_cavalry) tCav.value = c.train_cavalry;

    const tArc = document.getElementById('cfgTrainArchers');
    if (tArc && c.train_archers) tArc.value = c.train_archers;

    const tSg = document.getElementById('cfgTrainSiege');
    if (tSg && c.train_siege) tSg.value = c.train_siege;

    const bTr = document.getElementById('cfgBattleTraining');
    if (bTr && c.battle_training_mode) bTr.value = c.battle_training_mode;

    const gen = botConfig.general || {};
    const intHours = document.getElementById('cfgIntervalHours');
    if (intHours && gen.loop_interval_hours) intHours.value = gen.loop_interval_hours;

  } catch (err) {
    console.error('Failed to load config:', err);
  }
}

window.saveCurrentConfig = async function() {
  const updated = {
    ...botConfig,
    gathering: {
      food_marches: parseInt(document.getElementById('cntFoodMarch')?.textContent || '1', 10),
      wood_marches: parseInt(document.getElementById('cntWoodMarch')?.textContent || '1', 10),
      stone_marches: parseInt(document.getElementById('cntStoneMarch')?.textContent || '1', 10),
      gold_marches: parseInt(document.getElementById('cntGoldMarch')?.textContent || '0', 10),
      max_node_level: document.getElementById('cfgMaxNodeLevel')?.value || 'Level 6 and below',
      only_finishable: document.getElementById('cfgOnlyFinishable')?.checked ?? true,
      skip_partially_gathered: document.getElementById('cfgSkipPartially')?.checked ?? true
    },
    city: {
      collect_resources: document.getElementById('cfgCollectCity')?.checked ?? true,
      produce_blacksmith: document.getElementById('cfgBlacksmith')?.checked ?? false,
      train_infantry: document.getElementById('cfgTrainInfantry')?.value || 'T1',
      train_cavalry: document.getElementById('cfgTrainCavalry')?.value || 'T1',
      train_archers: document.getElementById('cfgTrainArchers')?.value || 'T1',
      train_siege: document.getElementById('cfgTrainSiege')?.value || 'T1',
      battle_training_mode: document.getElementById('cfgBattleTraining')?.value || 'Off'
    },
    general: {
      ...(botConfig.general || {}),
      loop_interval_hours: parseInt(document.getElementById('cfgIntervalHours')?.value || '3', 10)
    }
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    });
    const result = await res.json();
    if (result.success) {
      showToast('Configuration saved successfully!', 'success');
      botConfig = updated;
    } else {
      showToast(result.error || 'Failed to save config', 'error');
    }
  } catch (err) {
    showToast('Failed to reach server to save config', 'error');
  }
};

// ==========================================
// BOT CONTROL BUTTONS (START / STOP TOGGLE)
// ==========================================
function initBotControls() {
  const btnToggle = document.getElementById('btnToggleBot');
  if (btnToggle) {
    btnToggle.addEventListener('click', async () => {
      // Check current active state
      const isCurrentlyRunning = Boolean(engineState.bot_enabled && (engineState.is_running || engineState.status === 'running' || engineState.status === 'gathering'));

      if (isCurrentlyRunning) {
        // Stop the bot
        // Optimistic UI update
        engineState.bot_enabled = false;
        engineState.status = 'standby';
        engineState.is_running = false;
        fetchEngineState();

        try {
          const res = await fetch('/api/standby', { method: 'POST' });
          const d = await res.json();
          showToast(d.message || 'Bot placed on standby');
          fetchEngineState();
        } catch (e) {
          showToast('Failed to stop bot', 'error');
        }
      } else {
        // Start the bot
        // Optimistic UI update
        engineState.bot_enabled = true;
        engineState.status = 'running';
        engineState.is_running = true;
        fetchEngineState();

        try {
          const res = await fetch('/api/start_daemon', { method: 'POST' });
          const d = await res.json();
          showToast(d.message || 'Smart 3-March Auto-Gather started', 'success');
          fetchEngineState();
        } catch (e) {
          showToast('Failed to start bot', 'error');
        }
      }
    });
  }

  const btnAddAcc = document.getElementById('btnAddAccount');
  if (btnAddAcc) {
    btnAddAcc.addEventListener('click', () => {
      showToast('Add Account: Enter game credentials in backend configuration.');
    });
  }

  const btnRss = document.getElementById('btnRssTransfer');
  if (btnRss) {
    btnRss.addEventListener('click', () => {
      showToast('RSS Transfer route ready. Select recipient governor.');
    });
  }
}

// ==========================================
// INITIALIZATION
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  initTabNavigation();
  initConfigSidebar();
  initTimePills();
  initLiveSearch();
  initBotControls();

  fetchEngineState();
  fetchLogs();
  loadAccounts();
  loadInventory();
  loadConfig();

  setInterval(fetchEngineState, 4000);
  setInterval(fetchLogs, 1500);
});
