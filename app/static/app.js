const $ = (id) => document.getElementById(id);
const threadId = sessionStorage.getItem('vocabulary-thread') || crypto.randomUUID();
sessionStorage.setItem('vocabulary-thread', threadId);
let busy = false;
let currentSource = null;
let currentInput = null;

function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
function action(label, callback, parent) {
  const button = element('button', label, parent);
  button.type = 'button';
  button.onclick = () => Promise.resolve(callback()).catch(error => { $('notice').textContent = error.message; });
  return button;
}
async function api(path, method = 'GET', data) {
  const response = await fetch(path, { method, headers: data ? { 'Content-Type': 'application/json' } : {}, body: data ? JSON.stringify(data) : undefined });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || 'Request failed'));
  }
  return response.status === 204 ? null : response.json();
}
function activate(tab) {
  document.querySelectorAll('.tab').forEach(node => { node.hidden = node.id !== tab; });
  document.querySelectorAll('nav button').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.tab === tab)));
}
document.querySelectorAll('nav button').forEach(button => button.onclick = async () => {
  activate(button.dataset.tab);
  try {
    if (button.dataset.tab === 'learn') await today();
    if (button.dataset.tab === 'logs') await logs();
  } catch (error) { $('notice').textContent = error.message; }
});

async function stream(path, payload) {
  if (busy) return;
  busy = true;
  $('notice').textContent = '';
  const submit = $('agent-form').querySelector('button');
  submit.disabled = true;
  let ended = false;
  try {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    while (true) {
      const { done, value } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = pending.indexOf('\n\n')) >= 0) {
        const block = pending.slice(0, boundary);
        pending = pending.slice(boundary + 2);
        const type = block.split('\n').find(line => line.startsWith('event: '))?.slice(7);
        const data = block.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
        if (!data) continue;
        const event = JSON.parse(data);
        if (type === 'step') $('agent-progress').textContent = event.label || event.summary;
        if (type === 'scope_confirm') { showScope(event.data); ended = true; }
        if (type === 'clarify') { $('agent-progress').textContent = event.question; ended = true; }
        if (type === 'error') { $('notice').textContent = event.message; ended = true; }
        if (type === 'final') { showResult(event); ended = true; }
      }
      if (done) break;
    }
    if (!ended) throw new Error('The stream ended before a result. Retry with the same input.');
  } finally {
    busy = false;
    submit.disabled = false;
  }
}
$('agent-form').onsubmit = async event => {
  event.preventDefault();
  const user_input = $('instruction').value.trim();
  const text = $('article').value.trim() || null;
  const inputKey = JSON.stringify({ user_input, text });
  if (inputKey !== currentInput) { currentSource = crypto.randomUUID(); currentInput = inputKey; }
  $('scope').replaceChildren();
  $('result').replaceChildren();
  try { await stream('/api/agent/stream', { user_input, text, thread_id: threadId, source_id: currentSource }); }
  catch (error) { $('notice').textContent = error.message; }
};
function showScope(data) {
  const container = $('scope');
  container.replaceChildren();
  element('h3', data.message, container);
  element('p', `${data.pool_summary.unique_words} unique words; ${data.pool_summary.existing_words} already in your vocabulary.`, container);
  const send = (selection, free_text = null) => stream('/api/agent/respond', { type: 'scope_response', confirm_id: data.confirm_id, thread_id: threadId, selection, free_text });
  data.presets.forEach(preset => action(preset.label, () => send({ preset_id: preset.id }), container));
  const label = element('label', 'Custom scope instruction', container);
  const input = element('input', undefined, label);
  action('Apply instruction', () => send({}, input.value), container);
  const advanced = element('details', undefined, container);
  element('summary', 'Advanced filters', advanced);
  const topLabel = element('label', 'Maximum words (blank for all)', advanced);
  const top = element('input', undefined, topLabel); top.type = 'number'; top.min = '1'; top.max = '100';
  const posLabel = element('label', 'Part of speech', advanced);
  const pos = element('select', undefined, posLabel);
  ['all', 'noun', 'verb', 'adj', 'adv', 'prep', 'other'].forEach(value => element('option', value, pos));
  const existingLabel = element('label', 'New words only', advanced);
  const existing = element('input', undefined, existingLabel); existing.type = 'checkbox';
  const minimumLabel = element('label', 'Minimum occurrences', advanced);
  const minimum = element('input', undefined, minimumLabel); minimum.type = 'number'; minimum.min = '1'; minimum.value = '1';
  action('Apply filters', () => send({ filter: { top_n: top.value ? Number(top.value) : null, exclude_existing: existing.checked, pos_include: pos.value === 'all' ? [] : [pos.value], min_occurrences: Number(minimum.value) } }), advanced);
}
function showResult(result) {
  $('scope').replaceChildren();
  $('agent-progress').textContent = 'Completed';
  const target = $('result'); target.replaceChildren();
  element('p', result.summary, target);
  if (result.stats) element('pre', JSON.stringify(result.stats, null, 2), target);
  element('pre', JSON.stringify(result.highlights, null, 2), target);
  if (result.warnings.length) element('p', `Warnings: ${result.warnings.map(w => `${w.word || ''} ${w.reason}`).join('; ')}`, target);
  action('View log', async () => { activate('logs'); await loadLog(result.log_id); }, target);
}
$('search-form').onsubmit = async event => {
  event.preventDefault();
  try {
    const results = await api('/api/wiki/search?q=' + encodeURIComponent($('query').value));
    $('search-results').replaceChildren();
    if (!results.length) element('p', 'No matches.', $('search-results'));
    results.forEach(result => action(result.word, () => detail(result.word_id), $('search-results')));
  } catch (error) { $('notice').textContent = error.message; }
};
async function detail(id) {
  const data = await api('/api/words/' + id);
  const parent = $('detail'); parent.replaceChildren();
  element('h3', data.word.word, parent);
  element('p', data.word.definition_en || 'No English definition yet.', parent);
  element('p', data.word.definition_zh || '', parent);
  element('p', `${data.word.total_count} recorded occurrences.`, parent);
  const metadata = element('form', undefined, parent);
  const definitionLabel = element('label', 'English definition', metadata);
  const definition = element('textarea', undefined, definitionLabel); definition.value = data.word.definition_en || '';
  const translationLabel = element('label', 'Translation (optional; user-supplied)', metadata);
  const translation = element('input', undefined, translationLabel); translation.value = data.word.definition_zh || '';
  const saveMetadata = element('button', 'Save definitions', metadata); saveMetadata.type = 'submit';
  metadata.onsubmit = async event => { event.preventDefault(); try { await api('/api/words/' + id, 'PATCH', { definition_en: definition.value, definition_zh: translation.value }); await detail(id); } catch (error) { $('notice').textContent = error.message; } };
  for (const note of data.notes) {
    const card = element('div', undefined, parent); card.className = 'note';
    element('h4', note.title, card);
    const body = element('div', undefined, card); body.className = 'note-body';
    // Only server-rendered Markdown with raw HTML disabled reaches this HTML sink.
    body.innerHTML = note.body_html;
    body.querySelectorAll('a[href^="/words/"]').forEach(link => { link.onclick = event => { event.preventDefault(); detail(Number(link.getAttribute('href').split('/').pop())).catch(error => { $('notice').textContent = error.message; }); }; });
    action('Edit note', () => {
      const editor = element('form', undefined, card);
      const editTitle = element('input', undefined, editor); editTitle.value = note.title;
      const editBody = element('textarea', undefined, editor); editBody.value = note.body_md;
      const update = element('button', 'Update note', editor); update.type = 'submit';
      editor.onsubmit = async event => { event.preventDefault(); try { await api('/api/wiki/notes/' + note.id, 'PUT', { title: editTitle.value, body_md: editBody.value }); await detail(id); } catch (error) { $('notice').textContent = error.message; } };
    }, card);
    action('Delete note', async () => { await api('/api/wiki/notes/' + note.id, 'DELETE'); await detail(id); }, card);
  }
  const noteForm = element('form', undefined, parent);
  const titleLabel = element('label', 'New note title', noteForm);
  const title = element('input', undefined, titleLabel); title.required = true;
  const bodyLabel = element('label', 'Markdown note (use [[word]] for links)', noteForm);
  const body = element('textarea', undefined, bodyLabel);
  const save = element('button', 'Add note', noteForm); save.type = 'submit';
  noteForm.onsubmit = async event => { event.preventDefault(); try { await api('/api/wiki/notes', 'POST', { word_id: id, title: title.value, body_md: body.value }); await detail(id); } catch (error) { $('notice').textContent = error.message; } };
  element('h4', 'Backlinks', parent);
  data.backlinks.forEach(link => element('p', `${link.title}: ${link.snippet}`, parent));
}
async function today() {
  const data = await api('/api/learn/today');
  $('today').textContent = `${data.due_count} due · ${data.new_remaining_today} new remaining today · ${data.completed_today} reviews completed · ${data.streak_days} day streak`;
}
$('next-question').onclick = async () => {
  try {
    const question = await api('/api/learn/next');
    const parent = $('question'); parent.replaceChildren();
    if (!question) { element('p', 'No questions due.', parent); return; }
    if (question.question_type === 'first_contact') {
      element('h3', question.word.word, parent); element('p', question.message, parent);
      action('Edit this word', async () => { activate('wiki'); await detail(question.word.id); }, parent);
      return;
    }
    element('h3', question.question_type.replaceAll('_', ' '), parent);
    if (question.prompt.text) element('p', question.prompt.text, parent);
    if (question.prompt.audio_url && question.prompt.audio_url.startsWith('https://')) { const audio = element('audio', undefined, parent); audio.controls = true; audio.src = question.prompt.audio_url; }
    if (question.prompt.first_letter) element('p', `First letter: ${question.prompt.first_letter}`, parent);
    const start = performance.now();
    const send = async answer => {
      const result = await api('/api/learn/answer', 'POST', { question_id: question.question_id, answer, rating: 3, duration_ms: Math.round(performance.now() - start) });
      parent.replaceChildren();
      element('p', `${result.is_correct ? 'Correct' : 'Incorrect'} · Answer: ${result.correct_answer} · Next due: ${new Date(result.next_due).toLocaleString()}`, parent);
      await today();
    };
    if (question.question_type === 'spelling') {
      const form = element('form', undefined, parent); const input = element('input', undefined, form); input.autocomplete = 'off';
      const submit = element('button', 'Check spelling', form); submit.type = 'submit';
      form.onsubmit = event => { event.preventDefault(); send(input.value).catch(error => { $('notice').textContent = error.message; }); };
    } else question.options.forEach(option => action(option, () => send(option), parent));
    action('Mark mastered', async () => { await api('/api/learn/master/' + question.word.id, 'POST'); parent.replaceChildren(); await today(); }, parent);
  } catch (error) { $('notice').textContent = error.message; }
};
async function loadLog(id) { $('log-detail').textContent = JSON.stringify(await api('/api/logs/' + id), null, 2); }
async function logs() {
  const data = await api('/api/logs'); $('activity').replaceChildren();
  data.forEach(log => action(`${log.created_at} — ${log.summary}`, () => loadLog(log.log_id), $('activity')));
}
$('reload-logs').onclick = () => logs().catch(error => { $('notice').textContent = error.message; });
api('/api/health').then(data => { $('health').textContent = data.model_configured ? `Agent: ${data.model} · temperature ${data.temperature}` : 'Set DEEPSEEK_API_KEY to enable the Agent. Wiki and learning are available locally.'; }).catch(error => { $('health').textContent = error.message; });
