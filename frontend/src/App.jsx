import { Route, Routes } from 'react-router'

import { AuthProvider } from './AuthContext.jsx'
import Layout from './components/Layout.jsx'
import { GuestOnly, RequireAuth } from './components/RouteGuards.jsx'
import AccountSettingsPage from './pages/AccountSettingsPage.jsx'
import HomePage from './pages/HomePage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import SignupPage from './pages/SignupPage.jsx'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route
            path="/"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route
            path="/account"
            element={
              <RequireAuth>
                <AccountSettingsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/login"
            element={
              <GuestOnly>
                <LoginPage />
              </GuestOnly>
            }
          />
          <Route
            path="/signup"
            element={
              <GuestOnly>
                <SignupPage />
              </GuestOnly>
            }
          />
          {/* 알 수 없는 주소는 홈으로 보냅니다. 로그인하지 않았다면 홈이 다시 로그인 화면으로 보냅니다. */}
          <Route
            path="*"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
