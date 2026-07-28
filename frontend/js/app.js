/*
 * 화면 로직 — 데이터를 그리고, 입력을 API 호출로 바꾸고, 결과를 반영한다.
 *
 * 값은 전부 textContent 로 넣는다. innerHTML 에 데이터를 끼우면 값 안의 태그가
 * 실행된다(XSS). 지금은 우리가 넣은 데이터뿐이지만, AI 응답과 사용자 입력이 섞이는
 * 화면이라 처음부터 이 방식으로 쓴다.
 */

const $ = (id) => document.getElementById(id);

let currentConversationId = null;
let dataCache = [];

/* ── 서버 상태 ─────────────────────────────────────────────── */

async function checkHealth() {
  const status = $('apiStatus');
  try {
    const health = await api.health();
    const store = health.storage === 'firestore' ? 'Firestore' : '로컬 저장소';
    const ai = health.ai_ready ? 'AI 준비됨' : 'AI 키 없음';
    status.textContent = `연결됨 · ${store} · ${ai}`;
    status.className = 'status ok';
  } catch (error) {
    status.textContent = '서버 연결 실패';
    status.className = 'status bad';
    console.warn(error.message);
  }
}

/* ── 요약 + 미니 차트 ──────────────────────────────────────── */

async function renderSummary() {
  let summary;
  try {
    summary = await api.summary();
  } catch (error) {
    $('summaryKpis').textContent = error.message;
    return;
  }

  const items = [
    ['개수', `${summary.count}개`],
    ['기간', summary.period_from ? `${summary.period_from} ~ ${summary.period_to}` : '-'],
    ['평균', summary.mean ?? '-'],
    ['최소 / 최대', summary.count ? `${summary.minimum} / ${summary.maximum}` : '-'],
    ['최근 값', summary.latest_value ?? '-'],
    ['추세', summary.trend],
  ];

  const wrap = $('summaryKpis');
  wrap.innerHTML = '';
  items.forEach(([label, value]) => {
    const box = document.createElement('div');
    box.className = 'kpi';
    const l = document.createElement('div');
    l.className = 'label';
    l.textContent = label;
    const v = document.createElement('div');
    v.className = 'value';
    v.textContent = value;
    box.append(l, v);
    wrap.appendChild(box);
  });

  /* 추세 근거를 함께 보여 준다 — "증가" 만 있으면 왜 그렇게 봤는지 알 수 없다 */
  $('trendBasis').textContent = summary.trend_basis || '';
  drawMiniChart(dataCache);
}

/**
 * 보너스 — 데이터 흐름을 보여 주는 미니 차트(인라인 SVG).
 * 외부 차트 라이브러리를 쓰지 않는 이유: 선 하나에 수백 KB 를 받아 올 이유가 없다.
 */
function drawMiniChart(points) {
  const svg = $('miniChart');
  if (!points.length) {
    svg.innerHTML = '';
    return;
  }

  const sorted = [...points].sort((a, b) => String(a.period).localeCompare(String(b.period)));
  const values = sorted.map((p) => Number(p.value));
  const W = 640;
  const H = 180;
  const PAD = { l: 40, r: 10, t: 12, b: 22 };
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;

  const x = (i) => PAD.l + (i * (W - PAD.l - PAD.r)) / Math.max(1, values.length - 1);
  const y = (v) => H - PAD.b - ((v - lo) * (H - PAD.t - PAD.b)) / span;

  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const area = `${path} L${x(values.length - 1).toFixed(1)} ${H - PAD.b} L${PAD.l} ${H - PAD.b} Z`;

  svg.innerHTML =
    `<path d="${area}" fill="var(--brand)" opacity="0.12"/>` +
    `<path d="${path}" fill="none" stroke="var(--brand)" stroke-width="2"/>` +
    `<text x="4" y="${y(hi) + 4}" font-size="11" fill="currentColor" opacity="0.6">${hi}</text>` +
    `<text x="4" y="${y(lo) + 4}" font-size="11" fill="currentColor" opacity="0.6">${lo}</text>` +
    `<text x="${PAD.l}" y="${H - 6}" font-size="11" fill="currentColor" opacity="0.6">${sorted[0].period}</text>` +
    `<text x="${W - PAD.r}" y="${H - 6}" text-anchor="end" font-size="11" fill="currentColor" opacity="0.6">${sorted[sorted.length - 1].period}</text>`;
}

/* ── 데이터 관리 (CRUD) ────────────────────────────────────── */

async function renderData() {
  const body = $('dataBody');
  try {
    dataCache = await api.listData();
  } catch (error) {
    $('dataError').textContent = error.message;
    $('dataError').hidden = false;
    return;
  }

  body.innerHTML = '';
  /* 표에는 최근 것부터 30건만 — 144건을 전부 그리면 스크롤이 길어 쓸모가 없다 */
  dataCache.slice(0, 30).forEach((point) => {
    const tr = document.createElement('tr');

    const period = document.createElement('td');
    period.textContent = point.period;

    const value = document.createElement('td');
    value.className = 'num';
    value.textContent = point.value;

    const note = document.createElement('td');
    note.textContent = point.note || '-';

    const action = document.createElement('td');
    const remove = document.createElement('button');
    remove.className = 'link-danger';
    remove.type = 'button';
    remove.textContent = '삭제';
    remove.addEventListener('click', () => handleDelete(point.id, point.period));
    action.appendChild(remove);

    tr.append(period, value, note, action);
    body.appendChild(tr);
  });

  $('dataCount').textContent =
    `총 ${dataCache.length}건 (최근 ${Math.min(30, dataCache.length)}건 표시)`;
}

async function handleDelete(id, period) {
  if (!confirm(`${period} 데이터를 삭제할까요?`)) return;
  try {
    await api.deleteData(id);
    await refreshAll();
  } catch (error) {
    $('dataError').textContent = error.message;
    $('dataError').hidden = false;
  }
}

function initDataForm() {
  $('dataForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = $('dataError');
    error.hidden = true;

    const period = $('periodInput').value.trim();
    const rawValue = $('valueInput').value.trim();

    /* 서버가 다시 검증하지만, 여기서 막으면 왕복 한 번을 아낀다 */
    if (!period || !rawValue) {
      error.textContent = '시점과 값을 모두 입력해 주세요.';
      error.hidden = false;
      return;
    }

    try {
      await api.createData({
        period,
        value: Number(rawValue),
        note: $('noteInput').value.trim() || null,
      });
      $('dataForm').reset();
      await refreshAll();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
}

/* ── 채팅 ──────────────────────────────────────────────────── */

function addBubble(role, text) {
  const bubble = document.createElement('div');
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  $('chatLog').appendChild(bubble);
  $('chatLog').scrollTop = $('chatLog').scrollHeight;
  return bubble;
}

function initChat() {
  $('chatForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = $('chatInput');
    const message = input.value.trim();
    if (!message) return;

    addBubble('user', message);
    input.value = '';
    $('chatSend').disabled = true;

    /* 로딩 표시 — 응답이 올 때까지 화면이 멈춘 것처럼 보이면 안 된다 */
    const loading = addBubble('assistant loading', '생각하는 중');

    try {
      const result = await api.chat(message, currentConversationId);
      loading.remove();
      addBubble('assistant', result.reply);
      currentConversationId = result.conversation_id;

      const parts = [result.used_summary ? '데이터 요약 주입됨' : '데이터 없음'];
      if (result.tool_calls?.length) parts.push(`도구 호출: ${result.tool_calls.join(', ')}`);
      $('chatMeta').textContent = parts.join(' · ');

      await renderConversations();
    } catch (error) {
      loading.remove();
      addBubble('error', error.message);
    } finally {
      $('chatSend').disabled = false;
    }
  });
}

/* ── 대화 기록 ─────────────────────────────────────────────── */

async function renderConversations() {
  const list = $('convList');
  let conversations;
  try {
    conversations = await api.listConversations();
  } catch (error) {
    list.textContent = error.message;
    return;
  }

  list.innerHTML = '';
  if (!conversations.length) {
    const empty = document.createElement('li');
    empty.className = 'muted';
    empty.textContent = '아직 대화가 없습니다.';
    list.appendChild(empty);
    return;
  }

  conversations.forEach((conversation) => {
    const item = document.createElement('li');
    item.className = 'conv-item';

    const open = document.createElement('button');
    open.className = 'title';
    open.type = 'button';
    open.textContent = `${conversation.title} (${conversation.message_count})`;
    open.addEventListener('click', () => loadConversation(conversation.id));

    const remove = document.createElement('button');
    remove.className = 'link-danger';
    remove.type = 'button';
    remove.textContent = '삭제';
    remove.addEventListener('click', async () => {
      await api.deleteConversation(conversation.id);
      if (currentConversationId === conversation.id) currentConversationId = null;
      await renderConversations();
    });

    item.append(open, remove);
    list.appendChild(item);
  });
}

/**
 * 대화 불러오기 — 목록에는 messages 가 없으므로 상세를 따로 부른다.
 * 이것이 목록/상세를 나눈 설계가 화면에서 쓰이는 지점이다.
 */
async function loadConversation(id) {
  try {
    const conversation = await api.getConversation(id);
    $('chatLog').innerHTML = '';
    conversation.messages.forEach((message) => {
      addBubble(message.role === 'user' ? 'user' : 'assistant', message.content);
    });
    currentConversationId = id;
    $('chatMeta').textContent = `대화 불러옴: ${conversation.title}`;
  } catch (error) {
    addBubble('error', error.message);
  }
}

/* ── 내보내기(보너스) ──────────────────────────────────────── */

function download(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url); // 다 쓴 객체 URL 을 놓아 준다 — 안 하면 메모리에 남는다
}

function initExport() {
  $('exportCsv').addEventListener('click', () => {
    /* 값에 쉼표·따옴표가 들어갈 수 있으므로 큰따옴표로 감싸고 안의 따옴표는 두 번 쓴다 */
    const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const header = 'period,value,note,created_at';
    const rows = dataCache.map((p) =>
      [p.period, p.value, p.note, p.created_at].map(escape).join(',')
    );
    /* ﻿(BOM) — 엑셀이 UTF-8 임을 알아채게 한다. 없으면 한글이 깨진다 */
    download('data.csv', `﻿${header}\n${rows.join('\n')}`, 'text/csv;charset=utf-8');
  });

  $('exportJson').addEventListener('click', () => {
    download('data.json', JSON.stringify(dataCache, null, 2), 'application/json');
  });
}

/* ── 다크 모드(보너스) ─────────────────────────────────────── */

function initTheme() {
  const button = $('themeToggle');
  const apply = (isDark) => {
    document.body.classList.toggle('dark', isDark);
    button.textContent = isDark ? '☀️ 라이트' : '🌙 다크';
  };
  /* 선택을 저장한다 — 새로고침마다 밝은 화면으로 돌아가면 눈이 부시다 */
  apply(localStorage.getItem('theme') === 'dark');
  button.addEventListener('click', () => {
    const next = !document.body.classList.contains('dark');
    localStorage.setItem('theme', next ? 'dark' : 'light');
    apply(next);
  });
}

/* ── 시작 ──────────────────────────────────────────────────── */

async function refreshAll() {
  await renderData();
  await renderSummary();
}

async function main() {
  initTheme();
  initDataForm();
  initChat();
  initExport();
  await checkHealth();
  await refreshAll();
  await renderConversations();
}

main();
