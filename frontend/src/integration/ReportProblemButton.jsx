/**
 * FOR THE CHATBOT TEAM. Copy this file into the chatbot app (it has no other dependencies).
 *
 * After the chatbot answers, show <ReportProblemButton text={studentsMessage} />. If the message sounds like a
 * problem that needs somebody to act, a button appears that opens the grievance form with the text filled in.
 * Showing it is only a suggestion: nothing is sent until the student presses Submit on the grievance form.
 */

// Words that suggest "something is broken or wrong" rather than "please explain a rule". English and Hinglish.
const PROBLEM_WORDS = [
  'not working', 'not been working', 'not functioning', 'not been functioning',
  "hasn't been working", 'hasnt been working', "doesn't work", 'does not work', 'doesnt work', 'stopped working',
  'out of order', 'broken', 'broke', 'damaged',
  'leak', 'leaking', 'not available', 'complaint', 'complain', 'problem with', 'issue with', 'problem in', 'issue in',
  'report a', 'report this', 'wrong', 'no water', 'no electricity', 'harass', 'ragging', 'threat',
  'kharab', 'nahi chal', 'band hai', 'toot', 'kharaab', 'shikayat',
]
const PATTERN = new RegExp(`(${PROBLEM_WORDS.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'i')

export function looksLikeAProblem(text) {
  return typeof text === 'string' && text.trim().length >= 8 && PATTERN.test(text)
}

/** Link to the grievance form with the student's words filled in (cut to 1000 characters). */
export function reportUrl(text, base = '/grievance') {
  const clean = String(text || '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 1000)
  return `${base}/new${clean ? `?text=${encodeURIComponent(clean)}` : ''}`
}

export function ReportProblemButton({ text, base = '/grievance', className = '', always = false }) {
  if (!always && !looksLikeAProblem(text)) return null
  return (
    <a
      href={reportUrl(text, base)}
      className={`inline-flex items-center gap-2 rounded-xl bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 ${className}`}
    >
      Report this as a problem
    </a>
  )
}
