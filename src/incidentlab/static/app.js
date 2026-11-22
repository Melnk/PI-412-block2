const $ = id => document.getElementById(id);
const states = {
  supported: 'ГИПОТЕЗА ПРОШЛА ПРОВЕРКИ',
  insufficient_evidence: 'НЕДОСТАТОЧНО ДОКАЗАТЕЛЬСТВ',
  error: 'ОШИБКА ВЫПОЛНЕНИЯ',
  budget_exceeded: 'ДОСТИГНУТ ЛИМИТ',
};
let incidents = [];
let downloadURL;

function selectIncident() {
  const item = incidents.find(x => x.id === $('incident').value);
  $('description').textContent = item?.description || '';
}

function render(result) {
  $('result').hidden = false;
  $('verdict').dataset.status = result.status;
  $('status').textContent = states[result.status] || result.status;
  $('summary').textContent = result.summary;
  $('next').textContent = 'Следующий шаг для инженера: ' + result.next_step;
  $('error').textContent = result.error || '';
  $('stats').replaceChildren();
  const stats = [
    `${result.stats.elapsed_seconds} с`,
    `${result.stats.llm_calls} вызовов LLM`,
    `${result.stats.tool_calls} источника`,
    `${result.stats.input_tokens + result.stats.output_tokens} токенов`,
  ];
  for (const text of stats) {
    const span = document.createElement('span');
    span.textContent = text;
    $('stats').append(span);
  }
  if (!result.stats.token_usage_complete) {
    const note = document.createElement('span');
    note.textContent = 'Учёт токенов неполный';
    $('stats').append(note);
  }

  $('evidence').replaceChildren();
  const cited = new Set(result.citations.map(x => x.id));
  for (const fact of result.evidence) {
    const item = document.createElement('div');
    item.className = 'evidence';
    const title = document.createElement('strong');
    title.textContent = `${fact.id} · ${fact.source}${cited.has(fact.id) ? ' · использовано в выводе' : ''}`;
    const stamp = document.createElement('small');
    stamp.textContent = ' · ' + fact.timestamp;
    const text = document.createElement('p');
    // Evidence and model responses are untrusted; render them only as text.
    text.textContent = fact.text;
    item.append(title, stamp, text);
    $('evidence').append(item);
  }
  if (!result.evidence.length) $('evidence').textContent = 'Доступных фактов нет.';
  for (const [source, error] of Object.entries(result.source_failures)) {
    const text = document.createElement('p');
    text.textContent = `${source}: ${error}`;
    $('evidence').append(text);
  }

  $('trajectory').replaceChildren();
  for (const step of result.trajectory.filter(x => x.kind !== 'node')) {
    const item = document.createElement('li');
    let text = step.kind;
    if (step.kind === 'plan') text = `Исследователь: ${step.action} — ${step.reason}`;
    if (step.kind === 'tool') {
      text = `Источник ${step.tool}: ${step.available ? step.records + ' записей' : step.error}`;
    }
    if (step.kind === 'proposal') text = `Аналитик: ${step.cause} — ${step.reason}`;
    if (step.kind === 'verification') {
      text = step.errors.length
        ? 'Проверка ссылок: ' + step.errors.join('; ')
        : 'Программная проверка ссылок пройдена';
    }
    if (step.kind === 'review') text = `Валидатор: ${step.decision} — ${step.reason}`;
    if (step.kind === 'failure') text = `Остановка: ${step.error}`;
    item.textContent = text;
    const time = document.createElement('small');
    time.textContent = `${(step.elapsed_ms / 1000).toFixed(1)} с от начала`;
    item.append(time);
    $('trajectory').append(item);
  }
  $('review').textContent = JSON.stringify({
    proposal: result.proposal, review: result.review, guard_errors: result.guard_errors,
  }, null, 2);
  $('trace').textContent = `Run ${result.run_id} · Trace ${result.trace_id} · ${result.spans.length} spans`;
  $('raw').textContent = JSON.stringify(result, null, 2);
  if (downloadURL) URL.revokeObjectURL(downloadURL);
  downloadURL = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'}));
  $('download').href = downloadURL;
}

$('incident').addEventListener('change', selectIncident);
$('start').addEventListener('click', async () => {
  $('start').disabled = true;
  $('incident').disabled = true;
  $('result').hidden = true;
  const started = Date.now();
  $('progress').textContent = 'Исследование началось…';
  const timer = setInterval(() => {
    $('progress').textContent = `Агенты собирают и проверяют данные · ${Math.floor((Date.now() - started) / 1000)} с`;
  }, 1000);
  try {
    const response = await fetch('/investigations', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({incident_id: $('incident').value}),
    });
    const result = await response.json();
    if (!result.run_id) throw new Error(result.detail || 'Не удалось запустить исследование');
    render(result);
    $('progress').textContent = 'Исследование завершено. Отчёт сохранён.';
  } catch (error) {
    $('progress').textContent = String(error.message);
  } finally {
    clearInterval(timer);
    $('start').disabled = false;
    $('incident').disabled = false;
  }
});

fetch('/incidents')
  .then(response => {
    if (!response.ok) throw new Error('Не удалось загрузить инциденты');
    return response.json();
  })
  .then(items => {
    incidents = items;
    $('incident').replaceChildren();
    for (const item of items) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.title;
      $('incident').append(option);
    }
    $('incident').disabled = false;
    $('start').disabled = false;
    selectIncident();
  })
  .catch(error => { $('progress').textContent = error.message; });
