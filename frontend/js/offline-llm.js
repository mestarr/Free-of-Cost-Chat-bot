/**
 * In-browser offline chat via WebLLM (WebGPU). Loaded dynamically from CDN on first use.
 * Model weights are cached by the browser after the first successful download.
 */
(function (global) {
  const WEBLLM_MODULE = 'https://esm.run/@mlc-ai/web-llm';
  const MODEL_PRIMARY = 'Llama-3.2-1B-Instruct-q4f16_1-MLC';
  const MODEL_FALLBACK = 'SmolLM2-360M-Instruct-q4f16_1-MLC';

  let engine = null;
  let loadPromise = null;
  let loadedModelId = null;
  let lastProgressText = '';

  function isWebGpuSupported() {
    return typeof global.navigator !== 'undefined' && 'gpu' in global.navigator;
  }

  async function importWebLlm() {
    return import(/* webpackIgnore: true */ WEBLLM_MODULE);
  }

  async function createEngine(modelId, onProgress) {
    const webllm = await importWebLlm();
    const CreateMLCEngine = webllm.CreateMLCEngine || webllm.default?.CreateMLCEngine;
    if (!CreateMLCEngine) {
      throw new Error('WebLLM module did not export CreateMLCEngine');
    }
    return CreateMLCEngine(modelId, {
      initProgressCallback: (report) => {
        lastProgressText = report?.text || '';
        if (typeof onProgress === 'function') {
          onProgress(report);
        }
      },
    });
  }

  async function loadModel(onProgress, modelId) {
    if (!isWebGpuSupported()) {
      throw new Error('WebGPU is not available in this browser. Try Chrome or Edge on desktop.');
    }
    const target = modelId || MODEL_PRIMARY;
    if (engine && loadedModelId === target) {
      return { modelId: loadedModelId, cached: true };
    }
    if (loadPromise) {
      return loadPromise;
    }
    loadPromise = (async () => {
      try {
        engine = await createEngine(target, onProgress);
        loadedModelId = target;
        return { modelId: loadedModelId, cached: false };
      } catch (err) {
        if (target !== MODEL_FALLBACK) {
          engine = await createEngine(MODEL_FALLBACK, onProgress);
          loadedModelId = MODEL_FALLBACK;
          return { modelId: loadedModelId, cached: false, fallback: true };
        }
        throw err;
      } finally {
        loadPromise = null;
      }
    })();
    return loadPromise;
  }

  function unloadModel() {
    engine = null;
    loadedModelId = null;
    loadPromise = null;
  }

  function isModelReady() {
    return Boolean(engine && loadedModelId);
  }

  function getStatus() {
    return {
      webGpu: isWebGpuSupported(),
      ready: isModelReady(),
      modelId: loadedModelId,
      progress: lastProgressText,
    };
  }

  function buildSystemPrompt(marketContext) {
    const ctx = (marketContext || '').trim();
    const base =
      'You are Crypto ChatPal in offline mode. Answer crypto questions clearly and concisely. ' +
      'Use cached market context when provided; label numbers as from cache (may be stale). ' +
      'Do not invent live prices or headlines. General education is allowed when not contradicting cache.';
    return ctx ? `${base}\n\n${ctx}` : base;
  }

  function formatMarketContext(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return '';
    const lines = [];
    if (snapshot.saved_at) {
      lines.push(`Cache saved: ${snapshot.saved_at}`);
    }
    const prices = snapshot.prices;
    if (prices && typeof prices === 'object') {
      lines.push('Cached watchlist prices (USD):');
      for (const [id, row] of Object.entries(prices)) {
        if (!row || row.usd == null) continue;
        const ch =
          row.usd_24h_change != null && !Number.isNaN(Number(row.usd_24h_change))
            ? ` (${Number(row.usd_24h_change).toFixed(2)}% 24h)`
            : '';
        lines.push(`- ${id}: $${Number(row.usd).toLocaleString()}${ch}`);
      }
    }
    const news = snapshot.news;
    if (Array.isArray(news) && news.length) {
      lines.push('Cached headlines:');
      for (const it of news.slice(0, 12)) {
        if (!it || !it.title) continue;
        lines.push(`- [${it.source || 'news'}] ${it.title}`);
      }
    }
    return lines.join('\n');
  }

  /**
   * Stream a chat completion. messages: {role, content}[] (user/assistant only).
   */
  async function chatStream({ messages, marketSnapshot, onDelta, maxTokens = 768 }) {
    if (!engine) {
      throw new Error('Offline model not loaded. Download it once while online.');
    }
    const system = buildSystemPrompt(formatMarketContext(marketSnapshot));
    const apiMessages = [{ role: 'system', content: system }, ...messages];

    const stream = await engine.chat.completions.create({
      messages: apiMessages,
      temperature: 0.35,
      max_tokens: maxTokens,
      stream: true,
    });

    let full = '';
    for await (const chunk of stream) {
      const delta = chunk?.choices?.[0]?.delta?.content || '';
      if (delta) {
        full += delta;
        if (typeof onDelta === 'function') onDelta(full, delta);
      }
    }
    return full.trim();
  }

  global.CcpOfflineLlm = {
    MODEL_PRIMARY,
    MODEL_FALLBACK,
    isWebGpuSupported,
    isModelReady,
    getStatus,
    loadModel,
    unloadModel,
    buildSystemPrompt,
    formatMarketContext,
    chatStream,
  };
})(typeof window !== 'undefined' ? window : globalThis);
