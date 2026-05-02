(function () {
  const messagesEl = document.getElementById('messages');
  const form = document.getElementById('form');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const chatFileInput = document.getElementById('chat-file-input');
  const chatAttachChips = document.getElementById('chat-attach-chips');
  const chatAttachBtn = document.getElementById('chat-attach');
  const chatAttachStatus = document.getElementById('chat-attach-status');
  const pricesList = document.getElementById('prices-list');
  const pricesUpdated = document.getElementById('prices-updated');
  const pricesError = document.getElementById('prices-error');
  const newsList = document.getElementById('news-list');
  const newsUpdated = document.getElementById('news-updated');
  const newsError = document.getElementById('news-error');
  const pricesEditToggle = document.getElementById('prices-edit-toggle');
  const pricesEditor = document.getElementById('prices-editor');
  const pricesEditorRows = document.getElementById('prices-editor-rows');
  const pricesPresetSelect = document.getElementById('prices-preset-select');
  const pricesAddPreset = document.getElementById('prices-add-preset');
  const pricesCustomId = document.getElementById('prices-custom-id');
  const pricesCustomSym = document.getElementById('prices-custom-sym');
  const pricesAddCustom = document.getElementById('prices-add-custom');
  const pricesResetDefault = document.getElementById('prices-reset-default');
  const alertsCoinSelect = document.getElementById('alerts-coin-select');
  const alertsTypeSelect = document.getElementById('alerts-type-select');
  const alertsThresholdInput = document.getElementById('alerts-threshold-input');
  const alertsWindowInput = document.getElementById('alerts-window-input');
  const alertsAddBtn = document.getElementById('alerts-add-btn');
  const alertsList = document.getElementById('alerts-list');
  const alertsStatus = document.getElementById('alerts-status');
  const alertsNotifyBtn = document.getElementById('alerts-notify-btn');
  const alertsSoundChk = document.getElementById('alerts-sound');
  const alertsHistoryEl = document.getElementById('alerts-history');
  const alertsHistoryClear = document.getElementById('alerts-history-clear');
  const alertsPresetsEl = document.querySelector('.alerts-presets');
  const oilList = document.getElementById('oil-list');
  const oilUpdated = document.getElementById('oil-updated');
  const oilError = document.getElementById('oil-error');
  const fedList = document.getElementById('fed-list');
  const fedUpdated = document.getElementById('fed-updated');
  const fedError = document.getElementById('fed-error');
  const themeLightBtn = document.getElementById('theme-light');
  const themeDarkBtn = document.getElementById('theme-dark');

  const PRICE_STORAGE_KEY = 'cryptochatpal_price_rows';
  const PRICE_ALERTS_KEY = 'cryptochatpal_price_alerts';
  const PRICE_ALERTS_SOUND_KEY = 'cryptochatpal_alerts_sound';
  const PRICE_ALERT_LOG_KEY = 'cryptochatpal_price_alert_log';
  const THEME_KEY = 'cryptochatpal_theme';
  /** Optional SaaS API key (set via localStorage when server uses CCP_AUTH_MODE=required). */
  const CCP_API_KEY_STORAGE = 'ccp_api_key';

  function ccpApiAuthHeaders() {
    const h = {};
    try {
      const k = localStorage.getItem(CCP_API_KEY_STORAGE);
      if (k && String(k).trim()) h['X-CCP-API-Key'] = String(k).trim();
    } catch (e) {
      /* ignore */
    }
    return h;
  }

  function getTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function syncThemeButtons() {
    const light = getTheme() === 'light';
    if (themeLightBtn) {
      themeLightBtn.classList.toggle('theme-btn--active', light);
      themeLightBtn.setAttribute('aria-pressed', light ? 'true' : 'false');
    }
    if (themeDarkBtn) {
      themeDarkBtn.classList.toggle('theme-btn--active', !light);
      themeDarkBtn.setAttribute('aria-pressed', !light ? 'true' : 'false');
    }
  }

  function applyTheme(mode) {
    if (mode === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch (e) {}
    syncThemeButtons();
  }

  if (themeLightBtn) themeLightBtn.addEventListener('click', () => applyTheme('light'));
  if (themeDarkBtn) themeDarkBtn.addEventListener('click', () => applyTheme('dark'));
  syncThemeButtons();

  const MAX_PRICE_ROWS = 30;

  const ATTACH_MAX_FILES = 5;
  const ATTACH_MAX_BYTES = 256 * 1024;
  const ATTACH_NAME_RE = /\.(md|txt|csv|json|log)$/i;

  let pendingAttachments = [];

  function isAllowedTextFile(file) {
    if (ATTACH_NAME_RE.test(file.name)) return true;
    const t = (file.type || '').toLowerCase();
    return t.startsWith('text/') || t === 'application/json';
  }

  function uniqueAttachName(name) {
    const names = new Set(pendingAttachments.map((a) => a.name));
    if (!names.has(name)) return name;
    const m = name.match(/^(.+)(\.[^.]+)$/);
    const base = m ? m[1] : name;
    const ext = m ? m[2] : '';
    let n = 2;
    let candidate = `${base} (${n})${ext}`;
    while (names.has(candidate)) {
      n += 1;
      candidate = `${base} (${n})${ext}`;
    }
    return candidate;
  }

  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result || ''));
      r.onerror = () => reject(new Error('read failed'));
      r.readAsText(file);
    });
  }

  function mergeAttachmentsForApi(text, attachments) {
    const parts = [];
    const t = text.trim();
    if (t) parts.push(t);
    if (attachments.length) {
      parts.push('--- Attached files ---');
      for (const a of attachments) {
        parts.push(`### ${a.name}\n${a.content}`);
      }
    }
    return parts.join('\n\n');
  }

  function setAttachStatus(msg) {
    if (!chatAttachStatus) return;
    if (!msg) {
      chatAttachStatus.textContent = '';
      chatAttachStatus.classList.add('visually-hidden');
    } else {
      chatAttachStatus.textContent = msg;
      chatAttachStatus.classList.remove('visually-hidden');
    }
  }

  function renderAttachChips() {
    if (!chatAttachChips) return;
    chatAttachChips.innerHTML = '';
    pendingAttachments.forEach((a) => {
      const wrap = document.createElement('span');
      wrap.className = 'chat-attach-chip';
      const label = document.createElement('span');
      label.textContent = a.name;
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.setAttribute('aria-label', `Remove ${a.name}`);
      rm.textContent = '×';
      rm.addEventListener('click', () => {
        pendingAttachments = pendingAttachments.filter((x) => x.name !== a.name);
        renderAttachChips();
      });
      wrap.appendChild(label);
      wrap.appendChild(rm);
      chatAttachChips.appendChild(wrap);
    });
    if (pendingAttachments.length) chatAttachChips.classList.remove('hidden');
    else chatAttachChips.classList.add('hidden');
  }

  async function handleFilesSelected(fileList) {
    setAttachStatus('');
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const errors = [];
    for (const file of files) {
      if (pendingAttachments.length >= ATTACH_MAX_FILES) {
        errors.push(`At most ${ATTACH_MAX_FILES} files.`);
        break;
      }
      if (!isAllowedTextFile(file)) {
        errors.push(`Skipped (not a supported text file): ${file.name}`);
        continue;
      }
      if (file.size > ATTACH_MAX_BYTES) {
        errors.push(`Too large (max ${ATTACH_MAX_BYTES / 1024} KB): ${file.name}`);
        continue;
      }
      try {
        const content = await readFileAsText(file);
        pendingAttachments.push({ name: uniqueAttachName(file.name), content });
      } catch {
        errors.push(`Could not read: ${file.name}`);
      }
    }
    if (errors.length) setAttachStatus(errors[0]);
    renderAttachChips();
    if (chatFileInput) chatFileInput.value = '';
  }

  const DEFAULT_PRICE_ROWS = [
    { id: 'bitcoin', sym: 'BTC' },
    { id: 'ethereum', sym: 'ETH' },
    { id: 'solana', sym: 'SOL' },
    { id: 'ripple', sym: 'XRP' },
    { id: 'cardano', sym: 'ADA' },
    { id: 'binancecoin', sym: 'BNB' },
    { id: 'dogecoin', sym: 'DOGE' },
    { id: 'polkadot', sym: 'DOT' },
    { id: 'sui', sym: 'SUI' },
  ];

  const COIN_PRESETS = [
    { id: 'bitcoin', sym: 'BTC' },
    { id: 'ethereum', sym: 'ETH' },
    { id: 'solana', sym: 'SOL' },
    { id: 'ripple', sym: 'XRP' },
    { id: 'cardano', sym: 'ADA' },
    { id: 'binancecoin', sym: 'BNB' },
    { id: 'dogecoin', sym: 'DOGE' },
    { id: 'polkadot', sym: 'DOT' },
    { id: 'sui', sym: 'SUI' },
    { id: 'chainlink', sym: 'LINK' },
    { id: 'avalanche-2', sym: 'AVAX' },
    { id: 'matic-network', sym: 'MATIC' },
    { id: 'litecoin', sym: 'LTC' },
    { id: 'uniswap', sym: 'UNI' },
    { id: 'cosmos', sym: 'ATOM' },
    { id: 'near', sym: 'NEAR' },
    { id: 'aptos', sym: 'APT' },
    { id: 'arbitrum', sym: 'ARB' },
    { id: 'optimism', sym: 'OP' },
    { id: 'stellar', sym: 'XLM' },
    { id: 'monero', sym: 'XMR' },
    { id: 'tron', sym: 'TRX' },
    { id: 'shiba-inu', sym: 'SHIB' },
    { id: 'internet-computer', sym: 'ICP' },
    { id: 'filecoin', sym: 'FIL' },
    { id: 'hedera-hashgraph', sym: 'HBAR' },
    { id: 'render-token', sym: 'RNDR' },
    { id: 'immutable-x', sym: 'IMX' },
    { id: 'the-graph', sym: 'GRT' },
    { id: 'maker', sym: 'MKR' },
  ];

  /** Extra lowercase phrases to match RSS text to a CoinGecko id (beyond ticker + id segments). */
  const COIN_NEWS_EXTRA = {
    bitcoin: ['bitcoin', 'btc', 'satoshi'],
    ethereum: ['ethereum', 'ether', 'eth '],
    solana: ['solana'],
    ripple: ['ripple', 'xrp'],
    cardano: ['cardano', 'ada '],
    dogecoin: ['dogecoin', 'doge'],
    'matic-network': ['polygon', 'matic'],
    'avalanche-2': ['avalanche', 'avax'],
    sui: [' sui '],
    chainlink: ['chainlink', 'link '],
    polkadot: ['polkadot', 'dot '],
    binancecoin: ['bnb', 'binance'],
    'shiba-inu': ['shiba', 'shib'],
    litecoin: ['litecoin', 'ltc'],
    uniswap: ['uniswap', 'uni '],
    cosmos: ['cosmos', 'atom '],
    near: ['near protocol', 'near '],
    aptos: ['aptos'],
    arbitrum: ['arbitrum', 'arb '],
    optimism: ['optimism', 'op '],
    stellar: ['stellar', 'xlm'],
    monero: ['monero', 'xmr'],
    tron: ['tron', 'trx'],
    'internet-computer': ['internet computer', 'icp '],
    filecoin: ['filecoin', 'fil '],
    'hedera-hashgraph': ['hedera', 'hbar'],
    'render-token': ['render', 'rndr'],
    'immutable-x': ['immutable', 'imx'],
    'the-graph': ['the graph', 'grt'],
    maker: ['maker', 'mkr'],
  };

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function sanitizeCoinId(s) {
    return String(s)
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, '')
      .slice(0, 64);
  }

  function sanitizeSym(s) {
    return String(s)
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9.$-]/g, '')
      .slice(0, 12);
  }

  function loadPriceRows() {
    try {
      const raw = localStorage.getItem(PRICE_STORAGE_KEY);
      if (!raw) return DEFAULT_PRICE_ROWS.map((r) => ({ ...r }));
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr) || !arr.length) return DEFAULT_PRICE_ROWS.map((r) => ({ ...r }));
      const cleaned = [];
      const seen = new Set();
      for (const x of arr) {
        const id = sanitizeCoinId(x.id || '');
        const sym = sanitizeSym(x.sym || '') || id.slice(0, 12).toUpperCase();
        if (!id || seen.has(id)) continue;
        seen.add(id);
        cleaned.push({ id, sym });
      }
      if (!cleaned.length) return DEFAULT_PRICE_ROWS.map((r) => ({ ...r }));
      return cleaned.slice(0, MAX_PRICE_ROWS);
    } catch {
      return DEFAULT_PRICE_ROWS.map((r) => ({ ...r }));
    }
  }

  function savePriceRows(rows) {
    try {
      localStorage.setItem(PRICE_STORAGE_KEY, JSON.stringify(rows));
    } catch {
      /* ignore quota */
    }
  }

  let priceRows = loadPriceRows();

  const PORTFOLIO_STORAGE_KEY = 'cryptochatpal_portfolio';
  const MAX_PORTFOLIO_ROWS = 24;

  function sanitizeAmount(v) {
    const n = parseFloat(String(v).replace(/,/g, ''));
    if (!Number.isFinite(n) || n < 0) return 0;
    return Math.min(n, 1e15);
  }

  function sanitizeAvgUsdField(v) {
    if (v == null || String(v).trim() === '') return null;
    const n = parseFloat(String(v).replace(/,/g, ''));
    if (!Number.isFinite(n) || n < 0) return null;
    return Math.round(n * 1e6) / 1e6;
  }

  function loadPortfolio() {
    try {
      const raw = localStorage.getItem(PORTFOLIO_STORAGE_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      const out = [];
      const seen = new Set();
      for (const x of arr) {
        const id = sanitizeCoinId(x.id || '');
        const sym = sanitizeSym(x.sym || '') || id.slice(0, 12).toUpperCase();
        if (!id || seen.has(id)) continue;
        seen.add(id);
        const avgRaw = x.avg;
        let avg = null;
        if (avgRaw !== undefined && avgRaw !== null && String(avgRaw).trim() !== '') {
          avg = sanitizeAvgUsdField(avgRaw);
        }
        out.push({
          id,
          sym,
          amount: sanitizeAmount(x.amount),
          avg,
        });
      }
      return out.slice(0, MAX_PORTFOLIO_ROWS);
    } catch {
      return [];
    }
  }

  function savePortfolio() {
    try {
      localStorage.setItem(PORTFOLIO_STORAGE_KEY, JSON.stringify(portfolioRows));
    } catch (e) {
      /* ignore quota */
    }
  }

  let portfolioRows = loadPortfolio();

  let lastPricesPayload = {};
  let lastRenderKey = '';
  let lastNewsItems = [];

  let liveFeedMode = 'connecting';
  let liveWs = null;
  let liveWsBackoffMs = 2000;
  const liveFeedStatusEl = document.getElementById('live-feed-status');

  const STANCE_LEDGER_KEY = 'cryptochatpal_stance_ledger';
  const MAX_STANCE_ENTRIES = 24;

  function loadStanceLedger() {
    try {
      const raw = localStorage.getItem(STANCE_LEDGER_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr
        .filter((x) => x && typeof x === 'object' && typeof x.t === 'number')
        .slice(0, MAX_STANCE_ENTRIES);
    } catch {
      return [];
    }
  }

  function saveStanceLedger() {
    try {
      localStorage.setItem(STANCE_LEDGER_KEY, JSON.stringify(stanceLedger.slice(0, MAX_STANCE_ENTRIES)));
    } catch {
      /* ignore */
    }
  }

  let stanceLedger = loadStanceLedger();

  function parseStanceFromReply(text) {
    if (!text || typeof text !== 'string') return null;
    const viewM = text.match(/(?:^|\n)\s*[-•*]?\s*View:\s*(.+?)(?:\n|$)/im);
    const confM = text.match(/(?:^|\n)\s*[-•*]?\s*Confidence:\s*(\d+)\s*%?/im);
    const scoreM = text.match(/(?:^|\n)\s*[-•*]?\s*Score:\s*(\d+)/im);
    if (!viewM && !confM && !scoreM) return null;
    return {
      view: viewM ? viewM[1].trim().slice(0, 120) : '',
      confidence: confM ? confM[1] : '',
      score: scoreM ? scoreM[1] : '',
    };
  }

  function maybeCaptureStance(reply) {
    const parsed = parseStanceFromReply(reply);
    if (!parsed) return;
    stanceLedger.unshift({
      t: Date.now(),
      view: parsed.view,
      confidence: parsed.confidence,
      score: parsed.score,
    });
    stanceLedger = stanceLedger.slice(0, MAX_STANCE_ENTRIES);
    saveStanceLedger();
    updateSessionDeskUI();
  }

  function maybeCaptureStanceFromTrade(trade) {
    if (!trade || typeof trade !== 'object') return;
    const view = trade.view != null ? String(trade.view).trim().slice(0, 120) : '';
    if (!view && trade.confidence == null && trade.score_total == null) return;
    stanceLedger.unshift({
      t: Date.now(),
      view,
      confidence: trade.confidence != null ? String(trade.confidence) : '',
      score: trade.score_total != null ? String(trade.score_total) : '',
    });
    stanceLedger = stanceLedger.slice(0, MAX_STANCE_ENTRIES);
    saveStanceLedger();
    updateSessionDeskUI();
  }

  function renderTradeCard(botDiv, trade) {
    if (!trade || typeof trade !== 'object') return;
    let card = botDiv.querySelector('.trade-card');
    if (!card) {
      card = document.createElement('div');
      card.className = 'trade-card';
      const content = botDiv.querySelector('.content');
      if (content) botDiv.insertBefore(card, content);
      else botDiv.appendChild(card);
    }
    const v = (x) => (x == null || x === '' ? '—' : String(x));
    const risks = Array.isArray(trade.key_risks) ? trade.key_risks.slice(0, 6) : [];
    const riskHtml = risks.length
      ? `<ul class="trade-card-risks">${risks.map((r) => `<li>${escapeHtml(String(r))}</li>`).join('')}</ul>`
      : '';
    const scores =
      trade.score_total != null
        ? `<div class="trade-card-scores">Total <strong>${escapeHtml(String(trade.score_total))}</strong> · Trend ${escapeHtml(v(trade.score_trend))} · News ${escapeHtml(v(trade.score_news))} · R:R ${escapeHtml(v(trade.score_rr))} · Regime ${escapeHtml(v(trade.score_regime))}</div>`
        : '';
    const tf =
      trade.timeframe != null && String(trade.timeframe).trim()
        ? `<div class="trade-card-tf">${escapeHtml(String(trade.timeframe).trim())}</div>`
        : '';
    card.innerHTML = `
      <div class="trade-card-head">Trade snapshot</div>
      <div class="trade-card-view">${escapeHtml(v(trade.view))}</div>
      <div class="trade-card-meta">Confidence <strong>${escapeHtml(v(trade.confidence))}</strong>%</div>
      ${tf}
      ${scores}
      ${trade.thesis ? `<div class="trade-card-thesis">${escapeHtml(String(trade.thesis))}</div>` : ''}
      ${riskHtml}
      ${trade.what_changes_view ? `<div class="trade-card-change">${escapeHtml(String(trade.what_changes_view))}</div>` : ''}
    `;
  }

  function computeSessionPulse() {
    let sumAbs = 0;
    let nch = 0;
    for (const { id } of priceRows) {
      const row = lastPricesPayload[id];
      const ch = row && row.usd_24h_change;
      if (ch != null && !Number.isNaN(Number(ch))) {
        sumAbs += Math.min(Math.abs(Number(ch)), 24);
        nch += 1;
      }
    }
    const avgAbs = nch ? sumAbs / nch : 0;
    const heatScore = Math.min(100, (avgAbs / 10) * 100);

    const items = lastNewsItems.slice(0, 18);
    let pos = 0;
    let neg = 0;
    let neu = 0;
    for (const it of items) {
      const s = it.sentiment;
      if (s === 'positive') pos += 1;
      else if (s === 'negative') neg += 1;
      else neu += 1;
    }
    const ntot = pos + neg + neu || 1;
    const tilt = ((pos - neg) / ntot) * 50 + 50;

    const pulse = Math.round(heatScore * 0.52 + tilt * 0.48);
    const value = Math.max(0, Math.min(100, pulse));

    let mood = 'Balanced';
    if (value >= 68) mood = 'Heated';
    else if (value <= 38) mood = 'Cool';

    const wPart = nch
      ? `Watchlist avg |24h|: ${(sumAbs / nch).toFixed(1)}%`
      : 'No 24h change data yet';
    const hPart =
      items.length > 0
        ? `Headlines +${pos} / −${neg} / neutral ${neu}`
        : 'No headline sample';
    const detail = `${wPart} · ${hPart}`;

    return { value, mood, detail };
  }

  function updateSessionDeskUI() {
    const pulseBar = document.getElementById('session-pulse-bar');
    const pulseVal = document.getElementById('session-pulse-value');
    const pulseRead = document.getElementById('session-pulse-readout');
    const list = document.getElementById('session-stance-list');
    if (!pulseBar || !pulseVal || !pulseRead) return;

    const p = computeSessionPulse();
    pulseBar.style.width = `${p.value}%`;
    pulseVal.textContent = String(p.value);
    pulseRead.textContent = `${p.mood} — ${p.detail}`;

    if (!list) return;
    list.innerHTML = '';
    for (const e of stanceLedger) {
      const li = document.createElement('li');
      li.className = 'session-stance-item';
      const timeEl = document.createElement('time');
      timeEl.dateTime = new Date(e.t).toISOString();
      timeEl.textContent = new Date(e.t).toLocaleString();
      const line = document.createElement('div');
      line.className = 'stance-view';
      const bits = [];
      if (e.view) bits.push(e.view);
      if (e.confidence) bits.push(`Confidence ${e.confidence}%`);
      if (e.score) bits.push(`Score ${e.score}`);
      line.textContent = bits.length ? bits.join(' · ') : '(parsed)';
      li.appendChild(timeEl);
      li.appendChild(line);
      list.appendChild(li);
    }
  }

  const SESSIONS_STORE_KEY = 'cryptochatpal_sessions';
  const ACTIVE_SESSION_KEY = 'cryptochatpal_active_session';
  const LEGACY_CHAT_KEY = 'cryptochatpal_conversation';
  const MAX_SESSIONS = 25;
  const MAX_CHAT_MESSAGES = 30;

  let chatSessions = [];
  let activeSessionId = '';
  let conversation = [];

  function makeSessionId() {
    return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function cleanMessageList(arr) {
    const cleaned = [];
    if (!Array.isArray(arr)) return cleaned;
    for (const m of arr) {
      if (!m || typeof m !== 'object') continue;
      const role = m.role;
      const content = m.content;
      if ((role !== 'user' && role !== 'assistant') || typeof content !== 'string') continue;
      const text = content.trim();
      if (!text) continue;
      cleaned.push({ role, content: text });
    }
    return cleaned.slice(-MAX_CHAT_MESSAGES);
  }

  function loadLegacyConversation() {
    try {
      const raw = localStorage.getItem(LEGACY_CHAT_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return cleanMessageList(parsed);
    } catch {
      return [];
    }
  }

  function initChatSessions() {
    let sessions = [];
    try {
      const raw = localStorage.getItem(SESSIONS_STORE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          sessions = parsed.filter(
            (s) => s && typeof s === 'object' && typeof s.id === 'string' && Array.isArray(s.messages)
          );
        }
      }
    } catch {
      sessions = [];
    }
    if (!sessions.length) {
      const legacy = loadLegacyConversation();
      if (legacy.length) {
        sessions.push({
          id: makeSessionId(),
          title: 'Saved chat',
          updatedAt: Date.now(),
          messages: legacy,
        });
      } else {
        sessions.push({ id: makeSessionId(), title: 'Chat 1', updatedAt: Date.now(), messages: [] });
      }
    }
    for (const s of sessions) {
      s.messages = cleanMessageList(s.messages);
      if (typeof s.title !== 'string' || !s.title.trim()) s.title = 'Chat';
      if (typeof s.updatedAt !== 'number') s.updatedAt = Date.now();
    }
    let activeId = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!sessions.some((s) => s.id === activeId)) activeId = sessions[0].id;
    chatSessions = sessions.slice(0, MAX_SESSIONS);
    activeSessionId = activeId;
    const act = chatSessions.find((s) => s.id === activeSessionId) || chatSessions[0];
    activeSessionId = act.id;
    conversation = act.messages;
    return conversation;
  }

  initChatSessions();

  function persistChatSessions() {
    const act = chatSessions.find((s) => s.id === activeSessionId);
    if (act) {
      act.messages = cleanMessageList(act.messages);
      act.updatedAt = Date.now();
    }
    try {
      localStorage.setItem(SESSIONS_STORE_KEY, JSON.stringify(chatSessions));
      localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
      if (act) {
        localStorage.setItem(LEGACY_CHAT_KEY, JSON.stringify(act.messages.slice(-MAX_CHAT_MESSAGES)));
      }
    } catch {
      /* ignore quota */
    }
  }

  function formatChatDate(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function renderConversation(rows) {
    messagesEl.innerHTML = '';
    if (!rows?.length) return;
    for (const m of rows) {
      addMessage(m.role, m.content);
    }
  }

  function renderHistoryList() {
    const listEl = document.getElementById('chat-history-list');
    if (!listEl) return;
    listEl.innerHTML = '';
    const sorted = [...chatSessions].sort((a, b) => b.updatedAt - a.updatedAt);
    for (const s of sorted) {
      const row = document.createElement('div');
      row.className = 'chat-history-row';

      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'chat-history-item' + (s.id === activeSessionId ? ' active' : '');
      main.innerHTML = `<span class="chat-history-title">${escapeHtml(s.title)}</span><span class="chat-history-date">${escapeHtml(formatChatDate(s.updatedAt))}</span>`;
      main.addEventListener('click', () => {
        switchSession(s.id);
        const panel = document.getElementById('chat-history-panel');
        const toggle = document.getElementById('chat-history-toggle');
        if (panel) {
          panel.classList.add('hidden');
          panel.setAttribute('aria-hidden', 'true');
        }
        if (toggle) toggle.setAttribute('aria-expanded', 'false');
      });

      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'chat-history-del';
      del.setAttribute('aria-label', 'Delete chat');
      del.textContent = '×';
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(s.id);
      });

      row.appendChild(main);
      row.appendChild(del);
      listEl.appendChild(row);
    }
  }

  function switchSession(id) {
    if (id === activeSessionId) return;
    const s = chatSessions.find((x) => x.id === id);
    if (!s) return;
    activeSessionId = id;
    conversation = s.messages;
    renderConversation(conversation);
    persistChatSessions();
    renderHistoryList();
  }

  function newChatSession() {
    const id = makeSessionId();
    const n = chatSessions.length + 1;
    chatSessions.unshift({ id, title: 'Chat ' + n, updatedAt: Date.now(), messages: [] });
    if (chatSessions.length > MAX_SESSIONS) chatSessions.pop();
    activeSessionId = id;
    conversation = chatSessions.find((x) => x.id === id).messages;
    messagesEl.innerHTML = '';
    persistChatSessions();
    renderHistoryList();
  }

  function deleteSession(id) {
    if (chatSessions.length <= 1) return;
    const idx = chatSessions.findIndex((s) => s.id === id);
    if (idx < 0) return;
    chatSessions.splice(idx, 1);
    if (activeSessionId === id) {
      activeSessionId = chatSessions[0].id;
      conversation = chatSessions[0].messages;
      renderConversation(conversation);
    }
    persistChatSessions();
    renderHistoryList();
  }

  function formatUsd(n) {
    if (n == null || Number.isNaN(n)) return '—';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: n >= 100 ? 0 : 2,
    }).format(n);
  }

  function buildIdsQuery() {
    return priceRows.map((r) => r.id).join(',');
  }

  function portfolioSignature() {
    return portfolioRows.map((r) => `${r.id}:${r.amount}:${r.avg == null ? '' : r.avg}`).join('|');
  }

  function buildCombinedIdsQuery() {
    const seen = new Set();
    const out = [];
    for (const r of priceRows) {
      if (r.id && !seen.has(r.id)) {
        seen.add(r.id);
        out.push(r.id);
      }
    }
    for (const r of portfolioRows) {
      if (r.id && !seen.has(r.id)) {
        seen.add(r.id);
        out.push(r.id);
      }
    }
    return out.join(',');
  }

  const MAX_PRICE_ALERTS = 40;
  const ALERT_COOLDOWN_MS = 5 * 60 * 1000;
  const MAX_ALERT_LOG = 30;
  let priceAlerts = loadPriceAlerts();
  let priceHistoryById = {};
  let alertHitLog = loadAlertHitLog();
  let alertAudioCtx = null;

  function loadAlertHitLog() {
    try {
      const raw = localStorage.getItem(PRICE_ALERT_LOG_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr
        .filter((x) => x && typeof x === 'object' && Number.isFinite(Number(x.t)))
        .map((x) => ({
          t: Number(x.t),
          sym: String(x.sym || '').slice(0, 20),
          type: String(x.type || '').slice(0, 32),
          text: String(x.text || '').slice(0, 400),
        }))
        .slice(0, MAX_ALERT_LOG);
    } catch {
      return [];
    }
  }

  function saveAlertHitLog() {
    try {
      localStorage.setItem(PRICE_ALERT_LOG_KEY, JSON.stringify(alertHitLog.slice(0, MAX_ALERT_LOG)));
    } catch {
      /* ignore */
    }
  }

  function recordAlertHit(text, sym, type) {
    const entry = { t: Date.now(), sym, type, text: String(text || '') };
    alertHitLog.unshift(entry);
    alertHitLog = alertHitLog.slice(0, MAX_ALERT_LOG);
    saveAlertHitLog();
    renderAlertHistory();
  }

  function clearAlertHistory() {
    alertHitLog = [];
    saveAlertHitLog();
    renderAlertHistory();
  }

  function renderAlertHistory() {
    if (!alertsHistoryEl) return;
    if (!alertHitLog.length) {
      alertsHistoryEl.innerHTML = '<div class="alerts-history-empty sub">No triggers yet.</div>';
      return;
    }
    const html = alertHitLog
      .map((e) => {
        const when = new Date(e.t);
        const timeStr = Number.isNaN(when.getTime()) ? '—' : when.toLocaleString();
        return `<div class="alerts-history-item"><time datetime="${e.t}">${escapeHtml(
          timeStr
        )}</time><div class="alerts-history-text"><strong>${escapeHtml(e.sym)}</strong> · ${escapeHtml(
          e.text
        )}</div></div>`;
      })
      .join('');
    alertsHistoryEl.innerHTML = html;
  }

  function getAlertsSoundOn() {
    if (alertsSoundChk) return Boolean(alertsSoundChk.checked);
    try {
      return localStorage.getItem(PRICE_ALERTS_SOUND_KEY) === '1';
    } catch {
      return false;
    }
  }

  function applyAlertsSoundPrefToUi() {
    if (!alertsSoundChk) return;
    try {
      const v = localStorage.getItem(PRICE_ALERTS_SOUND_KEY);
      alertsSoundChk.checked = v === '1' || v === 'true';
    } catch {
      alertsSoundChk.checked = false;
    }
  }

  function playAlertBeep() {
    if (!getAlertsSoundOn()) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!alertAudioCtx) alertAudioCtx = new Ctx();
      const ctx = alertAudioCtx;
      if (ctx.state === 'suspended') void ctx.resume();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(880, ctx.currentTime);
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.1, ctx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.14);
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.15);
    } catch {
      /* ignore */
    }
  }

  function hasDropDuplicate(id, threshold, windowMin) {
    return priceAlerts.some(
      (a) =>
        a.id === id &&
        a.type === 'drop_pct_window' &&
        Number(a.threshold) === Number(threshold) &&
        Number(a.windowMin) === Number(windowMin)
    );
  }

  function addDropAlertsForRows(rows, pct, windowMin) {
    const w = Math.max(5, Math.min(24 * 60, Number(windowMin) || 60));
    const p = Math.abs(Number(pct));
    if (!Number.isFinite(p) || p <= 0) {
      setAlertsStatus('Invalid preset percent.');
      return 0;
    }
    let added = 0;
    for (const r of rows) {
      if (!r || !r.id) continue;
      if (hasDropDuplicate(r.id, p, w)) continue;
      if (priceAlerts.length >= MAX_PRICE_ALERTS) break;
      priceAlerts.push({
        id: r.id,
        sym: r.sym,
        type: 'drop_pct_window',
        threshold: p,
        windowMin: w,
        enabled: true,
        lastTriggeredAt: 0,
      });
      added += 1;
    }
    if (added) {
      savePriceAlerts();
      renderAlertsList();
      setAlertsStatus(
        `Added ${added} drop alert(s): −${p}% in ${w} min.`
      );
    } else {
      setAlertsStatus('No new alerts (duplicates or list full).');
    }
    return added;
  }

  function coinSymById(id) {
    const fromRows = priceRows.find((r) => r.id === id);
    if (fromRows) return fromRows.sym;
    const fromPreset = COIN_PRESETS.find((p) => p.id === id);
    if (fromPreset) return fromPreset.sym;
    return String(id || '').slice(0, 12).toUpperCase();
  }

  function loadPriceAlerts() {
    try {
      const raw = localStorage.getItem(PRICE_ALERTS_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      const out = [];
      for (const x of arr) {
        if (!x || typeof x !== 'object') continue;
        const id = sanitizeCoinId(x.id || '');
        const type = String(x.type || '');
        const threshold = Number(x.threshold);
        const windowMin = Number(x.windowMin || 60);
        if (!id || !Number.isFinite(threshold) || threshold <= 0) continue;
        if (!['cross_above', 'cross_below', 'drop_pct_window'].includes(type)) continue;
        out.push({
          id,
          sym: sanitizeSym(x.sym || '') || coinSymById(id),
          type,
          threshold,
          windowMin: Math.max(5, Math.min(24 * 60, Number.isFinite(windowMin) ? windowMin : 60)),
          enabled: x.enabled !== false,
          lastTriggeredAt:
            Number.isFinite(Number(x.lastTriggeredAt)) && Number(x.lastTriggeredAt) > 0
              ? Number(x.lastTriggeredAt)
              : 0,
        });
      }
      return out.slice(0, MAX_PRICE_ALERTS);
    } catch {
      return [];
    }
  }

  function savePriceAlerts() {
    try {
      localStorage.setItem(PRICE_ALERTS_KEY, JSON.stringify(priceAlerts.slice(0, MAX_PRICE_ALERTS)));
    } catch {
      /* ignore quota */
    }
  }

  function setAlertsStatus(msg) {
    if (!alertsStatus) return;
    alertsStatus.textContent = msg || '';
  }

  function alertTypeLabel(a) {
    if (a.type === 'cross_above') return `crosses above ${formatUsd(a.threshold)}`;
    if (a.type === 'cross_below') return `crosses below ${formatUsd(a.threshold)}`;
    return `drops ${a.threshold}% in ${a.windowMin} min`;
  }

  function refreshNotifyButton() {
    if (!alertsNotifyBtn) return;
    if (!('Notification' in window)) {
      alertsNotifyBtn.textContent = 'Notifications unavailable';
      alertsNotifyBtn.disabled = true;
      return;
    }
    const p = Notification.permission;
    if (p === 'granted') {
      alertsNotifyBtn.textContent = 'Notifications enabled';
      alertsNotifyBtn.disabled = true;
    } else if (p === 'denied') {
      alertsNotifyBtn.textContent = 'Notifications blocked';
      alertsNotifyBtn.disabled = true;
    } else {
      alertsNotifyBtn.textContent = 'Enable notifications';
      alertsNotifyBtn.disabled = false;
    }
  }

  function renderAlertsList() {
    if (!alertsList) return;
    alertsList.innerHTML = '';
    if (!priceAlerts.length) {
      const p = document.createElement('div');
      p.className = 'news-snippet';
      p.textContent = 'No alerts yet. Add one above.';
      alertsList.appendChild(p);
      return;
    }
    priceAlerts.forEach((a, idx) => {
      const row = document.createElement('div');
      row.className = 'alert-row';
      row.innerHTML = `
        <label class="alert-toggle">
          <input type="checkbox" data-act="toggle" data-i="${idx}" ${a.enabled ? 'checked' : ''} />
          <span>${escapeHtml(a.sym)}</span>
        </label>
        <span class="alert-rule">${escapeHtml(alertTypeLabel(a))}</span>
        <button type="button" class="prices-row-btn danger" data-act="del" data-i="${idx}" aria-label="Remove alert">×</button>
      `;
      alertsList.appendChild(row);
    });
  }

  function fillAlertsCoinSelect() {
    if (!alertsCoinSelect) return;
    const keep = alertsCoinSelect.value;
    alertsCoinSelect.innerHTML = '<option value="">Coin…</option>';
    const seen = new Set();
    for (const r of priceRows) {
      if (!r.id || seen.has(r.id)) continue;
      seen.add(r.id);
      const o = document.createElement('option');
      o.value = r.id;
      o.textContent = `${r.sym} · ${r.id}`;
      alertsCoinSelect.appendChild(o);
    }
    if (keep && seen.has(keep)) alertsCoinSelect.value = keep;
  }

  function syncAlertTypeInputs() {
    if (!alertsTypeSelect || !alertsWindowInput) return;
    const isDrop = alertsTypeSelect.value === 'drop_pct_window';
    alertsWindowInput.disabled = !isDrop;
    alertsWindowInput.placeholder = isDrop ? 'Window min' : 'n/a';
  }

  async function requestNotificationPermission() {
    if (!('Notification' in window)) {
      setAlertsStatus('Browser notifications are not supported here.');
      refreshNotifyButton();
      return;
    }
    if (Notification.permission === 'granted') {
      setAlertsStatus('Notifications already enabled.');
      refreshNotifyButton();
      return;
    }
    try {
      const p = await Notification.requestPermission();
      if (p === 'granted') setAlertsStatus('Notifications enabled.');
      else if (p === 'denied') setAlertsStatus('Notifications blocked by browser.');
      else setAlertsStatus('Notification permission dismissed.');
    } catch {
      setAlertsStatus('Could not request notification permission.');
    }
    refreshNotifyButton();
  }

  function notifyAlert(title, body) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      // Keep lightweight and non-blocking for rapid price updates.
      new Notification(title, { body, silent: false });
    } catch {
      /* ignore */
    }
  }

  function evaluatePriceAlerts(current, previous, nowMs) {
    if (!current || typeof current !== 'object') return;
    const maxWindowMin = Math.max(
      5,
      priceAlerts.reduce((m, a) => (a.type === 'drop_pct_window' ? Math.max(m, a.windowMin || 60) : m), 5)
    );
    const keepMs = maxWindowMin * 60 * 1000 + 2 * 60 * 1000;
    for (const [id, row] of Object.entries(current)) {
      const usd = row && typeof row.usd === 'number' ? row.usd : null;
      if (usd == null || Number.isNaN(usd)) continue;
      const hist = priceHistoryById[id] || [];
      hist.push({ t: nowMs, p: usd });
      const cutoff = nowMs - keepMs;
      while (hist.length > 2 && hist[0].t < cutoff) hist.shift();
      priceHistoryById[id] = hist;
    }

    let changed = false;
    for (const a of priceAlerts) {
      if (!a.enabled) continue;
      const cur = current[a.id];
      const prev = previous && previous[a.id];
      const curUsd = cur && typeof cur.usd === 'number' ? cur.usd : null;
      const prevUsd = prev && typeof prev.usd === 'number' ? prev.usd : null;
      if (curUsd == null || Number.isNaN(curUsd)) continue;
      if (nowMs - (a.lastTriggeredAt || 0) < ALERT_COOLDOWN_MS) continue;
      let fire = false;
      let body = '';
      if (a.type === 'cross_above' && prevUsd != null && prevUsd < a.threshold && curUsd >= a.threshold) {
        fire = true;
        body = `${a.sym} crossed above ${formatUsd(a.threshold)} (now ${formatUsd(curUsd)}).`;
      } else if (
        a.type === 'cross_below' &&
        prevUsd != null &&
        prevUsd > a.threshold &&
        curUsd <= a.threshold
      ) {
        fire = true;
        body = `${a.sym} crossed below ${formatUsd(a.threshold)} (now ${formatUsd(curUsd)}).`;
      } else if (a.type === 'drop_pct_window') {
        const hist = priceHistoryById[a.id] || [];
        const cutoff = nowMs - a.windowMin * 60 * 1000;
        let ref = null;
        for (let i = 0; i < hist.length; i += 1) {
          if (hist[i].t >= cutoff) {
            ref = hist[i].p;
            break;
          }
        }
        if (ref == null && hist.length) ref = hist[0].p;
        if (ref != null && ref > 0) {
          const pct = ((curUsd - ref) / ref) * 100;
          if (pct <= -Math.abs(a.threshold)) {
            fire = true;
            body = `${a.sym} is down ${Math.abs(pct).toFixed(2)}% in ${a.windowMin} min (now ${formatUsd(curUsd)}).`;
          }
        }
      }
      if (fire) {
        a.lastTriggeredAt = nowMs;
        changed = true;
        notifyAlert(`Crypto ChatPal alert: ${a.sym}`, body);
        recordAlertHit(body, a.sym, a.type);
        playAlertBeep();
        setAlertsStatus(body);
      }
    }
    if (changed) savePriceAlerts();
  }

  const portfolioSummaryEl = document.getElementById('portfolio-summary');
  const portfolioDisplayEl = document.getElementById('portfolio-display');
  const portfolioEditor = document.getElementById('portfolio-editor');
  const portfolioEditToggle = document.getElementById('portfolio-edit-toggle');
  const portfolioEditorRows = document.getElementById('portfolio-editor-rows');
  const portfolioPresetSelect = document.getElementById('portfolio-preset-select');
  const portfolioAddPresetBtn = document.getElementById('portfolio-add-preset');
  const portfolioAddAmount = document.getElementById('portfolio-add-amount');
  const portfolioAddAvg = document.getElementById('portfolio-add-avg');
  const portfolioCustomId = document.getElementById('portfolio-custom-id');
  const portfolioCustomSym = document.getElementById('portfolio-custom-sym');
  const portfolioCustomAmount = document.getElementById('portfolio-custom-amount');
  const portfolioCustomAvg = document.getElementById('portfolio-custom-avg');
  const portfolioAddCustomBtn = document.getElementById('portfolio-add-custom');
  const portfolioClearBtn = document.getElementById('portfolio-clear');

  function fillPortfolioPresetSelect() {
    if (!portfolioPresetSelect || portfolioPresetSelect.dataset.filled) return;
    portfolioPresetSelect.dataset.filled = '1';
    for (const p of COIN_PRESETS) {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = `${p.sym} · ${p.id}`;
      portfolioPresetSelect.appendChild(o);
    }
  }

  function renderPortfolioEditorRows() {
    if (!portfolioEditorRows) return;
    portfolioEditorRows.innerHTML = '';
    portfolioRows.forEach((row, i) => {
      const el = document.createElement('div');
      el.className = 'portfolio-edit-row';
      el.innerHTML = `
        <div class="pe-meta">
          <span class="pe-sym">${escapeHtml(row.sym)}</span>
          <span class="pe-id">${escapeHtml(row.id)}</span>
        </div>
        <input type="text" class="prices-input" data-port="amt" data-i="${i}" value="${row.amount === 0 ? '' : row.amount}" inputmode="decimal" aria-label="Amount ${escapeHtml(row.sym)}" />
        <input type="text" class="prices-input" data-port="avg" data-i="${i}" value="${row.avg == null ? '' : row.avg}" placeholder="Avg USD" inputmode="decimal" aria-label="Avg buy USD ${escapeHtml(row.sym)}" />
        <button type="button" class="prices-row-btn danger" data-port-del="${i}" aria-label="Remove ${escapeHtml(row.sym)}">×</button>`;
      portfolioEditorRows.appendChild(el);
    });
  }

  function renderPortfolioView(data) {
    if (!portfolioSummaryEl || !portfolioDisplayEl) return;
    const d = data && typeof data === 'object' ? data : {};
    if (!portfolioRows.length) {
      portfolioSummaryEl.innerHTML = '';
      portfolioDisplayEl.innerHTML =
        '<p class="news-snippet" style="margin:0">No holdings. Open <strong>Edit</strong> to add coins and amounts.</p>';
      return;
    }

    let totalValue = 0;
    let totalCost = 0;
    let costParts = 0;
    const lines = [];

    for (const row of portfolioRows) {
      const px = d[row.id];
      const spot = px && px.usd != null ? Number(px.usd) : null;
      const val = spot != null && !Number.isNaN(spot) ? row.amount * spot : null;
      if (val != null) totalValue += val;

      let linePl = null;
      let linePlPct = null;
      if (row.avg != null && row.amount > 0) {
        const cost = row.amount * row.avg;
        totalCost += cost;
        costParts += 1;
        if (val != null) {
          linePl = val - cost;
          linePlPct = cost > 0 ? (linePl / cost) * 100 : null;
        }
      }

      const valS = val != null ? formatUsd(val) : '—';
      let plS = '—';
      if (linePl != null) {
        const sign = linePl >= 0 ? '+' : '';
        plS = `${sign}${formatUsd(linePl)}`;
        if (linePlPct != null) plS += ` (${sign}${linePlPct.toFixed(1)}%)`;
      }

      const spotS = spot != null ? formatUsd(spot) : '—';
      lines.push(
        `<div class="portfolio-line"><span class="pl-sym">${escapeHtml(row.sym)}</span><span class="pl-detail">${escapeHtml(String(row.amount))} @ ${spotS} → <strong>${valS}</strong> · P/L ${plS}</span></div>`
      );
    }

    const plTotal = costParts > 0 ? totalValue - totalCost : null;
    const plPctTotal = costParts > 0 && totalCost > 0 ? ((totalValue - totalCost) / totalCost) * 100 : null;

    let plClass = '';
    let plValHtml = '—';
    if (plTotal != null) {
      plClass = plTotal >= 0 ? ' chg-pos' : ' chg-neg';
      const sign = plTotal >= 0 ? '+' : '';
      plValHtml = `${sign}${formatUsd(plTotal)}`;
      if (plPctTotal != null) plValHtml += ` (${sign}${plPctTotal.toFixed(1)}%)`;
    }

    const costHtml =
      costParts > 0 ? formatUsd(totalCost) : `<span class="sub">Add avg buy to see</span>`;

    portfolioSummaryEl.innerHTML = `
      <div><span class="ps-label">Value (spot)</span><span class="ps-value">${formatUsd(totalValue)}</span></div>
      <div><span class="ps-label">Cost basis</span><span class="ps-value">${costHtml}</span></div>
      <div><span class="ps-label">Unrealized P/L</span><span class="ps-value${plClass}">${plValHtml}</span></div>`;
    portfolioDisplayEl.innerHTML = lines.join('');
  }

  function persistPortfolioRedrawPrices() {
    savePortfolio();
    lastRenderKey = '';
    renderPortfolioEditorRows();
    loadPrices();
    sendLiveSubscribe();
  }

  /** Latest per-coin 24h sparkline series, keyed by CoinGecko id. */
  let lastSparklines = {};

  function buildSparklineSvg(points, ch24h) {
    if (!Array.isArray(points) || points.length < 2) return '';
    const w = 72;
    const h = 22;
    const pad = 1;
    let lo = Infinity;
    let hi = -Infinity;
    for (const p of points) {
      if (typeof p !== 'number' || Number.isNaN(p)) continue;
      if (p < lo) lo = p;
      if (p > hi) hi = p;
    }
    if (!isFinite(lo) || !isFinite(hi)) return '';
    const span = hi - lo || 1;
    const stepX = (w - pad * 2) / (points.length - 1);
    const coords = points.map((p, i) => {
      const x = pad + i * stepX;
      const y = pad + (h - pad * 2) * (1 - (p - lo) / span);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    const path = 'M' + coords.join(' L');
    let cls = 'spark-neutral';
    if (ch24h != null && Number.isFinite(ch24h)) {
      if (ch24h > 0) cls = 'spark-up';
      else if (ch24h < 0) cls = 'spark-down';
    } else {
      const last = points[points.length - 1];
      const first = points[0];
      if (typeof last === 'number' && typeof first === 'number' && !Number.isNaN(last) && !Number.isNaN(first)) {
        cls = last >= first ? 'spark-up' : 'spark-down';
      }
    }
    return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><path d="${path}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }

  function renderPrices(data) {
    pricesError.classList.add('hidden');
    const prevPricesPayload = lastPricesPayload;
    lastPricesPayload = data && typeof data === 'object' ? data : {};
    evaluatePriceAlerts(lastPricesPayload, prevPricesPayload, Date.now());
    const orderKey = priceRows.map((r) => r.id).join('|');
    const sparkKey = Object.keys(lastSparklines).sort().join(',');
    const composite =
      JSON.stringify(lastPricesPayload) + '|' + orderKey + '|' + sparkKey + '|' + portfolioSignature();
    if (composite === lastRenderKey) {
      pricesUpdated.textContent = 'Live · ' + new Date().toLocaleTimeString();
      renderPortfolioView(lastPricesPayload);
      updateSessionDeskUI();
      return;
    }
    lastRenderKey = composite;

    pricesList.innerHTML = '';
    for (const { id, sym } of priceRows) {
      const row = lastPricesPayload[id];
      const div = document.createElement('div');
      div.className = 'price-row';
      if (!row || row.usd == null) {
        div.innerHTML = `
          <span class="sym">${escapeHtml(sym)}</span>
          <span class="spark-cell"></span>
          <span class="usd">—</span>
          <button type="button" class="why-move-btn" data-coin-id="${escapeHtml(id)}" data-coin-sym="${escapeHtml(sym)}" title="Ask AI (spot may be missing)">Why move?</button>
          <span class="chg neutral">No data</span>`;
        pricesList.appendChild(div);
        continue;
      }
      const ch = row.usd_24h_change;
      let chClass = 'neutral';
      let chText = '24h —';
      if (ch != null && !Number.isNaN(ch)) {
        chClass = ch > 0 ? 'up' : ch < 0 ? 'down' : 'neutral';
        chText = `24h ${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%`;
      }
      const series = lastSparklines[id];
      const sparkHtml =
        series && series.length >= 2 ? buildSparklineSvg(series, ch) : '';
      div.innerHTML = `
          <span class="sym">${escapeHtml(sym)}</span>
          <span class="spark-cell">${sparkHtml}</span>
          <span class="usd">${formatUsd(row.usd)}</span>
          <button type="button" class="why-move-btn" data-coin-id="${escapeHtml(id)}" data-coin-sym="${escapeHtml(sym)}" title="Ask AI why this coin moved (uses spot + RSS headlines)">Why move?</button>
          <span class="chg ${chClass}">${chText}</span>`;
      pricesList.appendChild(div);
    }
    pricesUpdated.textContent = 'Live · ' + new Date().toLocaleTimeString();
    renderPortfolioView(lastPricesPayload);
    updateSessionDeskUI();
  }

  async function loadSparklines() {
    try {
      const url = '/api/prices/sparklines?ids=' + encodeURIComponent(buildCombinedIdsQuery());
      const res = await fetch(url, { headers: ccpApiAuthHeaders() });
      if (!res.ok) return;
      const data = await res.json().catch(() => null);
      if (data && typeof data === 'object') {
        lastSparklines = data;
        lastRenderKey = '';
        if (lastPricesPayload && Object.keys(lastPricesPayload).length) {
          renderPrices(lastPricesPayload);
        }
      }
    } catch (e) {
      /* silent — sparklines are decoration */
    }
  }

  async function loadPrices() {
    try {
      const url = '/api/prices?ids=' + encodeURIComponent(buildCombinedIdsQuery());
      const res = await fetch(url, { headers: ccpApiAuthHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const msg =
          typeof d === 'string' ? d : (d && JSON.stringify(d)) || res.statusText || 'Failed';
        throw new Error(msg);
      }
      renderPrices(data);
    } catch (e) {
      pricesError.textContent = 'Could not load prices. Check server / CoinGecko.';
      pricesError.classList.remove('hidden');
      pricesUpdated.textContent = '';
      renderPortfolioView(lastPricesPayload);
    }
  }

  function fillPresetSelect() {
    if (!pricesPresetSelect || pricesPresetSelect.dataset.filled) return;
    pricesPresetSelect.dataset.filled = '1';
    for (const p of COIN_PRESETS) {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = `${p.sym} · ${p.id}`;
      pricesPresetSelect.appendChild(o);
    }
  }

  function renderEditorRows() {
    if (!pricesEditorRows) return;
    pricesEditorRows.innerHTML = '';
    priceRows.forEach((row, i) => {
      const el = document.createElement('div');
      el.className = 'prices-edit-row';
      el.innerHTML = `
        <button type="button" class="prices-row-btn" data-act="up" data-i="${i}" aria-label="Move up" ${i === 0 ? 'disabled' : ''}>↑</button>
        <button type="button" class="prices-row-btn" data-act="down" data-i="${i}" aria-label="Move down" ${i === priceRows.length - 1 ? 'disabled' : ''}>↓</button>
        <span class="sym">${escapeHtml(row.sym)}</span>
        <span class="cg-id" title="${escapeHtml(row.id)}">${escapeHtml(row.id)}</span>
        <button type="button" class="prices-row-btn danger" data-act="del" data-i="${i}" aria-label="Remove">×</button>`;
      pricesEditorRows.appendChild(el);
    });
  }

  function persistPriceRowsAndRedraw() {
    savePriceRows(priceRows);
    lastRenderKey = '';
    renderEditorRows();
    fillAlertsCoinSelect();
    renderPrices(lastPricesPayload);
    loadPrices();
    loadSparklines();
    sendLiveSubscribe();
  }

  if (pricesEditorRows) {
    pricesEditorRows.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-act]');
      if (!btn || !pricesEditorRows.contains(btn)) return;
      const i = parseInt(btn.dataset.i, 10);
      if (Number.isNaN(i) || i < 0 || i >= priceRows.length) return;
      const act = btn.dataset.act;
      if (act === 'up' && i > 0) {
        const t = priceRows[i - 1];
        priceRows[i - 1] = priceRows[i];
        priceRows[i] = t;
        persistPriceRowsAndRedraw();
      } else if (act === 'down' && i < priceRows.length - 1) {
        const t = priceRows[i + 1];
        priceRows[i + 1] = priceRows[i];
        priceRows[i] = t;
        persistPriceRowsAndRedraw();
      } else if (act === 'del') {
        if (priceRows.length <= 1) return;
        priceRows.splice(i, 1);
        persistPriceRowsAndRedraw();
      }
    });
  }

  if (pricesEditToggle && pricesEditor) {
    pricesEditToggle.addEventListener('click', () => {
      const opening = pricesEditor.classList.contains('hidden');
      if (opening) {
        pricesEditor.classList.remove('hidden');
        pricesEditToggle.setAttribute('aria-expanded', 'true');
        pricesEditToggle.textContent = 'Done';
        pricesEditor.setAttribute('aria-hidden', 'false');
        fillPresetSelect();
        renderEditorRows();
      } else {
        pricesEditor.classList.add('hidden');
        pricesEditToggle.setAttribute('aria-expanded', 'false');
        pricesEditToggle.textContent = 'Edit list';
        pricesEditor.setAttribute('aria-hidden', 'true');
      }
    });
  }

  if (pricesAddPreset && pricesPresetSelect) {
    pricesAddPreset.addEventListener('click', () => {
      const id = pricesPresetSelect.value;
      if (!id) return;
      const p = COIN_PRESETS.find((x) => x.id === id);
      if (!p) return;
      if (priceRows.some((r) => r.id === p.id)) return;
      if (priceRows.length >= MAX_PRICE_ROWS) return;
      priceRows.push({ id: p.id, sym: p.sym });
      pricesPresetSelect.value = '';
      persistPriceRowsAndRedraw();
    });
  }

  if (pricesAddCustom && pricesCustomId) {
    pricesAddCustom.addEventListener('click', () => {
      const id = sanitizeCoinId(pricesCustomId.value);
      let sym = sanitizeSym(pricesCustomSym.value);
      if (!id) return;
      if (!sym) sym = id.slice(0, 12).toUpperCase();
      if (priceRows.some((r) => r.id === id)) return;
      if (priceRows.length >= MAX_PRICE_ROWS) return;
      priceRows.push({ id, sym });
      pricesCustomId.value = '';
      pricesCustomSym.value = '';
      persistPriceRowsAndRedraw();
    });
  }

  if (pricesResetDefault) {
    pricesResetDefault.addEventListener('click', () => {
      priceRows = DEFAULT_PRICE_ROWS.map((r) => ({ ...r }));
      if (pricesPresetSelect) pricesPresetSelect.value = '';
      persistPriceRowsAndRedraw();
    });
  }

  if (alertsTypeSelect) {
    alertsTypeSelect.addEventListener('change', () => {
      syncAlertTypeInputs();
    });
  }

  if (alertsAddBtn) {
    alertsAddBtn.addEventListener('click', () => {
      const id = sanitizeCoinId(alertsCoinSelect && alertsCoinSelect.value);
      const type = alertsTypeSelect ? alertsTypeSelect.value : '';
      const threshold = parseFloat(String((alertsThresholdInput && alertsThresholdInput.value) || '').replace(/,/g, ''));
      const windowMin = parseInt(
        String((alertsWindowInput && alertsWindowInput.value) || '60').replace(/[^0-9]/g, ''),
        10
      );
      if (!id) {
        setAlertsStatus('Pick a coin first.');
        return;
      }
      if (!['cross_above', 'cross_below', 'drop_pct_window'].includes(type)) {
        setAlertsStatus('Pick a valid alert type.');
        return;
      }
      if (!Number.isFinite(threshold) || threshold <= 0) {
        setAlertsStatus(type === 'drop_pct_window' ? 'Enter a valid % drop.' : 'Enter a valid USD threshold.');
        return;
      }
      if (type === 'drop_pct_window' && (!Number.isFinite(windowMin) || windowMin < 5)) {
        setAlertsStatus('Window must be at least 5 minutes.');
        return;
      }
      if (priceAlerts.length >= MAX_PRICE_ALERTS) {
        setAlertsStatus(`Max ${MAX_PRICE_ALERTS} alerts reached.`);
        return;
      }
      priceAlerts.push({
        id,
        sym: coinSymById(id),
        type,
        threshold: threshold,
        windowMin: type === 'drop_pct_window' ? Math.min(windowMin, 24 * 60) : 60,
        enabled: true,
        lastTriggeredAt: 0,
      });
      savePriceAlerts();
      renderAlertsList();
      if (alertsThresholdInput) alertsThresholdInput.value = '';
      if (alertsWindowInput && type === 'drop_pct_window') alertsWindowInput.value = '';
      setAlertsStatus('Alert added.');
    });
  }

  if (alertsList) {
    alertsList.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-act="del"]');
      if (!btn || !alertsList.contains(btn)) return;
      const i = parseInt(btn.dataset.i, 10);
      if (Number.isNaN(i) || i < 0 || i >= priceAlerts.length) return;
      priceAlerts.splice(i, 1);
      savePriceAlerts();
      renderAlertsList();
      setAlertsStatus('Alert removed.');
    });
    alertsList.addEventListener('change', (e) => {
      const inp = e.target.closest('input[data-act="toggle"]');
      if (!inp || !alertsList.contains(inp)) return;
      const i = parseInt(inp.dataset.i, 10);
      if (Number.isNaN(i) || i < 0 || i >= priceAlerts.length) return;
      priceAlerts[i].enabled = Boolean(inp.checked);
      savePriceAlerts();
    });
  }

  if (alertsNotifyBtn) {
    alertsNotifyBtn.addEventListener('click', () => {
      requestNotificationPermission();
    });
  }

  if (alertsSoundChk) {
    applyAlertsSoundPrefToUi();
    alertsSoundChk.addEventListener('change', () => {
      try {
        localStorage.setItem(PRICE_ALERTS_SOUND_KEY, alertsSoundChk.checked ? '1' : '0');
      } catch {
        /* ignore */
      }
      if (alertsSoundChk.checked) playAlertBeep();
    });
  }

  if (alertsHistoryClear) {
    alertsHistoryClear.addEventListener('click', () => {
      clearAlertHistory();
      setAlertsStatus('Alert history cleared.');
    });
  }

  if (alertsPresetsEl) {
    alertsPresetsEl.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-preset]');
      if (!btn || !alertsPresetsEl.contains(btn)) return;
      const preset = btn.getAttribute('data-preset') || '';
      if (preset === 'top3-3') {
        addDropAlertsForRows(priceRows.slice(0, 3), 3, 60);
      } else if (preset === 'top3-5') {
        addDropAlertsForRows(priceRows.slice(0, 3), 5, 60);
      } else if (preset === 'all-3') {
        addDropAlertsForRows([...priceRows], 3, 60);
      }
    });
  }

  fillAlertsCoinSelect();
  syncAlertTypeInputs();
  renderAlertsList();
  renderAlertHistory();
  refreshNotifyButton();

  if (portfolioEditToggle && portfolioEditor) {
    portfolioEditToggle.addEventListener('click', () => {
      const opening = portfolioEditor.classList.contains('hidden');
      if (opening) {
        portfolioEditor.classList.remove('hidden');
        portfolioEditToggle.setAttribute('aria-expanded', 'true');
        portfolioEditToggle.textContent = 'Done';
        portfolioEditor.setAttribute('aria-hidden', 'false');
        fillPortfolioPresetSelect();
        renderPortfolioEditorRows();
      } else {
        portfolioEditor.classList.add('hidden');
        portfolioEditToggle.setAttribute('aria-expanded', 'false');
        portfolioEditToggle.textContent = 'Edit';
        portfolioEditor.setAttribute('aria-hidden', 'true');
      }
    });
  }

  if (portfolioEditorRows) {
    portfolioEditorRows.addEventListener('change', (e) => {
      const inp = e.target.closest('input[data-port]');
      if (!inp || !portfolioEditorRows.contains(inp)) return;
      const i = parseInt(inp.dataset.i, 10);
      if (Number.isNaN(i) || i < 0 || i >= portfolioRows.length) return;
      if (inp.dataset.port === 'amt') portfolioRows[i].amount = sanitizeAmount(inp.value);
      if (inp.dataset.port === 'avg') portfolioRows[i].avg = sanitizeAvgUsdField(inp.value);
      persistPortfolioRedrawPrices();
    });
    portfolioEditorRows.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-port-del]');
      if (!btn || !portfolioEditorRows.contains(btn)) return;
      const i = parseInt(btn.dataset.portDel, 10);
      if (Number.isNaN(i) || i < 0 || i >= portfolioRows.length) return;
      portfolioRows.splice(i, 1);
      persistPortfolioRedrawPrices();
    });
  }

  if (portfolioAddPresetBtn && portfolioPresetSelect) {
    portfolioAddPresetBtn.addEventListener('click', () => {
      const id = portfolioPresetSelect.value;
      if (!id) return;
      const p = COIN_PRESETS.find((x) => x.id === id);
      if (!p) return;
      if (portfolioRows.some((r) => r.id === p.id)) return;
      if (portfolioRows.length >= MAX_PORTFOLIO_ROWS) return;
      const amt = sanitizeAmount(portfolioAddAmount && portfolioAddAmount.value);
      if (amt <= 0) return;
      const avg = portfolioAddAvg ? sanitizeAvgUsdField(portfolioAddAvg.value) : null;
      portfolioRows.push({ id: p.id, sym: p.sym, amount: amt, avg });
      if (portfolioAddAmount) portfolioAddAmount.value = '';
      if (portfolioAddAvg) portfolioAddAvg.value = '';
      portfolioPresetSelect.value = '';
      persistPortfolioRedrawPrices();
    });
  }

  if (portfolioAddCustomBtn) {
    portfolioAddCustomBtn.addEventListener('click', () => {
      const id = sanitizeCoinId(portfolioCustomId && portfolioCustomId.value);
      let sym = sanitizeSym(portfolioCustomSym && portfolioCustomSym.value);
      if (!id) return;
      if (!sym) sym = id.slice(0, 12).toUpperCase();
      if (portfolioRows.some((r) => r.id === id)) return;
      if (portfolioRows.length >= MAX_PORTFOLIO_ROWS) return;
      const amt = sanitizeAmount(portfolioCustomAmount && portfolioCustomAmount.value);
      if (amt <= 0) return;
      const avg = portfolioCustomAvg ? sanitizeAvgUsdField(portfolioCustomAvg.value) : null;
      portfolioRows.push({ id, sym, amount: amt, avg });
      if (portfolioCustomId) portfolioCustomId.value = '';
      if (portfolioCustomSym) portfolioCustomSym.value = '';
      if (portfolioCustomAmount) portfolioCustomAmount.value = '';
      if (portfolioCustomAvg) portfolioCustomAvg.value = '';
      persistPortfolioRedrawPrices();
    });
  }

  if (portfolioClearBtn) {
    portfolioClearBtn.addEventListener('click', () => {
      if (!portfolioRows.length) return;
      if (!window.confirm('Remove all portfolio holdings?')) return;
      portfolioRows = [];
      persistPortfolioRedrawPrices();
    });
  }

  renderPortfolioView({});
  loadPrices();
  loadSparklines();
  setInterval(function ccpPriceHttpFallback() {
    if (liveFeedMode === 'live') return;
    loadPrices();
  }, 45000);
  setInterval(function ccpPriceResyncWs() {
    if (liveFeedMode === 'live') loadPrices();
  }, 600000);
  setInterval(loadSparklines, 300000);

  function formatUtcLabel(ts) {
    if (!ts) return '';
    const d = Date.parse(ts);
    if (Number.isNaN(d)) return '';
    return new Date(d).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function fngZoneClassFromValue(v) {
    if (v == null || Number.isNaN(v)) return '';
    if (v <= 24) return 'fng--extreme-fear';
    if (v <= 44) return 'fng--fear';
    if (v <= 55) return 'fng--neutral';
    if (v <= 74) return 'fng--greed';
    return 'fng--extreme-greed';
  }

  function formatFngCountdown(sec) {
    if (sec == null || Number.isNaN(sec) || sec < 0) return '';
    if (sec < 90) return `Next update in ~${Math.round(sec)}s`;
    if (sec < 7200) return `Next update in ~${Math.round(sec / 60)} min`;
    return `Next update in ~${(sec / 3600).toFixed(1)} h`;
  }

  function parseFngValue(raw) {
    if (raw == null) return null;
    if (typeof raw === 'number' && Number.isFinite(raw)) return Math.max(0, Math.min(100, Math.round(raw)));
    if (typeof raw === 'string' && raw.trim() !== '') {
      const n = parseInt(raw, 10);
      return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null;
    }
    return null;
  }

  function renderFng(data) {
    const panel = document.getElementById('fng-panel');
    const valueEl = document.getElementById('fng-value');
    const classEl = document.getElementById('fng-classification');
    const markerEl = document.getElementById('fng-marker');
    const metaEl = document.getElementById('fng-meta');
    const updatedEl = document.getElementById('fng-updated');
    const errEl = document.getElementById('fng-error');
    if (!panel || !valueEl || !classEl || !markerEl || !metaEl) return;
    if (errEl) errEl.classList.add('hidden');
    const v = parseFngValue(data && data.value);
    if (v == null) {
      valueEl.textContent = '—';
      classEl.textContent = '';
      classEl.className = 'fng-classification';
      markerEl.style.left = '0%';
      metaEl.textContent = '';
      if (updatedEl) updatedEl.textContent = '';
      if (errEl) {
        errEl.textContent = 'Fear & Greed data unavailable right now.';
        errEl.classList.remove('hidden');
      }
      return;
    }
    valueEl.textContent = String(v);
    const label = (data.classification && String(data.classification).trim()) || '';
    classEl.textContent = label;
    classEl.className = 'fng-classification ' + fngZoneClassFromValue(v);
    markerEl.style.left = `${Math.max(0, Math.min(100, v))}%`;
    const parts = [];
    const nu = formatFngCountdown(data.next_update_in_seconds);
    if (nu) parts.push(nu);
    const stamp = data.updated_at ? formatUtcLabel(data.updated_at) : '';
    if (stamp) parts.push(`Index time · ${stamp}`);
    metaEl.textContent = parts.join(' · ');
    if (updatedEl) updatedEl.textContent = stamp ? `Updated · ${stamp}` : 'Updated';
  }

  async function loadFng() {
    const panel = document.getElementById('fng-panel');
    const updatedEl = document.getElementById('fng-updated');
    const errEl = document.getElementById('fng-error');
    if (!panel) return;
    try {
      const res = await fetch('/api/markets/fear-greed', { headers: ccpApiAuthHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const msg =
          typeof d === 'string' ? d : (d && JSON.stringify(d)) || res.statusText || 'Failed';
        throw new Error(msg);
      }
      renderFng(data);
    } catch (e) {
      if (errEl) {
        errEl.textContent = 'Could not load Fear & Greed index.';
        errEl.classList.remove('hidden');
      }
      if (updatedEl) updatedEl.textContent = '';
    }
  }

  function renderOil(data) {
    if (!oilList || !oilUpdated || !oilError) return;
    oilError.classList.add('hidden');
    const items = data.items || [];
    oilList.innerHTML = '';
    if (!items.length) {
      const p = document.createElement('div');
      p.className = 'news-snippet';
      p.textContent = 'No oil quote data right now.';
      oilList.appendChild(p);
      oilUpdated.textContent = '';
      return;
    }
    for (const it of items) {
      const ch = it.change_pct;
      const chClass = ch > 0 ? 'up' : ch < 0 ? 'down' : 'neutral';
      const chText = ch == null || Number.isNaN(ch) ? '24h —' : `24h ${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%`;
      const series = it.sparkline;
      const sparkHtml =
        Array.isArray(series) && series.length >= 2 ? buildSparklineSvg(series, ch) : '';
      const row = document.createElement('div');
      row.className = 'oil-row';
      row.innerHTML = `
        <span class="label">${escapeHtml(it.label || it.symbol || 'Oil')}</span>
        <span class="spark-cell">${sparkHtml}</span>
        <span class="usd">${formatUsd(it.usd)}</span>
        <span class="chg ${chClass}">${chText}</span>`;
      oilList.appendChild(row);
    }
    const stamp = formatUtcLabel(data.fetched_at);
    oilUpdated.textContent = stamp ? `Updated · ${stamp}` : 'Updated';
  }

  async function loadOil() {
    if (!oilList) return;
    try {
      const res = await fetch('/api/markets/oil', { headers: ccpApiAuthHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const msg =
          typeof d === 'string' ? d : (d && JSON.stringify(d)) || res.statusText || 'Failed';
        throw new Error(msg);
      }
      renderOil(data);
    } catch (e) {
      oilError.textContent = 'Could not load oil prices.';
      oilError.classList.remove('hidden');
      oilUpdated.textContent = '';
    }
  }

  function renderFedNews(data) {
    if (!fedList || !fedUpdated || !fedError) return;
    fedError.classList.add('hidden');
    const items = data.items || [];
    fedList.innerHTML = '';
    if (!items.length) {
      const p = document.createElement('div');
      p.className = 'news-snippet';
      p.textContent = 'No Federal Reserve rate-cut headlines right now.';
      fedList.appendChild(p);
      fedUpdated.textContent = '';
      return;
    }
    for (const it of items.slice(0, 4)) {
      const el = document.createElement('div');
      el.className = 'fed-item';
      const href = it.link && /^https?:\/\//i.test(it.link) ? it.link : '#';
      const t = it.title || 'Untitled';
      const when = formatNewsTime(it.published);
      el.innerHTML = `
        <a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t)}</a>
        <div class="fed-time">${escapeHtml(when)}</div>`;
      fedList.appendChild(el);
    }
    const stamp = formatUtcLabel(data.fetched_at);
    fedUpdated.textContent = stamp ? `Updated · ${stamp}` : 'Updated';
  }

  async function loadFedNews() {
    if (!fedList) return;
    try {
      const res = await fetch('/api/news/fed', { headers: ccpApiAuthHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const msg =
          typeof d === 'string' ? d : (d && JSON.stringify(d)) || res.statusText || 'Failed';
        throw new Error(msg);
      }
      renderFedNews(data);
    } catch (e) {
      fedError.textContent = 'Could not load Federal Reserve news.';
      fedError.classList.remove('hidden');
      fedUpdated.textContent = '';
    }
  }

  loadOil();
  loadFng();
  loadFedNews();
  setInterval(loadOil, 300000);
  setInterval(loadFng, 300000);
  setInterval(loadFedNews, 300000);

  function formatNewsTime(pub) {
    if (!pub) return '';
    const d = Date.parse(pub);
    if (!Number.isNaN(d)) {
      return new Date(d).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    const parts = pub.split(',');
    return (parts[parts.length - 1] || pub).trim();
  }

  function sentimentTriClass(s) {
    if (s === 'positive') return 'up';
    if (s === 'negative') return 'down';
    return 'neutral';
  }

  function renderNews(data) {
    if (!newsList || !newsUpdated) return;
    newsError.classList.add('hidden');
    const items = data.items || [];
    lastNewsItems = Array.isArray(items) ? items.slice(0, 25) : [];
    newsList.innerHTML = '';
    if (!items.length) {
      const p = document.createElement('p');
      p.className = 'news-snippet';
      p.textContent = 'No headlines right now.';
      newsList.appendChild(p);
      newsUpdated.textContent = '';
      updateSessionDeskUI();
      return;
    }

    for (const it of items.slice(0, 15)) {
      const row = document.createElement('div');
      row.className = 'news-item';

      const meta = document.createElement('div');
      meta.className = 'news-item-meta';

      const timeEl = document.createElement('span');
      timeEl.className = 'news-time';
      timeEl.textContent = formatNewsTime(it.published);

      const sent = document.createElement('span');
      const label = it.sentiment === 'positive' || it.sentiment === 'negative' ? it.sentiment : 'neutral';
      sent.className = `sentiment ${label}`;

      const tri = document.createElement('span');
      tri.className = `sent-tri ${sentimentTriClass(label)}`;
      tri.setAttribute('aria-hidden', 'true');

      const sentLabel = document.createElement('span');
      sentLabel.textContent = label.charAt(0).toUpperCase() + label.slice(1);

      sent.appendChild(tri);
      sent.appendChild(sentLabel);
      meta.appendChild(timeEl);
      meta.appendChild(sent);

      const titleRow = document.createElement('div');
      titleRow.className = 'news-title';
      const a = document.createElement('a');
      if (it.link && /^https?:\/\//i.test(it.link)) {
        a.href = it.link;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
      } else {
        a.href = '#';
        a.addEventListener('click', (e) => e.preventDefault());
      }
      a.textContent = it.title || 'Untitled';
      titleRow.appendChild(a);

      row.appendChild(meta);
      row.appendChild(titleRow);

      if (it.summary) {
        const sn = document.createElement('div');
        sn.className = 'news-snippet';
        sn.textContent = it.summary;
        row.appendChild(sn);
      }

      const src = document.createElement('div');
      src.className = 'news-source';
      src.textContent = it.source || '';
      row.appendChild(src);

      newsList.appendChild(row);
    }

    newsUpdated.textContent = data.fetched_at ? `Feed refreshed · ${data.fetched_at}` : 'Feed refreshed';
    updateSessionDeskUI();
  }

  async function loadNews() {
    if (!newsList) return;
    try {
      const res = await fetch('/api/news', { headers: ccpApiAuthHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const msg =
          typeof d === 'string' ? d : (d && JSON.stringify(d)) || res.statusText || 'Failed';
        throw new Error(msg);
      }
      renderNews(data);
    } catch (e) {
      newsError.textContent = 'Could not load news (RSS).';
      newsError.classList.remove('hidden');
      newsUpdated.textContent = '';
    }
  }

  function clipText(s, n) {
    const t = String(s || '')
      .replace(/\s+/g, ' ')
      .trim();
    if (t.length <= n) return t;
    return t.slice(0, n - 1) + '…';
  }

  function headlineMentionsCoin(sym, coinId, blob) {
    const hay = String(blob).toLowerCase();
    const sy = String(sym).toLowerCase().trim();
    if (sy.length >= 2) {
      try {
        const re = new RegExp(`\\b${sy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
        if (re.test(blob)) return true;
      } catch {
        if (hay.includes(sy)) return true;
      }
    }
    const id = String(coinId).toLowerCase();
    for (const part of id.split('-')) {
      if (part.length < 4) continue;
      if (hay.includes(part)) return true;
    }
    const extras = COIN_NEWS_EXTRA[id];
    if (extras) {
      for (const x of extras) {
        if (hay.includes(String(x).toLowerCase())) return true;
      }
    }
    return false;
  }

  function pickHeadlinesForWhyMove(sym, coinId, items, maxRel, maxFb) {
    const rel = [];
    const rest = [];
    for (const it of items) {
      if (!it || typeof it !== 'object') continue;
      const blob = `${it.title || ''} ${it.summary || ''}`;
      if (headlineMentionsCoin(sym, coinId, blob)) rel.push(it);
      else rest.push(it);
    }
    if (rel.length) return { lines: rel.slice(0, maxRel), usedFallback: false };
    return { lines: rest.slice(0, maxFb), usedFallback: true };
  }

  function formatHeadlineBullet(it, idx) {
    const sent = it.sentiment === 'positive' || it.sentiment === 'negative' ? it.sentiment : 'neutral';
    const title = clipText(it.title || 'Untitled', 140);
    const sum = it.summary ? clipText(it.summary, 160) : '';
    const src = it.source ? ` — ${clipText(it.source, 40)}` : '';
    const time = formatNewsTime(it.published);
    const sentTag = sent.charAt(0).toUpperCase() + sent.slice(1);
    const body = sum ? `${title} — ${sum}` : title;
    return `${idx}. [${sentTag}] ${body}${src}${time ? ` (${time})` : ''}`;
  }

  function buildWhyMovePrompt(sym, coinId) {
    const row = lastPricesPayload[coinId];
    const ts = new Date().toLocaleString();
    let priceBlock = `Snapshot time (browser): ${ts}\nCoinGecko id: ${coinId}\nTicker/label: ${sym}\n`;
    if (!row || row.usd == null || Number.isNaN(Number(row.usd))) {
      priceBlock +=
        'Spot USD: (no live price in this session yet — explain typical drivers for this asset and note missing price.)\n';
    } else {
      priceBlock += `Spot USD (approx.): ${formatUsd(row.usd)}\n`;
      const ch = row.usd_24h_change;
      if (ch != null && !Number.isNaN(Number(ch))) {
        priceBlock += `24h change (reported): ${ch >= 0 ? '+' : ''}${Number(ch).toFixed(2)}%\n`;
      } else {
        priceBlock += '24h change: not available in snapshot\n';
      }
    }

    const items = Array.isArray(lastNewsItems) ? lastNewsItems : [];
    const { lines, usedFallback } = pickHeadlinesForWhyMove(sym, coinId, items, 10, 8);
    let newsBlock = '';
    if (!lines.length) {
      newsBlock =
        'Recent RSS headlines: none loaded — say news was unavailable and reason only from macro/sentiment with caveats.';
    } else {
      const intro = usedFallback
        ? `No headlines clearly matched this coin by text; sample from the latest app RSS bundle follows — flag when a story may not apply to ${sym}.`
        : `Headlines below were auto-filtered when title/summary likely mentions ${sym} or parts of "${coinId}" — still verify relevance.`;
      newsBlock = `${intro}\n\n${lines.map((it, i) => formatHeadlineBullet(it, i + 1)).join('\n')}`;
    }

    return (
      `Why did ${sym} move? Give a concise, honest take (bullets ok): plausible drivers, what is uncertain, and whether headlines actually tie to this coin.\n\n` +
      `${priceBlock}\n` +
      `${newsBlock}\n\n` +
      `Label speculation as speculation. Do not invent prices.`
    );
  }

  async function sendWhyMoveForCoin(sym, coinId) {
    const col = document.querySelector('.chat-column');
    if (col) col.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    const prompt = buildWhyMovePrompt(sym, coinId);
    await runChatPipeline({
      displayUser: prompt,
      storedUserContent: prompt,
      apiUserContent: prompt,
      clearAttachmentsOnSuccess: false,
    });
  }

  function setLiveFeedStatus(mode, titleHint) {
    liveFeedMode = mode;
    if (!liveFeedStatusEl) return;
    liveFeedStatusEl.classList.remove('live-feed--live', 'live-feed--poll', 'live-feed--warn');
    let label = '';
    if (mode === 'live') {
      liveFeedStatusEl.classList.add('live-feed--live');
      label = 'Realtime';
      liveFeedStatusEl.title = titleHint || 'WebSocket feed active (~1s prices)';
    } else if (mode === 'connecting') {
      liveFeedStatusEl.classList.add('live-feed--warn');
      label = 'Connecting…';
      liveFeedStatusEl.title = titleHint || 'Connecting to live feed';
    } else {
      liveFeedStatusEl.classList.add('live-feed--poll');
      label = 'Polling';
      liveFeedStatusEl.title = titleHint || 'Using HTTP refresh (fallback)';
    }
    liveFeedStatusEl.textContent = label;
  }

  function liveWsUrl() {
    const p = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let base = p + '//' + location.host + '/api/ws/live';
    try {
      const k = localStorage.getItem(CCP_API_KEY_STORAGE);
      if (k && String(k).trim()) {
        base += '?api_key=' + encodeURIComponent(String(k).trim());
      }
    } catch (e) {
      /* ignore */
    }
    return base;
  }

  function sendLiveSubscribe() {
    if (!liveWs || liveWs.readyState !== WebSocket.OPEN) return;
    try {
      liveWs.send(JSON.stringify({ type: 'subscribe', ids: buildCombinedIdsQuery() }));
    } catch (err) {}
  }

  function connectLiveFeed() {
    if (!('WebSocket' in window)) {
      setLiveFeedStatus('polling');
      return;
    }
    try {
      liveWs = new WebSocket(liveWsUrl());
    } catch (e) {
      setLiveFeedStatus('polling');
      return;
    }
    setLiveFeedStatus('connecting');
    liveWs.onopen = () => {
      liveWsBackoffMs = 2000;
      setLiveFeedStatus('live');
      sendLiveSubscribe();
    };
    liveWs.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (x) {
        return;
      }
      if (!msg || !msg.type) return;
      if (msg.type === 'prices' && msg.data && typeof msg.data === 'object') {
        renderPrices(msg.data);
      } else if (msg.type === 'news' && msg.data) {
        renderNews(msg.data);
      } else if (msg.type === 'macro') {
        if (msg.oil) renderOil(msg.oil);
        if (msg.fed) renderFedNews(msg.fed);
        if (msg.fng) renderFng(msg.fng);
      }
    };
    liveWs.onerror = () => {};
    liveWs.onclose = () => {
      liveWs = null;
      setLiveFeedStatus('connecting', 'Reconnecting…');
      setTimeout(connectLiveFeed, liveWsBackoffMs);
      liveWsBackoffMs = Math.min(liveWsBackoffMs * 2, 60000);
    };
  }

  loadNews();
  setInterval(function ccpNewsHttpFallback() {
    if (liveFeedMode === 'live') return;
    loadNews();
  }, 120000);
  connectLiveFeed();

  function formatContent(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
      .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code>${escapeHtml(code.trim())}</code></pre>`
      )
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function scrollChatToBottom() {
    const wrap = messagesEl.closest('.messages-scroll');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  }

  function addMessage(role, content, isError = false) {
    const div = document.createElement('div');
    div.className = `msg ${role}${isError ? ' error' : ''}`;
    div.innerHTML = `<span class="role">${role}</span><div class="content">${formatContent(content)}</div>`;
    messagesEl.appendChild(div);
    scrollChatToBottom();
    return div;
  }

  function setTyping(div, on) {
    const content = div.querySelector('.content');
    if (on) content.classList.add('typing');
    else content.classList.remove('typing');
  }

  if (chatAttachBtn && chatFileInput) {
    chatAttachBtn.addEventListener('click', () => chatFileInput.click());
    chatFileInput.addEventListener('change', () => handleFilesSelected(chatFileInput.files));
  }

  function setWhyMoveBusy(on) {
    if (!pricesList) return;
    pricesList.querySelectorAll('.why-move-btn').forEach((b) => {
      b.disabled = Boolean(on);
    });
  }

  async function runChatPipeline({
    displayUser,
    storedUserContent,
    apiUserContent,
    clearAttachmentsOnSuccess = true,
  }) {
    if (!messagesEl || !form || !sendBtn) return;
    addMessage('user', displayUser);
    conversation.push({ role: 'user', content: storedUserContent });
    persistChatSessions();

    const messagesForApi = [
      ...conversation.slice(0, -1),
      { role: 'user', content: apiUserContent },
    ];

    const botDiv = addMessage('assistant', '');
    setTyping(botDiv, true);
    sendBtn.disabled = true;
    if (chatAttachBtn) chatAttachBtn.disabled = true;
    setWhyMoveBusy(true);

    let structuredTrade = null;
    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/x-ndjson',
          ...ccpApiAuthHeaders(),
        },
        body: JSON.stringify({ messages: messagesForApi }),
      });

      if (!res.ok) {
        const t = await res.text();
        let msg = t;
        try {
          const j = JSON.parse(t);
          if (typeof j.detail === 'string') msg = j.detail;
          else if (j.detail != null) msg = JSON.stringify(j.detail);
        } catch (x) {
          /* use raw text */
        }
        setTyping(botDiv, false);
        botDiv.querySelector('.content').innerHTML = formatContent(
          msg || res.statusText || 'Request failed.'
        );
        botDiv.classList.add('error');
        return;
      }

      const reader = res.body && res.body.getReader ? res.body.getReader() : null;
      if (!reader) {
        setTyping(botDiv, false);
        botDiv.querySelector('.content').innerHTML = formatContent('Streaming not supported in this browser.');
        botDiv.classList.add('error');
        return;
      }

      const dec = new TextDecoder();
      let buf = '';
      let full = '';
      let gotChunk = false;

      const applyLine = (line) => {
        if (!line) return 'continue';
        let obj;
        try {
          obj = JSON.parse(line);
        } catch (x) {
          return 'continue';
        }
        if (obj.error) {
          setTyping(botDiv, false);
          botDiv.classList.remove('streaming');
          botDiv.querySelector('.content').innerHTML = formatContent(
            full ? `${full}\n\n— ${obj.error}` : obj.error
          );
          botDiv.classList.add('error');
          return 'error';
        }
        if (obj.trade && typeof obj.trade === 'object') {
          structuredTrade = obj.trade;
          setTyping(botDiv, false);
          renderTradeCard(botDiv, obj.trade);
          scrollChatToBottom();
        }
        if (typeof obj.c === 'string' && obj.c) {
          if (!gotChunk) {
            gotChunk = true;
            setTyping(botDiv, false);
            botDiv.classList.add('streaming');
          }
          full += obj.c;
          botDiv.querySelector('.content').innerHTML = formatContent(full);
          scrollChatToBottom();
        }
        if (obj.done) {
          if (obj.trade && typeof obj.trade === 'object') {
            structuredTrade = obj.trade;
            renderTradeCard(botDiv, obj.trade);
          }
          setTyping(botDiv, false);
          botDiv.classList.remove('streaming');
        }
        return 'continue';
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          const r = applyLine(line);
          if (r === 'error') {
            return;
          }
        }
      }
      buf += dec.decode();
      const tail = buf.trim();
      if (tail) {
        const r = applyLine(tail);
        if (r === 'error') {
          return;
        }
      }

      setTyping(botDiv, false);
      botDiv.classList.remove('streaming');
      const reply = full.trim();
      const stored = reply || '(No text returned.)';
      if (!reply) {
        botDiv.querySelector('.content').innerHTML = formatContent('(Empty reply.)');
      }
      conversation.push({ role: 'assistant', content: stored });
      if (structuredTrade) {
        maybeCaptureStanceFromTrade(structuredTrade);
      } else {
        maybeCaptureStance(stored);
      }
      persistChatSessions();
      if (clearAttachmentsOnSuccess) {
        pendingAttachments = [];
        renderAttachChips();
        setAttachStatus('');
      }
    } catch (err) {
      setTyping(botDiv, false);
      botDiv.classList.remove('streaming');
      botDiv.querySelector('.content').innerHTML = formatContent(
        'Network error. Is the server running? Check your API key (Groq) or Ollama.'
      );
      botDiv.classList.add('error');
    } finally {
      sendBtn.disabled = false;
      if (chatAttachBtn) chatAttachBtn.disabled = false;
      setWhyMoveBusy(false);
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text && !pendingAttachments.length) return;

    const names = pendingAttachments.map((a) => a.name);
    const storedUserContent = text
      ? names.length
        ? `${text}\n\n(Attached: ${names.join(', ')})`
        : text
      : names.length
        ? `(Attached: ${names.join(', ')})`
        : '';
    const displayUser = text
      ? names.length
        ? `${text}\n\n📎 ${names.join(', ')}`
        : text
      : names.length
        ? `📎 ${names.join(', ')}`
        : '';
    const snapshot = pendingAttachments.map((a) => ({ name: a.name, content: a.content }));
    const apiUserContent = mergeAttachmentsForApi(text, snapshot);

    input.value = '';
    await runChatPipeline({
      displayUser,
      storedUserContent,
      apiUserContent,
      clearAttachmentsOnSuccess: true,
    });
  });

  if (pricesList) {
    pricesList.addEventListener('click', (e) => {
      const btn = e.target.closest('.why-move-btn');
      if (!btn || !pricesList.contains(btn)) return;
      if (btn.disabled) return;
      const sym = btn.getAttribute('data-coin-sym') || '';
      const id = btn.getAttribute('data-coin-id') || '';
      if (!sym || !id) return;
      void sendWhyMoveForCoin(sym, id);
    });
  }

  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    form.requestSubmit();
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });

  const chatSaveBtn = document.getElementById('chat-save');
  const chatNewBtn = document.getElementById('chat-new');
  const chatHistoryToggle = document.getElementById('chat-history-toggle');
  const chatHistoryPanel = document.getElementById('chat-history-panel');
  const chatSaveStatus = document.getElementById('chat-save-status');

  if (chatSaveBtn) {
    chatSaveBtn.addEventListener('click', () => {
      const s = chatSessions.find((x) => x.id === activeSessionId);
      if (!s) return;
      const name = prompt('Name this chat (optional)', s.title || '');
      if (name === null) return;
      if (name.trim()) s.title = name.trim();
      s.updatedAt = Date.now();
      persistChatSessions();
      renderHistoryList();
      if (chatSaveStatus) {
        chatSaveStatus.textContent = 'Saved';
        setTimeout(() => {
          chatSaveStatus.textContent = '';
        }, 2000);
      }
    });
  }

  if (chatNewBtn) {
    chatNewBtn.addEventListener('click', () => newChatSession());
  }

  if (chatHistoryToggle && chatHistoryPanel) {
    chatHistoryToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const hidden = chatHistoryPanel.classList.contains('hidden');
      if (hidden) {
        chatHistoryPanel.classList.remove('hidden');
        chatHistoryToggle.setAttribute('aria-expanded', 'true');
        chatHistoryPanel.setAttribute('aria-hidden', 'false');
        renderHistoryList();
      } else {
        chatHistoryPanel.classList.add('hidden');
        chatHistoryToggle.setAttribute('aria-expanded', 'false');
        chatHistoryPanel.setAttribute('aria-hidden', 'true');
      }
    });
  }

  document.addEventListener('click', (e) => {
    if (!chatHistoryPanel || chatHistoryPanel.classList.contains('hidden')) return;
    if (chatHistoryPanel.contains(e.target)) return;
    if (e.target.closest && e.target.closest('#chat-history-toggle')) return;
    chatHistoryPanel.classList.add('hidden');
    if (chatHistoryToggle) chatHistoryToggle.setAttribute('aria-expanded', 'false');
    chatHistoryPanel.setAttribute('aria-hidden', 'true');
  });

  const sessionDeskToggle = document.getElementById('session-desk-toggle');
  const sessionDeskPanel = document.getElementById('session-desk-panel');
  const sessionDeskExport = document.getElementById('session-desk-export');
  const sessionDeskClearLedger = document.getElementById('session-desk-clear-ledger');

  function exportSessionDeskSnapshot() {
    const p = computeSessionPulse();
    const body = JSON.stringify(
      {
        app: 'Crypto ChatPal',
        kind: 'session_desk_snapshot',
        exportedAt: new Date().toISOString(),
        marketPulse: p,
        stanceLog: stanceLedger,
      },
      null,
      2
    );
    const blob = new Blob([body], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `cryptochatpal-session-desk-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (sessionDeskToggle && sessionDeskPanel) {
    sessionDeskToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const hidden = sessionDeskPanel.classList.contains('hidden');
      if (hidden) {
        sessionDeskPanel.classList.remove('hidden');
        sessionDeskToggle.setAttribute('aria-expanded', 'true');
        sessionDeskPanel.setAttribute('aria-hidden', 'false');
        updateSessionDeskUI();
      } else {
        sessionDeskPanel.classList.add('hidden');
        sessionDeskToggle.setAttribute('aria-expanded', 'false');
        sessionDeskPanel.setAttribute('aria-hidden', 'true');
      }
    });
  }

  document.addEventListener('click', (e) => {
    if (!sessionDeskPanel || sessionDeskPanel.classList.contains('hidden')) return;
    if (sessionDeskPanel.contains(e.target)) return;
    if (e.target.closest && e.target.closest('#session-desk-toggle')) return;
    sessionDeskPanel.classList.add('hidden');
    if (sessionDeskToggle) sessionDeskToggle.setAttribute('aria-expanded', 'false');
    sessionDeskPanel.setAttribute('aria-hidden', 'true');
  });

  if (sessionDeskExport) {
    sessionDeskExport.addEventListener('click', () => exportSessionDeskSnapshot());
  }

  if (sessionDeskClearLedger) {
    sessionDeskClearLedger.addEventListener('click', () => {
      stanceLedger = [];
      saveStanceLedger();
      updateSessionDeskUI();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const hp = document.getElementById('chat-history-panel');
    const ht = document.getElementById('chat-history-toggle');
    if (hp && !hp.classList.contains('hidden')) {
      hp.classList.add('hidden');
      if (ht) ht.setAttribute('aria-expanded', 'false');
      hp.setAttribute('aria-hidden', 'true');
    }
    const dp = document.getElementById('session-desk-panel');
    const dt = document.getElementById('session-desk-toggle');
    if (dp && !dp.classList.contains('hidden')) {
      dp.classList.add('hidden');
      if (dt) dt.setAttribute('aria-expanded', 'false');
      dp.setAttribute('aria-hidden', 'true');
    }
  });

  // Now that `addMessage` exists, restore and render any saved conversation.
  renderConversation(conversation);
  renderHistoryList();
  updateSessionDeskUI();

  window.addEventListener('online', () => {
    sendLiveSubscribe();
    if (liveFeedMode !== 'live') loadPrices();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
  }
})();
