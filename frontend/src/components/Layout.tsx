import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="shell">
      <header className="topbar">
        <strong className="brand">API Gateway</strong>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/playground">Playground</NavLink>
        </nav>
        <div className="spacer" />
        <span className="muted">
          {user?.username} <span className="badge">{user?.role}</span>
        </span>
        <button className="btn secondary" onClick={() => void logout()}>Sign out</button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
