"""Execute HeadRush authoring state transitions without external AI calls."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _run_ui(script: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for the rig authoring UI contract")
    source = Path(__file__).parents[1] / "src/fretwise/web/static/js/headrush.js"
    harness = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
class Element {
  constructor() {
    this.value = ''; this.hidden = false; this.disabled = false; this.checked = false;
    this.textContent = ''; this.innerHTML = ''; this.style = {}; this.handlers = {};
    this.children = []; this.attributes = {};
    this.classList = {add() {}, toggle() {}};
    this.fields = new Map();
  }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  querySelectorAll() { return this.children; }
  querySelector(selector) {
    if (!this.fields.has(selector)) this.fields.set(selector, new Element());
    return this.fields.get(selector);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  trigger(event = 'click', payload) { return this.handlers[event]?.(payload); }
}
const response = (data, status = 200) => ({
  ok: status < 400, status, json: async () => structuredClone(data),
  text: async () => typeof data === 'string' ? data : JSON.stringify(data),
  headers: { get: () => '' },
});
const settings = {
  mode: 'openai', canEdit: true, canGenerate: true, webSearch: false,
  openai: { model: 'gpt-5.6-terra', configured: true, editable: true, keySource: 'file' },
  anthropic: { model: 'claude-sonnet-4-6', configured: true, editable: true, keySource: 'file' },
};
(async () => {
  const encoded = fs.readFileSync(process.argv[1]).toString('base64');
  const module = await import('data:text/javascript;base64,' + encoded);
SCRIPT
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
""".replace("SCRIPT", script)
    completed = subprocess.run(
        [node, "-e", harness, str(source), str(
            Path(__file__).parents[1] / "src/fretwise/devices/headrush_core/studio/static/studio.js"
        )],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_api_explicit_trigger_and_stale_song_guard_with_manual_fallback() -> None:
    _run_ui(r"""
  const ids = new Map();
  const get = id => ids.get(id);
  for (const name of ['panel', 'prompt', 'paste', 'status', 'result', 'title', 'guidance',
    'download-btn', 'generate-btn', 'validate-btn', 'regen-btn', 'copy-btn',
    'close', 'mode-hint']) {
    ids.set('headrush-' + name, new Element());
  }
  const manualFields = [get('headrush-validate-btn'), get('headrush-regen-btn'),
    new Element(), new Element()];
  manualFields[2].children = [get('headrush-prompt'), get('headrush-copy-btn')];
  manualFields[3].children = [get('headrush-paste')];
  get('headrush-panel').children = manualFields;
  global.document = { getElementById: id => ids.get(id) || null };
  let song = { artist: 'Artist A', title: 'Song A' };
  let saved = 0;
  let finishGeneration;
  let ingestStatus = 200;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/rig-ai/settings') return response(settings);
    if (url === '/api/devices') return response({ active: 'headrush_core' });
    if (url.startsWith('/api/devices/headrush/prompt?')) return response('MANUAL PROMPT');
    if (url === '/api/devices/headrush/generate') {
      return new Promise(resolve => { finishGeneration = resolve; });
    }
    if (url === '/api/devices/headrush/ingest') return ingestStatus === 200
      ? response({binding: {}, blocks: 1, rig: 'manual', view: {blocks: []}})
      : response({detail: 'Invalid block'}, ingestStatus);
    throw Error('Unexpected URL: ' + url);
  };
  const api = module.initHeadrush({getSong: () => song, onSaved: () => saved++});
  await api.ready;
  await api.open();
  assert.equal(calls.filter(c => c.url.includes('/generate')).length, 0,
    'Opening must not spend API credit');
  assert.equal(calls.filter(c => c.url.includes('/prompt?')).length, 0);
  assert.equal(get('headrush-paste').disabled, true);
  assert.ok(manualFields.every(el => el.hidden));
  assert.equal(get('headrush-generate-btn').hidden, false);
  assert.match(get('headrush-mode-hint').textContent, /2 appels API maximum/);
  assert.equal(get('headrush-panel').attributes['data-hr-mode'], 'api');
  assert.equal(get('headrush-panel').style.height, '');
  get('headrush-panel').style.height = '350px';
  get('headrush-guidance').value = 'Studio, rhythm, humbuckers';
  const pending = get('headrush-generate-btn').trigger();
  assert.match(get('headrush-status').textContent,
    /Correction technique automatique si nécessaire/);
  await get('headrush-generate-btn').trigger();
  assert.equal(calls.filter(c => c.url.includes('/generate')).length, 1);
  assert.equal(get('headrush-generate-btn').disabled, true);
  const posted = JSON.parse(calls.find(c => c.url.includes('/generate')).options.body);
  assert.deepEqual(posted, {...song, guidance: 'Studio, rhythm, humbuckers'});
  song = {artist: 'Artist B', title: 'Song B'};
  finishGeneration(response({binding: {}, blocks: 1, rig: 'WRONG SONG', view: {blocks: []}}));
  await pending;
  assert.equal(saved, 0);
  assert.equal(get('headrush-result').innerHTML, '');
  await api.open();
  const retry = get('headrush-generate-btn').trigger();
  finishGeneration(response({detail: {detail: 'Provider unavailable'}}, 502));
  await retry;
  assert.match(get('headrush-status').textContent, /Provider unavailable/);
  assert.equal(get('headrush-generate-btn').disabled, false, 'Error must permit retry');
  const success = get('headrush-generate-btn').trigger();
  finishGeneration(response({binding: {}, blocks: 2, rig: 'Song B rig', view: {blocks: []},
    generation: {provider: 'openai', model: 'gpt-5.6-terra'}}));
  await success;
  assert.equal(saved, 1);
  assert.match(get('headrush-result').innerHTML, /Song B rig/);
  assert.match(get('headrush-status').textContent, /OpenAI/);
  settings.mode = 'manual';
  await api.refreshAiSettings();
  await api.open();
  assert.equal(get('headrush-prompt').value, 'MANUAL PROMPT');
  assert.equal(get('headrush-paste').disabled, false);
  assert.ok(manualFields.every(el => !el.hidden));
  assert.equal(get('headrush-generate-btn').hidden, true);
  assert.equal(get('headrush-panel').attributes['data-hr-mode'], 'manual');
  assert.equal(get('headrush-panel').style.height, '');
  get('headrush-paste').value = '{}';
  ingestStatus = 422;
  await get('headrush-validate-btn').trigger();
  assert.equal(saved, 1);
  assert.match(get('headrush-result').innerHTML, /Invalid block/);
  assert.equal(get('headrush-validate-btn').disabled, false);
  ingestStatus = 200;
  await get('headrush-validate-btn').trigger();
  assert.equal(saved, 2);
  assert.equal(get('headrush-download-btn').style.display, '');
  get('headrush-panel').style.height = '680px';
  settings.mode = 'openai';
  await api.refreshAiSettings();
  assert.equal(get('headrush-panel').style.height, '350px');
  settings.mode = 'manual';
  await api.refreshAiSettings();
  assert.equal(get('headrush-panel').style.height, '680px');
""")


def test_studio_generation_requires_click_and_ignores_previous_song_result() -> None:
    _run_ui(r"""
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const manual = ['st-gen', 'st-copy', 'st-prompt', 'st-paste', 'st-validate'].map(get);
  global.document = {
    getElementById: get,
    querySelectorAll: selector => selector === '[data-st-manual]' ? manual : [],
  };
  global.setInterval = () => 0;
  let finishGeneration;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/rig-ai/settings') return response(settings);
    if (url === '/api/devices/headrush/status') return response({reachable: false});
    if (url === '/api/devices/headrush/rigs') return response({rigs: []});
    if (url.startsWith('/api/devices/headrush/rig?')) return response({binding: null});
    if (url === '/api/devices/headrush/generate') {
      return new Promise(resolve => { finishGeneration = resolve; });
    }
    throw Error('Unexpected URL: ' + url);
  };
  const source = fs.readFileSync(process.argv[2], 'utf8').replace(
    /import\s*\{([\s\S]*?)\}\s*from '\/shared\/headrush.js';/,
    'const {$1} = module;'
  );
  new Function('module', source)(module);
  await new Promise(resolve => setImmediate(resolve));
  const selectSong = async (artist, title) => {
    get('st-open-artist').value = artist;
    get('st-open-title').value = title;
    get('st-open').trigger('submit', {preventDefault() {}});
    await new Promise(resolve => setImmediate(resolve));
  };
  await selectSong('Artist A', 'Song A');
  assert.equal(calls.filter(c => c.url.endsWith('/generate')).length, 0);
  assert.ok(manual.every(el => el.hidden && el.disabled));
  assert.match(get('st-ai-hint').textContent, /2 appels API maximum/);
  const pending = get('st-api-generate').trigger();
  assert.match(get('st-gen-status').textContent, /Correction technique automatique si nécessaire/);
  await get('st-api-generate').trigger();
  assert.equal(calls.filter(c => c.url.endsWith('/generate')).length, 1);
  await selectSong('Artist B', 'Song B');
  finishGeneration(response({binding: {}, blocks: 1, warnings: ['WRONG SONG']}));
  await pending;
  assert.equal(get('st-validate-result').innerHTML, '');
  assert.equal(get('tab-design').hidden, false);
  assert.equal(get('st-api-generate').disabled, false);
""")


def test_settings_secret_replacement_and_inactive_provider_controls() -> None:
    _run_ui(r"""
  const fields = new Map();
  const container = new Element();
  container.querySelector = selector => {
    if (!fields.has(selector)) fields.set(selector, new Element());
    return fields.get(selector);
  };
  const el = name => container.querySelector(`[data-ai="${name}"]`);
  const provider = name => container.querySelector(`[data-provider="${name}"]`);
  const posts = [];
  global.fetch = async (url, options) => {
    assert.equal(url, '/api/rig-ai/settings');
    if (options?.method === 'POST') {
      const body = JSON.parse(options.body);
      posts.push(body);
      settings.mode = body.mode;
    }
    return response(settings);
  };
  const controller = module.initRigAiSettings({container});
  await controller.refresh();
  assert.equal(el('openai-key').value, '');
  assert.equal(provider('anthropic').hidden, true);
  assert.equal(provider('anthropic').disabled, true);
  assert.equal(el('anthropic-key').disabled, true);
  assert.equal(provider('openai').hidden, false);
  el('openai-key').value = 'fake-new-key';
  el('save').trigger();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts.length, 1);
  assert.equal(posts[0].openai_api_key, 'fake-new-key');
  assert.equal(posts[0].anthropic_api_key, undefined);
  assert.equal(el('openai-key').value, '');
  el('openai-key').value = 'unsaved-fake-key';
  el('mode').value = 'manual';
  el('mode').trigger('change');
  assert.equal(el('openai-key').value, '');
  assert.equal(provider('openai').hidden, true);
  assert.equal(provider('anthropic').hidden, true);
  assert.equal(el('search-field').hidden, true);
  settings.canEdit = false;
  settings.openai.editable = false;
  await controller.refresh();
  assert.equal(el('save').hidden, true);
  assert.equal(el('mode').disabled, true);
  assert.equal(el('openai-key-field').hidden, true);
  assert.equal(el('openai-key').disabled, true);
  await el('save').trigger();
  assert.equal(posts.length, 1, 'Read-only preferences must not submit');
""")
