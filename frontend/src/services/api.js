/**
 * API Configuration and Endpoints
 *
 * Configured for FastAPI backend service and Django session injection.
 */

// API Configuration
export const API_CONFIG = {
  // Respect Django-injected variables if served from Django, else fallback to Vite .env
  BASE_URL: (typeof window !== 'undefined' && window.FASTAPI_SERVICE_URL) || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  TIMEOUT: 60000, // 60 seconds
  DEMO_MODE: (typeof window !== 'undefined' && typeof window.DEMO_MODE === 'boolean') ? window.DEMO_MODE : import.meta.env.VITE_DEMO_MODE === 'true',
  DEFAULT_USER_EMAIL: (typeof window !== 'undefined' && window.USER_EMAIL) || import.meta.env.VITE_DEFAULT_USER_EMAIL || 'user@gmail.com',
};

// API Endpoints
export const chatEndpoints = {
  get ask() {
    const base = (typeof window !== 'undefined' && window.FASTAPI_SERVICE_URL) || API_CONFIG.BASE_URL;
    return `${base}/query/ask`;
  },
  get uploadFile() {
    const base = (typeof window !== 'undefined' && window.FASTAPI_SERVICE_URL) || API_CONFIG.BASE_URL;
    return `${base}/documents/upload`;
  },
  get googleLogin() {
    const base = (typeof window !== 'undefined' && window.FASTAPI_SERVICE_URL) || API_CONFIG.BASE_URL;
    return `${base}/auth/google/login`;
  },
};

/**
 * Generic API request handler
 * @param {string} url - API endpoint
 * @param {object} options - Fetch options
 * @returns {Promise} Response data
 */
async function apiRequest(url, options = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('askai_token') : null;
  const config = {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    ...options,
  };

  // Add timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT);
  config.signal = controller.signal;

  try {
    const response = await fetch(url, config);
    clearTimeout(timeoutId);

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Server error (status ${response.status})`);
    }

    return await response.json();
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error('Request timed out. Please check if the FastAPI server is running.');
    }
    throw error;
  }
}

/**
 * Send a message to the FastAPI RAG Endpoint
 * @param {string} message - User question
 * @param {object} metadata - Optional metadata (userEmail, etc.)
 */
export async function sendMessage(message, metadata = {}) {
  const userEmail = (typeof window !== 'undefined' && window.USER_EMAIL) || metadata.userEmail || API_CONFIG.DEFAULT_USER_EMAIL;

  const data = await apiRequest(chatEndpoints.ask, {
    method: 'POST',
    body: JSON.stringify({
      question: message,
      user_email: userEmail,
      chat_history: metadata.chatHistory || [],
    }),
  });

  return {
    success: true,
    data: {
      message: data.answer,
      sources: data.sources || [],
      question: data.question,
      timestamp: new Date().toISOString(),
    },
  };
}

/**
 * Upload a document to FastAPI
 * @param {File} file - File to upload
 * @param {string} userEmail - User email for access control
 */
export async function uploadFile(file, userEmail) {
  const email = (typeof window !== 'undefined' && window.USER_EMAIL) || userEmail || API_CONFIG.DEFAULT_USER_EMAIL;
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(chatEndpoints.uploadFile, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.detail || `Upload failed with status ${response.status}`);
  }

  return await response.json();
}
