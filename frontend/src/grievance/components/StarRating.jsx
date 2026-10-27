import { Star } from 'lucide-react'

export function StarRating({ value, onChange, label = 'Rating' }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} out of 5`}
          onClick={() => onChange(n)}
          className="rounded p-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400"
        >
          <Star className={`h-7 w-7 ${n <= value ? 'fill-amber-400 text-amber-400' : 'text-white/30'}`} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
