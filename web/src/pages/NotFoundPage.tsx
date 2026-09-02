import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="center-screen">
      <h1>404</h1>
      <p>你访问的页面不存在。</p>
      <Link to="/">返回项目工作台</Link>
    </div>
  )
}
