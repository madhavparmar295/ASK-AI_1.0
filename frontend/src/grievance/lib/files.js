import { ALLOWED_EXTENSIONS, ALLOWED_TYPES, MAX_FILE_MB, MAX_FILES } from '../config'

export function sizeLabel(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/**
 * Quick checks so people get instant feedback. The server checks the real file content again.
 * Returns { accepted: File[], errors: string[] }.
 */
export function checkFiles(files, alreadyAttached = 0) {
  const accepted = []
  const errors = []
  for (const f of files) {
    const ext = (f.name.split('.').pop() || '').toLowerCase()
    const typeOk = f.type ? ALLOWED_TYPES.includes(f.type) : ALLOWED_EXTENSIONS.includes(ext)
    if (!typeOk || !ALLOWED_EXTENSIONS.includes(ext)) errors.push(`"${f.name}" is not a JPG, PNG or PDF file.`)
    else if (f.size > MAX_FILE_MB * 1024 * 1024) errors.push(`"${f.name}" is larger than ${MAX_FILE_MB} MB.`)
    else if (f.size === 0) errors.push(`"${f.name}" is empty.`)
    else if (alreadyAttached + accepted.length >= MAX_FILES) errors.push(`You can add at most ${MAX_FILES} files.`)
    else accepted.push(f)
  }
  return { accepted, errors }
}
