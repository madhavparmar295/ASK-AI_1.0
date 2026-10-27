import { useRef } from 'react'
import { FileText, Image as ImageIcon, Paperclip, X } from 'lucide-react'
import { ALLOWED_EXTENSIONS, MAX_FILE_MB, MAX_FILES } from '../config'
import { checkFiles, sizeLabel } from '../lib/files'
import { Alert, Button } from './ui'

export const FILE_NOTICE =
  'Photos can contain the place where they were taken, and documents may contain personal details. Add only what is needed.'

/** Choose up to 3 files. Shows instant checks; the server checks again. */
export function FilePicker({ files, onChange, alreadyAttached = 0, errors = [], onErrors = () => {} }) {
  const input = useRef(null)
  const room = MAX_FILES - alreadyAttached - files.length

  function pick(e) {
    const { accepted, errors: problems } = checkFiles(Array.from(e.target.files || []), alreadyAttached + files.length)
    onErrors(problems)
    if (accepted.length) onChange([...files, ...accepted])
    e.target.value = ''
  }

  return (
    <div className="space-y-2">
      <input
        ref={input} type="file" className="sr-only" aria-label="Attach files" tabIndex={-1} multiple
        accept={ALLOWED_EXTENSIONS.map((e) => '.' + e).join(',')} onChange={pick}
      />
      <Button variant="secondary" disabled={room <= 0} onClick={() => input.current?.click()}>
        <Paperclip className="h-4 w-4" aria-hidden="true" /> Add photos or PDF
      </Button>
      <p className="text-xs text-white/50">
        JPG, PNG or PDF, up to {MAX_FILE_MB} MB each, at most {MAX_FILES} files. {FILE_NOTICE}
      </p>
      {errors.map((e) => <Alert key={e} tone="warn">{e}</Alert>)}
      {files.length > 0 && (
        <ul className="space-y-1">
          {files.map((f, i) => (
            <li key={f.name + i} className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-1.5 text-sm text-white/90">
              {f.type === 'application/pdf' ? <FileText className="h-4 w-4" aria-hidden="true" /> : <ImageIcon className="h-4 w-4" aria-hidden="true" />}
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <span className="text-xs text-white/50">{sizeLabel(f.size)}</span>
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => onChange(files.filter((_, j) => j !== i))}
                className="rounded p-1 hover:bg-white/10"><X className="h-4 w-4" aria-hidden="true" /></button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
