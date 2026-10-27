import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Modal } from '../components/ui'

// Regression: typing in a dialog whose parent re-renders on every key must keep the cursor in the field.
function Parent() {
  const [v, setV] = useState('')
  const [open, setOpen] = useState(true)
  return open ? <Modal open title="Edit" onClose={() => setOpen(false)}><input aria-label="name" value={v} onChange={(e) => setV(e.target.value)} /></Modal> : <p>closed</p>
}

describe('Modal', () => {
  it('keeps focus in the field while the parent re-renders on every keystroke', async () => {
    const user = userEvent.setup()
    render(<Parent />)
    await user.type(screen.getByLabelText('name'), 'Sports')
    expect(screen.getByLabelText('name')).toHaveValue('Sports')
    expect(screen.getByLabelText('name')).toHaveFocus()
  })

  it('still closes on Escape using the latest handler', async () => {
    const user = userEvent.setup()
    render(<Parent />)
    await user.type(screen.getByLabelText('name'), 'a')
    await user.keyboard('{Escape}')
    expect(screen.getByText('closed')).toBeInTheDocument()
  })
})
