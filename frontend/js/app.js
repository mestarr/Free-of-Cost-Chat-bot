(function () {
  const messagesEl = document.getElementById('messages');
  const form = document.getElementById('form');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
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
  const oilList = document.getElementById('oil-list');
  const oilUpdated = document.getElementById('oil-updated');
  const oilError = document.getElementById('oil-error');
  const fedList = document.getElementById('fed-list');
  const fedUpdated = document.getElementById('fed-updated');
  const fedError = document.getElementById('fed-error');

  const PRICE_STORAGE_KEY = 'cryptochatpal_price_rows';
  const MAX_PRICE_ROWS = 30;

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
  let lastPricesPayload = {};
  let lastRenderKey = '';

  let conversation = [];

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

  function renderPrices(data) {
    pricesError.classList.add('hidden');
    lastPricesPayload = data && typeof data === 'object' ? data : {};
    const orderKey = priceRows.map((r) => r.id).join('|');
    const composite = JSON.stringify(lastPricesPayload) + '|' + orderKey;
    if (composite === lastRenderKey) {
      pricesUpdated.textContent = 'Live · ' + new Date().toLocaleTimeString();
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
          <span class="usd">—</span>
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
      div.innerHTML = `
          <span class="sym">${escapeHtml(sym)}</span>
          <span class="usd">${formatUsd(row.usd)}</span>
          <span class="chg ${chClass}">${chText}</span>`;
      pricesList.appendChild(div);
    }
    pricesUpdated.textContent = 'Live · ' + new Date().toLocaleTimeString();
  }

  async function loadPrices() {
    try {
      const url = '/api/prices?ids=' + encodeURIComponent(buildIdsQuery());
      const res = await fetch(url);
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
    renderPrices(lastPricesPayload);
    loadPrices();
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

  loadPrices();
  setInterval(loadPrices, 60000);

  function formatUtcLabel(ts) {
    if (!ts) return '';
    const d = Date.parse(ts);
    if (Number.isNaN(d)) return '';
    return new Date(d).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
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
      const row = document.createElement('div');
      row.className = 'oil-row';
      row.innerHTML = `
        <span class="label">${escapeHtml(it.label || it.symbol || 'Oil')}</span>
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
      const res = await fetch('/api/markets/oil');
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
      const res = await fetch('/api/news/fed');
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
  loadFedNews();
  setInterval(loadOil, 300000);
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
    newsList.innerHTML = '';
    if (!items.length) {
      const p = document.createElement('p');
      p.className = 'news-snippet';
      p.textContent = 'No headlines right now.';
      newsList.appendChild(p);
      newsUpdated.textContent = '';
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
  }

  async function loadNews() {
    if (!newsList) return;
    try {
      const res = await fetch('/api/news');
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

  loadNews();
  setInterval(loadNews, 120000);

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

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    addMessage('user', text);
    conversation.push({ role: 'user', content: text });

    const botDiv = addMessage('assistant', '');
    setTyping(botDiv, true);
    sendBtn.disabled = true;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: conversation }),
      });
      const data = await res.json().catch(() => ({}));
      setTyping(botDiv, false);

      if (!res.ok) {
        botDiv.querySelector('.content').innerHTML = formatContent(
          data.detail || res.statusText || 'Request failed.'
        );
        botDiv.classList.add('error');
        return;
      }
      const reply = data.message || '';
      botDiv.querySelector('.content').innerHTML = formatContent(reply);
      conversation.push({ role: 'assistant', content: reply });
    } catch (err) {
      setTyping(botDiv, false);
      botDiv.querySelector('.content').innerHTML = formatContent(
        'Network error. Is the server running? Check your API key (Groq) or Ollama.'
      );
      botDiv.classList.add('error');
    } finally {
      sendBtn.disabled = false;
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    form.requestSubmit();
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });
})();
