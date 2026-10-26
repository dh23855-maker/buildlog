import { useId } from 'react'

// 라벨, 입력 칸, 안내 문장, 오류 문장을 한 묶음으로 보여줍니다.
export default function FormField({ label, hint, error, ...inputProps }) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} {...inputProps} />
      {hint && (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={errorId}>
          {error}
        </p>
      )}
    </div>
  )
}
