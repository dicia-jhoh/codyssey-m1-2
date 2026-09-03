/*
 * API 계층 — 백엔드 호출을 한곳에 모은다.
 *
 * 화면 로직(app.js)과 나눈 이유: 서버 주소·오류 처리·타임아웃 규칙이 화면 코드에 흩어지면
 * 엔드포인트를 하나 고칠 때 여러 곳을 찾아야 한다. 여기만 보면 "이 앱이 서버와 무엇을
 * 주고받는지" 가 전부 드러난다.
 */

/*
 * 백엔드 주소. Vercel 환경 변수로 주입하는 것이 원칙이지만, 이 프로젝트는 빌드 단계가
 * 없는 순수 HTML/JS 라 번들러가 process.env 를 바꿔치기해 줄 수 없다.
 * 그래서 배포 시 이 파일의 값을 바꾸거나, 아래 window.__API_BASE__ 로 덮어쓴다.
 * (Vercel 은 정적 파일 배포이므로 config.js 를 따로 두고 환경별로 교체하는 방식도 흔하다.)
 */
/* 기본 '' = same-origin — 백엔드가 /app 에 이 프론트를 함께 서빙하는 단일 서버 배포에서
 * 그대로 동작한다. 분리 배포(Vercel 정적 + Render API)면 아래 두 오버라이드로 지정한다. */
const API_BASE =
  window.__API_BASE__ ||
  localStorage.getItem('api-base') ||
  '';

/* 무료 티어(Render)는 잠들었다 깨는 데 오래 걸린다 — 넉넉히 잡되 무한정 기다리지 않는다 */
const TIMEOUT_MS = 70000;
/* 이 시간을 넘기면 "서버 깨우는 중" 안내를 띄운다 */
const COLD_START_HINT_MS = 4000;

/**
 * 실제 fetch + JSON 파싱. keep-alive 연결이 서버 타임아웃과 겹치면 uvicorn 이 요청을
 * 파싱하기도 전에 평문 "Invalid HTTP request received."(400)를 돌려줄 때가 있다 —
 * 그 응답은 connection: close 라 재시도는 새 연결을 쓴다. GET 은 부작용이 없어 한 번만
 * 조용히 재시도하고, 쓰기 요청은 서버가 실제로 처리했을 수도 있어 재시도하지 않는다.
 */
async function fetchJson(path, options, signal, isRetry = false) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    signal,
    ...options,
  });

  if (response.status === 204) return null; // 삭제 성공 — 본문이 없다

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (parseError) {
    const method = (options.method || 'GET').toUpperCase();
    if (method === 'GET' && !isRetry) {
      return fetchJson(path, options, signal, true);
    }
    throw new Error('서버 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }

  if (!response.ok) {
    throw new Error(describeError(response.status, data));
  }
  return data;
}

/**
 * fetch 한 겹 감싸기 — 타임아웃·JSON 파싱·오류 메시지를 한 곳에서 처리한다.
 * 실패는 Error 로 올리고, 화면 쪽이 사용자에게 보일 문장을 만든다.
 */
async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  /* 응답이 늦으면 콜드스타트 안내를 띄운다 — 화면이 멈춘 것처럼 보이면 안 된다 */
  const hint = setTimeout(() => {
    const notice = document.getElementById('coldStart');
    if (notice) notice.hidden = false;
  }, COLD_START_HINT_MS);

  try {
    return await fetchJson(path, options, controller.signal);
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('응답이 너무 늦어 요청을 취소했습니다. 잠시 후 다시 시도해 주세요.');
    }
    if (error instanceof TypeError) {
      /* fetch 자체가 실패 — 서버가 꺼졌거나 CORS 가 막혔다 */
      throw new Error(
        `서버(${API_BASE})에 연결할 수 없습니다. 주소와 CORS 설정을 확인해 주세요.`
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
    clearTimeout(hint);
    const notice = document.getElementById('coldStart');
    if (notice) notice.hidden = true;
  }
}

/** 상태 코드 + 서버 응답 → 사용자가 읽고 행동할 수 있는 문장 */
function describeError(status, data) {
  /* FastAPI 검증 오류(422)는 어느 필드가 왜 틀렸는지를 담아 준다 — 그대로 보여 준다 */
  if (status === 422 && Array.isArray(data?.detail)) {
    return data.detail
      .map((item) => `${item.loc?.slice(1).join('.') || '입력'}: ${item.msg}`)
      .join('\n');
  }
  if (typeof data?.detail === 'string') return data.detail;
  if (status === 404) return '대상을 찾을 수 없습니다.';
  if (status === 503) return 'AI 기능을 쓸 수 없습니다. 서버의 API 키 설정을 확인해 주세요.';
  if (status >= 500) return '서버에 문제가 있습니다. 잠시 후 다시 시도해 주세요.';
  return `요청이 실패했습니다 (HTTP ${status}).`;
}

const api = {
  base: API_BASE,
  health: () => request('/'),

  listData: () => request('/api/data'),
  createData: (payload) => request('/api/data', { method: 'POST', body: JSON.stringify(payload) }),
  updateData: (id, payload) =>
    request(`/api/data/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteData: (id) => request(`/api/data/${id}`, { method: 'DELETE' }),
  summary: () => request('/api/data/summary'),
  statistics: () => request('/api/data/statistics'),

  listConversations: () => request('/api/conversations'),
  getConversation: (id) => request(`/api/conversations/${id}`),
  deleteConversation: (id) => request(`/api/conversations/${id}`, { method: 'DELETE' }),

  chat: (message, conversationId) =>
    request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message, conversation_id: conversationId || null }),
    }),
};
