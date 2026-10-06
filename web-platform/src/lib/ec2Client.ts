// EC2 Direct Browser Communication Client (Zero Vercel CPU Costs)
const EC2_BASE_URL = process.env.NEXT_PUBLIC_EC2_BASE_URL || 'http://16.171.9.216:8000/api';
const BOT_SECRET = process.env.NEXT_PUBLIC_BOT_SECRET || 'rok_stealth_7f93a1c84b2e65d09e3a8412c0915f7b';

export interface Ec2FetchOptions extends RequestInit {
  userId?: string;
  botId?: string;
}

export async function ec2Fetch<T = any>(
  endpoint: string,
  options: Ec2FetchOptions = {}
): Promise<{ data: T | null; error: string | null }> {
  const { userId, botId, headers, ...rest } = options;

  const url = endpoint.startsWith('http')
    ? endpoint
    : `${EC2_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  const customHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Bot-Secret': BOT_SECRET,
    ...(headers as Record<string, string>),
  };

  if (userId) {
    customHeaders['X-User-Id'] = userId;
  }
  if (botId) {
    customHeaders['X-Bot-Id'] = botId;
  }

  try {
    const res = await fetch(url, {
      ...rest,
      headers: customHeaders,
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => 'Network error');
      return { data: null, error: `HTTP ${res.status}: ${errText}` };
    }

    const data = await res.json().catch(() => null);
    return { data, error: null };
  } catch (err: any) {
    console.error('[EC2_FETCH_ERROR]', err);
    return { data: null, error: err?.message || 'Failed to connect to EC2 backend' };
  }
}

export default ec2Fetch;
