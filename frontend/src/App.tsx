import { useEffect, useState } from 'react'

export default function App() {
  const [health, setHealth] = useState<string>('загрузка...')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setHealth(JSON.stringify(d)))
      .catch((e) => setHealth(`ошибка: ${e.message}`))
  }, [])

  return (
    <>
      <h1>МПРК</h1>
      <p>Backend: {health}</p>
    </>
  )
}
