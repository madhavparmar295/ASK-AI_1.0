import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { useAuth } from '../../auth/AuthContext'
import { FilePicker } from '../../components/FilePicker'
import { HintBox } from '../../components/HintBox'
import { Alert, Button, Card, ErrorBox, Field, Spinner, inputClass } from '../../components/ui'
import { HINT_URL, href } from '../../config'
import { useAsync } from '../../hooks/useAsync'
import { useDebounce } from '../../hooks/useDebounce'
import { fetchHint } from '../../lib/hint'

const MIN_CLASSIFY = 15
const MIN_HINT = 25

export default function NewIssuePage({ hintUrl = HINT_URL }) {
  const api = useApi()
  const { me } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const options = useAsync(() => api.formOptions(), [])

  const [text, setText] = useState(params.get('text') || '')       // the chatbot can send ?text=
  const [categoryId, setCategoryId] = useState('')
  const [unitId, setUnitId] = useState('')
  const [location, setLocation] = useState('')
  const [confidential, setConfidential] = useState(false)
  const [files, setFiles] = useState([])
  const [fileErrors, setFileErrors] = useState([])
  const [suggestion, setSuggestion] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const categoryTouched = useRef(false)
  const unitTouched = useRef(false)
  const debounced = useDebounce(text, 700)
  const hintText = useDebounce(text, 1500)
  const [hint, setHint] = useState(null)
  const [hintDismissed, setHintDismissed] = useState(false)

  const categories = options.data?.categories || []
  const category = categories.find((c) => c.id === categoryId)
  const needsUnit = !!category && category.unit_type !== 'campus'
  const unitChoices = needsUnit ? options.data.units.filter((u) => u.type === category.unit_type) : []
  const confidentialLocked = !!(suggestion?.confidential || category?.confidential)

  // Ask the server to suggest a category while the person types. Suggestions only.
  useEffect(() => {
    if (debounced.trim().length < MIN_CLASSIFY) { setSuggestion(null); return undefined }
    const ctl = new AbortController()
    api.classify(debounced, ctl.signal).then((s) => {
      setSuggestion({ ...s, for: debounced })        // remember which text this answer is about
      if (!categoryTouched.current && s.suggested && s.confidence !== 'none') setCategoryId(s.suggested.id)
      if (s.confidential) setConfidential(true)
    }).catch(() => { /* a missing suggestion must never block the form */ })
    return () => ctl.abort()
  }, [debounced, api])

  // Optional: let the chatbot answer first. Any failure simply shows nothing.
  // Privacy rule: the text is sent to the chatbot ONLY after the server has classified this exact text and found
  // it not sensitive, and the student has not marked it confidential. If classification failed, no hint.
  const safeForHint = !!suggestion && suggestion.for === hintText && !suggestion.confidential && !confidential && !category?.confidential
  useEffect(() => {
    if (!hintUrl || hintText.trim().length < MIN_HINT || !safeForHint) { setHint(null); return undefined }
    const ctl = new AbortController()
    fetchHint(hintText.trim(), { signal: ctl.signal, url: hintUrl }).then((h) => { if (!ctl.signal.aborted) setHint(h) })
    return () => ctl.abort()
  }, [hintText, hintUrl, safeForHint])

  // Pick the person's own hostel or department when the category needs a location.
  useEffect(() => {
    if (!needsUnit || unitTouched.current) return
    const mine = category.unit_type === 'hostel' ? me?.hostel : category.unit_type === 'department' ? me?.department : null
    const match = unitChoices.find((u) => mine && u.name.toLowerCase() === mine.toLowerCase())
    setUnitId(match ? match.id : '')
  }, [categoryId]) // eslint-disable-line react-hooks/exhaustive-deps

  function validate() {
    const e = {}
    if (text.trim().length < 5) e.text = 'Please describe the problem (at least a few words).'
    if (!categoryId) e.category = 'Please choose the category that fits best.'
    setFieldErrors(e)
    return Object.keys(e).length === 0
  }

  async function submit(ev) {
    ev.preventDefault()
    if (!validate()) return
    setSubmitting(true); setError(null)
    let ticket
    try {
      ticket = await api.createIssue({
        description: text.trim(), category_id: categoryId, unit_id: needsUnit && unitId ? unitId : null,
        location_text: location.trim() || null, confidential: confidential || confidentialLocked,
      })
    } catch (err) {
      setError(err); setSubmitting(false); return
    }
    // The ticket exists now. Add files one by one; a failed file must not lose the ticket.
    const failed = []
    for (const f of files) {
      try { await api.uploadAttachment(ticket.id, f) } catch (err) { failed.push(`${f.name}: ${err.message}`) }
    }
    navigate(href(`issues/${ticket.id}`), { state: { created: true, uploadFailures: failed } })
  }

  if (options.loading) return <Spinner />
  if (options.error) return <ErrorBox error={options.error} onRetry={options.reload} />

  const duplicate = error?.status === 409 && error.data?.existing_ticket_id
  const weak = suggestion && ['low', 'none'].includes(suggestion.confidence)

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Card className="space-y-4">
        <h2 className="text-lg font-semibold text-white">Report a problem</h2>

        <Field label="What is the problem?" required error={fieldErrors.text}
          hint="Say what is wrong and where. You can write in English or Hinglish.">
          {(p) => <textarea {...p} rows={5} maxLength={5000} value={text} onChange={(e) => setText(e.target.value)} className={inputClass} placeholder="For example: the AC in my room has not worked for two days" />}
        </Field>

        <Field label="Category" required error={fieldErrors.category}
          hint={weak ? 'We are not sure about this one. Please check the category.' : suggestion?.suggested ? 'Suggested from your description. You can change it.' : undefined}>
          {(p) => (
            <select {...p} value={categoryId} className={inputClass}
              onChange={(e) => { categoryTouched.current = true; setCategoryId(e.target.value) }}>
              <option value="">Choose a category…</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </Field>

        {needsUnit && (
          <Field label={category.unit_type === 'hostel' ? 'Which hostel?' : category.unit_type === 'department' ? 'Which department?' : 'Which place?'}
            hint="Optional, but it helps us send your ticket to the right person.">
            {(p) => (
              <select {...p} value={unitId} className={inputClass} onChange={(e) => { unitTouched.current = true; setUnitId(e.target.value) }}>
                <option value="">Not sure</option>
                {unitChoices.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            )}
          </Field>
        )}

        <Field label="Room, floor or exact spot" hint="Optional.">
          {(p) => <input {...p} type="text" maxLength={300} value={location} onChange={(e) => setLocation(e.target.value)} className={inputClass} />}
        </Field>

        <div className="space-y-2">
          <label className="flex items-start gap-3 text-sm text-white/90">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-purple-500" checked={confidential || confidentialLocked}
              disabled={confidentialLocked} onChange={(e) => setConfidential(e.target.checked)} />
            <span>
              <span className="font-medium">Keep this confidential</span>
              <span className="block text-xs text-white/60">Only designated officers will see it. Nobody else, including administrators.</span>
            </span>
          </label>
          {confidentialLocked && (
            <Alert tone="info" title="This looks sensitive">
              <p className="flex gap-1"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                It will be handled only by designated officers. If you are in danger right now, please also contact campus security or the police.</p>
            </Alert>
          )}
        </div>

        <FilePicker files={files} onChange={setFiles} errors={fileErrors} onErrors={setFileErrors} />
      </Card>

      {hint && !hintDismissed && <HintBox hint={hint} onDismiss={() => setHintDismissed(true)} />}

      {duplicate && (
        <Alert tone="warn" title="You already have an open ticket for this">
          <p>Please add details to it instead of opening a new one. <Link className="underline" to={href(`issues/${error.data.existing_ticket_id}`)}>Open {error.data.existing_ticket_no || 'it'}</Link></p>
        </Alert>
      )}
      {error && !duplicate && <Alert tone="error">{error.message}</Alert>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate(href('issues'))}>Cancel</Button>
        <Button type="submit" loading={submitting}>{submitting && files.length ? 'Sending…' : 'Submit'}</Button>
      </div>
    </form>
  )
}
