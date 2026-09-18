import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

// Custom latency tracking per read-heavy endpoint
const docListTrend = new Trend('doc_list_duration');
const deadlinesTrend = new Trend('deadlines_duration');
const graphTrend = new Trend('graph_duration');
const assistantTrend = new Trend('assistant_duration');

export const options = {
  stages: [
    { duration: '30s', target: 20 }, // Warmup
    { duration: '4m', target: 50 },  // 50 concurrent VUs for sustained read load
    { duration: '30s', target: 0 },  // Cooldown
  ],
  thresholds: {
    // Flag anything exceeding 400 ms at p95
    http_req_duration: ['p(95)<400'],
    doc_list_duration: ['p(95)<400'],
    deadlines_duration: ['p(95)<400'],
    graph_duration: ['p(95)<400'],
    assistant_duration: ['p(95)<800'], // LLM/retrieval threshold
    http_req_failed: ['rate<0.01'],    // <1% errors allowed
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const FAMILY_ID = __ENV.FAMILY_ID || '11111111-2222-3333-4444-555555555555';
const AUTH_TOKEN = __ENV.AUTH_TOKEN || 'demo-bearer-token';

const headers = {
  'Content-Type': 'application/json',
  Authorization: `Bearer ${AUTH_TOKEN}`,
};

export default function () {
  // 1. GET Document List
  {
    const res = http.get(`${BASE_URL}/api/v1/families/${FAMILY_ID}/documents`, { headers });
    docListTrend.add(res.timings.duration);
    check(res, {
      'doc list 200': (r) => r.status === 200,
    });
  }
  sleep(0.5);

  // 2. GET Deadlines
  {
    const res = http.get(`${BASE_URL}/api/v1/families/${FAMILY_ID}/deadlines?within_days=90`, { headers });
    deadlinesTrend.add(res.timings.duration);
    check(res, {
      'deadlines 200': (r) => r.status === 200,
    });
  }
  sleep(0.5);

  // 3. GET Family Knowledge Graph
  {
    const res = http.get(`${BASE_URL}/api/v1/families/${FAMILY_ID}/graph`, { headers });
    graphTrend.add(res.timings.duration);
    check(res, {
      'graph 200': (r) => r.status === 200,
    });
  }
  sleep(0.5);

  // 4. POST Assistant Grounded Retrieval
  {
    const payload = JSON.stringify({
      question: 'What is our health insurance policy number and expiry date?',
    });
    const res = http.post(`${BASE_URL}/api/v1/families/${FAMILY_ID}/assistant/ask`, payload, { headers });
    assistantTrend.add(res.timings.duration);
    check(res, {
      'assistant 200': (r) => r.status === 200,
    });
  }
  sleep(1);
}
