# دليل دمج واجهة GhostBot مع البرنامج الخاص (Host Program Integration Guide)

تحتوي هذه الحزمة على نسختين جاهزتين للإرسال والدمج الفوري داخل برنامج البوت الخاص بك (سواء كان مبنياً بلغة **C# WPF / WinForms WebView2**، أو **Python PyQt / PyWebView**، أو **Electron / Node.js**):

1. **`GhostBot-Standalone-SingleFile.html` (موصى به للدمج داخل البرامج)**:
   - ملف HTML واحد مستقل 100% (مدمج بداخله الخلفية `kingdom-bg.jpg` والشعار والأيقونات والـ CSS والـ JS بصيغة Base64).
   - يمكنك إرساله كملف واحد أو تحميله مباشرة داخل `WebView2` بدون الحاجة لأي مجلدات صور خارجية.
2. **`index.html` + الصور (`kingdom-bg.jpg`, `ghostbot-logo.png`)**:
   - النسخة القياسية المفصولة للرفع على استضافة ويب أو خادم محلي.

---

## الجسر البرمجي المدمج (`window.GhostBotAPI`)

تم تجهيز الواجهة بجسر برمجي جاهز (`window.GhostBotAPI`) يمكنك استدعاؤه مباشرة من كود البرنامج (C# / Python / JS) لتحديث البيانات الحية في الواجهة:

### 1. إرسال سطور سجل العمليات المباشر (Live Telemetry Console)
```javascript
window.GhostBotAPI.log("[BOT-CORE] Connected to Governor #234166259 — Gathering Food...");
```

### 2. إرسال إشعار فوري إلى مركز الإشعارات (`Notifications Bell`)
```javascript
window.GhostBotAPI.notify(
  "تم تفعيل درع الحماية",
  "Peace Shield Activated",
  "تم رصد استطلاع معادٍ وتفعيل درع 8 ساعات تلقائياً.",
  "Hostile scout detected; 8h shield deployed."
);
```

### 3. تحديث عدادات الموارد الحية (`Food, Wood, Stone, Gold, Gems`)
```javascript
window.GhostBotAPI.setResources({
  food: 14.8,
  wood: 12.4,
  stone: 8.5,
  gold: 3.2,
  gems: 1450
});
```

### 4. تغيير حالة تشغيل الوحدة (`RUNNING / STANDBY`)
```javascript
window.GhostBotAPI.setBotRunning(true); // أو false للإيقاف
```

### 5. قراءة الإعدادات التي اختارها المستخدم (`7-Category Config`)
```javascript
const currentSettings = window.GhostBotAPI.getConfig();
```

---

## أمثلة الربط السريع مع البرنامج (Desktop Integration)

### أ) في برامج C# (WPF / WinForms — Microsoft WebView2)
```csharp
// تحميل الملف المدمج المستقل
webView.Source = new Uri(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "GhostBot-Standalone-SingleFile.html"));

// إرسال سطر سجل أو تحديث موارد من C# إلى الواجهة:
await webView.ExecuteScriptAsync("window.GhostBotAPI.log('[C#-CORE] Bot Engine Initialized.');");
await webView.ExecuteScriptAsync("window.GhostBotAPI.setResources({ food: 25.4, wood: 19.1, stone: 11.2, gold: 4.8, gems: 920 });");
```

### ب) في برامج Python (`pywebview` أو `PyQt6 QWebEngineView`)
```python
import webview

window = webview.create_window('GhostBot Tactical Controller', 'GhostBot-Standalone-SingleFile.html', width=1400, height=880)

def on_loaded():
    window.evaluate_js("window.GhostBotAPI.log('[PYTHON-ENGINE] Stealth Wire Ready.');")

webview.start(on_loaded)
```
