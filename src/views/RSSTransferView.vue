<template>
  <div class="arcane-clean-theme">
    <!-- Top Header Navigation -->
    <header class="clean-navbar">
      <div class="nav-title">
        <span class="icon-caravan">🚚</span>
        <div>
          <h1>مركز إمداد ونقل الموارد</h1>
          <p class="nav-sub">إدارة القوافل المتزامنة والمراقبة اللحظية للعمليات</p>
        </div>
      </div>
      <router-link to="/dashboard" class="nav-exit-btn">← العودة للوحة الرئيسية</router-link>
    </header>

    <!-- LIVE MONITORING VIEW (When Job is Active or Finished) -->
    <main v-if="activeJob" class="monitor-surface">
      <!-- Order Status Summary Strip -->
      <section class="order-summary-strip">
        <div class="summary-left">
          <div class="order-id">مهمة الإمداد رقم #{{ activeJob.job_id }}</div>
          <div class="order-destination">
            المستلم: <strong>الحاكم {{ activeJob.target_role_id }}</strong> | الإحداثيات: ({{ activeJob.x }}, {{ activeJob.y }})
          </div>
        </div>

        <div class="summary-right">
          <!-- Dynamic Status Badge -->
          <span 
            class="status-indicator-badge"
            :class="getStatusClass(activeJob.status)"
          >
            {{ getStatusArabic(activeJob.status) }}
          </span>

          <button 
            v-if="activeJob.status === 'RUNNING'" 
            class="btn-stop-danger" 
            @click="cancelTransferJob"
          >
            إلغاء العملية فوراً
          </button>
        </div>
      </section>

      <!-- Warning/Note Box if Partial or Cancelled -->
      <div v-if="activeJob.status === 'PARTIAL'" class="alert-box warning">
        ⚠️ <strong>اكتمل الإمداد جزئياً:</strong> نفدت الموارد الآمنة في بعض المزارع قبل اكتمال كامل الطلب.
      </div>
      <div v-if="activeJob.status === 'CANCELLED'" class="alert-box danger">
        🛑 <strong>تم إلغاء المهمة:</strong> أوقف المستخدم العملية يدوياً وتم سحب جميع القوافل.
      </div>

      <!-- Hydraulic Live Progress Bars -->
      <section class="hydraulic-container">
        <div v-for="res in ['food', 'wood', 'stone', 'gold']" :key="res" class="hydraulic-item">
          <div class="hydraulic-top">
            <span class="res-badge" :class="res">
              <img :src="`/images/Item_${res.charAt(0).toUpperCase() + res.slice(1)}.webp`" class="mini-res-icon" :alt="res" />
              {{ getResArabicName(res) }}
            </span>
            <span class="res-metric-txt">
              {{ formatMillions(activeJob.delivered?.[res]) }}M / {{ formatMillions(activeJob.requested?.[res]) }}M 
              <span class="percent-tag">({{ getPercent(activeJob.delivered?.[res], activeJob.requested?.[res]) }}%)</span>
            </span>
          </div>

          <div class="hydraulic-groove">
            <div 
              class="hydraulic-fill-fluid" 
              :class="res" 
              :style="{ width: getPercent(activeJob.delivered?.[res], activeJob.requested?.[res]) + '%' }"
            ></div>
          </div>
        </div>
      </section>

      <!-- Clean Worker Ledger List (No Developer Opcodes) -->
      <section class="worker-ledger-clean">
        <div class="ledger-title-row">
          <span>حالة المزارع المشاركة في الإمداد</span>
          <span class="counter">{{ activeJob.workers ? activeJob.workers.length : 0 }} مزرعة</span>
        </div>

        <div class="worker-flow-list">
          <div 
            v-for="worker in (activeJob.workers || [])" 
            :key="worker.role_id" 
            class="worker-row-clean"
            :class="{ active: worker.status === 'WORKING' }"
          >
            <div class="w-identity">
              <span class="w-name">{{ worker.name }}</span>
              <span class="w-stage">{{ worker.stage_msg }}</span>
            </div>

            <div class="w-specs">
              <span class="market-pill">سوق لفل {{ worker.market_lvl || 17 }} | ضريبة {{ worker.tax_rate || 19 }}%</span>
            </div>

            <div class="w-output">
              <span class="sent-lbl">الكمية المشحونة:</span>
              <strong>{{ formatShortNum(worker.sent_amount) }}</strong>
            </div>

            <div class="w-state">
              <span class="pill-state" :class="(worker.status || '').toLowerCase()">
                {{ getWorkerStatusArabic(worker.status) }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <div class="actions-bottom">
        <button class="btn-new-order" @click="resetToCreateView">إعداد طلب نقل جديد</button>
      </div>
    </main>

    <!-- CONFIGURATION VIEW (When No Job is Active) -->
    <main v-else class="config-surface">
      <!-- Section 1: Recipient Details -->
      <section class="config-section">
        <div class="section-heading">بيانات المستلم (Recipient Details)</div>
        <p class="section-hint">أدخل معرّف الحاكم المستلم وإحداثيات مملكته لنقل الموارد إليها مباشرة.</p>
        <div class="input-inline-group">
          <input 
            type="text" 
            v-model="order.target_role_id" 
            placeholder="معرّف الحاكم (Governor ID)" 
            class="clean-input wide" 
          />
          <div class="coord-inputs">
            <span class="coord-label">X:</span>
            <input type="number" v-model.number="order.x" placeholder="X" class="clean-input sm" />
            <span class="coord-label">Y:</span>
            <input type="number" v-model.number="order.y" placeholder="Y" class="clean-input sm" />
          </div>
        </div>
      </section>

      <!-- Section 2: Resource Demand Inputs -->
      <section class="config-section">
        <div class="section-heading">الموارد المطلوبة (الصافي المستلم)</div>
        <p class="section-hint">يتم احتساب الضريبة تلقائياً بناءً على مستوى السوق لكل مزرعة وإضافتها على الكمية المرسلة.</p>
        
        <div class="rss-strip-grid">
          <div v-for="res in ['food', 'wood', 'stone', 'gold']" :key="res" class="rss-strip">
            <div class="rss-type">
              <img :src="`/images/Item_${res.charAt(0).toUpperCase() + res.slice(1)}.webp`" class="res-img-icon" :alt="res" />
              <span class="res-name">{{ getResArabicName(res) }}</span>
            </div>
            <div class="rss-value-box">
              <input 
                type="number" 
                v-model.number="order.requested_rss[res]" 
                placeholder="0" 
                class="clean-input-rss" 
              />
              <span class="calc-tax-tag">المخصوم التقريبي: {{ getGrossFormatted(order.requested_rss[res]) }}</span>
            </div>
            <button class="btn-max-pill" @click="setMaxAvailable(res)">MAX</button>
          </div>
        </div>
      </section>

      <!-- Section 3: Farm Selection -->
      <section class="config-section">
        <div class="farms-header-row">
          <div>
            <div class="section-heading">المزارع المشاركة في الإمداد ({{ order.selected_farm_roles.length }}/{{ availableFarms.length }})</div>
            <p class="section-hint">حدد المزارع التي ترغب في الإرسال منها. سيتم تسيير القوافل بشكل متزامن وآمن.</p>
          </div>
          <div class="bulk-select-buttons">
            <button class="btn-text-action" @click="selectAllFarms(true)">تحديد الكل</button>
            <span class="divider">/</span>
            <button class="btn-text-action" @click="selectAllFarms(false)">إلغاء التحديد</button>
          </div>
        </div>

        <div class="farms-flat-list">
          <div 
            v-for="farm in availableFarms" 
            :key="farm.role_id" 
            class="farm-flat-item"
            :class="{ selected: isFarmSelected(farm.role_id) }"
            @click="toggleFarm(farm.role_id)"
          >
            <div class="farm-checkbox">
              <span class="custom-chk" :class="{ checked: isFarmSelected(farm.role_id) }"></span>
            </div>
            <div class="farm-meta-text">
              <span class="farm-name">{{ farm.name }}</span>
              <span class="farm-tag">[{{ farm.alliance_tag || 'No Ally' }}] • سوق لفل {{ farm.city_level || 17 }} ({{ farm.tax_rate || 19 }}%)</span>
            </div>
            <div class="farm-rss-pill-group">
              <span class="pill"><img src="/images/Item_Food.webp" class="mini-icon" alt="food" /> {{ formatShort(farm.resources?.food) }}</span>
              <span class="pill"><img src="/images/Item_Wood.webp" class="mini-icon" alt="wood" /> {{ formatShort(farm.resources?.wood) }}</span>
              <span class="pill"><img src="/images/Item_Stone.webp" class="mini-icon" alt="stone" /> {{ formatShort(farm.resources?.stone) }}</span>
              <span class="pill"><img src="/images/Item_Gold.webp" class="mini-icon" alt="gold" /> {{ formatShort(farm.resources?.gold) }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Launch Action Button -->
      <div class="action-dock">
        <button 
          class="btn-clean-launch" 
          :disabled="isLaunching || order.selected_farm_roles.length === 0" 
          @click="startExecution"
        >
          <span class="launch-icon">🚀</span>
          بدء تسيير قوافل الإمداد
        </button>
      </div>
    </main>
  </div>
</template>

<script>
import axios from 'axios';
import { getDatabase, ref, onValue } from 'firebase/database';

export default {
  data() {
    return {
      activeJob: null,
      isLaunching: false,
      availableFarms: [],
      telemetryPollTimer: null,
      order: {
        target_role_id: '',
        x: 419,
        y: 513,
        requested_rss: { food: 0, wood: 0, stone: 0, gold: 0 },
        selected_farm_roles: []
      }
    };
  },
  mounted() {
    this.fetchFarms();
  },
  beforeUnmount() {
    if (this.telemetryPollTimer) {
      clearInterval(this.telemetryPollTimer);
    }
  },
  methods: {
    formatMillions(val) {
      if (!val) return '0.00';
      return (val / 1000000).toFixed(2);
    },
    formatShortNum(val) {
      if (!val) return '0';
      if (val >= 1000000000) return (val / 1000000000).toFixed(2) + 'B';
      if (val >= 1000000) return (val / 1000000).toFixed(1) + 'M';
      if (val >= 1000) return (val / 1000).toFixed(0) + 'K';
      return val.toLocaleString();
    },
    formatShort(val) {
      return this.formatShortNum(val);
    },
    getPercent(cur, max) {
      if (!max || max <= 0) return 0;
      return Math.min(100, Math.round(((cur || 0) / max) * 100));
    },
    getResArabicName(res) {
      const map = {
        food: 'طعام (Food)',
        wood: 'خشب (Wood)',
        stone: 'حجر (Stone)',
        gold: 'ذهب (Gold)'
      };
      return map[res] || res;
    },
    getStatusArabic(status) {
      const map = {
        RUNNING: 'جاري النقل والتحميل...',
        COMPLETED: 'اكتمل الإمداد بنجاح',
        PARTIAL: 'اكتمل جزئياً',
        CANCELLED: 'تم الإلغاء',
        FAILED: 'فشل النقل'
      };
      return map[status] || status;
    },
    getStatusClass(status) {
      return status ? status.toLowerCase() : 'running';
    },
    getWorkerStatusArabic(status) {
      const map = {
        WORKING: 'قيد الشحن',
        RUNNING: 'قيد الشحن',
        WAITING: 'بانتظار التأمين',
        COMPLETED: 'تم الانتهاء',
        DRAINED: 'تم الانتهاء',
        SKIPPED: 'مكتمل الحصة',
        STOPPED: 'متوقف',
        FAILED: 'متوقف'
      };
      return map[status] || status;
    },
    getGrossFormatted(net) {
      if (!net || net <= 0) return '0';
      return Math.ceil(net / (1 - 0.19)).toLocaleString();
    },
    isFarmSelected(id) {
      return this.order.selected_farm_roles.includes(id);
    },
    toggleFarm(id) {
      const idx = this.order.selected_farm_roles.indexOf(id);
      if (idx > -1) this.order.selected_farm_roles.splice(idx, 1);
      else this.order.selected_farm_roles.push(id);
    },
    selectAllFarms(status) {
      if (status) {
        this.order.selected_farm_roles = this.availableFarms.map(f => f.role_id);
      } else {
        this.order.selected_farm_roles = [];
      }
    },
    setMaxAvailable(res) {
      const totalAvailable = this.availableFarms
        .filter(f => this.isFarmSelected(f.role_id))
        .reduce((sum, f) => sum + (f.resources?.[res] || 0), 0);
      this.order.requested_rss[res] = Math.max(0, Math.floor(totalAvailable * 0.81));
    },
    async fetchFarms() {
      try {
        const res = await axios.get('/api/v1/characters/summary');
        this.availableFarms = res.data.characters || [];
        if (this.availableFarms.length > 0 && this.order.selected_farm_roles.length === 0) {
          this.order.selected_farm_roles = this.availableFarms.map(f => f.role_id);
        }
      } catch (err) {
        console.error("Failed to load farms", err);
      }
    },
    async startExecution() {
      this.isLaunching = true;
      try {
        const res = await axios.post('/api/v1/start-transfer', this.order);
        this.listenToJobTelemetry(res.data.job_id);
      } catch (err) {
        alert(err.response?.data?.detail || "فشل بدء مهمة نقل الموارد.");
        this.isLaunching = false;
      }
    },
    listenToJobTelemetry(jobId) {
      try {
        const db = getDatabase();
        const jobRef = ref(db, `transfer_telemetry/${jobId}`);
        onValue(jobRef, (snapshot) => {
          const val = snapshot.val();
          if (val) {
            this.activeJob = val;
          }
        });
      } catch (e) {
        console.debug("Firebase listener fallback to HTTP polling:", e);
      }

      // Safe HTTP Polling Fallback
      if (this.telemetryPollTimer) clearInterval(this.telemetryPollTimer);
      this.telemetryPollTimer = setInterval(async () => {
        try {
          const res = await axios.get(`/api/v1/transfer/${jobId}/status`);
          if (res.data) {
            this.activeJob = res.data;
            if (['COMPLETED', 'PARTIAL', 'CANCELLED', 'FAILED'].includes(res.data.status)) {
              clearInterval(this.telemetryPollTimer);
            }
          }
        } catch (err) {
          // ignore transient poll errors
        }
      }, 1500);
    },
    async cancelTransferJob() {
      if (this.activeJob) {
        await axios.post(`/api/v1/transfer/${this.activeJob.job_id}/cancel`);
      }
    },
    resetToCreateView() {
      if (this.telemetryPollTimer) {
        clearInterval(this.telemetryPollTimer);
      }
      this.activeJob = null;
      this.isLaunching = false;
      this.fetchFarms();
    }
  }
};
</script>

<style scoped>
.arcane-clean-theme {
  background: #080d1a;
  color: #e2e8f0;
  min-height: 100vh;
  padding: 30px 50px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  direction: rtl;
}

.clean-navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 20px;
  border-bottom: 1px solid rgba(56, 189, 248, 0.2);
  margin-bottom: 25px;
}

.nav-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.icon-caravan {
  font-size: 2rem;
}

.nav-title h1 {
  font-size: 1.6rem;
  margin: 0;
  color: #ffffff;
  font-weight: 700;
}

.nav-sub {
  margin: 0;
  font-size: 0.85rem;
  color: #94a3b8;
}

.nav-exit-btn {
  color: #38bdf8;
  text-decoration: none;
  font-weight: bold;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  background: rgba(56, 189, 248, 0.08);
  transition: all 0.2s ease;
}

.nav-exit-btn:hover {
  background: rgba(56, 189, 248, 0.18);
  color: #ffffff;
}

/* MONITOR SURFACE */
.monitor-surface, .config-surface {
  max-width: 1080px;
  margin: 0 auto;
}

.order-summary-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #0d172e;
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 18px 26px;
  border-radius: 12px;
  margin-bottom: 20px;
}

.order-id {
  font-size: 1.2rem;
  font-weight: bold;
  color: #ffffff;
}

.order-destination {
  font-size: 0.9rem;
  color: #94a3b8;
  margin-top: 4px;
}

.summary-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.status-indicator-badge {
  padding: 6px 16px;
  border-radius: 20px;
  font-weight: bold;
  font-size: 0.85rem;
}

.status-indicator-badge.running { background: #0284c7; color: #f0f9ff; }
.status-indicator-badge.completed { background: #059669; color: #ffffff; }
.status-indicator-badge.partial { background: #d97706; color: #ffffff; }
.status-indicator-badge.cancelled { background: #dc2626; color: #ffffff; }
.status-indicator-badge.failed { background: #dc2626; color: #ffffff; }

.btn-stop-danger {
  background: #dc2626;
  border: none;
  color: #ffffff;
  padding: 7px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: bold;
  transition: background 0.2s;
}

.btn-stop-danger:hover {
  background: #b91c1c;
}

.alert-box {
  padding: 14px 20px;
  border-radius: 10px;
  font-size: 0.9rem;
  margin-bottom: 20px;
}

.alert-box.warning {
  background: rgba(217, 119, 6, 0.15);
  border: 1px solid #d97706;
  color: #fde68a;
}

.alert-box.danger {
  background: rgba(220, 38, 38, 0.15);
  border: 1px solid #dc2626;
  color: #fca5a5;
}

/* Hydraulic Container */
.hydraulic-container {
  background: #0d172e;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-bottom: 25px;
}

.hydraulic-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.92rem;
  margin-bottom: 8px;
}

.res-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #f8fafc;
}

.mini-res-icon {
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.res-metric-txt {
  font-family: monospace;
  font-size: 0.92rem;
  font-weight: 600;
  color: #cbd5e1;
}

.percent-tag {
  color: #38bdf8;
  font-weight: bold;
}

.hydraulic-groove {
  width: 100%;
  height: 12px;
  background: #030712;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.hydraulic-fill-fluid {
  height: 100%;
  transition: width 0.4s ease-in-out;
}

.hydraulic-fill-fluid.food { background: linear-gradient(90deg, #ec4899, #f43f5e); }
.hydraulic-fill-fluid.wood { background: linear-gradient(90deg, #06b6d4, #3b82f6); }
.hydraulic-fill-fluid.stone { background: linear-gradient(90deg, #8b5cf6, #a855f7); }
.hydraulic-fill-fluid.gold { background: linear-gradient(90deg, #eab308, #f59e0b); }

/* Worker Ledger Clean */
.worker-ledger-clean {
  background: #0d172e;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 12px;
  padding: 22px;
}

.ledger-title-row {
  display: flex;
  justify-content: space-between;
  font-weight: bold;
  color: #e2e8f0;
  border-bottom: 1px solid rgba(56, 189, 248, 0.15);
  padding-bottom: 12px;
  margin-bottom: 14px;
}

.counter {
  color: #38bdf8;
}

.worker-flow-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.worker-row-clean {
  display: grid;
  grid-template-columns: 2fr 1.5fr 1.2fr 1fr;
  align-items: center;
  padding: 12px 16px;
  background: #070e1e;
  border: 1px solid rgba(56, 189, 248, 0.1);
  border-radius: 8px;
  transition: border-color 0.2s;
}

.worker-row-clean.active {
  border-color: #0284c7;
  background: #09142b;
}

.w-identity {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.w-name {
  font-weight: bold;
  color: #ffffff;
  font-size: 0.95rem;
}

.w-stage {
  font-size: 0.82rem;
  color: #38bdf8;
}

.market-pill {
  font-size: 0.8rem;
  background: rgba(56, 189, 248, 0.12);
  color: #bae6fd;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.w-output {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sent-lbl {
  font-size: 0.75rem;
  color: #94a3b8;
}

.w-output strong {
  color: #f8fafc;
  font-family: monospace;
}

.pill-state {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: bold;
  text-align: center;
}

.pill-state.working, .pill-state.running { background: rgba(2, 132, 199, 0.25); color: #38bdf8; border: 1px solid #0284c7; }
.pill-state.completed, .pill-state.drained { background: rgba(5, 150, 105, 0.25); color: #34d399; border: 1px solid #059669; }
.pill-state.waiting { background: rgba(217, 119, 6, 0.2); color: #fbbf24; border: 1px solid #d97706; }
.pill-state.skipped { background: rgba(51, 65, 85, 0.4); color: #94a3b8; border: 1px solid #334155; }
.pill-state.stopped, .pill-state.failed { background: rgba(220, 38, 38, 0.2); color: #f87171; border: 1px solid #dc2626; }

.actions-bottom {
  margin-top: 24px;
}

.btn-new-order {
  background: linear-gradient(135deg, #0284c7, #2563eb);
  border: none;
  color: #ffffff;
  padding: 12px 28px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-new-order:hover {
  opacity: 0.9;
}

/* CONFIGURATION STYLES */
.config-section {
  background: #0d172e;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 12px;
  padding: 22px;
  margin-bottom: 22px;
}

.section-heading {
  font-size: 1.15rem;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 4px;
}

.section-hint {
  font-size: 0.85rem;
  color: #94a3b8;
  margin-bottom: 16px;
}

.input-inline-group {
  display: flex;
  gap: 16px;
  align-items: center;
}

.coord-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
}

.coord-label {
  font-weight: bold;
  color: #38bdf8;
}

.clean-input {
  background: #070e1e;
  border: 1px solid #1e293b;
  color: #ffffff;
  padding: 10px 14px;
  border-radius: 8px;
  outline: none;
}

.clean-input.wide { width: 340px; }
.clean-input.sm { width: 90px; }

.rss-strip-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rss-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #070e1e;
  border: 1px solid rgba(56, 189, 248, 0.12);
  padding: 12px 20px;
  border-radius: 8px;
}

.rss-type {
  width: 160px;
  font-weight: 600;
  color: #f1f5f9;
  display: flex;
  align-items: center;
  gap: 12px;
}

.res-img-icon {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

.clean-input-rss {
  background: #040915;
  border: 1px solid #1e3a5f;
  color: #ffffff;
  padding: 8px 14px;
  border-radius: 6px;
  width: 220px;
}

.calc-tax-tag {
  margin-right: 14px;
  font-size: 0.8rem;
  color: #38bdf8;
}

.btn-max-pill {
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid #38bdf8;
  color: #38bdf8;
  padding: 6px 14px;
  border-radius: 20px;
  cursor: pointer;
  font-weight: 700;
}

.farms-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 12px;
}

.bulk-select-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-text-action {
  background: transparent;
  border: none;
  color: #38bdf8;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
}

.divider {
  color: #475569;
}

.farms-flat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow-y: auto;
}

.farm-flat-item {
  display: flex;
  align-items: center;
  background: #070e1e;
  border: 1px solid rgba(56, 189, 248, 0.12);
  padding: 10px 16px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.farm-flat-item.selected {
  border-color: #0284c7;
  background: #0a1838;
}

.farm-checkbox {
  margin-left: 14px;
}

.custom-chk {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 1px solid #38bdf8;
  border-radius: 4px;
}

.custom-chk.checked {
  background: #38bdf8;
}

.farm-meta-text {
  width: 280px;
  display: flex;
  flex-direction: column;
}

.farm-name {
  font-weight: 700;
  color: #ffffff;
}

.farm-tag {
  font-size: 0.75rem;
  color: #94a3b8;
}

.farm-rss-pill-group {
  display: flex;
  gap: 10px;
  font-size: 0.85rem;
  margin-right: auto;
}

.pill {
  background: rgba(15, 23, 42, 0.8);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #1e293b;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #cbd5e1;
  font-family: monospace;
}

.mini-icon {
  width: 16px;
  height: 16px;
  object-fit: contain;
}

.action-dock {
  margin-top: 24px;
}

.btn-clean-launch {
  width: 100%;
  padding: 16px;
  background: linear-gradient(135deg, #0284c7, #2563eb);
  border: 1px solid #38bdf8;
  border-radius: 10px;
  color: #ffffff;
  font-size: 1.15rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  transition: opacity 0.2s;
}

.btn-clean-launch:hover:not(:disabled) {
  opacity: 0.92;
}

.btn-clean-launch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.launch-icon {
  font-size: 1.3rem;
}
</style>
