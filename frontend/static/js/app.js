// RoK Cloud Fleet Control - Unified Single Page Application
document.addEventListener('alpine:init', () => {
    Alpine.data('rokApp', () => ({
        // Navigation State
        currentTab: 'live',
        configSubTab: 'general',

        // Bot Control State
        botRunning: false,
        botStarting: false,

        // Real-Time Activity Log
        activityLines: [],
        ws: null,
        wsConnected: false,

        // Fleet Data
        accounts: [],
        searchQuery: '',
        loadingFleet: false,

        // Config Form State
        configTargetAccount: 'all',
        configApplyTarget: 'all',
        runFrequency: 'Every 2 hours',
        discordNotifications: false,
        discordWebhook: '',
        autoReconnect: true,
        savingConfig: false,

        // Connect Account Modal & Captcha
        showConnectModal: false,
        connectEmail: '',
        connectPassword: '',
        connecting: false,
        connectError: '',
        needsCaptcha: false,
        captchaParams: null,

        // Task / Action Modals
        showTrainModal: false,
        showGatherModal: false,
        selectedCharacter: null,
        trainPct: 100,
        trainCats: ['infantry', 'cavalry', 'archery', 'siege'],
        modalTiers: {
            infantry: 't1',
            cavalry: 't1',
            archery: 't1',
            siege: 't1'
        },
        trainCustomCount: null,
        gatherTargets: ['food', 'wood', 'stone'],
        gatherLevel: 6,
        gatherOnlyFinishable: true,
        gatherSkipPartial: true,
        dispatchingTask: false,

        // RSS Transfer State
        showRssModal: false,
        rssTargetRoleId: '',
        rssTargetName: '',
        rssTargetX: 500,
        rssTargetY: 500,
        rssTradingPostLvl: 17,
        rssRequested: { food: 0, wood: 0, stone: 0, gold: 0 },
        rssSelectedFarms: [],
        rssSavedRecipients: [],
        rssIsTransferring: false,
        rssJobId: null,
        rssJobProgress: 0,
        rssLogs: [],
        rssPollTimer: null,

        // Training Configuration State
        trainSettings: {
            enabled: true,
            auto_collect: true,
            train_pct: 100,
            train_count_custom: null,
            tiers: {
                infantry: 't1',
                cavalry: 't1',
                archery: 't1',
                siege: 't1'
            }
        },

        // Gathering Configuration State
        gatherSettings: {
            food: 1,
            wood: 1,
            stone: 1,
            gold: 0,
            gem: 0,
            max_node_level: 'Level 6 and below',
            only_finishable: true,
            skip_partially: true,
            max_marches: 'auto',
            territory: 'alliance_preferred',
            recall_on_attack: true
        },

        // Toast Messages
        toasts: [],

        init() {
            console.log("[RoK Cloud] Initializing Application...");
            this.setupCaptchaListener();
            this.fetchFleet();
            this.fetchBotStatus();
            this.fetchGatherConfig();
            this.fetchTrainConfig();
            this.initActivityWebSocket();

            // Refresh fleet every 30 seconds
            setInterval(() => {
                this.fetchFleet(true);
            }, 30000);
        },

        // --- Real-time Activity WebSocket ---
        initActivityWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/activity`;
            
            try {
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    this.wsConnected = true;
                    console.log("[WS] Activity stream connected.");
                };

                this.ws.onmessage = (event) => {
                    const text = event.data;
                    if (text) {
                        this.activityLines.push(text);
                        if (this.activityLines.length > 100) {
                            this.activityLines.shift();
                        }
                        this.$nextTick(() => {
                            this.scrollTerminalToBottom();
                        });
                    }
                };

                this.ws.onclose = () => {
                    this.wsConnected = false;
                    console.log("[WS] Activity stream disconnected, retrying in 4s...");
                    setTimeout(() => this.initActivityWebSocket(), 4000);
                };

                this.ws.onerror = (err) => {
                    console.error("[WS Error]", err);
                };
            } catch (e) {
                console.error("[WS Init Error]", e);
                // Fallback polling
                this.fetchRecentActivity();
            }
        },

        scrollTerminalToBottom() {
            const el = document.getElementById('activity-terminal');
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        },

        async fetchRecentActivity() {
            try {
                const res = await fetch('/api/activity/recent');
                if (res.ok) {
                    const data = await res.json();
                    if (data.lines) {
                        this.activityLines = data.lines;
                        this.$nextTick(() => this.scrollTerminalToBottom());
                    }
                }
            } catch (e) {}
        },

        formatTerminalLine(line) {
            // e.g. 12:25:17 AM [18 KD] Starting visit for 18 KD
            // Matches: (HH:MM:SS [AP]M) (\[.*?\])? (.*)
            const regex = /^(\d{1,2}:\d{2}:\d{2}\s+(?:AM|PM))\s*(?:\[(.*?)\])?\s*(.*)$/i;
            const match = line.match(regex);
            if (match) {
                const time = match[1];
                const kd = match[2];
                const text = match[3];
                let out = `<span class="text-purple-400 font-semibold">${time}</span> `;
                if (kd) {
                    out += `<span class="text-sky-400 font-bold">[${kd}]</span> `;
                }
                out += `<span class="text-slate-200">${text}</span>`;
                return out;
            }
            return `<span class="text-slate-200">${line}</span>`;
        },

        // --- Bot Engine Control ---
        async fetchBotStatus() {
            try {
                const res = await fetch('/api/bot/status');
                if (res.ok) {
                    const data = await res.json();
                    this.botRunning = !!data.running;
                    if (data.settings) {
                        if (data.settings.run_frequency) this.runFrequency = data.settings.run_frequency;
                        if (data.settings.discord_notifications) this.discordNotifications = data.settings.discord_notifications === 'true';
                        if (data.settings.discord_webhook) this.discordWebhook = data.settings.discord_webhook;
                        if (data.settings.auto_reconnect) this.autoReconnect = data.settings.auto_reconnect === 'true';
                    }
                }
            } catch (e) {
                console.error("Error fetching bot status:", e);
            }
        },

        async toggleBot() {
            this.botStarting = true;
            try {
                const endpoint = this.botRunning ? '/api/bot/stop' : '/api/bot/start';
                const res = await fetch(endpoint, { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    this.botRunning = !!data.running;
                    this.showToast(this.botRunning ? "Bot scheduler started." : "Bot scheduler stopped.", "info");
                }
            } catch (e) {
                this.showToast("Failed to toggle bot scheduler.", "error");
            } finally {
                this.botStarting = false;
            }
        },

        // --- Fleet Data & Search Filtering ---
        async fetchFleet(background = false) {
            if (!background) this.loadingFleet = true;
            try {
                const res = await fetch('/api/fleet/grouped');
                if (res.ok) {
                    const data = await res.json();
                    this.accounts = data.accounts || [];
                }
            } catch (e) {
                console.error("Error fetching fleet:", e);
            } finally {
                if (!background) this.loadingFleet = false;
            }
        },

        get filteredAccounts() {
            const query = this.searchQuery.trim().toLowerCase();
            if (!query) return this.accounts;

            return this.accounts.map(acc => {
                const matchAcc = acc.email.toLowerCase().includes(query);
                const matchingChars = (acc.characters || []).filter(c => 
                    (c.name && c.name.toLowerCase().includes(query)) ||
                    (c.role_id && c.role_id.toString().includes(query)) ||
                    (c.kingdom_id && c.kingdom_id.toString().includes(query))
                );

                if (matchAcc) return acc;
                if (matchingChars.length > 0) {
                    return { ...acc, characters: matchingChars };
                }
                return null;
            }).filter(Boolean);
        },

        async toggleAccount(acc) {
            try {
                const res = await fetch(`/api/accounts/${acc.id}/toggle`, { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    acc.is_active = data.is_active;
                    this.showToast(`Account ${acc.email} is now ${data.is_active ? 'active' : 'paused'}.`, 'info');
                }
            } catch (e) {
                this.showToast("Failed to toggle account.", "error");
            }
        },

        async toggleCharacter(char) {
            try {
                const res = await fetch(`/api/characters/${char.role_id}/toggle`, { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    char.enabled = data.enabled;
                    this.showToast(`${char.name || char.role_id} is now ${data.enabled ? 'enabled' : 'disabled'}.`, 'info');
                }
            } catch (e) {
                this.showToast("Failed to toggle character.", "error");
            }
        },

        async syncAccount(acc) {
            this.showToast(`Syncing characters for ${acc.email}...`, 'info');
            try {
                const res = await fetch('/api/accounts/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: acc.email, password: '' })
                });
                if (res.ok) {
                    this.showToast(`Sync complete for ${acc.email}`, 'success');
                    await this.fetchFleet();
                } else {
                    this.showToast(`Sync failed. Please reconnect account.`, 'error');
                }
            } catch (e) {
                this.showToast("Sync error.", "error");
            }
        },

        async deleteAccount(acc) {
            const confirmMsg = `Are you sure you want to permanently remove account:\n${acc.email}?\n\nAll linked characters and settings will be deleted.`;
            if (!confirm(confirmMsg)) return;

            try {
                const res = await fetch(`/api/accounts/${acc.id}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast(`Account ${acc.email} deleted successfully.`, 'success');
                    await this.fetchFleet();
                } else {
                    this.showToast("Failed to delete account.", "error");
                }
            } catch (e) {
                this.showToast("Error deleting account.", "error");
            }
        },

        async deleteCharacter(char) {
            const confirmMsg = `Are you sure you want to remove governor:\n${char.name || char.role_id} (#${char.role_id})?`;
            if (!confirm(confirmMsg)) return;

            try {
                const res = await fetch(`/api/characters/${char.role_id}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast(`Governor ${char.name || char.role_id} removed.`, 'success');
                    await this.fetchFleet();
                } else {
                    this.showToast("Failed to delete governor.", "error");
                }
            } catch (e) {
                this.showToast("Error deleting governor.", "error");
            }
        },

        // --- Routine / Action Execution ---
        async runRoutineNow(char) {
            this.showToast(`Dispatching visit for ${char.name} (KD ${char.kingdom_id})...`, 'info');
            try {
                const res = await fetch(`/api/characters/${char.role_id}/task`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_type: 'harvest', role_id: char.role_id, params: {} })
                });
                if (res.ok) {
                    this.showToast(`Visit routine launched for ${char.name}!`, 'success');
                } else {
                    this.showToast(`Failed to launch routine.`, 'error');
                }
            } catch (e) {
                this.showToast("Execution error.", "error");
            }
        },

        async dispatchAllianceResource(char) {
            if (!char && this.selectedCharacter) char = this.selectedCharacter;
            if (!char) return;
            this.showToast(`🏰 [حقل التحالف] جاري إرسال مسيرة للحاكم ${char.name}...`, 'info');
            try {
                const res = await fetch(`/api/characters/${char.role_id}/dispatch-alliance-resource`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    this.showToast(`🏰 تم إرسال مسيرة حقل التحالف للحاكم ${char.name}!`, 'success');
                } else {
                    this.showToast(`تعذر إرسال مسيرة حقل التحالف: ${data.detail || data.message || 'خطأ'}`, 'error');
                }
            } catch (e) {
                this.showToast("خطأ في الاتصال بالخادم لإرسال مسيرة حقل التحالف.", "error");
            }
        },

        async recallMarches(char) {
            if (!char && this.selectedCharacter) char = this.selectedCharacter;
            if (!char) return;
            this.showToast(`🚩 [سحب المسيرات] جاري إعادة مسيرات الحاكم ${char.name}...`, 'info');
            try {
                const res = await fetch(`/api/characters/${char.role_id}/recall-marches`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    this.showToast(`🚩 تم سحب مسيرات الحاكم ${char.name} بنجاح!`, 'success');
                } else {
                    this.showToast(`تعذر سحب المسيرات: ${data.detail || data.message || 'خطأ'}`, 'error');
                }
            } catch (e) {
                this.showToast("خطأ في الاتصال بالخادم لسحب المسيرات.", "error");
            }
        },

        openTrainModal(char) {
            this.selectedCharacter = char;
            this.trainPct = this.trainSettings.train_pct || 100;
            this.modalTiers = { ...this.trainSettings.tiers };
            if (char.tiers && typeof char.tiers === 'object' && Object.keys(char.tiers).length > 0) {
                this.modalTiers = { ...this.modalTiers, ...char.tiers };
            }
            this.trainCustomCount = this.trainSettings.train_count_custom || null;
            this.showTrainModal = true;
        },

        async dispatchTraining() {
            if (!this.selectedCharacter) return;
            this.dispatchingTask = true;
            try {
                const activeCats = Object.keys(this.modalTiers).filter(c => this.modalTiers[c] !== 'off');
                const res = await fetch('/api/train/dispatch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role_id: this.selectedCharacter.role_id,
                        categories: activeCats.length > 0 ? activeCats : ['infantry', 'cavalry', 'archery', 'siege'],
                        tiers: this.modalTiers,
                        train_pct: parseInt(this.trainPct) || 100,
                        train_count_custom: this.trainCustomCount ? parseInt(this.trainCustomCount) : null,
                        auto_collect: true
                    })
                });
                if (res.ok) {
                    this.showToast(`Training dispatched for ${this.selectedCharacter.name}!`, 'success');
                    this.showTrainModal = false;
                } else {
                    this.showToast(`Failed to dispatch training.`, 'error');
                }
            } catch (e) {
                this.showToast("Training dispatch error.", "error");
            } finally {
                this.dispatchingTask = false;
            }
        },

        openGatherModal(char) {
            this.selectedCharacter = char;
            this.gatherTargets = ['food', 'wood', 'stone'];
            this.gatherLevel = 6;
            this.gatherOnlyFinishable = true;
            this.gatherSkipPartial = true;
            this.showGatherModal = true;
        },

        async dispatchGathering() {
            if (!this.selectedCharacter) return;
            this.dispatchingTask = true;
            try {
                const res = await fetch('/api/gather/dispatch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role_id: this.selectedCharacter.role_id,
                        targets: this.gatherTargets,
                        level: parseInt(this.gatherLevel) || 6,
                        level_mode: 'highest_first',
                        only_finishable: this.gatherOnlyFinishable,
                        skip_partially: this.gatherSkipPartial
                    })
                });
                if (res.ok) {
                    this.showToast(`Gathering marches dispatched for ${this.selectedCharacter.name}!`, 'success');
                    this.showGatherModal = false;
                } else {
                    this.showToast(`Failed to dispatch gathering.`, 'error');
                }
            } catch (e) {
                this.showToast("Gathering dispatch error.", "error");
            } finally {
                this.dispatchingTask = false;
            }
        },

        // --- Config Tab Management ---
        async fetchGatherConfig() {
            try {
                const res = await fetch('/api/config/gather');
                if (res.ok) {
                    const data = await res.json();
                    if (data.gather) {
                        this.gatherSettings = { ...this.gatherSettings, ...data.gather };
                    }
                }
            } catch (e) {
                console.error("Error fetching gather config:", e);
            }
        },

        async fetchTrainConfig() {
            try {
                const res = await fetch('/api/config/train');
                if (res.ok) {
                    const data = await res.json();
                    if (data.train) {
                        this.trainSettings = {
                            ...this.trainSettings,
                            ...data.train,
                            tiers: { ...this.trainSettings.tiers, ...(data.train.tiers || {}) }
                        };
                    }
                }
            } catch (e) {
                console.error("Error fetching train config:", e);
            }
        },

        async saveConfig() {
            this.savingConfig = true;
            try {
                const payload = {
                    run_frequency: this.runFrequency,
                    discord_notifications: this.discordNotifications ? 'true' : 'false',
                    discord_webhook: this.discordWebhook,
                    auto_reconnect: this.autoReconnect ? 'true' : 'false'
                };
                await fetch('/api/bot/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                await fetch('/api/config/gather', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scope: this.configApplyTarget,
                        account_id: this.configTargetAccount,
                        gather: this.gatherSettings
                    })
                });

                await fetch('/api/config/train', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scope: this.configApplyTarget,
                        account_id: this.configTargetAccount,
                        train: this.trainSettings
                    })
                });

                this.showToast("Configuration saved successfully!", "success");
            } catch (e) {
                this.showToast("Configuration error.", "error");
            } finally {
                this.savingConfig = false;
            }
        },

        // --- Account Connection & Lilith Captcha Handling ---
        openAddAccountModal() {
            this.connectEmail = '';
            this.connectPassword = '';
            this.connectError = '';
            this.needsCaptcha = false;
            this.captchaParams = null;
            this.showConnectModal = true;
        },

        async submitConnectAccount() {
            this.connecting = true;
            this.connectError = '';
            this.needsCaptcha = false;

            try {
                const res = await fetch('/api/accounts/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: this.connectEmail,
                        password: this.connectPassword
                    })
                });

                const data = await res.json();
                if (data.status === 'CAPTCHA_REQUIRED') {
                    this.needsCaptcha = true;
                    this.captchaParams = data.captcha_params;
                    this.renderCaptcha(data.captcha_params);
                } else if (data.success) {
                    this.showToast(`Account connected: ${data.message}`, 'success');
                    this.showConnectModal = false;
                    await this.fetchFleet();
                } else {
                    this.connectError = data.message || "Failed to connect account.";
                }
            } catch (e) {
                this.connectError = "Network error connecting to cloud passport.";
            } finally {
                this.connecting = false;
            }
        },

        setupCaptchaListener() {
            window.addEventListener('message', async (event) => {
                try {
                    let data = event.data;
                    if (typeof data === 'string' && (data.includes('token') || data.includes('ticket') || data.startsWith('{'))) {
                        try { data = JSON.parse(data); } catch(e) {}
                    }
                    let ticket = null;
                    let randstr = '';
                    if (data && typeof data === 'object') {
                        ticket = data.captchaId || data.captcha_id || data.content || data.ticket || data.geetest_validate || data.validate;
                        randstr = data.randstr || data.geetest_challenge || data.challenge || '';
                    }
                    if (ticket && this.needsCaptcha) {
                        await this.submitFinalizeCaptcha(ticket, randstr);
                    }
                } catch (err) {}
            });
        },

        renderCaptcha(params) {
            if (!params) return;
            const fallbackUrl = params.fallback_url || (params.data && params.data.url);
            if (fallbackUrl) {
                window.open(fallbackUrl, '_blank', 'width=450,height=550,top=100,left=100');
            }
        },

        async submitFinalizeCaptcha(ticket, randstr) {
            this.connecting = true;
            try {
                const res = await fetch('/api/accounts/finalize-captcha', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: this.connectEmail,
                        password: this.connectPassword,
                        ticket: ticket,
                        randstr: randstr
                    })
                });
                const data = await res.json();
                if (data.success) {
                    this.showToast(`Authenticated! Synced ${data.characters ? data.characters.length : 0} characters.`, 'success');
                    this.showConnectModal = false;
                    this.needsCaptcha = false;
                    await this.fetchFleet();
                } else {
                    this.connectError = data.message || "Captcha verification failed.";
                }
            } catch (e) {
                this.connectError = "Verification submission failed.";
            } finally {
                this.connecting = false;
            }
        },

        // --- RSS Transfer Wizard ---
        async openRssTransferModal() {
            this.showRssModal = true;
            this.rssIsTransferring = false;
            this.rssLogs = [];
            this.rssJobProgress = 0;
            // Pre-select all available characters from fleet
            const allRoles = [];
            (this.accounts || []).forEach(acc => {
                (acc.characters || []).forEach(ch => {
                    allRoles.push(String(ch.role_id || ch.id));
                });
            });
            this.rssSelectedFarms = allRoles;
            // Fetch saved recipients
            try {
                const res = await fetch('/api/v1/saved-recipients');
                if (res.ok) {
                    const data = await res.json();
                    this.rssSavedRecipients = data.recipients || [];
                }
            } catch (e) {}
        },

        closeRssTransferModal() {
            this.showRssModal = false;
            if (this.rssPollTimer) {
                clearInterval(this.rssPollTimer);
                this.rssPollTimer = null;
            }
        },

        onSelectRssSavedRecipient(target) {
            const roleId = target.value;
            const rec = (this.rssSavedRecipients || []).find(r => String(r.role_id) === String(roleId));
            if (rec) {
                this.rssTargetName = rec.name;
                this.rssTargetRoleId = rec.role_id;
                this.rssTargetX = rec.x;
                this.rssTargetY = rec.y;
            }
        },

        getRssTaxRate() {
            const rates = {
                1: 0.35, 2: 0.34, 3: 0.33, 4: 0.32, 5: 0.31, 6: 0.30, 7: 0.29, 8: 0.28, 9: 0.27, 10: 0.26,
                11: 0.25, 12: 0.24, 13: 0.23, 14: 0.22, 15: 0.21, 16: 0.20, 17: 0.19, 18: 0.18, 19: 0.17,
                20: 0.16, 21: 0.15, 22: 0.14, 23: 0.12, 24: 0.10, 25: 0.08
            };
            return rates[this.rssTradingPostLvl] || 0.19;
        },

        calcGrossNeeded(net) {
            const n = parseInt(net) || 0;
            if (n <= 0) return 0;
            const tax = this.getRssTaxRate();
            return Math.ceil(n / (1.0 - tax));
        },

        calcTaxAmount(net) {
            const n = parseInt(net) || 0;
            if (n <= 0) return 0;
            return this.calcGrossNeeded(n) - n;
        },

        toggleRssFarm(roleId) {
            const r = String(roleId);
            const idx = this.rssSelectedFarms.indexOf(r);
            if (idx > -1) this.rssSelectedFarms.splice(idx, 1);
            else this.rssSelectedFarms.push(r);
        },

        toggleAllRssFarms() {
            const allRoles = [];
            (this.accounts || []).forEach(acc => {
                (acc.characters || []).forEach(ch => {
                    allRoles.push(String(ch.role_id || ch.id));
                });
            });
            if (this.rssSelectedFarms.length === allRoles.length) {
                this.rssSelectedFarms = [];
            } else {
                this.rssSelectedFarms = allRoles;
            }
        },

        async startRssTransfer() {
            if (!this.rssTargetRoleId) {
                this.showToast('يرجى إدخال معرف الحاكم المستلم.', 'error');
                return;
            }
            if (this.rssSelectedFarms.length === 0) {
                this.showToast('يرجى تحديد مزرعة واحدة على الأقل.', 'error');
                return;
            }

            this.rssIsTransferring = true;
            this.rssLogs = [];
            this.rssJobProgress = 5;

            const payload = {
                target_role_id: String(this.rssTargetRoleId).trim(),
                target_name: this.rssTargetName.trim() || 'Governor',
                x: parseInt(this.rssTargetX) || 0,
                y: parseInt(this.rssTargetY) || 0,
                requested_rss: {
                    food: parseInt(this.rssRequested.food) || 0,
                    wood: parseInt(this.rssRequested.wood) || 0,
                    stone: parseInt(this.rssRequested.stone) || 0,
                    gold: parseInt(this.rssRequested.gold) || 0
                },
                selected_farm_roles: this.rssSelectedFarms
            };

            try {
                const res = await fetch('/api/v1/start-transfer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    this.rssJobId = data.job_id;
                    this.rssLogs.push(`[${new Date().toLocaleTimeString()}] 🚀 ${data.message}`);
                    this.pollRssTransferStatus(data.job_id);
                } else {
                    this.rssIsTransferring = false;
                    this.showToast(data.detail || 'تعذر إطلاق النقل.', 'error');
                }
            } catch (e) {
                this.rssIsTransferring = false;
                this.showToast(`خطأ في الاتصال: ${e.message}`, 'error');
            }
        },

        pollRssTransferStatus(jobId) {
            if (this.rssPollTimer) clearInterval(this.rssPollTimer);
            this.rssPollTimer = setInterval(async () => {
                try {
                    const res = await fetch(`/api/v1/status/${jobId}`);
                    if (res.ok) {
                        const data = await res.json();
                        this.rssLogs = data.logs || [];
                        this.rssJobProgress = data.progress || 0;
                        if (data.completed) {
                            this.rssIsTransferring = false;
                            clearInterval(this.rssPollTimer);
                            this.rssPollTimer = null;
                            this.showToast('اكتملت مهمة نقل الموارد بنجاح!', 'success');
                        }
                    }
                } catch (e) {}
            }, 1500);
        },

        async stopRssTransfer() {
            if (!this.rssJobId) return;
            try {
                await fetch(`/api/v1/stop/${this.rssJobId}`, { method: 'POST' });
                this.rssIsTransferring = false;
                if (this.rssPollTimer) clearInterval(this.rssPollTimer);
                this.rssLogs.push(`[${new Date().toLocaleTimeString()}] 🛑 تم إيقاف النقل.`);
                this.showToast('تم إيقاف النقل واستئناف الجدولة.', 'info');
            } catch (e) {}
        },

        // --- Toasts ---
        showToast(message, type = 'info') {
            const id = Date.now();
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 4500);
        }
    }));
});
