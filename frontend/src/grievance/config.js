// Everything that may need changing when the module is dropped into the chatbot app.
export const BASE_PATH = '/grievance'                                   // where the module is mounted
export const API_BASE = import.meta.env?.VITE_API_BASE || '/api/grievance'
export const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || ''

// Upload limits shown in the UI. The server enforces the real ones.
export const MAX_FILES = 3
export const MAX_FILE_MB = 10
export const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
export const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'pdf']

/** Build an in-app link: href('issues/123') -> '/grievance/issues/123' */
export const href = (path = '') => (path ? `${BASE_PATH}/${String(path).replace(/^\/+/, '')}` : BASE_PATH)

// "Before you submit" hint from the chatbot: POST <url> {text} -> {answer, sources?}.
// The chatbot provides this endpoint (routers/grievance_bridge.py), so it is on by
// default. An unset variable used to mean "off", which silently disabled the hint
// whenever the dev server had started before the .env file gained the setting.
// Set VITE_HINT_URL= (empty) to switch it off deliberately.
const configuredHintUrl = import.meta.env?.VITE_HINT_URL
export const HINT_URL = configuredHintUrl === undefined ? '/chat/api/ask' : configuredHintUrl
